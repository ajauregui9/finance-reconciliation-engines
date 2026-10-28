"""Frontera única de montos: todo importe del módulo es `Decimal` a dos decimales.

Hacia la base SQLite los montos viajan como centavos enteros (`a_centavos`) y de regreso
se convierten una sola vez (`desde_centavos`). Así ninguna suma ni resta del libro mayor
pasa por punto flotante: SQLite suma enteros de 64 bits de forma exacta y falla si se
desbordan.

La lectura de un monto externo delega en la frontera compartida (`frontera.leer_importe`):
hasta dos decimales, dígitos ASCII y nunca un redondeo del insumo.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Union

from frontera import ErrorFrontera, FormaImporte, leer_importe

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")
CENTAVOS_MAXIMOS = 2**63 - 1  # el mayor entero que SQLite guarda sin pasar a REAL

ValorCrudo = Union[str, int, Decimal]
FORMA_MONTO = FormaImporte(decimales=2, numeros=True)


class ErrorMonto(ValueError):
    """El valor no es un importe decimal finito."""


def a_decimal(valor: ValorCrudo) -> Decimal:
    """Convierte texto, entero o `Decimal` (hasta dos decimales) a `Decimal` en centavos, sin redondear.

    Un `float` se rechaza: su valor binario ya no es el monto que alguien escribió. Más de
    dos decimales, dígitos no ASCII o un separador de miles también son error.
    """
    if isinstance(valor, bool):
        raise ErrorMonto(f"un booleano no es un monto: {valor!r}")
    if isinstance(valor, float):
        raise ErrorMonto(f"un float no es un monto exacto: {valor!r}; llega como texto decimal")
    try:
        numero = leer_importe(valor, FORMA_MONTO)
    except ErrorFrontera as exc:
        raise ErrorMonto(f"monto inválido: {exc}") from None
    return _sin_cero_negativo(numero)


def a_decimal_opcional(valor: Optional[ValorCrudo]) -> Optional[Decimal]:
    return None if valor is None else a_decimal(valor)


def a_centavos(monto: Decimal) -> int:
    """`Decimal("116.00")` -> `11600`. Solo acepta montos exactos al centavo y dentro de rango."""
    if not isinstance(monto, Decimal):
        raise ErrorMonto(f"a_centavos recibe un Decimal, no {type(monto).__name__}: {monto!r}")
    if not monto.is_finite():
        raise ErrorMonto(f"monto no finito: {monto!r}")
    if not tiene_centavos_exactos(monto):
        raise ErrorMonto(f"el monto {monto} tiene más de dos decimales: no es un centavo exacto")
    centavos = int(monto.scaleb(2))
    _validar_rango(centavos)
    return centavos


def desde_centavos(centavos: object) -> Decimal:
    """`11600` -> `Decimal("116.00")`: la conversión de regreso, exacta, desde la base."""
    if isinstance(centavos, bool) or not isinstance(centavos, int):
        raise ErrorMonto(f"se esperaban centavos enteros y llegó {type(centavos).__name__}: {centavos!r}")
    _validar_rango(centavos)
    return Decimal(centavos).scaleb(-2)


def tiene_centavos_exactos(numero: Decimal) -> bool:
    """Verdadero si el número no tiene más de dos decimales significativos."""
    return numero == numero.quantize(CENTAVO)


def formatear(numero: Decimal) -> str:
    """Texto con exactamente dos decimales y sin `-0.00`."""
    return str(_sin_cero_negativo(numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)))


def _validar_rango(centavos: int) -> None:
    if abs(centavos) > CENTAVOS_MAXIMOS:
        raise ErrorMonto(f"{centavos} centavos está fuera del rango de un entero de 64 bits")


def _sin_cero_negativo(numero: Decimal) -> Decimal:
    return CERO if numero == 0 else numero
