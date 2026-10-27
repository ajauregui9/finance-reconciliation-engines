"""Aritmética y formato de montos. Todo monto es `Decimal`; nunca `float`."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

CENTAVO = Decimal("0.01")
DIEZMILESIMA = Decimal("0.0001")
TASA_IVA = Decimal("0.16")
CERO = Decimal("0.00")


def q2(valor: Decimal) -> Decimal:
    """Redondea a centavos con ROUND_HALF_UP."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def q4(valor: Decimal) -> Decimal:
    """Redondea a cuatro decimales (tipos de cambio)."""
    return valor.quantize(DIEZMILESIMA, rounding=ROUND_HALF_UP)


def desde_centavos(centavos: int) -> Decimal:
    return q2(Decimal(centavos) / 100)


def separar_iva(total: Decimal) -> Tuple[Decimal, Decimal]:
    """Devuelve (subtotal, iva) tales que subtotal + iva == total, al centavo."""
    subtotal = q2(total / (1 + TASA_IVA))
    return subtotal, q2(total - subtotal)


def texto(valor: Decimal) -> str:
    """Formato canónico de salida: `-1234.56` (sin separador de miles)."""
    return f"{q2(valor):.2f}"


def texto_miles(valor: Decimal) -> str:
    """Formato con separador de miles: `-1,234.56`."""
    return f"{q2(valor):,.2f}"


def texto_tc(valor: Decimal) -> str:
    """Formato de tipo de cambio con cuatro decimales."""
    return f"{q4(valor):.4f}"
