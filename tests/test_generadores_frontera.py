"""Frontera de entrada de los generadores sintéticos: importes y fechas con dígitos ASCII.

Los parámetros del generador de flujo y la tolerancia de `examples/generate.py` pasan por
`frontera`: ningún valor se redondea y los dígitos de otros alfabetos se rechazan.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

RAIZ = Path(__file__).resolve().parents[1]
EJEMPLOS = RAIZ / "examples"
for ruta in (str(EJEMPLOS),):
    if ruta not in sys.path:
        sys.path.insert(0, ruta)

import generate  # noqa: E402
from generador_flujo.parametros import ErrorParametros, parametros_desde_dict  # noqa: E402

PARAMETROS = EJEMPLOS / "generador_flujo" / "parametros.json"
ARABE = "".join(chr(0x0660 + int(c)) if c.isdigit() else c for c in "100.50")
ARABE_FECHA = "".join(chr(0x0660 + int(c)) if c.isdigit() else c for c in "2026-11-02")


def _crudos() -> Dict[str, Any]:
    datos: Dict[str, Any] = json.loads(PARAMETROS.read_text(encoding="utf-8"))
    return datos


def test_monto_con_mas_de_dos_decimales_se_rechaza_sin_redondear() -> None:
    crudos = _crudos()
    crudos["nomina"]["monto_min"] = "100.005"
    with pytest.raises(ErrorParametros, match="nomina.monto_min"):
        parametros_desde_dict(crudos)


def test_monto_con_digitos_no_ascii_se_rechaza() -> None:
    crudos = _crudos()
    crudos["nomina"]["monto_min"] = ARABE
    with pytest.raises(ErrorParametros, match="nomina.monto_min"):
        parametros_desde_dict(crudos)


def test_monto_entero_se_lleva_a_dos_decimales() -> None:
    crudos = _crudos()
    crudos["nomina"]["monto_min"] = "100"
    assert parametros_desde_dict(crudos).nomina.rango.minimo == Decimal("100.00")


def test_corte_con_digitos_no_ascii_se_rechaza() -> None:
    crudos = _crudos()
    crudos["corte"] = ARABE_FECHA
    with pytest.raises(ErrorParametros, match="corte"):
        parametros_desde_dict(crudos)


@pytest.mark.parametrize("tolerancia", [ARABE, "1.005", "uno"])
def test_tolerancia_fuera_de_contrato_sale_con_codigo_2(
    tolerancia: str, tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    assert generate.main(["--salida", str(tmp_path / "x"), "--tolerancia", tolerancia]) == 2
    assert "Parámetros inválidos" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()
