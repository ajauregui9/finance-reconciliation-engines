"""Lectura y formato de importes del universo de cargos.

La lectura delega en la frontera compartida (`frontera.leer_importe`): dígitos solo
ASCII, ningún redondeo de insumos, espacios ASCII recortados al borde de las celdas.
Este módulo fija las formas del universo: celdas con exactamente dos decimales, tipo de
cambio positivo con hasta cuatro y montos del resumen como texto `-1234.56` sin
separador de miles ni espacios.

Las funciones de lectura de celdas devuelven `None` cuando el texto no tiene la
forma esperada: quien llama decide el motivo con que se marca la fila. La
lectura del resumen, en cambio, lanza `ValueError`, porque un resumen mal
formado detiene la corrida.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

from frontera import CENTAVO, ErrorFrontera, FormaImporte
from frontera import leer_importe as _leer

DIEZMILESIMA = Decimal("0.0001")
DECIMALES_TIPO_CAMBIO = 4

_FORMAS_CELDA = {
    (signo, miles): FormaImporte(decimales=2, exactos=True, negativo=signo, miles=miles)
    for signo in (False, True)
    for miles in (False, True)
}
_FORMA_TIPO_CAMBIO = FormaImporte(decimales=DECIMALES_TIPO_CAMBIO, negativo=False)
_FORMA_RESUMEN = FormaImporte(decimales=2, exactos=True, recortar=False)

__all__ = ["CENTAVO", "DIEZMILESIMA", "ErrorFrontera", "a_centavos", "leer_importe", "leer_monto_resumen",
           "leer_tipo_cambio", "texto_monto", "texto_tipo_cambio"]


def a_centavos(valor: Decimal) -> Decimal:
    """Redondea a dos decimales con mitad hacia arriba (solo valores calculados, nunca insumos)."""
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def leer_importe(texto: str, *, con_signo: bool, con_miles: bool) -> Optional[Decimal]:
    """Lee un importe de celda con exactamente dos decimales.

    `con_signo` permite un `-` inicial; `con_miles` permite comas de miles bien
    colocadas (sin exigirlas). Devuelve `None` si el texto no tiene esa forma.
    """
    try:
        return _leer(texto, _FORMAS_CELDA[(con_signo, con_miles)])
    except ErrorFrontera:
        return None


def leer_tipo_cambio(texto: str) -> Optional[Decimal]:
    """Lee un tipo de cambio positivo con hasta cuatro decimales, o `None`."""
    try:
        valor = _leer(texto, _FORMA_TIPO_CAMBIO)
    except ErrorFrontera:
        return None
    return valor if valor > 0 else None


def leer_monto_resumen(valor: object, campo: str) -> Decimal:
    """Lee un monto del resumen: texto `-1234.56` sin separador de miles.

    Rechaza números JSON (int, float, bool) y cualquier otra forma, con un
    mensaje que nombra el campo.
    """
    if not isinstance(valor, str):
        raise ValueError(
            f"{campo}: se esperaba texto con dos decimales, llegó {type(valor).__name__}")
    try:
        return _leer(valor, _FORMA_RESUMEN)
    except ErrorFrontera as error:
        raise ValueError(f"{campo}: {valor!r} no tiene la forma -1234.56 ({error})") from None


def texto_monto(valor: Decimal) -> str:
    """Formato canónico de salida de un importe: `-1234.56`."""
    return f"{a_centavos(valor):.2f}"


def texto_tipo_cambio(valor: Decimal) -> str:
    """Formato canónico de salida de un tipo de cambio: cuatro decimales."""
    return f"{valor.quantize(DIEZMILESIMA, rounding=ROUND_HALF_UP):.4f}"
