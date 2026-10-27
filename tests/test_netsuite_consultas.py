"""Pruebas de las queries SuiteQL contra el esquema sintético.

Cada query se compara contra el manifiesto de discrepancias plantadas: debe encontrar
exactamente lo plantado, ni más ni menos.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "netsuite-gl-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from netsuite_gl.compat import CAMPOS_DF  # noqa: E402
from netsuite_gl.config import CONFIG_DEFAULT, PlanDiscrepancias  # noqa: E402
from netsuite_gl.consultas import (  # noqa: E402
    DIR_QUERIES,
    ORDEN_CONSULTAS,
    Consulta,
    ErrorConsulta,
    cargar_consulta,
    ejecutar,
    ejecutar_por_nombre,
    parsear_consulta,
)
from netsuite_gl.poblado import construir_base  # noqa: E402
from netsuite_gl.salida import manifiesto_a_json, resultado_a_csv  # noqa: E402

CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"
CENTAVO = Decimal("0.01")


def _crudos() -> Dict[str, Dict[str, Any]]:
    with CFDIS.open(encoding="utf-8") as archivo:
        registros = [json.loads(linea) for linea in archivo if linea.strip()]
    return {
        r["uuid"]: r
        for r in registros
        if r["direccion"] == "recibido"
        and r["rfc_receptor"] == CONFIG_DEFAULT.rfc_empresa
        and r["tipo_comprobante"] in ("I", "E")
    }


def _signo(registro: Dict[str, Any]) -> Decimal:
    return Decimal("-1") if registro["tipo_comprobante"] == "E" else Decimal("1")


def _iva_mxn(registro: Dict[str, Any]) -> Decimal:
    if registro["moneda"] == "MXN":
        return Decimal(registro["iva"])
    subtotal = (Decimal(registro["subtotal"]) * Decimal(registro["tipo_cambio"])).quantize(
        CENTAVO, rounding=ROUND_HALF_UP
    )
    return Decimal(registro["total_mxn"]) - subtotal


def _filas(resultado: Any) -> List[Dict[str, Any]]:
    return [dict(zip(resultado.columnas, fila)) for fila in resultado.filas]


@pytest.fixture(scope="module")
def base() -> Iterator[Any]:
    with construir_base(CFDIS) as abierta:
        yield abierta


@pytest.fixture(scope="module")
def manifiesto(base: Any) -> Dict[str, Any]:
    return json.loads(manifiesto_a_json(base.manifiesto))


@pytest.fixture()
def base_nueva() -> Iterator[Any]:
    with construir_base(CFDIS) as abierta:
        yield abierta


# ---------------------------------------------------------------- carga de archivos .sql


def test_cada_archivo_sql_esta_registrado_y_tiene_descripcion() -> None:
    archivos = sorted(p.stem for p in DIR_QUERIES.glob("*.sql"))
    assert archivos == sorted(ORDEN_CONSULTAS)
    assert 4 <= len(ORDEN_CONSULTAS) <= 6
    for nombre in ORDEN_CONSULTAS:
        consulta = cargar_consulta(nombre)
        assert consulta.descripcion
        assert consulta.nombre == nombre


def test_las_queries_usan_cada_traduccion_de_builtin_df() -> None:
    textos = [cargar_consulta(n).suiteql for n in ORDEN_CONSULTAS]
    assert sum(1 for t in textos if "BUILTIN.DF(" in t) >= 2
    usados = {m.group(1) for t in textos for m in re.finditer(r"BUILTIN\.DF\(\w+\.(\w+)\)", t)}
    assert usados == set(CAMPOS_DF)


def test_parsear_encabezado_con_montos() -> None:
    texto = "-- @descripcion: Prueba corta\n-- @montos: debito, credito\nSELECT 1 AS debito, 2 AS credito\n"
    consulta = parsear_consulta("prueba", texto)
    assert consulta == Consulta("prueba", "Prueba corta", ("debito", "credito"), texto)


@pytest.mark.parametrize(
    "texto, fragmento",
    [
        ("SELECT 1\n", "descripcion"),
        ("-- @descripcion: x\n-- @color: rojo\nSELECT 1\n", "color"),
        ("-- @descripcion:\nSELECT 1\n", "descripcion"),
        ("-- @descripcion: x\n-- @montos: a, , b\nSELECT 1\n", "montos"),
    ],
)
def test_encabezado_invalido_falla(texto: str, fragmento: str) -> None:
    with pytest.raises(ErrorConsulta, match=fragmento):
        parsear_consulta("prueba", texto)


@pytest.mark.parametrize("nombre", ["no_existe", "../SPEC", "saldos_cuenta_periodo_clase.sql", ""])
def test_nombre_de_consulta_invalido_falla(nombre: str) -> None:
    with pytest.raises(ErrorConsulta):
        cargar_consulta(nombre)


def test_columna_monetaria_ausente_falla(base: Any) -> None:
    consulta = parsear_consulta("p", "-- @descripcion: x\n-- @montos: saldo\nSELECT 1 AS otra\n")
    with pytest.raises(ErrorConsulta, match="saldo"):
        ejecutar(base.conexion, consulta)


def test_float_en_columna_no_monetaria_falla(base: Any) -> None:
    consulta = parsear_consulta("p", "-- @descripcion: x\nSELECT CAST(5 AS REAL) AS proporcion\n")
    with pytest.raises(ErrorConsulta, match="proporcion"):
        ejecutar(base.conexion, consulta)


@pytest.mark.parametrize("expresion, fragmento", [("CAST(5 AS REAL)", "float"), ("'1.00'", "str")])
def test_columna_monetaria_que_no_es_centavo_entero_falla(base: Any, expresion: str, fragmento: str) -> None:
    consulta = parsear_consulta("p", f"-- @descripcion: x\n-- @montos: m\nSELECT {expresion} AS m\n")
    with pytest.raises(ErrorConsulta, match=fragmento):
        ejecutar(base.conexion, consulta)


def test_literal_decimal_en_una_query_falla_con_su_nombre(base: Any) -> None:
    consulta = parsear_consulta("umbral", "-- @descripcion: x\nSELECT COUNT(*) AS n FROM account WHERE 1 > 0.5\n")
    with pytest.raises(ErrorConsulta, match="umbral.*literal decimal"):
        ejecutar(base.conexion, consulta)


def test_error_de_sqlite_se_reporta_con_nombre_de_consulta(base: Any) -> None:
    consulta = parsear_consulta("rota", "-- @descripcion: x\nSELECT * FROM tabla_que_no_existe\n")
    with pytest.raises(ErrorConsulta, match="rota"):
        ejecutar(base.conexion, consulta)


def test_montos_salen_de_centavos_enteros_a_decimal_con_dos_decimales(base: Any) -> None:
    texto = "-- @descripcion: x\n-- @montos: m, n, v\nSELECT 11600 AS m, -10 - 20 AS n, NULL AS v\n"
    consulta = parsear_consulta("p", texto)
    (fila,) = ejecutar(base.conexion, consulta).filas
    assert fila == (Decimal("116.00"), Decimal("-0.30"), None)
    assert all(isinstance(v, Decimal) and v.as_tuple().exponent == -2 for v in fila[:2])


def _cfdi_grande(uuid: str, folio: str) -> Dict[str, Any]:
    return {
        "uuid": uuid, "serie": "BIG", "folio": folio, "fecha_emision": "2026-07-10", "tipo_comprobante": "I",
        "direccion": "recibido", "rfc_emisor": "RFC_PRUEBA_01", "nombre_emisor": "PROVEEDOR DE PRUEBA SA DE CV",
        "rfc_receptor": CONFIG_DEFAULT.rfc_empresa, "nombre_receptor": "EMPRESA DEMO SA DE CV", "moneda": "MXN",
        "tipo_cambio": None, "subtotal": "100000000000000.00", "iva": "0.01", "total": "100000000000000.01",
        "total_mxn": "100000000000000.01", "forma_pago": "03", "metodo_pago": "PUE", "uso_cfdi": "G03",
        "concepto": "SERVICIO DE HOSPEDAJE", "uuid_relacionado": None,
    }


def test_montos_que_un_float_no_representa_salen_exactos(tmp_path: Path) -> None:
    """100 billones con un centavo: en binario de 64 bits se vuelve ...0.02; en centavos enteros, no."""
    ruta = tmp_path / "cfdis.jsonl"
    registros = [_cfdi_grande("SINT0101-AAAA-4AAA-8AAA-0AAAAAAAAA01", "1"),
                 _cfdi_grande("SINT0102-AAAA-4AAA-8AAA-0AAAAAAAAA02", "2")]
    ruta.write_text("".join(json.dumps(r) + "\n" for r in registros), encoding="utf-8")
    plan = PlanDiscrepancias(sin_registro=1, monto_distinto=0, duplicado=0, periodo_equivocado=0)
    exacto = Decimal("100000000000000.01")
    with construir_base(ruta, plan=plan) as grande:
        (sin_registro,) = _filas(ejecutar_por_nombre(grande.conexion, "cfdi_sin_registro"))
        saldos = _filas(ejecutar_por_nombre(grande.conexion, "saldos_cuenta_periodo_clase"))
        cuadre = ejecutar_por_nombre(grande.conexion, "cuadre_cfdi_gl").filas
    assert sin_registro["total"] == exacto
    proveedores = [f for f in saldos if f["cuenta"].startswith(CONFIG_DEFAULT.cuenta_proveedores + " ")]
    assert [f["credito"] for f in proveedores] == [exacto]
    assert sum((f["debito"] for f in saldos), Decimal("0")) == exacto
    assert cuadre == ()


# ---------------------------------------------------------------- saldos


def test_saldos_cuadran_en_total_y_por_periodo(base: Any) -> None:
    filas = _filas(ejecutar_por_nombre(base.conexion, "saldos_cuenta_periodo_clase"))
    assert filas
    por_periodo: Dict[str, Tuple[Decimal, Decimal]] = defaultdict(lambda: (Decimal("0"), Decimal("0")))
    for f in filas:
        assert f["saldo"] == f["debito"] - f["credito"]
        debe, haber = por_periodo[f["periodo"]]
        por_periodo[f["periodo"]] = (debe + f["debito"], haber + f["credito"])
    assert all(debe == haber for debe, haber in por_periodo.values())


def test_saldos_solo_periodos_de_registro_con_nombres_visibles(base: Any) -> None:
    filas = _filas(ejecutar_por_nombre(base.conexion, "saldos_cuenta_periodo_clase"))
    periodos = {f["periodo"] for f in filas}
    assert periodos <= {"Jun 2026", "Jul 2026", "Aug 2026", "Sep 2026"}
    assert "Jul 2026" in periodos
    clases = {c.nombre for c in CONFIG_DEFAULT.clases}
    for f in filas:
        assert f["cuenta"] and f["cuenta"].split(" ", 1)[0] in {c.numero for c in CONFIG_DEFAULT.cuentas}
        assert f["clase"] in clases
    llaves = [(f["periodo"], f["cuenta"], f["clase"]) for f in filas]
    assert len(llaves) == len(set(llaves))


def test_saldo_de_proveedores_e_iva_coincide_con_cfdis_y_plantas(
    base: Any, manifiesto: Dict[str, Any]
) -> None:
    crudos = _crudos()
    disc = manifiesto["discrepancias"]
    factor = {u: 1 for u in crudos}
    factor.update({p["uuid"]: 0 for p in disc["sin_registro"]})
    factor.update({p["uuid"]: 2 for p in disc["duplicado"]})
    esperado_ap = sum((_signo(r) * Decimal(r["total_mxn"]) * factor[u] for u, r in crudos.items()), Decimal("0"))
    esperado_ap += sum((Decimal(p["diferencia_esperada"]) for p in disc["monto_distinto"]), Decimal("0"))
    esperado_iva = sum((_signo(r) * _iva_mxn(r) * factor[u] for u, r in crudos.items()), Decimal("0"))

    filas = _filas(ejecutar_por_nombre(base.conexion, "saldos_cuenta_periodo_clase"))

    def _saldo(numero: str) -> Decimal:
        return sum((f["saldo"] for f in filas if f["cuenta"].startswith(numero + " ")), Decimal("0"))

    assert -_saldo(CONFIG_DEFAULT.cuenta_proveedores) == esperado_ap
    assert _saldo(CONFIG_DEFAULT.cuenta_iva) == esperado_iva


# ---------------------------------------------------------------- verificación de registro


def test_cfdi_sin_registro_encuentra_exactamente_lo_plantado(base: Any, manifiesto: Dict[str, Any]) -> None:
    filas = _filas(ejecutar_por_nombre(base.conexion, "cfdi_sin_registro"))
    esperados = [p["uuid"] for p in manifiesto["discrepancias"]["sin_registro"]]
    assert [f["uuid"] for f in filas] == esperados
    crudos = _crudos()
    for f in filas:
        r = crudos[f["uuid"]]
        assert f["total"] == Decimal(r["total_mxn"])
        assert f["referencia"] == f"{r['serie']}-{r['folio']}"
        assert f["tipo"] == r["tipo_comprobante"]
        assert f["subtotal"] + f["iva"] == f["total"]


def test_cfdi_con_transaccion_no_contabilizada_sigue_sin_registro(
    base_nueva: Any, manifiesto: Dict[str, Any]
) -> None:
    conexion = base_nueva.conexion
    pendiente = manifiesto["discrepancias"]["sin_registro"][0]["uuid"]
    conexion.execute(
        "INSERT INTO \"transaction\" (id, tranid, trandate, type, postingperiod, entity, memo, posting, "
        "custbody_mx_cfdi_uuid) SELECT 99001, 'X-1', trandate, type, postingperiod, entity, memo, 'F', ? "
        "FROM \"transaction\" ORDER BY id LIMIT 1",
        (pendiente,),
    )
    registrado = conexion.execute(
        "SELECT custbody_mx_cfdi_uuid, MIN(id) FROM \"transaction\" WHERE posting = 'T' "
        "GROUP BY custbody_mx_cfdi_uuid HAVING COUNT(*) = 1 ORDER BY 1 LIMIT 1"
    ).fetchone()
    conexion.execute("UPDATE \"transaction\" SET posting = 'F' WHERE id = ?", (registrado[1],))
    filas = _filas(ejecutar_por_nombre(conexion, "cfdi_sin_registro"))
    uuids = {f["uuid"] for f in filas}
    assert pendiente in uuids
    assert registrado[0] in uuids


# ---------------------------------------------------------------- cuadre CFDI ↔ GL


def test_cuadre_detecta_montos_distintos_y_duplicados(base: Any, manifiesto: Dict[str, Any]) -> None:
    disc = manifiesto["discrepancias"]
    esperado = {p["uuid"]: (Decimal(p["diferencia_esperada"]), 1) for p in disc["monto_distinto"]}
    esperado.update({p["uuid"]: (Decimal(p["diferencia_esperada"]), 2) for p in disc["duplicado"]})
    filas = _filas(ejecutar_por_nombre(base.conexion, "cuadre_cfdi_gl"))
    assert [f["uuid"] for f in filas] == sorted(esperado)
    crudos = _crudos()
    for f in filas:
        r = crudos[f["uuid"]]
        assert (f["diferencia"], f["num_transacciones"]) == esperado[f["uuid"]]
        assert f["total_cfdi"] == _signo(r) * Decimal(r["total_mxn"])
        assert f["total_gl"] == f["total_cfdi"] + f["diferencia"]
        assert f["emisor"] == r["nombre_emisor"]


def test_duplicado_en_cuadre_dobla_el_total(manifiesto: Dict[str, Any]) -> None:
    crudos = _crudos()
    for p in manifiesto["discrepancias"]["duplicado"]:
        r = crudos[p["uuid"]]
        assert Decimal(p["diferencia_esperada"]) == _signo(r) * Decimal(r["total_mxn"])


# ---------------------------------------------------------------- duplicados y periodo


def test_duplicados_encuentra_exactamente_lo_plantado(base: Any, manifiesto: Dict[str, Any]) -> None:
    filas = _filas(ejecutar_por_nombre(base.conexion, "duplicados_registro"))
    esperados = manifiesto["discrepancias"]["duplicado"]
    assert [f["uuid"] for f in filas] == [p["uuid"] for p in esperados]
    crudos = _crudos()
    for f, p in zip(filas, esperados):
        assert f["num_registros"] == 2
        assert [f["primera_transaccion"], f["ultima_transaccion"]] == p["transacciones"]
        r = crudos[f["uuid"]]
        assert f["referencia"] == f"{r['serie']}-{r['folio']}"


def test_periodo_equivocado_encuentra_exactamente_lo_plantado(base: Any, manifiesto: Dict[str, Any]) -> None:
    filas = _filas(ejecutar_por_nombre(base.conexion, "periodo_equivocado"))
    esperados = manifiesto["discrepancias"]["periodo_equivocado"]
    assert [f["uuid"] for f in filas] == [p["uuid"] for p in esperados]
    crudos = _crudos()
    for f, p in zip(filas, esperados):
        assert f["transaccion"] == p["transaccion"]
        assert f["periodo_registrado"] == p["periodo_registrado"]
        assert f["periodo_esperado"] == p["periodo_esperado"]
        assert f["fecha_cfdi"] == crudos[f["uuid"]]["fecha_emision"]
        assert f["tipo_transaccion"] == ("Bill" if crudos[f["uuid"]]["tipo_comprobante"] == "I" else "Bill Credit")
        assert f["proveedor"].startswith("PROV-") and f["proveedor"].endswith(crudos[f["uuid"]]["nombre_emisor"])


# ---------------------------------------------------------------- determinismo


def test_resultados_son_deterministas() -> None:
    def _correr() -> List[str]:
        with construir_base(CFDIS) as nueva:
            return [resultado_a_csv(ejecutar_por_nombre(nueva.conexion, n)) for n in ORDEN_CONSULTAS]

    assert _correr() == _correr()
