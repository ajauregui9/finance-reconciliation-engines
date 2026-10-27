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
    CENTAVOS_MAXIMOS,
    ErrorMonto,
    a_centavos,
    a_decimal,
    a_decimal_opcional,
    desde_centavos,
    formatear,
    tiene_centavos_exactos,
)


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("10.005", Decimal("10.01")),
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


@pytest.mark.parametrize("crudo", [True, "abc", "NaN", "Infinity", float("inf"), "", 0.1 + 0.2, 1.5])
def test_a_decimal_rechaza_lo_que_no_es_monto(crudo: Any) -> None:
    with pytest.raises(ErrorMonto):
        a_decimal(crudo)


def test_a_decimal_rechaza_float_aunque_parezca_exacto() -> None:
    with pytest.raises(ErrorMonto, match="float"):
        a_decimal(100.0)


# ---------------------------------------------------------------- centavos enteros (esquema SQLite)


@pytest.mark.parametrize(
    "monto, centavos",
    [
        (Decimal("116.00"), 11600),
        (Decimal("-10.5"), -1050),
        (Decimal("0"), 0),
        (Decimal("0.01"), 1),
        (Decimal("100000000000000.01"), 10000000000000001),
    ],
)
def test_ida_y_vuelta_por_centavos_es_exacta(monto: Decimal, centavos: int) -> None:
    assert a_centavos(monto) == centavos and type(a_centavos(monto)) is int
    regreso = desde_centavos(centavos)
    assert regreso == monto and regreso.as_tuple().exponent == -2


def test_desde_centavos_no_da_cero_negativo() -> None:
    assert str(desde_centavos(0)) == "0.00"
    assert str(desde_centavos(-1)) == "-0.01"


@pytest.mark.parametrize(
    "crudo, fragmento",
    [
        (Decimal("1.001"), "dos decimales"),
        (Decimal("NaN"), "finito"),
        (Decimal(CENTAVOS_MAXIMOS + 1) / 100, "rango"),
        (1.5, "Decimal"),
        (100, "Decimal"),
        ("1.00", "Decimal"),
        (True, "Decimal"),
    ],
)
def test_a_centavos_rechaza_lo_que_no_es_un_centavo_exacto(crudo: Any, fragmento: str) -> None:
    with pytest.raises(ErrorMonto, match=fragmento):
        a_centavos(crudo)


@pytest.mark.parametrize("crudo", [True, 1.0, "100", Decimal("100"), None, CENTAVOS_MAXIMOS + 1])
def test_desde_centavos_solo_acepta_enteros_en_rango(crudo: Any) -> None:
    with pytest.raises(ErrorMonto):
        desde_centavos(crudo)


def test_opcional_formatear_y_centavos() -> None:
    assert a_decimal_opcional(None) is None
    assert a_decimal_opcional("1") == Decimal("1.00")
    assert formatear(Decimal("-0")) == "0.00"
    assert formatear(Decimal("5")) == "5.00"
    assert tiene_centavos_exactos(Decimal("1.10"))
    assert not tiene_centavos_exactos(Decimal("1.101"))
