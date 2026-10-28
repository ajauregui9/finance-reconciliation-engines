"""Frontera única de montos: todo importe del flujo es `Decimal` con dos decimales.

La lectura delega en la frontera compartida (`frontera.leer_importe`): texto con signo
opcional y hasta dos decimales, dígitos ASCII, sin separador de miles. Un insumo nunca se
redondea; `centavos` redondea solo valores calculados.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from frontera import CENTAVO, ErrorFrontera, FormaImporte, leer_importe

CERO = Decimal("0.00")
EXPONENTE_CENTAVOS = CENTAVO.as_tuple().exponent
FORMA_MONTO = FormaImporte(decimales=2)


def centavos(valor: Decimal) -> Decimal:
    """Redondea a centavos (medio hacia arriba) y normaliza el cero negativo."""
    redondeado = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return redondeado if redondeado != 0 else CERO


def a_monto(valor: object) -> Decimal:
    """Convierte el texto de un monto (`-1234.56`, hasta dos decimales) en un `Decimal` en centavos.

    Solo texto: un número, un float, más de dos decimales, dígitos no ASCII o un separador
    de miles lanzan `ValueError` con un mensaje legible. `-0.00` se normaliza a `0.00`.
    """
    try:
        numero = leer_importe(valor, FORMA_MONTO)
    except ErrorFrontera as exc:
        raise ValueError(str(exc)) from None
    return numero if numero != 0 else CERO


def es_centavos(valor: object) -> bool:
    """Verdadero si `valor` es un `Decimal` finito con exactamente dos decimales."""
    return (
        isinstance(valor, Decimal)
        and valor.is_finite()
        and valor.as_tuple().exponent == EXPONENTE_CENTAVOS
    )


def texto_monto(valor: Decimal) -> str:
    """Formato canónico de salida: `-1234.56`, sin separador de miles."""
    return f"{centavos(valor):.2f}"
