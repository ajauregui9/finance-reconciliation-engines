"""Pruebas del generador sintético de insumos de flujo de efectivo.

Leen los archivos escritos, que son el contrato público del generador.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import subprocess
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLOS = RAIZ / "examples"
if str(EJEMPLOS) not in sys.path:
    sys.path.insert(0, str(EJEMPLOS))

from generador_flujo import ARCHIVOS, cargar_parametros, contenidos, escribir_salida, generar  # noqa: E402
from generador_flujo.__main__ import main as main_generador  # noqa: E402
from generador_flujo.parametros import ErrorParametros, parametros_desde_dict  # noqa: E402

PARAMETROS = EJEMPLOS / "generador_flujo" / "parametros.json"
VERSIONADO = EJEMPLOS / "synthetic_flujo"
SABADO = 5
D = Decimal


def _crudos() -> Dict[str, Any]:
    datos: Dict[str, Any] = json.loads(PARAMETROS.read_text(encoding="utf-8"))
    return datos


def _filas(texto: str) -> List[Dict[str, str]]:
    return list(csv.DictReader(io.StringIO(texto)))


@pytest.fixture(scope="module")
def generados() -> Dict[str, str]:
    return contenidos(generar(cargar_parametros(PARAMETROS)))


def test_dos_corridas_dan_archivos_identicos(tmp_path: Path) -> None:
    parametros = cargar_parametros(PARAMETROS)
    rutas_a = escribir_salida(generar(parametros), tmp_path / "a")
    rutas_b = escribir_salida(generar(parametros), tmp_path / "b")
    assert [r.name for r in rutas_a] == sorted(ARCHIVOS)
    for ruta_a, ruta_b in zip(rutas_a, rutas_b):
        assert hashlib.sha256(ruta_a.read_bytes()).hexdigest() == hashlib.sha256(ruta_b.read_bytes()).hexdigest()


def test_archivos_versionados_coinciden_con_el_generador(generados: Dict[str, str]) -> None:
    for nombre, texto in generados.items():
        assert (VERSIONADO / nombre).read_text(encoding="utf-8") == texto, nombre


def test_otra_semilla_cambia_los_datos() -> None:
    otra = parametros_desde_dict({**_crudos(), "semilla": 99})
    assert contenidos(generar(otra)) != contenidos(generar(cargar_parametros(PARAMETROS)))


def test_totales_de_control_cuadran_con_los_csv(generados: Dict[str, str]) -> None:
    control = json.loads(generados["totales_control.json"])
    assert control["esquema"] == "totales_control_flujo/v2"
    columnas = {"saldos_bancarios": "saldo", "cxc_antiguedad": "saldo", "cxp_programadas": "monto",
                "nomina": "monto", "impuestos": "monto"}
    for fuente, columna in columnas.items():
        filas = _filas(generados[f"{fuente}.csv"])
        assert control["fuentes"][fuente]["registros"] == len(filas) > 0
        assert D(control["fuentes"][fuente]["suma"]) == sum((D(f[columna]) for f in filas), D("0"))


def test_cxc_planta_las_antiguedades_borde(generados: Dict[str, str]) -> None:
    crudos = _crudos()
    corte = date.fromisoformat(crudos["corte"])
    filas = _filas(generados["cxc_antiguedad.csv"])
    antiguedades = {(corte - date.fromisoformat(f["fecha_vencimiento"])).days for f in filas}
    assert set(crudos["cxc_antiguedad"]["antiguedades_borde"]) <= antiguedades
    assert any(a <= 0 for a in antiguedades) and any(a > 0 for a in antiguedades)
    for fila in filas:
        assert date.fromisoformat(fila["fecha_factura"]) <= corte
        assert date.fromisoformat(fila["fecha_vencimiento"]) >= date.fromisoformat(fila["fecha_factura"])
    positivos = [D(f["saldo"]) for f in filas if D(f["saldo"]) > 0]
    assert len(positivos) == crudos["cxc_antiguedad"]["facturas"]
    assert all(D(crudos["cxc_antiguedad"]["monto_min"]) <= s <= D(crudos["cxc_antiguedad"]["monto_max"])
               for s in positivos)
    assert len({f["factura"] for f in filas}) == len(filas)


def test_cxc_planta_saldos_acreedores_y_saldos_en_cero(generados: Dict[str, str]) -> None:
    crudos = _crudos()["cxc_antiguedad"]
    filas = _filas(generados["cxc_antiguedad.csv"])
    acreedores = [D(f["saldo"]) for f in filas if D(f["saldo"]) < 0]
    rango = crudos["saldos_acreedores"]
    assert len(acreedores) == rango["registros"] > 0
    assert all(D(rango["monto_min"]) <= -s <= D(rango["monto_max"]) for s in acreedores)
    assert sum(1 for f in filas if D(f["saldo"]) == 0) == crudos["saldos_cero"] > 0
    casos = json.loads(generados["totales_control.json"])["casos"]
    assert casos["cxc_saldo_acreedor"] == {"registros": len(acreedores), "suma": f"{sum(acreedores):.2f}"}
    assert casos["cxc_saldo_cero"] == {"registros": crudos["saldos_cero"]}


def test_cxp_planta_los_dias_borde_del_horizonte(generados: Dict[str, str]) -> None:
    crudos = _crudos()
    corte = date.fromisoformat(crudos["corte"])
    filas = _filas(generados["cxp_programadas.csv"])
    dias = {(date.fromisoformat(f["fecha_programada"]) - corte).days for f in filas}
    assert set(crudos["cxp_programadas"]["dias_borde"]) <= dias
    assert max(dias) <= crudos["dias_programacion"]
    assert len({(f["proveedor_id"], f["factura"]) for f in filas}) == len(filas)


def test_cxp_planta_pagos_vencidos_antes_del_corte(generados: Dict[str, str]) -> None:
    crudos = _crudos()
    corte = date.fromisoformat(crudos["corte"])
    filas = _filas(generados["cxp_programadas.csv"])
    vencidas = [f for f in filas if date.fromisoformat(f["fecha_programada"]) < corte]
    dias = sorted((date.fromisoformat(f["fecha_programada"]) - corte).days for f in vencidas)
    assert dias == sorted(crudos["cxp_programadas"]["dias_vencidos"]) and dias
    assert len(filas) == crudos["cxp_programadas"]["facturas"] + len(dias)
    casos = json.loads(generados["totales_control.json"])["casos"]
    suma = sum((D(f["monto"]) for f in vencidas), D("0"))
    assert casos["egresos_vencidos"] == {"registros": len(vencidas), "suma": f"{suma:.2f}"}


def test_nomina_e_impuestos_caen_en_dias_habiles_dentro_de_la_ventana(generados: Dict[str, str]) -> None:
    crudos = _crudos()
    corte = date.fromisoformat(crudos["corte"])
    fin = corte + timedelta(days=crudos["dias_programacion"])
    for nombre, columna in (("nomina.csv", "fecha_pago"), ("impuestos.csv", "fecha_limite")):
        fechas = [date.fromisoformat(f[columna]) for f in _filas(generados[nombre])]
        assert fechas and all(corte <= f <= fin and f.weekday() < SABADO for f in fechas), nombre
    impuestos = _filas(generados["impuestos.csv"])
    conceptos = {c["impuesto"] for c in crudos["impuestos"]["conceptos"]}
    assert {f["impuesto"] for f in impuestos} == conceptos
    assert len({(f["impuesto"], f["periodo_fiscal"]) for f in impuestos}) == len(impuestos)


def test_saldos_tienen_la_fecha_de_corte(generados: Dict[str, str]) -> None:
    crudos = _crudos()
    filas = _filas(generados["saldos_bancarios.csv"])
    assert {f["fecha_saldo"] for f in filas} == {crudos["corte"]}
    assert [f["cuenta"] for f in filas] == sorted(c["cuenta"] for c in crudos["saldos_bancarios"]["cuentas"])


def test_csv_con_lf_sin_bom_y_montos_con_dos_decimales(generados: Dict[str, str]) -> None:
    for nombre, texto in generados.items():
        assert "\r" not in texto and not texto.startswith("﻿"), nombre
        if nombre.endswith(".csv"):
            for fila in _filas(texto):
                monto = fila.get("saldo") or fila.get("monto")
                assert monto is not None and D(monto) == D(monto).quantize(D("0.01")) and "." in monto


# --- parámetros inválidos ---------------------------------------------------------------


def _con(ruta: str, valor: Any) -> Dict[str, Any]:
    crudos = _crudos()
    partes = ruta.split(".")
    destino = crudos
    for parte in partes[:-1]:
        destino = destino[parte]
    destino[partes[-1]] = valor
    return crudos


@pytest.mark.parametrize("crudos, mensaje", [
    ({**_crudos(), "extra": 1}, "desconocidas"),
    (_con("esquema", "otro"), "esquema"),
    (_con("semilla", "1"), "entero"),
    (_con("corte", "02/11/2026"), "fecha"),
    (_con("cxc_antiguedad.monto_min", 10.5), "texto decimal"),
    (_con("cxc_antiguedad.monto_min", "900000.00"), "monto_min"),
    (_con("cxc_antiguedad.facturas", 0), "mayor que cero"),
    (_con("cxc_antiguedad.plazos_dias", [15]), "plazo"),
    (_con("cxp_programadas.dias_borde", [500]), "dias_programacion"),
    (_con("cxp_programadas.dias_borde", [-1]), "dias_programacion"),
    (_con("cxp_programadas.dias_vencidos", [0]), "dias_vencidos"),
    (_con("cxp_programadas.dias_vencidos", [-3, -3]), "repetid"),
    (_con("cxp_programadas.dias_vencidos", "x"), "lista"),
    (_con("cxc_antiguedad.saldos_cero", -1), "saldos_cero"),
    (_con("cxc_antiguedad.saldos_cero", True), "saldos_cero"),
    (_con("cxc_antiguedad.saldos_acreedores.registros", -2), "saldos_acreedores"),
    (_con("cxc_antiguedad.saldos_acreedores.monto_min", "0.00"), "mayor que cero"),
    (_con("cxc_antiguedad.saldos_acreedores", {"registros": 1}), "faltan"),
    (_con("impuestos.dia_limite", 31), "dia_limite"),
    (_con("saldos_bancarios.cuentas", []), "al menos una"),
])
def test_parametros_invalidos_son_error(crudos: Dict[str, Any], mensaje: str) -> None:
    with pytest.raises(ErrorParametros, match=mensaje):
        parametros_desde_dict(crudos)


def test_cli_del_generador(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main_generador(["--salida", str(tmp_path / "out")]) == 0
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(ARCHIVOS)
    assert json.loads(capsys.readouterr().out)["archivos"] == sorted(ARCHIVOS)
    malo = tmp_path / "malo.json"
    malo.write_text("{}", encoding="utf-8")
    assert main_generador(["--parametros", str(malo), "--salida", str(tmp_path / "x")]) == 2
    assert not (tmp_path / "x").exists()


def test_sanitizer_no_encuentra_huellas_en_los_datos(tmp_path: Path) -> None:
    corrida = subprocess.run(
        [sys.executable, str(RAIZ / "tools" / "sanitize_audit.py"), "audit", str(VERSIONADO)],
        capture_output=True, text=True, check=False,
    )
    assert corrida.returncode == 0, corrida.stdout + corrida.stderr
