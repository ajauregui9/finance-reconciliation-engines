"""Frontera de montos: el único lugar donde un valor externo se vuelve `Decimal`.

Todos los lectores pasan cada monto por `a_decimal`, que delega en la frontera compartida
(`frontera.leer_importe`): texto con comas de miles opcionales y bien colocadas, o número
JSON; hasta dos decimales, dígitos ASCII, nunca se redondea. Las tasas de la config pasan
por `a_tasa`, que valida igual pero conserva todos sus decimales. `tasa_releida` convierte
la tasa que openpyxl devuelve como float al volver a leer el xlsx propio.
"""
from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

from frontera import CENTAVO, ErrorFrontera, FormaImporte, leer_importe

CERO = Decimal("0.00")
_SEIS_DECIMALES = Decimal("0.000001")
FORMA_MONTO = FormaImporte(decimales=2, miles=True, numeros=True)
FORMA_TASA = FormaImporte(decimales=None, numeros=True)


def q2(valor: Decimal) -> Decimal:
    """Cuantiza a centavos con medio hacia arriba (solo valores calculados, nunca insumos)."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def a_decimal(valor: object, *, vacio_es_cero: bool = False) -> Decimal:
    """Convierte texto, entero, float o Decimal a monto con dos decimales, sin redondear.

    El texto acepta separador de miles bien colocado. Un float pasa por su `repr` y se
    rechaza si es ambiguo o trae más de dos decimales significativos. Un texto vacío es
    cero solo con `vacio_es_cero` (celdas de la liquidación, spec 2.1); en otro caso es error.
    """
    if vacio_es_cero and isinstance(valor, str) and not valor.strip():
        return CERO
    try:
        return leer_importe(valor, FORMA_MONTO)
    except ErrorFrontera as exc:
        raise ValueError(f"monto inválido: {exc}") from None


def a_tasa(valor: object) -> Decimal:
    """Convierte una tasa de config. Solo texto o Decimal, sin redondear."""
    if not isinstance(valor, (str, Decimal)):
        raise ValueError(f"la tasa debe venir como texto, no {type(valor).__name__}")
    try:
        return leer_importe(valor, FORMA_TASA)
    except ErrorFrontera as exc:
        raise ValueError(f"tasa inválida: {exc}") from None


def tasa_releida(valor: object) -> Decimal:
    """Tasa leída de vuelta del xlsx propio (openpyxl la entrega como float), vía su `repr`.

    No es un insumo: se compara contra la tasa calculada a seis decimales, así que no se
    exige un número máximo de dígitos.
    """
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        raise ValueError(f"se esperaba un número y se leyó {valor!r}")
    if isinstance(valor, float) and not math.isfinite(valor):
        raise ValueError(f"tasa no finita: {valor!r}")
    return Decimal(repr(valor)) if isinstance(valor, float) else Decimal(valor)


def _sin_cero_negativo(valor: Decimal) -> Decimal:
    return abs(valor) if valor == 0 else valor


def texto_monto(valor: Decimal) -> str:
    """Formato canónico de salida: `-1234.56`, sin separador de miles."""
    return f"{_sin_cero_negativo(q2(valor)):.2f}"


def texto_tasa(valor: Decimal) -> str:
    """Formato canónico de una tasa: seis decimales."""
    redondeada = valor.quantize(_SEIS_DECIMALES, rounding=ROUND_HALF_UP)
    return f"{_sin_cero_negativo(redondeada):.6f}"
