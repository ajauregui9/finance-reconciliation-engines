"""Pruebas de los adaptadores de fuente a filas contrato.

Cada prueba escribe sus propios CSV en un directorio temporal; ninguna comparte estado.
"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Sequence

import pytest

RAIZ = Path(__file__).resolve().parents[1]
MODULO = RAIZ / "skills" / "cashflow-forecasting"
if str(MODULO) not in sys.path:
    sys.path.insert(0, str(MODULO))

from flujo.config import cargar_config, validar_curva  # noqa: E402
from flujo.contrato import FUENTES  # noqa: E402
from flujo.errores import ErrorInsumo  # noqa: E402
from flujo.fuentes import (  # noqa: E402
    leer_cxc,
    leer_cxp,
    leer_fuentes,
    leer_impuestos,
    leer_nomina,
    leer_saldos,
)

CORTE = date(2026, 11, 2)
D = Decimal
COLS_SALDOS = ("cuenta", "banco", "fecha_saldo", "moneda", "saldo")
COLS_CXC = ("cliente_id", "cliente", "factura", "fecha_factura", "fecha_vencimiento", "moneda", "saldo")
COLS_CXP = ("proveedor_id", "proveedor", "factura", "fecha_programada", "moneda", "monto")
COLS_NOMINA = ("periodo", "descripcion", "fecha_pago", "moneda", "monto")
COLS_IMPUESTOS = ("impuesto", "periodo_fiscal", "fecha_limite", "moneda", "monto")


def _csv(directorio: Path, nombre: str, encabezado: Sequence[str], filas: Sequence[Sequence[str]]) -> Path:
    ruta = directorio / nombre
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, lineterminator="\n")
        escritor.writerow(encabezado)
        escritor.writerows(filas)
    return ruta


def _dia(dias: int) -> str:
    return (CORTE + timedelta(days=dias)).isoformat()


def _curva() -> Any:
    return validar_curva([
        {"tramo": "por_vencer", "dias_desde": None, "dias_hasta": 0, "pesos": ["0.60", "0.25", "0.10"]},
        {"tramo": "vencido", "dias_desde": 1, "dias_hasta": None, "pesos": ["0.50", "0.30"]},
    ])


# --- saldos bancarios -------------------------------------------------------------------


def test_saldos_validos_dan_una_fila_por_cuenta(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [
        ["CTA-2", "BANCO DOS", _dia(0), "MXN", "-1500.50"],
        ["CTA-1", "BANCO UNO", _dia(0), "MXN", "250000.00"],
    ])
    resultado = leer_saldos(ruta, CORTE, "MXN")
    assert resultado.fuente == "saldos_bancarios"
    assert resultado.archivo == "saldos.csv"
    assert resultado.sha256 == hashlib.sha256(ruta.read_bytes()).hexdigest()
    assert resultado.registros == 2
    assert resultado.total_insumo == D("248499.50")
    assert {f.referencia: f.monto for f in resultado.filas} == {"CTA-1": D("250000.00"), "CTA-2": D("-1500.50")}
    assert all(f.semana == 1 and f.fecha == CORTE and f.concepto == "saldo_inicial" for f in resultado.filas)


def test_saldo_con_fecha_distinta_al_corte_es_error(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", _dia(-1), "MXN", "10.00"]])
    with pytest.raises(ErrorInsumo, match=r"saldos\.csv, fila 1.*fecha_saldo.*corte"):
        leer_saldos(ruta, CORTE, "MXN")


def test_saldos_sin_filas_es_error(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [])
    with pytest.raises(ErrorInsumo, match="al menos una cuenta"):
        leer_saldos(ruta, CORTE, "MXN")


def test_saldos_cuenta_repetida_es_error(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [
        ["CTA-1", "BANCO UNO", _dia(0), "MXN", "10.00"],
        ["CTA-1", "BANCO UNO", _dia(0), "MXN", "20.00"],
    ])
    with pytest.raises(ErrorInsumo, match=r"fila 2.*repetid"):
        leer_saldos(ruta, CORTE, "MXN")


# --- esquema y valores inválidos (comunes a todas las fuentes) --------------------------


def test_columna_faltante_es_error_de_esquema(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS[:-1], [["CTA-1", "BANCO UNO", _dia(0), "MXN"]])
    with pytest.raises(ErrorInsumo, match=r"faltan columnas.*saldo"):
        leer_saldos(ruta, CORTE, "MXN")


def test_columna_sobrante_es_error_de_esquema(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS + ("notas",), [["CTA-1", "B", _dia(0), "MXN", "1.00", "x"]])
    with pytest.raises(ErrorInsumo, match=r"columnas no esperadas.*notas"):
        leer_saldos(ruta, CORTE, "MXN")


def test_columna_duplicada_es_error_de_esquema(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS + ("saldo",), [["CTA-1", "B", _dia(0), "MXN", "1.00", "2"]])
    with pytest.raises(ErrorInsumo, match="repetida"):
        leer_saldos(ruta, CORTE, "MXN")


def test_fila_con_campos_de_mas_o_de_menos_es_error(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", _dia(0), "MXN"]])
    with pytest.raises(ErrorInsumo, match=r"fila 1.*5 campos"):
        leer_saldos(ruta, CORTE, "MXN")
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", _dia(0), "MXN", "1.00", "x"]])
    with pytest.raises(ErrorInsumo, match=r"fila 1.*5 campos"):
        leer_saldos(ruta, CORTE, "MXN")


@pytest.mark.parametrize("monto", ["", "abc", "1,234.56", "NaN", "Infinity", "1e400000"])
def test_monto_invalido_es_error(tmp_path: Path, monto: str) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", _dia(0), "MXN", monto]])
    with pytest.raises(ErrorInsumo, match=r"fila 1, columna 'saldo'"):
        leer_saldos(ruta, CORTE, "MXN")


def test_monto_con_mas_de_dos_decimales_es_error_no_se_redondea(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", _dia(0), "MXN", "10.005"]])
    with pytest.raises(ErrorInsumo, match=r"columna 'saldo'.*a lo más 2 decimales"):
        leer_saldos(ruta, CORTE, "MXN")


@pytest.mark.parametrize("fecha", ["", "2026-02-30", "02/11/2026", "2026-11-2"])
def test_fecha_invalida_es_error(tmp_path: Path, fecha: str) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", fecha, "MXN", "1.00"]])
    with pytest.raises(ErrorInsumo, match=r"columna 'fecha_saldo'"):
        leer_saldos(ruta, CORTE, "MXN")


def test_texto_obligatorio_vacio_es_error(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["  ", "BANCO UNO", _dia(0), "MXN", "1.00"]])
    with pytest.raises(ErrorInsumo, match=r"columna 'cuenta'.*vac"):
        leer_saldos(ruta, CORTE, "MXN")


def test_moneda_distinta_a_la_config_es_error(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "saldos.csv", COLS_SALDOS, [["CTA-1", "BANCO UNO", _dia(0), "USD", "1.00"]])
    with pytest.raises(ErrorInsumo, match=r"moneda 'USD'.*'MXN'"):
        leer_saldos(ruta, CORTE, "MXN")


def test_archivo_inexistente_es_error_de_insumo(tmp_path: Path) -> None:
    with pytest.raises(ErrorInsumo, match="no se pudo leer"):
        leer_saldos(tmp_path / "no_existe.csv", CORTE, "MXN")


def test_archivo_no_utf8_es_error_de_insumo(tmp_path: Path) -> None:
    ruta = tmp_path / "saldos.csv"
    ruta.write_bytes(",".join(COLS_SALDOS).encode() + b"\nCTA-\xff1,B,2026-11-02,MXN,1.00\n")
    with pytest.raises(ErrorInsumo, match="UTF-8"):
        leer_saldos(ruta, CORTE, "MXN")


def test_archivo_vacio_es_error_de_insumo(tmp_path: Path) -> None:
    ruta = tmp_path / "saldos.csv"
    ruta.write_text("", encoding="utf-8")
    with pytest.raises(ErrorInsumo, match="encabezado"):
        leer_saldos(ruta, CORTE, "MXN")


def test_bom_utf8_se_tolera(tmp_path: Path) -> None:
    ruta = tmp_path / "saldos.csv"
    ruta.write_bytes(b"\xef\xbb\xbf" + ",".join(COLS_SALDOS).encode() + b"\nCTA-1,B,2026-11-02,MXN,7.00\n")
    assert leer_saldos(ruta, CORTE, "MXN").total_insumo == D("7.00")


# --- cuentas por cobrar -----------------------------------------------------------------


def test_cxc_reparte_con_la_curva_y_cuadra(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [
        ["CLI-1", "CLIENTE UNO", "FV-1", _dia(-60), _dia(-10), "MXN", "1000.00"],
        ["CLI-2", "CLIENTE DOS", "FV-2", _dia(-5), _dia(14), "MXN", "500.00"],
        ["CLI-2", "CLIENTE DOS", "FV-3", _dia(-1), _dia(200), "MXN", "300.00"],
    ])
    resultado = leer_cxc(ruta, CORTE, "MXN", _curva())
    assert resultado.fuente == "cxc_antiguedad"
    assert resultado.registros == 3
    assert resultado.total_insumo == D("1800.00")
    por_factura: Dict[str, List[Any]] = {}
    for fila in resultado.filas:
        por_factura.setdefault(fila.referencia, []).append((fila.semana, fila.monto))
    assert por_factura["FV-1"] == [(1, D("500.00")), (2, D("300.00"))]
    assert por_factura["FV-2"] == [(3, D("300.00")), (4, D("125.00")), (5, D("50.00"))]
    assert "FV-3" not in por_factura
    assert resultado.fuera_horizonte == D("285.00")
    assert resultado.no_cobrable == D("200.00") + D("25.00") + D("15.00")
    suma = sum((f.monto for f in resultado.filas), D("0"))
    assert suma + resultado.fuera_horizonte + resultado.no_cobrable == resultado.total_insumo
    assert all(f.concepto == "cobranza_clientes" and f.contraparte.startswith("CLIENTE") for f in resultado.filas)
    assert all(f.fecha == CORTE + timedelta(days=7 * (f.semana - 1)) for f in resultado.filas)


@pytest.mark.parametrize("fila, mensaje", [
    (["CLI-1", "C", "FV-1", _dia(1), _dia(30), "MXN", "5.00"], "posterior al corte"),
    (["CLI-1", "C", "FV-1", _dia(-10), _dia(-11), "MXN", "5.00"], "anterior a la fecha_factura"),
    (["CLI-1", "C", "NC-1", _dia(1), _dia(30), "MXN", "-5.00"], "posterior al corte"),
    (["CLI-1", "C", "FV-1", _dia(-10), _dia(-11), "MXN", "0.00"], "anterior a la fecha_factura"),
])
def test_cxc_valores_invalidos(tmp_path: Path, fila: List[str], mensaje: str) -> None:
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [fila])
    with pytest.raises(ErrorInsumo, match=mensaje):
        leer_cxc(ruta, CORTE, "MXN", _curva())


def test_cxc_saldo_negativo_resta_integro_en_la_semana_1(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [
        ["CLI-1", "CLIENTE UNO", "FV-1", _dia(-60), _dia(-10), "MXN", "1000.00"],
        ["CLI-1", "CLIENTE UNO", "NC-1", _dia(-3), _dia(40), "MXN", "-250.00"],
        ["CLI-2", "CLIENTE DOS", "AN-1", _dia(-20), _dia(-20), "MXN", "-0.01"],
    ])
    resultado = leer_cxc(ruta, CORTE, "MXN", _curva())
    acreedoras = [f for f in resultado.filas if f.marca == "saldo_acreedor"]
    assert [(f.referencia, f.semana, f.fecha, f.monto) for f in acreedoras] == [
        ("AN-1", 1, CORTE, D("-0.01")), ("NC-1", 1, CORTE, D("-250.00")),
    ]
    assert all(f.concepto == "cobranza_clientes" for f in acreedoras)
    assert {f.marca for f in resultado.filas if f.referencia == "FV-1"} == {None}
    assert resultado.total_insumo == D("749.99")
    assert resultado.no_cobrable == D("200.00")
    assert resultado.fuera_horizonte == D("0.00")
    assert resultado.registros_en_cero == 0
    suma = sum((f.monto for f in resultado.filas), D("0"))
    assert suma + resultado.fuera_horizonte + resultado.no_cobrable == resultado.total_insumo


@pytest.mark.parametrize("saldo", ["0.00", "0", "-0.00", "-0"])
def test_cxc_saldo_cero_no_genera_filas_y_se_cuenta(tmp_path: Path, saldo: str) -> None:
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [
        ["CLI-1", "C", "FV-1", _dia(-30), _dia(0), "MXN", saldo],
        ["CLI-1", "C", "FV-2", _dia(-30), _dia(-5), "MXN", "100.00"],
    ])
    resultado = leer_cxc(ruta, CORTE, "MXN", _curva())
    assert resultado.registros == 2
    assert resultado.registros_en_cero == 1
    assert {f.referencia for f in resultado.filas} == {"FV-2"}
    assert resultado.total_insumo == D("100.00")


def test_cxc_saldo_cero_tambien_cuenta_para_llave_unica(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [
        ["CLI-1", "C", "FV-1", _dia(-30), _dia(0), "MXN", "0.00"],
        ["CLI-1", "C", "FV-1", _dia(-30), _dia(0), "MXN", "5.00"],
    ])
    with pytest.raises(ErrorInsumo, match=r"fila 2.*repetid"):
        leer_cxc(ruta, CORTE, "MXN", _curva())


def test_cxc_factura_repetida_es_error(tmp_path: Path) -> None:
    fila = ["CLI-1", "C", "FV-1", _dia(-30), _dia(0), "MXN", "5.00"]
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [fila, fila])
    with pytest.raises(ErrorInsumo, match="repetid"):
        leer_cxc(ruta, CORTE, "MXN", _curva())


def test_cxc_sin_filas_es_valida_y_suma_cero(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxc.csv", COLS_CXC, [])
    resultado = leer_cxc(ruta, CORTE, "MXN", _curva())
    assert resultado.filas == () and resultado.total_insumo == D("0.00")
    assert resultado.registros_en_cero == 0


# --- egresos programados ----------------------------------------------------------------


def test_cxp_programadas_son_salidas_y_las_lejanas_quedan_fuera(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxp.csv", COLS_CXP, [
        ["PRV-1", "PROVEEDOR UNO", "FP-1", _dia(0), "MXN", "100.00"],
        ["PRV-1", "PROVEEDOR UNO", "FP-2", _dia(90), "MXN", "200.00"],
        ["PRV-2", "PROVEEDOR DOS", "FP-1", _dia(91), "MXN", "300.00"],
    ])
    resultado = leer_cxp(ruta, CORTE, "MXN")
    assert resultado.fuente == "cxp_programadas"
    assert resultado.total_insumo == D("-600.00")
    assert resultado.fuera_horizonte == D("-300.00")
    assert resultado.no_cobrable == D("0.00")
    assert [(f.semana, f.referencia, f.monto, f.fecha) for f in resultado.filas] == [
        (1, "PRV-1/FP-1", D("-100.00"), CORTE),
        (13, "PRV-1/FP-2", D("-200.00"), CORTE + timedelta(days=90)),
    ]
    assert {f.concepto for f in resultado.filas} == {"pago_proveedores"}


def test_cxp_misma_factura_de_otro_proveedor_no_es_duplicado(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxp.csv", COLS_CXP, [
        ["PRV-1", "P1", "FP-1", _dia(3), "MXN", "1.00"],
        ["PRV-2", "P2", "FP-1", _dia(3), "MXN", "1.00"],
    ])
    assert leer_cxp(ruta, CORTE, "MXN").registros == 2
    ruta = _csv(tmp_path, "cxp.csv", COLS_CXP, [
        ["PRV-1", "P1", "FP-1", _dia(3), "MXN", "1.00"],
        ["PRV-1", "P1", "FP-1", _dia(4), "MXN", "1.00"],
    ])
    with pytest.raises(ErrorInsumo, match="repetid"):
        leer_cxp(ruta, CORTE, "MXN")


@pytest.mark.parametrize("fecha, monto, mensaje", [
    (_dia(5), "0.00", "mayor que cero"),
    (_dia(-5), "0.00", "mayor que cero"),
    (_dia(5), "0.004", "a lo más 2 decimales"),
    (_dia(5), "-10.00", "mayor que cero"),
])
def test_cxp_valores_invalidos(tmp_path: Path, fecha: str, monto: str, mensaje: str) -> None:
    ruta = _csv(tmp_path, "cxp.csv", COLS_CXP, [["PRV-1", "P1", "FP-1", fecha, "MXN", monto]])
    with pytest.raises(ErrorInsumo, match=mensaje):
        leer_cxp(ruta, CORTE, "MXN")


def test_cxp_vencida_cae_en_la_semana_1_marcada(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "cxp.csv", COLS_CXP, [
        ["PRV-1", "PROVEEDOR UNO", "FP-1", _dia(-1), "MXN", "100.00"],
        ["PRV-1", "PROVEEDOR UNO", "FP-2", _dia(-45), "MXN", "40.00"],
        ["PRV-2", "PROVEEDOR DOS", "FP-3", _dia(0), "MXN", "7.00"],
    ])
    resultado = leer_cxp(ruta, CORTE, "MXN")
    assert [(f.referencia, f.semana, f.fecha, f.monto, f.marca) for f in resultado.filas] == [
        ("PRV-1/FP-1", 1, CORTE, D("-100.00"), "vencido"),
        ("PRV-1/FP-2", 1, CORTE, D("-40.00"), "vencido"),
        ("PRV-2/FP-3", 1, CORTE, D("-7.00"), None),
    ]
    assert resultado.total_insumo == D("-147.00")
    assert resultado.fuera_horizonte == D("0.00")
    assert resultado.registros_en_cero == 0


@pytest.mark.parametrize("lector, columnas, fila, referencia", [
    (leer_nomina, COLS_NOMINA, ["2026-10-Q2", "NOMINA", _dia(-2), "MXN", "9.00"], "2026-10-Q2"),
    (leer_impuestos, COLS_IMPUESTOS, ["IVA", "2026-09", _dia(-16), "MXN", "9.00"], "IVA/2026-09"),
])
def test_nomina_e_impuestos_vencidos_tambien_caen_en_la_semana_1(
    tmp_path: Path, lector: Any, columnas: Sequence[str], fila: List[str], referencia: str,
) -> None:
    resultado = lector(_csv(tmp_path, "egresos.csv", columnas, [fila]), CORTE, "MXN")
    assert [(f.referencia, f.semana, f.fecha, f.monto, f.marca) for f in resultado.filas] == [
        (referencia, 1, CORTE, D("-9.00"), "vencido"),
    ]


def test_nomina_es_salida_con_referencia_de_periodo(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "nomina.csv", COLS_NOMINA, [
        ["2026-11-Q1", "NOMINA QUINCENAL", _dia(11), "MXN", "350000.00"],
        ["2026-11-Q2", "NOMINA QUINCENAL", _dia(26), "MXN", "351000.00"],
    ])
    resultado = leer_nomina(ruta, CORTE, "MXN")
    assert resultado.fuente == "nomina"
    assert [(f.semana, f.referencia, f.monto) for f in resultado.filas] == [
        (2, "2026-11-Q1", D("-350000.00")), (4, "2026-11-Q2", D("-351000.00")),
    ]
    assert {f.concepto for f in resultado.filas} == {"pago_nomina"}
    assert {f.contraparte for f in resultado.filas} == {"NOMINA QUINCENAL"}


def test_nomina_periodo_repetido_es_error(tmp_path: Path) -> None:
    fila = ["2026-11-Q1", "NOMINA", _dia(11), "MXN", "1.00"]
    ruta = _csv(tmp_path, "nomina.csv", COLS_NOMINA, [fila, fila])
    with pytest.raises(ErrorInsumo, match="repetid"):
        leer_nomina(ruta, CORTE, "MXN")


def test_impuestos_son_salidas_por_impuesto_y_periodo(tmp_path: Path) -> None:
    ruta = _csv(tmp_path, "impuestos.csv", COLS_IMPUESTOS, [
        ["ISR", "2026-10", _dia(15), "MXN", "80000.00"],
        ["IVA", "2026-10", _dia(15), "MXN", "120000.00"],
    ])
    resultado = leer_impuestos(ruta, CORTE, "MXN")
    assert resultado.fuente == "impuestos"
    assert resultado.total_insumo == D("-200000.00")
    assert {(f.referencia, f.contraparte) for f in resultado.filas} == {("ISR/2026-10", "ISR"), ("IVA/2026-10", "IVA")}
    assert {f.concepto for f in resultado.filas} == {"pago_impuestos"}


def test_impuesto_repetido_es_error(tmp_path: Path) -> None:
    fila = ["ISR", "2026-10", _dia(15), "MXN", "1.00"]
    ruta = _csv(tmp_path, "impuestos.csv", COLS_IMPUESTOS, [fila, fila])
    with pytest.raises(ErrorInsumo, match="repetid"):
        leer_impuestos(ruta, CORTE, "MXN")


# --- todas las fuentes desde la config --------------------------------------------------


def _config_completa(tmp_path: Path) -> Path:
    datos = tmp_path / "datos"
    datos.mkdir()
    _csv(datos, "s.csv", COLS_SALDOS, [["CTA-1", "B", _dia(0), "MXN", "1000.00"]])
    _csv(datos, "c.csv", COLS_CXC, [["CLI-1", "C", "FV-1", _dia(-40), _dia(-5), "MXN", "100.00"]])
    _csv(datos, "p.csv", COLS_CXP, [["PRV-1", "P", "FP-1", _dia(2), "MXN", "10.00"]])
    _csv(datos, "n.csv", COLS_NOMINA, [["Q1", "NOMINA", _dia(3), "MXN", "20.00"]])
    _csv(datos, "i.csv", COLS_IMPUESTOS, [["ISR", "2026-10", _dia(4), "MXN", "30.00"]])
    config = {
        "esquema": "flujo_config/v1",
        "moneda": "MXN",
        "insumos": {
            "saldos_bancarios": "datos/s.csv", "cxc_antiguedad": "datos/c.csv",
            "cxp_programadas": "datos/p.csv", "nomina": "datos/n.csv", "impuestos": "datos/i.csv",
        },
        "curva_cobranza": [{"tramo": "todo", "dias_desde": None, "dias_hasta": None, "pesos": ["1"]}],
    }
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps(config), encoding="utf-8")
    return ruta


def test_leer_fuentes_usa_cada_ruta_de_la_config_en_orden(tmp_path: Path) -> None:
    resultados = leer_fuentes(cargar_config(_config_completa(tmp_path)), CORTE)
    assert tuple(r.fuente for r in resultados) == FUENTES
    assert [r.archivo for r in resultados] == ["s.csv", "c.csv", "p.csv", "n.csv", "i.csv"]
    assert [r.total_insumo for r in resultados] == [D("1000.00"), D("100.00"), D("-10.00"), D("-20.00"), D("-30.00")]
