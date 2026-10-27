"""Pruebas de la frontera única de montos del módulo NetSuite."""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "netsuite-gl-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from netsuite_gl.montos import (  # noqa: E402
    ErrorMonto,
    a_decimal,
    a_decimal_opcional,
    formatear,
    tiene_centavos_exactos,
)


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("10.005", Decimal("10.01")),
        (0.1 + 0.2, Decimal("0.30")),
        (100, Decimal("100.00")),
        (Decimal("-2.345"), Decimal("-2.35")),
        (" 7.1 ", Decimal("7.10")),
        ("-0.001", Decimal("0.00")),
    ],
)
def test_a_decimal_cuantiza_al_centavo_half_up(crudo: Any, esperado: Decimal) -> None:
    resultado = a_decimal(crudo)
    assert resultado == esperado and resultado.as_tuple().exponent == -2
    assert str(resultado) == str(esperado)


@pytest.mark.parametrize("crudo", [True, "abc", "NaN", "Infinity", float("inf"), ""])
def test_a_decimal_rechaza_lo_que_no_es_monto(crudo: Any) -> None:
    with pytest.raises(ErrorMonto):
        a_decimal(crudo)


def test_opcional_formatear_y_centavos() -> None:
    assert a_decimal_opcional(None) is None
    assert a_decimal_opcional("1") == Decimal("1.00")
    assert formatear(Decimal("-0")) == "0.00"
    assert formatear(Decimal("5")) == "5.00"
    assert tiene_centavos_exactos(Decimal("1.10"))
    assert not tiene_centavos_exactos(Decimal("1.101"))
