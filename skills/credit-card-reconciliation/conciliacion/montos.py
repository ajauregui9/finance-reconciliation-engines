"""Lectura y formato de importes del universo de cargos.

Todo importe se representa con `Decimal`. Ningún insumo de esta etapa trae
floats: los CSV son texto y el resumen exige texto. Por eso las funciones de
lectura validan la forma exacta del texto con expresiones que solo aceptan
dígitos ASCII (`[0-9]`, nunca `\\d`, que en Python admite dígitos de cualquier
alfabeto) y construyen el `Decimal` directamente del texto validado.

Las funciones de lectura de celdas devuelven `None` cuando el texto no tiene la
forma esperada: quien llama decide el motivo con que se marca la fila. La
lectura del resumen, en cambio, lanza `ValueError`, porque un resumen mal
formado detiene la corrida.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Pattern

CENTAVO = Decimal("0.01")
DIEZMILESIMA = Decimal("0.0001")
DECIMALES_TIPO_CAMBIO = 4

# Parte entera con comas de miles bien colocadas, o sin agrupar.
_ENTERO_CON_MILES = r"(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)"
_ENTERO_SIMPLE = r"[0-9]+"
_CENTAVOS = r"\.[0-9]{2}"


def _patron_importe(con_signo: bool, con_miles: bool) -> Pattern[str]:
    signo = "-?" if con_signo else ""
    entero = _ENTERO_CON_MILES if con_miles else _ENTERO_SIMPLE
    return re.compile(f"{signo}{entero}{_CENTAVOS}")


_PATRONES_IMPORTE = {
    (signo, miles): _patron_importe(signo, miles)
    for signo in (False, True)
    for miles in (False, True)
}
_PATRON_TIPO_CAMBIO = re.compile(r"[0-9]+(?:\.[0-9]{1,%d})?" % DECIMALES_TIPO_CAMBIO)
_PATRON_MONTO_RESUMEN = _patron_importe(con_signo=True, con_miles=False)


def a_centavos(valor: Decimal) -> Decimal:
    """Redondea a dos decimales con mitad hacia arriba."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def leer_importe(texto: str, *, con_signo: bool, con_miles: bool) -> Optional[Decimal]:
    """Lee un importe de celda con exactamente dos decimales.

    `con_signo` permite un `-` inicial; `con_miles` permite comas de miles bien
    colocadas (sin exigirlas). Devuelve `None` si el texto no tiene esa forma.
    """
    limpio = texto.strip()
    if not _PATRONES_IMPORTE[(con_signo, con_miles)].fullmatch(limpio):
        return None
    return Decimal(limpio.replace(",", ""))


def leer_tipo_cambio(texto: str) -> Optional[Decimal]:
    """Lee un tipo de cambio positivo con hasta cuatro decimales, o `None`."""
    limpio = texto.strip()
    if not _PATRON_TIPO_CAMBIO.fullmatch(limpio):
        return None
    valor = Decimal(limpio)
    return valor if valor > 0 else None


def leer_monto_resumen(valor: object, campo: str) -> Decimal:
    """Lee un monto del resumen: texto `-1234.56` sin separador de miles.

    Rechaza números JSON (int, float, bool) y cualquier otra forma, con un
    mensaje que nombra el campo.
    """
    if not isinstance(valor, str):
        raise ValueError(
            f"{campo}: se esperaba texto con dos decimales, llegó {type(valor).__name__}")
    if not _PATRON_MONTO_RESUMEN.fullmatch(valor):
        raise ValueError(f"{campo}: {valor!r} no tiene la forma -1234.56")
    return Decimal(valor)


def texto_monto(valor: Decimal) -> str:
    """Formato canónico de salida de un importe: `-1234.56`."""
    return f"{a_centavos(valor):.2f}"


def texto_tipo_cambio(valor: Decimal) -> str:
    """Formato canónico de salida de un tipo de cambio: cuatro decimales."""
    return f"{valor.quantize(DIEZMILESIMA, rounding=ROUND_HALF_UP):.4f}"
