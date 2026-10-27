"""Veredicto humano: insumo que nunca se sobrescribe; conflictos y resultado final.

Orden de la corrida (spec, "Veredicto humano y conflictos"): propuesta libre del motor,
comparación contra cada veredicto y segunda corrida solo para los cargos sin veredicto,
con los asientos citados por la persona ya reservados.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from . import cruce_libro_motor as motor
from .cruce_libro_modelo import (
    CONFLICTO_ASIENTO,
    CONFLICTO_CON_CRUCE,
    CONFLICTO_SIN_CRUCE,
    MOTIVO_VEREDICTO,
    ORIGEN_MOTOR,
    ORIGEN_VEREDICTO,
    VEREDICTO_REGISTRADO,
    Cargo,
    ConfigCruceLibro,
    Cruce,
    EvaluacionCargo,
    LineaLibro,
    Veredicto,
)


@dataclass(frozen=True)
class ResultadoFinal:
    """Lo que vale para un cargo después de aplicar los veredictos."""

    cargo_id: str
    asiento_id: Optional[str]
    origen: str
    riesgo_cubeta: bool
    motivo: Optional[str]
    reasignado: bool


@dataclass(frozen=True)
class Conciliacion:
    """Todo lo que produce una corrida, en mapas de solo lectura por `cargo_id`."""

    evaluaciones: Tuple[EvaluacionCargo, ...]
    propuesta: Mapping[str, Cruce]
    veredictos: Mapping[str, Veredicto]
    conflictos: Mapping[str, str]
    final: Mapping[str, ResultadoFinal]


def tipo_conflicto(veredicto: Veredicto, propuesta: Cruce) -> Optional[str]:
    """Desacuerdo entre lo que dijo la persona y lo que propuso el motor (o None)."""
    sugerido = propuesta.asiento_id
    if veredicto.veredicto == VEREDICTO_REGISTRADO:
        if sugerido is None:
            return CONFLICTO_SIN_CRUCE
        return None if sugerido == veredicto.asiento_id else CONFLICTO_ASIENTO
    return CONFLICTO_CON_CRUCE if sugerido is not None else None


def _asientos_cubeta(lineas: Tuple[LineaLibro, ...], config: ConfigCruceLibro) -> frozenset[str]:
    return frozenset(x.asiento_id for x in lineas if x.proveedor_id in config.proveedores_cubeta)


def _desde_veredicto(veredicto: Veredicto, cubeta: frozenset[str]) -> ResultadoFinal:
    asiento = veredicto.asiento_id
    motivo = None if veredicto.veredicto == VEREDICTO_REGISTRADO else MOTIVO_VEREDICTO
    return ResultadoFinal(veredicto.cargo_id, asiento, ORIGEN_VEREDICTO, asiento in cubeta, motivo, False)


def _desde_motor(cruce: Cruce, propuesta: Cruce) -> ResultadoFinal:
    return ResultadoFinal(cruce.cargo_id, cruce.asiento_id, ORIGEN_MOTOR, cruce.riesgo_cubeta, cruce.motivo,
                          cruce.asiento_id != propuesta.asiento_id)


def conciliar(cargos: Tuple[Cargo, ...], lineas: Tuple[LineaLibro, ...], veredictos: Tuple[Veredicto, ...],
              config: ConfigCruceLibro) -> Conciliacion:
    """Corre el cruce completo: propuesta, conflictos y resultado final."""
    evaluaciones = motor.evaluar_cargos(cargos, lineas, config)
    propuesta = motor.asignar(evaluaciones)
    por_cargo = {v.cargo_id: v for v in sorted(veredictos, key=lambda v: v.cargo_id)}
    conflictos = {cid: tipo for cid, v in por_cargo.items()
                  if (tipo := tipo_conflicto(v, propuesta[cid])) is not None}
    reservados = frozenset(v.asiento_id for v in por_cargo.values() if v.asiento_id is not None)
    segunda = motor.asignar(evaluaciones, excluidos=frozenset(por_cargo), reservados=reservados)
    cubeta = _asientos_cubeta(lineas, config)
    final = {cid: (_desde_veredicto(por_cargo[cid], cubeta) if cid in por_cargo
                   else _desde_motor(segunda[cid], propuesta[cid])) for cid in sorted(propuesta)}
    return Conciliacion(evaluaciones, MappingProxyType(propuesta), MappingProxyType(por_cargo),
                        MappingProxyType(conflictos), MappingProxyType(final))
