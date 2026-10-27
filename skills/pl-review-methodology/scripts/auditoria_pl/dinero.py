"""Aritmética de montos y porcentajes. Todo es `Decimal`; aquí nunca entra un `float`."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")
CIEN = Decimal("100")


def redondear(valor: Decimal) -> Decimal:
    """Redondea a centavos con ROUND_HALF_UP y normaliza el cero negativo."""
    resultado = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return resultado if resultado != 0 else CERO


def porcentaje(parte: Decimal, total: Decimal) -> Decimal:
    """`parte / total * 100`, redondeado a dos decimales. `total` no puede ser cero."""
    return redondear(parte * CIEN / total)


def proporcion(monto: Decimal, pct: Decimal) -> Decimal:
    """`monto * pct / 100`, redondeado a centavos."""
    return redondear(monto * pct / CIEN)


def texto(valor: Decimal) -> str:
    """Formato canónico de salida: `-1234.56`, sin separador de miles."""
    return f"{redondear(valor):.2f}"
