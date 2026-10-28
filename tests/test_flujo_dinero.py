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
    (" 10.01 ", D("10.01")),
    ("-10.05", D("-10.05")),
    ("7", D("7.00")),
])
def test_a_monto_convierte_texto_sin_redondear(valor: object, esperado: Decimal) -> None:
    resultado = a_monto(valor)
    assert resultado == esperado
    assert es_centavos(resultado)


def test_a_monto_normaliza_el_cero_negativo() -> None:
    assert str(a_monto("-0.00")) == "0.00"
    assert texto_monto(D("-0.00")) == "0.00"
    assert a_monto("-0.00") == CERO and not a_monto("-0.00").is_signed()


@pytest.mark.parametrize("valor, mensaje", [
    (True, "no es un importe"),
    (None, "NoneType"),
    ([1], "list"),
    ("", "vacío"),
    ("NaN", "no es un importe"),
    (D("Infinity"), "se espera texto"),
    ("1e400000", "no es un importe"),
    ("9" * 40, "rango"),
    (" 10.005 ", "a lo más 2 decimales"),
    ("-0.001", "a lo más 2 decimales"),
    (7, "se espera texto"),
    (D("2.34"), "se espera texto"),
    (0.1, "se espera texto"),
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
