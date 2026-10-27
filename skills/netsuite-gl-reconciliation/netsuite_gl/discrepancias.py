"""Elección determinista de los CFDIs que reciben una discrepancia plantada, y su manifiesto.

Cada CFDI recibe la llave `sha256("<semilla>:<uuid>")`; se ordenan por esa llave y se cortan
bloques consecutivos en el orden de `CATEGORIAS`. No depende de `random` ni de la versión
de Python, y un CFDI nunca recibe dos discrepancias.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Dict, FrozenSet, Mapping, Sequence, Tuple

from netsuite_gl.cfdis import Cfdi
from netsuite_gl.config import PlanDiscrepancias
from netsuite_gl.errores import ErrorPoblado
from netsuite_gl.montos import tiene_centavos_exactos

SIN_REGISTRO = "sin_registro"
MONTO_DISTINTO = "monto_distinto"
DUPLICADO = "duplicado"
PERIODO_EQUIVOCADO = "periodo_equivocado"
CATEGORIAS: Tuple[str, ...] = (SIN_REGISTRO, MONTO_DISTINTO, DUPLICADO, PERIODO_EQUIVOCADO)


@dataclass(frozen=True)
class Asignacion:
    """Qué CFDI (por uuid) recibe qué discrepancia; `monto_distinto` lleva su delta."""

    sin_registro: FrozenSet[str]
    monto_distinto: Mapping[str, Decimal]
    duplicado: FrozenSet[str]
    periodo_equivocado: FrozenSet[str]


@dataclass(frozen=True)
class PlantaMonto:
    uuid: str
    delta: Decimal
    diferencia_esperada: Decimal


@dataclass(frozen=True)
class PlantaDuplicado:
    uuid: str
    transacciones: Tuple[int, int]
    diferencia_esperada: Decimal


@dataclass(frozen=True)
class PlantaPeriodo:
    uuid: str
    transaccion: int
    periodo_esperado: str
    periodo_registrado: str


@dataclass(frozen=True)
class Manifiesto:
    """Contrato de lo plantado: las pruebas comparan cada query contra esto."""

    plan: PlanDiscrepancias
    rfc_empresa: str
    cfdis_leidos: int
    universo: int
    transacciones: int
    proveedores: int
    excluidos: Mapping[str, int]
    sin_registro: Tuple[str, ...]
    monto_distinto: Tuple[PlantaMonto, ...]
    duplicado: Tuple[PlantaDuplicado, ...]
    periodo_equivocado: Tuple[PlantaPeriodo, ...]


def llave_de_orden(semilla: int, uuid: str) -> str:
    return hashlib.sha256(f"{semilla}:{uuid}".encode("utf-8")).hexdigest()


def asignar(universo: Sequence[Cfdi], plan: PlanDiscrepancias) -> Asignacion:
    """Reparte las discrepancias del plan sobre el universo, sin traslapes."""
    tamanos = _validar_plan(plan, len(universo))
    ordenados = sorted(universo, key=lambda c: (llave_de_orden(plan.semilla, c.uuid), c.uuid))
    bloques: Dict[str, Tuple[str, ...]] = {}
    inicio = 0
    for categoria, tamano in zip(CATEGORIAS, tamanos):
        bloques[categoria] = tuple(c.uuid for c in ordenados[inicio:inicio + tamano])
        inicio += tamano
    deltas = {
        uuid: plan.deltas_monto[i % len(plan.deltas_monto)]
        for i, uuid in enumerate(bloques[MONTO_DISTINTO])
    }
    return Asignacion(
        sin_registro=frozenset(bloques[SIN_REGISTRO]),
        monto_distinto=MappingProxyType(deltas),
        duplicado=frozenset(bloques[DUPLICADO]),
        periodo_equivocado=frozenset(bloques[PERIODO_EQUIVOCADO]),
    )


def _validar_plan(plan: PlanDiscrepancias, disponibles: int) -> Tuple[int, ...]:
    tamanos = (plan.sin_registro, plan.monto_distinto, plan.duplicado, plan.periodo_equivocado)
    negativos = [c for c, t in zip(CATEGORIAS, tamanos) if t < 0]
    if negativos:
        raise ErrorPoblado(f"el plan tiene tamaños negativos en: {', '.join(negativos)}")
    if plan.monto_distinto > 0 and not plan.deltas_monto:
        raise ErrorPoblado("monto_distinto > 0 requiere al menos un valor en deltas_monto")
    if any(d == 0 for d in plan.deltas_monto):
        raise ErrorPoblado("deltas_monto no puede contener cero: no plantaría ninguna diferencia")
    if any(not d.is_finite() or not tiene_centavos_exactos(d) for d in plan.deltas_monto):
        raise ErrorPoblado("deltas_monto solo admite montos finitos con a lo sumo dos decimales")
    if sum(tamanos) > disponibles:
        raise ErrorPoblado(
            f"el plan pide {sum(tamanos)} CFDIs con discrepancia, pero el universo solo tiene {disponibles}"
        )
    return tamanos
