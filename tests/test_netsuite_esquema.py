"""Pruebas del esquema sintético de NetSuite y de su poblado determinista.

Las expectativas se derivan del archivo de CFDIs leído aparte, no del estado interno del
poblado, para que la prueba no repita la implementación.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "netsuite-gl-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from netsuite_gl.cfdis import ErrorInsumo, leer_cfdis  # noqa: E402
from netsuite_gl.config import CONFIG_DEFAULT, PlanDiscrepancias  # noqa: E402
from netsuite_gl.poblado import ErrorPoblado, construir_base  # noqa: E402
from netsuite_gl.salida import manifiesto_a_json  # noqa: E402

CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"
RFC_EMPRESA = CONFIG_DEFAULT.rfc_empresa
PLAN_VACIO = PlanDiscrepancias(sin_registro=0, monto_distinto=0, duplicado=0, periodo_equivocado=0)

TABLAS_ESPERADAS = {
    "account": {"id", "acctnumber", "fullname", "accttype", "isinactive"},
    "accountingperiod": {
        "id", "periodname", "startdate", "enddate", "isposting", "isquarter", "isyear", "closed",
    },
    "classification": {"id", "name", "fullname", "isinactive"},
    "vendor": {"id", "entityid", "companyname", "custentity_mx_rfc", "isinactive"},
    "transaction": {
        "id", "tranid", "trandate", "type", "postingperiod", "entity", "memo", "posting",
        "custbody_mx_cfdi_uuid",
    },
    "transactionline": {
        "transaction", "id", "linesequencenumber", "mainline", "taxline", "class", "entity", "memo",
    },
    "transactionaccountingline": {
        "transaction", "transactionline", "account", "debit", "credit", "amount", "posting",
    },
    "customrecord_cfdi_recibido": {
        "id", "name", "custrecord_cfdi_uuid", "custrecord_cfdi_fecha", "custrecord_cfdi_tipo",
        "custrecord_cfdi_rfc_emisor", "custrecord_cfdi_nombre_emisor", "custrecord_cfdi_serie",
        "custrecord_cfdi_folio", "custrecord_cfdi_concepto", "custrecord_cfdi_subtotal",
        "custrecord_cfdi_iva", "custrecord_cfdi_total", "custrecord_cfdi_uuid_relacionado",
    },
}


def _crudos() -> List[Dict[str, Any]]:
    with CFDIS.open(encoding="utf-8") as archivo:
        return [json.loads(linea) for linea in archivo if linea.strip()]


def _es_universo(c: Dict[str, Any]) -> bool:
    return (
        c["direccion"] == "recibido"
        and c["rfc_receptor"] == RFC_EMPRESA
        and c["tipo_comprobante"] in ("I", "E")
    )


def _cfdi_valido(**cambios: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "uuid": "SINT0001-AAAA-4AAA-8AAA-0AAAAAAAAAA1",
        "serie": "TST",
        "folio": "10",
        "fecha_emision": "2026-07-10",
        "tipo_comprobante": "I",
        "direccion": "recibido",
        "rfc_emisor": "RFC_PRUEBA_01",
        "nombre_emisor": "PROVEEDOR DE PRUEBA SA DE CV",
        "rfc_receptor": RFC_EMPRESA,
        "nombre_receptor": "EMPRESA DEMO SA DE CV",
        "moneda": "MXN",
        "tipo_cambio": None,
        "subtotal": "100.00",
        "iva": "16.00",
        "total": "116.00",
        "total_mxn": "116.00",
        "forma_pago": "03",
        "metodo_pago": "PUE",
        "uso_cfdi": "G03",
        "concepto": "SERVICIO DE HOSPEDAJE",
        "uuid_relacionado": None,
    }
    base.update(cambios)
    return base


def _escribir(tmp_path: Path, registros: List[Dict[str, Any]]) -> Path:
    ruta = tmp_path / "cfdis.jsonl"
    ruta.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in registros), encoding="utf-8")
    return ruta


def _sha_dump(conexion: Any) -> str:
    return hashlib.sha256("\n".join(conexion.iterdump()).encode("utf-8")).hexdigest()


@pytest.fixture(scope="module")
def base() -> Any:
    return construir_base(CFDIS)


@pytest.fixture(scope="module")
def manifiesto(base: Any) -> Dict[str, Any]:
    return json.loads(manifiesto_a_json(base.manifiesto))


# ---------------------------------------------------------------- lectura de CFDIs


def test_lectura_separa_universo_y_cuenta_excluidos_por_motivo() -> None:
    crudos = _crudos()
    lectura = leer_cfdis(CFDIS, RFC_EMPRESA)
    esperados_excluidos = Counter(
        "emitido" if c["direccion"] == "emitido" else "receptor_ajeno"
        for c in crudos
        if not _es_universo(c)
    )
    assert lectura.leidos == len(crudos)
    assert len(lectura.universo) == sum(1 for c in crudos if _es_universo(c))
    assert dict(lectura.excluidos) == dict(esperados_excluidos)
    assert len(lectura.universo) + sum(lectura.excluidos.values()) == len(crudos)


def test_lectura_convierte_usd_a_mxn_sin_floats(tmp_path: Path) -> None:
    usd = _cfdi_valido(
        moneda="USD", tipo_cambio="18.5000", subtotal="100.00", iva="16.00",
        total="116.00", total_mxn="2146.00",
    )
    (cfdi,) = leer_cfdis(_escribir(tmp_path, [usd]), RFC_EMPRESA).universo
    assert cfdi.subtotal_mxn == Decimal("1850.00")
    assert cfdi.iva_mxn == Decimal("296.00")
    assert cfdi.total_mxn == Decimal("2146.00")
    assert all(isinstance(v, Decimal) for v in (cfdi.subtotal_mxn, cfdi.iva_mxn, cfdi.total_mxn))


def test_lectura_clasifica_tipo_no_aplica(tmp_path: Path) -> None:
    pago = _cfdi_valido(tipo_comprobante="P")
    lectura = leer_cfdis(_escribir(tmp_path, [pago]), RFC_EMPRESA)
    assert lectura.universo == ()
    assert dict(lectura.excluidos) == {"tipo_no_aplica": 1}


@pytest.mark.parametrize(
    "cambios, fragmento",
    [
        ({"total": 116.0}, "total"),
        ({"fecha_emision": "10/07/2026"}, "fecha_emision"),
        ({"fecha_emision": "2026-W28-5"}, "fecha_emision"),
        ({"fecha_emision": "2026-02-30"}, "fecha_emision"),
        ({"fecha_emision": "２０２６-07-10"}, "fecha_emision"),
        ({"total": "117.00", "total_mxn": "117.00"}, "subtotal + iva"),
        ({"total_mxn": "120.00"}, "total_mxn"),
        ({"moneda": "USD", "tipo_cambio": None}, "tipo_cambio"),
        ({"moneda": "EUR"}, "moneda"),
        ({"tipo_comprobante": "X"}, "tipo_comprobante"),
        ({"direccion": "otro"}, "direccion"),
        ({"subtotal": "abc"}, "subtotal"),
        ({"uuid": ""}, "uuid"),
    ],
)
def test_lectura_rechaza_registro_invalido_con_linea(
    tmp_path: Path, cambios: Dict[str, Any], fragmento: str
) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido(uuid="SINT0002-AAAA-4AAA-8AAA-0AAAAAAAAAA2"), _cfdi_valido(**cambios)])
    with pytest.raises(ErrorInsumo) as error:
        leer_cfdis(ruta, RFC_EMPRESA)
    assert "línea 2" in str(error.value)
    assert fragmento in str(error.value)


def test_lectura_rechaza_campo_faltante(tmp_path: Path) -> None:
    registro = _cfdi_valido()
    del registro["concepto"]
    with pytest.raises(ErrorInsumo, match="concepto"):
        leer_cfdis(_escribir(tmp_path, [registro]), RFC_EMPRESA)


def test_lectura_rechaza_uuid_duplicado(tmp_path: Path) -> None:
    with pytest.raises(ErrorInsumo, match="duplicado"):
        leer_cfdis(_escribir(tmp_path, [_cfdi_valido(), _cfdi_valido()]), RFC_EMPRESA)


def test_lectura_rechaza_json_invalido_y_archivo_inexistente(tmp_path: Path) -> None:
    ruta = tmp_path / "roto.jsonl"
    ruta.write_text('{"uuid": \n', encoding="utf-8")
    with pytest.raises(ErrorInsumo, match="línea 1"):
        leer_cfdis(ruta, RFC_EMPRESA)
    lista = tmp_path / "lista.jsonl"
    lista.write_text("[1, 2]\n", encoding="utf-8")
    with pytest.raises(ErrorInsumo, match="objeto"):
        leer_cfdis(lista, RFC_EMPRESA)
    with pytest.raises(ErrorInsumo, match="no existe"):
        leer_cfdis(tmp_path / "no_hay.jsonl", RFC_EMPRESA)


# ---------------------------------------------------------------- esquema


def test_esquema_tiene_tablas_y_columnas_estilo_suiteql(base: Any) -> None:
    for tabla, columnas in TABLAS_ESPERADAS.items():
        reales = {fila[1] for fila in base.conexion.execute(f'PRAGMA table_info("{tabla}")')}
        assert reales == columnas, tabla


def test_cada_transaccion_cuadra_y_amount_es_debit_menos_credit(base: Any) -> None:
    descuadres = base.conexion.execute(
        "SELECT \"transaction\" FROM transactionaccountingline GROUP BY \"transaction\" "
        "HAVING ROUND(SUM(COALESCE(debit, 0)) - SUM(COALESCE(credit, 0)), 2) <> 0"
    ).fetchall()
    assert descuadres == []
    mal_amount = base.conexion.execute(
        "SELECT COUNT(*) FROM transactionaccountingline "
        "WHERE ROUND(amount - (COALESCE(debit, 0) - COALESCE(credit, 0)), 2) <> 0 "
        "OR (debit IS NULL) = (credit IS NULL)"
    ).fetchone()
    assert mal_amount == (0,)


def test_lineas_de_cuenta_y_accounting_line_son_uno_a_uno(base: Any) -> None:
    huerfanas = base.conexion.execute(
        "SELECT COUNT(*) FROM transactionline tl LEFT JOIN transactionaccountingline tal "
        "ON tal.\"transaction\" = tl.\"transaction\" AND tal.transactionline = tl.id WHERE tal.account IS NULL"
    ).fetchone()
    assert huerfanas == (0,)


def test_mainline_va_a_proveedores_con_proveedor(base: Any) -> None:
    filas = base.conexion.execute(
        "SELECT a.accttype, tl.entity, t.entity FROM transactionline tl "
        "JOIN \"transaction\" t ON t.id = tl.\"transaction\" "
        "JOIN transactionaccountingline tal "
        "ON tal.\"transaction\" = tl.\"transaction\" AND tal.transactionline = tl.id "
        "JOIN account a ON a.id = tal.account WHERE tl.mainline = 'T'"
    ).fetchall()
    assert filas
    assert all(tipo == "AcctPay" and linea == cabeza for tipo, linea, cabeza in filas)


def test_proveedores_uno_por_rfc_y_nombre(base: Any) -> None:
    pares = {(c["rfc_emisor"], c["nombre_emisor"]) for c in _crudos() if _es_universo(c)}
    filas = base.conexion.execute("SELECT custentity_mx_rfc, companyname, entityid FROM vendor").fetchall()
    assert {(rfc, nombre) for rfc, nombre, _ in filas} == pares
    assert len(filas) == len(pares)
    assert all(entityid.startswith("PROV-") for _, _, entityid in filas)


def test_registro_personalizado_tiene_todo_el_universo(base: Any) -> None:
    universo = {c["uuid"] for c in _crudos() if _es_universo(c)}
    filas = base.conexion.execute("SELECT custrecord_cfdi_uuid FROM customrecord_cfdi_recibido").fetchall()
    assert {f[0] for f in filas} == universo


def test_periodos_anual_trimestres_y_meses(base: Any) -> None:
    filas = base.conexion.execute(
        "SELECT periodname, isposting, isquarter, isyear, closed FROM accountingperiod ORDER BY id"
    ).fetchall()
    nombres = {f[0]: f for f in filas}
    assert nombres["FY 2026"][1:4] == ("F", "F", "T")
    assert nombres["Q3 2026"][1:4] == ("F", "T", "F")
    assert nombres["Jul 2026"][1:4] == ("T", "F", "F")
    assert nombres["May 2026"][4] == "T"
    assert nombres["Jul 2026"][4] == "F"


# ---------------------------------------------------------------- discrepancias


def test_manifiesto_respeta_tamanos_del_plan_y_es_disjunto(manifiesto: Dict[str, Any]) -> None:
    plan = PlanDiscrepancias()
    disc = manifiesto["discrepancias"]
    assert len(disc["sin_registro"]) == plan.sin_registro
    assert len(disc["monto_distinto"]) == plan.monto_distinto
    assert len(disc["duplicado"]) == plan.duplicado
    assert len(disc["periodo_equivocado"]) == plan.periodo_equivocado
    todos = [p["uuid"] for lista in disc.values() for p in lista]
    assert len(todos) == len(set(todos))
    universo = {c["uuid"] for c in _crudos() if _es_universo(c)}
    assert set(todos) <= universo
    for lista in disc.values():
        assert [p["uuid"] for p in lista] == sorted(p["uuid"] for p in lista)


def test_manifiesto_resumen_y_parametros(manifiesto: Dict[str, Any], base: Any) -> None:
    crudos = _crudos()
    resumen = manifiesto["resumen"]
    assert manifiesto["esquema"] == "netsuite_discrepancias/v1"
    assert resumen["cfdis_leidos"] == len(crudos)
    assert resumen["universo"] == sum(1 for c in crudos if _es_universo(c))
    num_tx = base.conexion.execute('SELECT COUNT(*) FROM "transaction"').fetchone()[0]
    assert resumen["transacciones"] == num_tx
    plan = PlanDiscrepancias()
    assert num_tx == resumen["universo"] - plan.sin_registro + plan.duplicado
    assert manifiesto["parametros"]["semilla"] == plan.semilla
    assert manifiesto["parametros"]["deltas_monto"] == [str(d) for d in plan.deltas_monto]


def test_sin_registro_no_tiene_transaccion(base: Any, manifiesto: Dict[str, Any]) -> None:
    for planta in manifiesto["discrepancias"]["sin_registro"]:
        n = base.conexion.execute(
            "SELECT COUNT(*) FROM \"transaction\" WHERE custbody_mx_cfdi_uuid = ?", (planta["uuid"],)
        ).fetchone()[0]
        assert n == 0


def test_duplicado_tiene_dos_transacciones_identicas(base: Any, manifiesto: Dict[str, Any]) -> None:
    for planta in manifiesto["discrepancias"]["duplicado"]:
        filas = base.conexion.execute(
            "SELECT id, tranid, trandate, postingperiod, entity FROM \"transaction\" "
            "WHERE custbody_mx_cfdi_uuid = ? ORDER BY id",
            (planta["uuid"],),
        ).fetchall()
        assert [f[0] for f in filas] == planta["transacciones"]
        assert filas[0][1:] == filas[1][1:]


def test_monto_distinto_cicla_deltas_y_sigue_cuadrado(base: Any, manifiesto: Dict[str, Any]) -> None:
    plan = PlanDiscrepancias()
    plantas = manifiesto["discrepancias"]["monto_distinto"]
    assert {p["delta"] for p in plantas} == {str(d) for d in plan.deltas_monto}
    tipos = {c["uuid"]: c["tipo_comprobante"] for c in _crudos()}
    for planta in plantas:
        signo = Decimal("-1") if tipos[planta["uuid"]] == "E" else Decimal("1")
        assert Decimal(planta["diferencia_esperada"]) == signo * Decimal(planta["delta"])


def test_periodo_equivocado_es_el_mes_siguiente(base: Any, manifiesto: Dict[str, Any]) -> None:
    for planta in manifiesto["discrepancias"]["periodo_equivocado"]:
        fila = base.conexion.execute(
            "SELECT p.periodname, t.trandate FROM \"transaction\" t "
            "JOIN accountingperiod p ON p.id = t.postingperiod WHERE t.id = ?",
            (planta["transaccion"],),
        ).fetchone()
        assert fila[0] == planta["periodo_registrado"]
        assert planta["periodo_registrado"] != planta["periodo_esperado"]


def test_poblado_es_determinista_y_depende_de_la_semilla() -> None:
    primera = construir_base(CFDIS)
    segunda = construir_base(CFDIS)
    assert manifiesto_a_json(primera.manifiesto) == manifiesto_a_json(segunda.manifiesto)
    assert _sha_dump(primera.conexion) == _sha_dump(segunda.conexion)
    otra = construir_base(CFDIS, plan=PlanDiscrepancias(semilla=99))
    assert otra.manifiesto.sin_registro != primera.manifiesto.sin_registro


# ---------------------------------------------------------------- casos con insumo propio


def test_nota_de_credito_usa_cuenta_de_la_factura_relacionada(tmp_path: Path) -> None:
    factura = _cfdi_valido(concepto="SERVICIO DE HOSPEDAJE")
    nota = _cfdi_valido(
        uuid="SINT0003-AAAA-4AAA-8AAA-0AAAAAAAAAA3", tipo_comprobante="E", concepto="DEVOLUCION O BONIFICACION",
        subtotal="10.00", iva="1.60", total="11.60", total_mxn="11.60",
        uuid_relacionado=factura["uuid"],
    )
    suelta = _cfdi_valido(
        uuid="SINT0004-AAAA-4AAA-8AAA-0AAAAAAAAAA4", tipo_comprobante="E", concepto="DEVOLUCION O BONIFICACION",
        subtotal="10.00", iva="0.00", total="10.00", total_mxn="10.00",
        uuid_relacionado="SINT9999-AAAA-4AAA-8AAA-0AAAAAAAAAA9",
    )
    base = construir_base(_escribir(tmp_path, [factura, nota, suelta]), plan=PLAN_VACIO)
    consulta = (
        "SELECT t.type, a.acctnumber, tal.debit, tal.credit FROM \"transaction\" t "
        "JOIN transactionaccountingline tal ON tal.\"transaction\" = t.id AND tal.transactionline = ? "
        "JOIN account a ON a.id = tal.account WHERE t.custbody_mx_cfdi_uuid = ?"
    )
    cuenta_hospedaje = CONFIG_DEFAULT.gasto_por_concepto["SERVICIO DE HOSPEDAJE"].cuenta
    gasto_nota = base.conexion.execute(consulta, (1, nota["uuid"])).fetchone()
    assert gasto_nota[0] == "VendCred"
    assert gasto_nota[1] == cuenta_hospedaje
    assert gasto_nota[2] is None and Decimal(str(gasto_nota[3])) == Decimal("10.00")
    proveedores_nota = base.conexion.execute(consulta, (0, nota["uuid"])).fetchone()
    assert Decimal(str(proveedores_nota[2])) == Decimal("11.60") and proveedores_nota[3] is None
    gasto_suelta = base.conexion.execute(consulta, (1, suelta["uuid"])).fetchone()
    assert gasto_suelta[1] == CONFIG_DEFAULT.gasto_default.cuenta
    sin_iva = base.conexion.execute(consulta, (2, suelta["uuid"])).fetchone()
    assert sin_iva is None


def test_plan_que_excede_el_universo_falla(tmp_path: Path) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido()])
    with pytest.raises(ErrorPoblado, match="universo"):
        construir_base(ruta, plan=dataclasses.replace(PLAN_VACIO, sin_registro=2))


def test_plan_invalido_falla(tmp_path: Path) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido()])
    with pytest.raises(ErrorPoblado, match="negativo"):
        construir_base(ruta, plan=dataclasses.replace(PLAN_VACIO, duplicado=-1))
    with pytest.raises(ErrorPoblado, match="deltas"):
        construir_base(ruta, plan=dataclasses.replace(PLAN_VACIO, monto_distinto=1, deltas_monto=()))


def test_delta_que_deja_gasto_no_positivo_falla(tmp_path: Path) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido()])
    plan = dataclasses.replace(PLAN_VACIO, monto_distinto=1, deltas_monto=(Decimal("-100.00"),))
    with pytest.raises(ErrorPoblado, match="delta"):
        construir_base(ruta, plan=plan)


def test_fecha_sin_periodo_falla(tmp_path: Path) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido(fecha_emision="2027-03-01")])
    with pytest.raises(ErrorPoblado, match="periodo"):
        construir_base(ruta, plan=PLAN_VACIO)


def test_periodo_equivocado_sin_mes_siguiente_falla(tmp_path: Path) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido(fecha_emision="2026-08-10")])
    config = dataclasses.replace(CONFIG_DEFAULT, meses=((2026, 7), (2026, 8)), meses_cerrados=())
    with pytest.raises(ErrorPoblado, match="siguiente"):
        construir_base(ruta, config=config, plan=dataclasses.replace(PLAN_VACIO, periodo_equivocado=1))


@pytest.mark.parametrize(
    "cambios, fragmento",
    [
        ({"meses": ()}, "meses"),
        ({"meses": ((2026, 13),), "meses_cerrados": ()}, "inválidos"),
        ({"meses_cerrados": ((2025, 1),)}, "cerrados"),
        ({"cuenta_iva": "0000-000"}, "0000-000"),
        ({"cuenta_proveedores": "6900-000"}, "AcctPay"),
    ],
)
def test_config_invalida_falla_sin_ajustes(tmp_path: Path, cambios: Dict[str, Any], fragmento: str) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido()])
    with pytest.raises(ErrorPoblado, match=fragmento):
        construir_base(ruta, config=dataclasses.replace(CONFIG_DEFAULT, **cambios), plan=PLAN_VACIO)


def test_delta_cero_falla(tmp_path: Path) -> None:
    ruta = _escribir(tmp_path, [_cfdi_valido()])
    plan = dataclasses.replace(PLAN_VACIO, monto_distinto=1, deltas_monto=(Decimal("0.00"),))
    with pytest.raises(ErrorPoblado, match="cero"):
        construir_base(ruta, plan=plan)
