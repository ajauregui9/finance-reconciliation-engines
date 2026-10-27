"""Frontera única de montos: todo importe del módulo es `Decimal` a dos decimales."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Optional, Union

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")

ValorCrudo = Union[str, int, float, Decimal]


class ErrorMonto(ValueError):
    """El valor no es un importe decimal finito."""


def a_decimal(valor: ValorCrudo) -> Decimal:
    """Convierte texto, entero, `float` o `Decimal` a `Decimal` cuantizado al centavo.

    El `float` solo aparece al leer resultados de SQLite; pasa por `str` para no arrastrar
    el error binario de representación.
    """
    if isinstance(valor, bool):
        raise ErrorMonto(f"un booleano no es un monto: {valor!r}")
    texto = str(valor).strip() if isinstance(valor, (str, float)) else valor
    try:
        numero = Decimal(texto)
    except (InvalidOperation, ValueError) as exc:
        raise ErrorMonto(f"monto inválido: {valor!r}") from exc
    if not numero.is_finite():
        raise ErrorMonto(f"monto no finito: {valor!r}")
    return _sin_cero_negativo(numero.quantize(CENTAVO, rounding=ROUND_HALF_UP))


def a_decimal_opcional(valor: Optional[ValorCrudo]) -> Optional[Decimal]:
    return None if valor is None else a_decimal(valor)


def tiene_centavos_exactos(numero: Decimal) -> bool:
    """Verdadero si el número no tiene más de dos decimales significativos."""
    return numero == numero.quantize(CENTAVO)


def formatear(numero: Decimal) -> str:
    """Texto con exactamente dos decimales y sin `-0.00`."""
    return str(_sin_cero_negativo(numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)))


def _sin_cero_negativo(numero: Decimal) -> Decimal:
    return CERO if numero == 0 else numero
