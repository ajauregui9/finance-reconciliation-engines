"""Contrato de los umbrales de la evaluación de `prompt_guard` (`--deteccion-minima`, `--falsos-maximos`).

Una proporción es texto decimal con dígitos ASCII entre 0 y 1. Otra forma (dígitos de otro
alfabeto, `NaN`, exponentes) sale con código 2 y un mensaje, nunca con una traza.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

import evaluar_guardia as ev


@pytest.mark.parametrize("texto, esperado", [("0.95", "0.95"), ("0", "0"), ("1", "1"), (" 0.5 ", "0.5")])
def test_proporcion_valida(texto: str, esperado: str) -> None:
    assert ev._proporcion(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", ["٠.٥", "NaN", "Infinity", "1e-1", "0,5", "1.5", "-0.1", ""])
def test_proporcion_fuera_de_contrato_sale_con_2(texto: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert ev.main(["--deteccion-minima", texto]) == 2
    assert "evaluar_guardia:" in capsys.readouterr().err
