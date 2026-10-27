"""Frontera única de montos: todo importe del flujo es `Decimal` con dos decimales."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")
EXPONENTE_CENTAVOS = CENTAVO.as_tuple().exponent


def centavos(valor: Decimal) -> Decimal:
    """Redondea a centavos (medio hacia arriba) y normaliza el cero negativo."""
    redondeado = valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return redondeado if redondeado != 0 else CERO


def a_monto(valor: object) -> Decimal:
    """Convierte texto, entero, `Decimal` o `float` en un monto en centavos.

    Es el único lugar donde un `float` puede volverse dinero (vía su `str`).
    Lanza `ValueError` con un mensaje legible si el valor no es un monto.
    """
    if isinstance(valor, bool):
        raise ValueError("un booleano no es un monto")
    if isinstance(valor, float):
        valor = str(valor)
    if isinstance(valor, str):
        texto = valor.strip()
        try:
            numero = Decimal(texto)
        except InvalidOperation:
            raise ValueError(f"'{texto}' no es un número decimal (usa punto y sin separador de miles)") from None
    elif isinstance(valor, (int, Decimal)):
        numero = Decimal(valor)
    else:
        raise ValueError(f"tipo {type(valor).__name__} no es un monto")
    if not numero.is_finite():
        raise ValueError(f"'{valor}' no es un monto finito")
    try:
        return centavos(numero)
    except InvalidOperation:
        raise ValueError(f"'{valor}' está fuera del rango representable") from None


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
