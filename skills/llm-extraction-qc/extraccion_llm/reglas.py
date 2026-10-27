"""Reglas deterministas sobre la propuesta del modelo: forma de cada campo y cuadre de montos.

Cada falla es una `Observacion`; ninguna regla corrige un valor. Las observaciones salen en
el orden de los campos y luego las que cruzan campos (cuadre, receptor).
"""
from __future__ import annotations

import re
from datetime import date
from typing import List, Optional, Tuple

from .config import Config
from .modelo import (
    CAMPO_AUSENTE,
    CAMPOS,
    CAMPOS_MONTO,
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


def _cuadre(propuesta: Campos) -> Optional[Observacion]:
    subtotal, iva, total = (monto_estricto(propuesta.valor(c)) for c in ("subtotal", "iva", "total"))
    if subtotal is None or iva is None or total is None or subtotal + iva == total:
        return None
    return Observacion(NO_CUADRA, "total",
                       f"subtotal + iva = {texto_monto(subtotal + iva)} y el total es {texto_monto(total)}")


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
        if valor is None:
            observaciones.append(Observacion(CAMPO_AUSENTE, campo, f"{campo}: el modelo no lo reportó"))
        else:
            observaciones.append(_forma(campo, valor, config))
    observaciones += [_cuadre(propuesta), _receptor(propuesta, config)]
    return tuple(o for o in observaciones if o is not None)
