"""Reglas deterministas sobre la propuesta del modelo: forma de cada campo y cuadre de montos.

Cada falla es una `Observacion`; ninguna regla corrige un valor. Las observaciones salen en
el orden de los campos y luego las que cruzan campos (cuadre, receptor).

El cuadre es la identidad del CFDI: subtotal − descuento + IVA + IEPS − ISR retenido − IVA
retenido = total, dentro de `tolerancia_cuadre` (redondeo de centavos). Un monto opcional en
`null` vale cero; si algún monto presente no es válido, el cuadre no se evalúa (ya hay una
observación `monto_invalido`).
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import List, Optional, Tuple

from .config import Config
from .modelo import (
    CAMPO_AUSENTE,
    CAMPOS,
    CAMPOS_MONTO,
    CAMPOS_OPCIONALES,
    FECHA_INVALIDA,
    MONEDA_NO_PERMITIDA,
    MONTO_INVALIDO,
    NO_CUADRA,
    RECEPTOR_DISTINTO,
    RFC_INVALIDO,
    UUID_INVALIDO,
    Campos,
    Observacion,
    monto_estricto,
    texto_monto,
)

# Forma SAT: 3 letras (moral) o 4 (física), 6 dígitos de fecha y homoclave de 3.
FORMA_RFC_SAT = re.compile(r"[A-ZÑ&]{3,4}[0-9]{6}[A-Z0-9]{2}[0-9A]")
# Marcador sintético del repo (nunca hay RFCs con forma real en los datos versionados).
FORMA_RFC_MARCADOR = re.compile(r"RFC_[A-Z0-9_]{3,}")
FORMA_UUID = re.compile(r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")
FORMA_FECHA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
CAMPOS_RFC = ("rfc_emisor", "rfc_receptor")
# Signo de cada monto en la identidad del CFDI (el total es el lado derecho).
SIGNOS_CUADRE: Tuple[Tuple[str, int], ...] = (("subtotal", 1), ("descuento", -1), ("iva", 1), ("ieps", 1),
                                              ("isr_retenido", -1), ("iva_retenido", -1))
CERO = Decimal("0.00")


def rfc_valido(rfc: str, acepta_marcador: bool) -> bool:
    return bool(FORMA_RFC_SAT.fullmatch(rfc) or (acepta_marcador and FORMA_RFC_MARCADOR.fullmatch(rfc)))


def uuid_valido(uuid: str) -> bool:
    return FORMA_UUID.fullmatch(uuid) is not None


def fecha_valida(texto: str) -> bool:
    if not FORMA_FECHA.fullmatch(texto):
        return False
    try:
        date.fromisoformat(texto)
    except ValueError:
        return False
    return True


def _forma(campo: str, valor: str, config: Config) -> Optional[Observacion]:
    """La observación de forma de un campo presente, o None si la forma es válida."""
    if campo in CAMPOS_RFC and not rfc_valido(valor, config.aceptar_rfc_marcador):
        return Observacion(RFC_INVALIDO, campo, f"{campo}: {valor!r} no tiene forma de RFC")
    if campo == "uuid" and not uuid_valido(valor):
        return Observacion(UUID_INVALIDO, campo, f"uuid: {valor!r} no tiene forma 8-4-4-4-12 hexadecimal")
    if campo == "fecha" and not fecha_valida(valor):
        return Observacion(FECHA_INVALIDA, campo, f"fecha: {valor!r} no es una fecha AAAA-MM-DD válida")
    if campo in CAMPOS_MONTO and monto_estricto(valor) is None:
        return Observacion(MONTO_INVALIDO, campo, f"{campo}: {valor!r} no es un monto (solo dígitos y punto decimal)")
    if campo == "moneda" and valor not in config.monedas_permitidas:
        return Observacion(MONEDA_NO_PERMITIDA, campo,
                           f"moneda: {valor!r} no está en {list(config.monedas_permitidas)}")
    return None


def _monto_del_cuadre(propuesta: Campos, campo: str) -> Optional[Decimal]:
    """El monto como Decimal; un opcional en null vale cero. None si no se puede cuadrar."""
    valor = propuesta.valor(campo)
    if valor is None and campo in CAMPOS_OPCIONALES:
        return CERO
    return monto_estricto(valor)


def _cuadre(propuesta: Campos, tolerancia: Decimal) -> Optional[Observacion]:
    montos = [_monto_del_cuadre(propuesta, campo) for campo, _ in SIGNOS_CUADRE]
    total = monto_estricto(propuesta.total)
    if total is None or any(m is None for m in montos):
        return None
    calculado = sum((signo * m for (_, signo), m in zip(SIGNOS_CUADRE, montos) if m is not None), CERO)
    if abs(calculado - total) <= tolerancia:
        return None
    return Observacion(NO_CUADRA, "total",
                       f"subtotal − descuento + iva + ieps − isr_retenido − iva_retenido = {texto_monto(calculado)} "
                       f"y el total es {texto_monto(total)} (tolerancia {tolerancia})")


def _receptor(propuesta: Campos, config: Config) -> Optional[Observacion]:
    receptor = propuesta.rfc_receptor
    if receptor is None or receptor == config.rfc_empresa or not rfc_valido(receptor, config.aceptar_rfc_marcador):
        return None
    return Observacion(RECEPTOR_DISTINTO, "rfc_receptor",
                       f"rfc_receptor: {receptor!r} no es la empresa ({config.rfc_empresa})")


def validar(propuesta: Campos, config: Config) -> Tuple[Observacion, ...]:
    observaciones: List[Optional[Observacion]] = []
    for campo in CAMPOS:
        valor = propuesta.valor(campo)
        if valor is not None:
            observaciones.append(_forma(campo, valor, config))
        elif campo not in CAMPOS_OPCIONALES:
            observaciones.append(Observacion(CAMPO_AUSENTE, campo, f"{campo}: el modelo no lo reportó"))
    observaciones += [_cuadre(propuesta, config.tolerancia_cuadre), _receptor(propuesta, config)]
    return tuple(o for o in observaciones if o is not None)
