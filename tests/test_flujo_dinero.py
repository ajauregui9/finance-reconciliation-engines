"""Pruebas de la frontera única de montos del flujo."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
MODULO = RAIZ / "skills" / "cashflow-forecasting"
if str(MODULO) not in sys.path:
    sys.path.insert(0, str(MODULO))

from flujo.dinero import CERO, a_monto, es_centavos, texto_monto  # noqa: E402

D = Decimal


@pytest.mark.parametrize("valor, esperado", [
    ("1234.5", D("1234.50")),
    (" 10.005 ", D("10.01")),
    ("-10.005", D("-10.01")),
    (7, D("7.00")),
    (D("2.345"), D("2.35")),
    (0.1, D("0.10")),
    (1.005, D("1.01")),
])
def test_a_monto_convierte_y_redondea_medio_hacia_arriba(valor: object, esperado: Decimal) -> None:
    resultado = a_monto(valor)
    assert resultado == esperado
    assert es_centavos(resultado)


def test_a_monto_normaliza_el_cero_negativo() -> None:
    assert str(a_monto("-0.001")) == "0.00"
    assert texto_monto(D("-0.00")) == "0.00"
    assert a_monto("-0.004") == CERO and not a_monto("-0.004").is_signed()


@pytest.mark.parametrize("valor, mensaje", [
    (True, "booleano"),
    (None, "tipo NoneType"),
    ([1], "tipo list"),
    ("", "no es un número"),
    ("NaN", "finito"),
    (D("Infinity"), "finito"),
    ("1e400000", "rango"),
])
def test_a_monto_rechaza_lo_que_no_es_monto(valor: object, mensaje: str) -> None:
    with pytest.raises(ValueError, match=mensaje):
        a_monto(valor)


@pytest.mark.parametrize("valor, esperado", [
    (D("1.00"), True), (D("1.0"), False), (D("1.000"), False), (D("NaN"), False), (1.0, False), ("1.00", False),
])
def test_es_centavos(valor: object, esperado: bool) -> None:
    assert es_centavos(valor) is esperado


def test_texto_monto_sin_separador_de_miles() -> None:
    assert texto_monto(D("-1234567.8")) == "-1234567.80"
