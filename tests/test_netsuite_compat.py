"""Pruebas de la capa de compatibilidad SuiteQL → SQLite."""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "netsuite-gl-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from netsuite_gl.compat import (  # noqa: E402
    CAMPOS_DF,
    ErrorCompatibilidad,
    quitar_comentarios,
    round_centavos,
    traducir,
)
from netsuite_gl.poblado import construir_base  # noqa: E402

CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"


@pytest.fixture(scope="module")
def conexion() -> Iterator[sqlite3.Connection]:
    with construir_base(CFDIS) as base:
        yield base.conexion


def _uno(conexion: sqlite3.Connection, suiteql: str) -> Any:
    return conexion.execute(traducir(suiteql)).fetchone()


def test_df_de_cuenta_devuelve_numero_y_nombre(conexion: sqlite3.Connection) -> None:
    fila = _uno(
        conexion,
        "SELECT BUILTIN.DF(tal.account) AS cuenta, a.acctnumber, a.fullname "
        "FROM transactionaccountingline tal JOIN account a ON a.id = tal.account "
        "ORDER BY tal.transaction, tal.transactionline",
    )
    assert fila[0] == f"{fila[1]} {fila[2]}"


def test_df_de_clase_periodo_proveedor_y_tipo(conexion: sqlite3.Connection) -> None:
    fila = _uno(
        conexion,
        "SELECT BUILTIN.DF(tl.class), BUILTIN.DF(t.postingperiod), BUILTIN.DF(t.entity), "
        "BUILTIN.DF(t.type), c.fullname, p.periodname, v.entityid || ' ' || v.companyname "
        "FROM transaction t JOIN transactionline tl ON tl.transaction = t.id AND tl.id = 0 "
        "JOIN classification c ON c.id = tl.class JOIN accountingperiod p ON p.id = t.postingperiod "
        "JOIN vendor v ON v.id = t.entity WHERE t.type = 'VendBill' ORDER BY t.id",
    )
    assert fila[0] == fila[4]
    assert fila[1] == fila[5]
    assert fila[2] == fila[6]
    assert fila[3] == "Bill"


def test_df_de_nota_de_credito_y_referencia_nula(conexion: sqlite3.Connection) -> None:
    fila = _uno(conexion, "SELECT BUILTIN.DF(t.type) FROM transaction t WHERE t.type = 'VendCred' ORDER BY t.id")
    assert fila == ("Bill Credit",)
    nulo = _uno(conexion, "SELECT BUILTIN.DF(x.account) FROM (SELECT NULL AS account) x")
    assert nulo == (None,)


def test_df_acepta_campo_sin_alias_y_minusculas(conexion: sqlite3.Connection) -> None:
    fila = _uno(
        conexion,
        "SELECT builtin.df( account ) FROM transactionaccountingline ORDER BY transaction, transactionline",
    )
    assert fila[0] is not None and " " in fila[0]


def test_df_de_campo_sin_traduccion_falla_con_campos_soportados() -> None:
    with pytest.raises(ErrorCompatibilidad) as error:
        traducir("SELECT BUILTIN.DF(t.subsidiary) FROM transaction t")
    assert "subsidiary" in str(error.value)
    for campo in CAMPOS_DF:
        assert campo in str(error.value)


def test_identificador_transaction_se_cita_para_sqlite(conexion: sqlite3.Connection) -> None:
    sql = traducir(
        "SELECT t.id, tal.transaction FROM transaction t "
        "JOIN transactionaccountingline tal ON tal.transaction = t.id ORDER BY t.id"
    )
    assert sql.count('"transaction"') == 3
    assert "transactionaccountingline" in sql
    fila = conexion.execute(sql).fetchone()
    assert fila[0] == fila[1]


def test_nvl_se_vuelve_coalesce(conexion: sqlite3.Connection) -> None:
    sql = traducir("SELECT NVL(NULL, 5), nvl (NULL, 'x')")
    assert "NVL" not in sql.upper()
    assert conexion.execute(sql).fetchone() == (5, "x")


def test_nvl_anidado_con_df(conexion: sqlite3.Connection) -> None:
    fila = _uno(conexion, "SELECT NVL(BUILTIN.DF(x.entity), 'SIN PROVEEDOR') FROM (SELECT NULL AS entity) x")
    assert fila == ("SIN PROVEEDOR",)


