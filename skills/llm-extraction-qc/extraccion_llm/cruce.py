"""Cruce de la propuesta del modelo contra la lectura determinista del pool de CFDIs conocidos.

El UUID propuesto localiza el CFDI (sin distinguir mayúsculas); luego se comparan con
`mismo_valor` los campos que el motor lee (`CAMPOS_DEL_MOTOR`, los doce). Así, un subtotal y
un IVA alterados que conservan su suma (invisibles para la regla de cuadre) discrepan aquí.
Sin UUID válido o sin CFDI en el pool no hay respaldo.
"""
from __future__ import annotations

from typing import Tuple

from .modelo import DISCREPANCIA_MOTOR, SIN_RESPALDO, Campos, Observacion, mismo_valor
from .pool import CAMPOS_DEL_MOTOR, Pool
from .reglas import uuid_valido


def cruzar(propuesta: Campos, pool: Pool) -> Tuple[Observacion, ...]:
    uuid = propuesta.uuid
    if uuid is None or not uuid_valido(uuid):
        return (Observacion(SIN_RESPALDO, "uuid", "sin un UUID válido no se puede buscar el CFDI en el pool"),)
    motor = pool.cfdis.get(uuid.upper())
    if motor is None:
        return (Observacion(SIN_RESPALDO, "uuid", f"el UUID {uuid} no está en el pool de CFDIs conocidos"),)
    discrepancias = []
    for campo in CAMPOS_DEL_MOTOR:
        propuesto, leido = propuesta.valor(campo), motor.valor(campo)
        if not mismo_valor(campo, propuesto, leido):
            discrepancias.append(Observacion(DISCREPANCIA_MOTOR, campo,
                                             f"{campo}: el modelo propone {propuesto!r} y el motor leyó {leido!r}",
                                             propuesto, leido))
    return tuple(discrepancias)
