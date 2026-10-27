"""Frontera de montos: el único lugar donde un valor externo se vuelve `Decimal`.

Todos los lectores pasan cada monto por `a_decimal`. Las tasas de la config pasan por
`a_tasa`, que valida igual pero conserva todos sus decimales.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")
_SEIS_DECIMALES = Decimal("0.000001")


def q2(valor: Decimal) -> Decimal:
    """Cuantiza a centavos con medio hacia arriba."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _interpretar(valor: object) -> Decimal:
    if isinstance(valor, bool) or valor is None:
        raise ValueError(f"no es un monto: {valor!r}")
    if isinstance(valor, Decimal):
        numero = valor
    elif isinstance(valor, (int, float)):
        numero = Decimal(str(valor))
    elif isinstance(valor, str):
        limpio = valor.strip().replace(",", "")
        if not limpio:
            return CERO
        try:
            numero = Decimal(limpio)
        except InvalidOperation as exc:
            raise ValueError(f"no es un monto: {valor!r}") from exc
    else:
        raise ValueError(f"tipo de monto no admitido: {type(valor).__name__}")
    if not numero.is_finite():
        raise ValueError(f"monto no finito: {valor!r}")
    return numero


def a_decimal(valor: object) -> Decimal:
    """Convierte texto, entero, float o Decimal a monto con dos decimales.

    El texto acepta separador de miles y vacío significa cero. Un float pasa por su
    representación de texto para no arrastrar el error binario.
    """
    return q2(_interpretar(valor))


def a_tasa(valor: object) -> Decimal:
    """Convierte una tasa de config. Solo texto o Decimal, sin redondear."""
    if not isinstance(valor, (str, Decimal)):
        raise ValueError(f"la tasa debe venir como texto, no {type(valor).__name__}")
    if isinstance(valor, str) and not valor.strip():
        raise ValueError("tasa vacía")
    return _interpretar(valor)


def _sin_cero_negativo(valor: Decimal) -> Decimal:
    return abs(valor) if valor == 0 else valor


def texto_monto(valor: Decimal) -> str:
    """Formato canónico de salida: `-1234.56`, sin separador de miles."""
    return f"{_sin_cero_negativo(q2(valor)):.2f}"


def texto_tasa(valor: Decimal) -> str:
    """Formato canónico de una tasa: seis decimales."""
    redondeada = valor.quantize(_SEIS_DECIMALES, rounding=ROUND_HALF_UP)
    return f"{_sin_cero_negativo(redondeada):.6f}"