def test_literales_e_identificadores_no_se_traducen(conexion: sqlite3.Connection) -> None:
    suiteql = "SELECT 'BUILTIN.DF(t.account) -- NVL(', 'O''Brien' AS \"NVL(x -- y\""
    sql = traducir(suiteql)
    assert sql == suiteql
    fila = conexion.execute(sql).fetchone()
    assert fila == ("BUILTIN.DF(t.account) -- NVL(", "O'Brien")


def test_comentarios_se_quitan_aunque_mencionen_builtin() -> None:
    suiteql = "-- encabezado BUILTIN.CONSOLIDATE\nSELECT 1 /* NVL( BUILTIN.X */ AS uno -- cola\n"
    limpio = quitar_comentarios(suiteql)
    assert "BUILTIN" not in limpio and "--" not in limpio and "/*" not in limpio
    assert "SELECT 1" in limpio and "AS uno" in limpio
    assert traducir(suiteql) == limpio


def test_otra_construccion_builtin_falla() -> None:
    with pytest.raises(ErrorCompatibilidad, match="BUILTIN.CONSOLIDATE"):
        traducir("SELECT BUILTIN.CONSOLIDATE(tal.amount, 'LEDGER') FROM transactionaccountingline tal")


@pytest.mark.parametrize(
    "suiteql, fragmento",
    [
        ("SELECT 'sin cerrar FROM account", "literal"),
        ("SELECT \"sin cerrar FROM account", "identificador"),
        ("SELECT 1 /* sin cerrar", "comentario"),
    ],
)
def test_texto_sin_cerrar_falla(suiteql: str, fragmento: str) -> None:
    with pytest.raises(ErrorCompatibilidad, match=fragmento):
        traducir(suiteql)


def test_traduccion_es_determinista() -> None:
    suiteql = "SELECT BUILTIN.DF(a.account), NVL(a.debit, 0) FROM transactionaccountingline a"
    assert traducir(suiteql) == traducir(suiteql)


# ---------------------------------------------------------------- montos en centavos enteros


def test_round_se_traduce_a_round_centavos_y_conserva_el_entero(conexion: sqlite3.Connection) -> None:
    sql = traducir(
        "SELECT ROUND(SUM(NVL(tal.debit, 0)), 2), round (SUM(tal.amount), 4) FROM transactionaccountingline tal")
    assert "ROUND(" not in sql.upper().replace("ROUND_CENTAVOS(", "")
    fila = conexion.execute(sql).fetchone()
    crudo = conexion.execute(
        'SELECT SUM(COALESCE(debit, 0)), SUM(amount) FROM transactionaccountingline').fetchone()
    assert fila == crudo and all(type(v) is int for v in fila)


def test_round_centavos_rechaza_float_texto_y_menos_de_dos_decimales() -> None:
    assert round_centavos(None, 2) is None
    assert round_centavos(11600, 2) == 11600
    for crudo, decimales, fragmento in ((1.5, 2, "float"), ("1.00", 2, "str"), (11600, 0, "2 decimales"),
                                        (11600, 1, "2 decimales"), (11600, 2.0, "decimales")):
        with pytest.raises(ValueError, match=fragmento):
            round_centavos(crudo, decimales)


def test_round_a_cero_decimales_falla_en_sqlite(conexion: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.OperationalError):
        conexion.execute(traducir("SELECT ROUND(SUM(tal.debit), 0) FROM transactionaccountingline tal")).fetchone()


@pytest.mark.parametrize("suiteql", [
    "SELECT tal.debit FROM transactionaccountingline tal WHERE tal.debit > 100.00",
    "SELECT .5 AS x",
    "SELECT 1e3 AS x",
    "SELECT 2. AS x",
])
def test_literal_decimal_falla_porque_los_montos_estan_en_centavos(suiteql: str) -> None:
    with pytest.raises(ErrorCompatibilidad, match="literal decimal"):
        traducir(suiteql)


def test_division_falla_porque_sqlite_trunca_entre_enteros() -> None:
    with pytest.raises(ErrorCompatibilidad, match="división"):
        traducir("SELECT SUM(tal.amount) / COUNT(*) FROM transactionaccountingline tal")


def test_numeros_en_identificadores_y_literales_de_texto_no_cuentan(conexion: sqlite3.Connection) -> None:
    suiteql = "SELECT 'a/b 1.50' AS texto, tal2.transactionline FROM transactionaccountingline tal2 WHERE 1 = 1"
    assert traducir(suiteql) == suiteql
    assert conexion.execute(traducir(suiteql)).fetchone()[0] == "a/b 1.50"
