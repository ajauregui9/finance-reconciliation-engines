"""Aritmética de montos del generador. Independiente del paquete que se prueba."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")


def q2(valor: Decimal) -> Decimal:
    """Redondea a centavos, medio hacia arriba."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def texto(valor: Decimal) -> str:
    """`-1234.56`: formato de los JSON."""
    redondeado = q2(valor)
    return f"{abs(redondeado) if redondeado == 0 else redondeado:.2f}"


def texto_csv(valor: Decimal) -> str:
    """Formato de las liquidaciones: vacío si es cero, separador de miles si hace falta."""
    redondeado = q2(valor)
    return "" if redondeado == 0 else f"{redondeado:,.2f}"
