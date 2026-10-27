"""Veredictos humanos sintéticos sobre el cruce cargo ↔ libro mayor.

Cada veredicto se planta sobre un cargo cuya respuesta de libro ya está en el oráculo,
así que el conflicto contra la propuesta correcta del motor se conoce de antemano.
Usa su propia instancia de `random.Random` (sub-semilla aparte): plantar veredictos no
consume el azar del resto de la corrida, y ningún otro archivo cambia por ellos.

Ningún veredicto toca un grupo de empate ni cita el asiento esperado de otro cargo, de
modo que el registro esperado de los cargos sin veredicto sigue siendo el del oráculo.
"""
from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from typing import Dict, FrozenSet, Iterator, List, Optional, Sequence, Set, Tuple, TypeVar

from .config import ConfigGenerador
from .contexto import SALTO_SEMILLA
from .modelo import Asiento, Datos, Expectativa, VeredictoHumano

T = TypeVar("T")

ARCHIVO_VEREDICTOS = "veredictos_libro.csv"
COLUMNAS_VEREDICTOS = ("cargo_id", "veredicto", "asiento_id", "nota")
SAL_VEREDICTOS = 500_009

REGISTRADO = "registrado"
NO_REGISTRADO = "no_registrado"
CONFLICTO_ASIENTO = "asiento_distinto"
CONFLICTO_SIN_CRUCE = "motor_sin_cruce"
CONFLICTO_CON_CRUCE = "motor_con_cruce"

# De dónde sale el asiento que cita el veredicto.
DEL_ORACULO = "esperado"
PROHIBIDO = "prohibido"
AJENO = "ajeno"
SIN_ASIENTO = "ninguno"
ORIGEN_AJENO = "CXP"


@dataclass(frozen=True)
class Plan:
    """Una familia de veredictos: sobre qué caso se planta, cuántos y qué dicen."""

    nombre: str
    cuota: int
    caso: str
    veredicto: str
    asiento: str
    nota: str


PLANES: Tuple[Plan, ...] = (
    Plan("confirma_registro", 4, "libro_registrado", REGISTRADO, DEL_ORACULO, "coincide con el estado de cuenta"),
    Plan("confirma_cubeta", 1, "libro_cubeta", REGISTRADO, DEL_ORACULO, "registrado en gastos varios"),
    Plan("confirma_sin_registro", 2, "libro_no_registrado", NO_REGISTRADO, SIN_ASIENTO, "pendiente de registrar"),
    Plan("niega_registro", 2, "libro_registrado", NO_REGISTRADO, SIN_ASIENTO, "no se encontro la poliza"),
    Plan("cita_cubeta_lejana", 1, "libro_cubeta_fecha_lejana", REGISTRADO, PROHIBIDO, "registrado en otro periodo"),
    Plan("cita_otro_asiento", 2, "libro_registrado", REGISTRADO, AJENO, "poliza de cuentas por pagar"),
)


def conflicto_esperado(veredicto: str, asiento: Optional[str], esperado: Optional[str]) -> Optional[str]:
    """Desacuerdo entre un veredicto y el registro que propone un motor correcto."""
    if veredicto == REGISTRADO:
        if esperado is None:
            return CONFLICTO_SIN_CRUCE
        return None if asiento == esperado else CONFLICTO_ASIENTO
    return CONFLICTO_CON_CRUCE if esperado is not None else None


def _barajar(azar: random.Random, opciones: Sequence[T]) -> List[T]:
    copia = list(opciones)
    azar.shuffle(copia)
    return copia


def _prohibidos_de_todos(expectativas: Sequence[Expectativa]) -> FrozenSet[str]:
    return frozenset(a for e in expectativas for a in e.libro_requerido().prohibidos)


def _elegible(e: Expectativa, plan: Plan, prohibidos: FrozenSet[str]) -> bool:
    """Cargos limpios del caso: fuera de grupos de empate y sin cruzarse con otro cargo."""
    libro = e.libro_requerido()
    if plan.caso not in e.casos or e.grupo_empate is not None:
        return False
    if plan.asiento == PROHIBIDO:
        return len(libro.prohibidos) == 1
    return not libro.prohibidos and libro.esperado not in prohibidos


def _asientos_ajenos(expectativas: Sequence[Expectativa], asientos: Sequence[Asiento]) -> Tuple[str, ...]:
    """Asientos de cuentas por pagar que ningún cargo espera ni tiene prohibidos."""
    citados = _prohibidos_de_todos(expectativas) | {
        e.libro_requerido().esperado or "" for e in expectativas}
    return tuple(sorted(a.asiento_id for a in asientos if a.origen == ORIGEN_AJENO and a.asiento_id not in citados))


def _asiento_para(plan: Plan, e: Expectativa, ajenos: Iterator[str]) -> Tuple[bool, Optional[str]]:
    """(se puede plantar, asiento citado) según el plan."""
    libro = e.libro_requerido()
    if plan.asiento == DEL_ORACULO:
        return libro.esperado is not None, libro.esperado
    if plan.asiento == PROHIBIDO:
        return True, libro.prohibidos[0]
    if plan.asiento == AJENO:
        siguiente = next(ajenos, None)
        return siguiente is not None, siguiente
    return True, None


def plantar_veredictos(config: ConfigGenerador, intento: int, expectativas: Tuple[Expectativa, ...],
                       asientos: Tuple[Asiento, ...]) -> Tuple[VeredictoHumano, ...]:
    """Veredictos de cada plan sobre cargos distintos, ordenados por `cargo_id`."""
    azar = random.Random(config.semilla + intento * SALTO_SEMILLA + SAL_VEREDICTOS)
    prohibidos = _prohibidos_de_todos(expectativas)
    ajenos = iter(_barajar(azar, _asientos_ajenos(expectativas, asientos)))
    con_veredicto: Set[str] = set()
    salida: List[VeredictoHumano] = []
    for plan in PLANES:
        elegibles = [e for e in expectativas if e.clave_cargo not in con_veredicto and _elegible(e, plan, prohibidos)]
        for e in _barajar(azar, elegibles)[:plan.cuota]:
            valido, asiento = _asiento_para(plan, e, ajenos)
            if not valido:
                continue
            esperado = e.libro_requerido().esperado
            salida.append(VeredictoHumano(e.clave_cargo, plan.veredicto, asiento, plan.nota,
                                          conflicto_esperado(plan.veredicto, asiento, esperado)))
            con_veredicto.add(e.clave_cargo)
    return tuple(sorted(salida, key=lambda v: v.cargo_id))


def _verificar_uno(v: VeredictoHumano, exp: Optional[Expectativa], asientos: Set[str],
                   duenos: Dict[str, str]) -> List[str]:
    if exp is None:
        return [f"{v.cargo_id}: veredicto sobre un cargo inexistente"]
    errores = []
    if (v.veredicto == REGISTRADO) != (v.asiento_id is not None):
        errores.append(f"{v.cargo_id}: veredicto {v.veredicto} incoherente con su asiento")
    if v.asiento_id is not None and v.asiento_id not in asientos:
        errores.append(f"{v.cargo_id}: veredicto cita el asiento inexistente {v.asiento_id}")
    dueno = duenos.get(v.asiento_id or "")
    if dueno not in (None, v.cargo_id):
        errores.append(f"{v.cargo_id}: veredicto desplaza el registro esperado de {dueno}")
    if exp.grupo_empate is not None:
        errores.append(f"{v.cargo_id}: veredicto dentro del grupo de empate {exp.grupo_empate}")
    esperado = conflicto_esperado(v.veredicto, v.asiento_id, exp.libro_requerido().esperado)
    if esperado != v.conflicto:
        errores.append(f"{v.cargo_id}: conflicto plantado {v.conflicto} y el oráculo implica {esperado}")
    return errores


def verificar_veredictos(datos: Datos) -> List[str]:
    """Violaciones de los veredictos plantados (lista vacía si son coherentes)."""
    expectativas = {e.clave_cargo: e for e in datos.expectativas}
    asientos = {a.asiento_id for a in datos.asientos}
    duenos = {e.libro_requerido().esperado or "": e.clave_cargo for e in datos.expectativas
              if e.libro_requerido().esperado}
    citados = Counter(v.asiento_id for v in datos.veredictos if v.asiento_id)
    por_cargo = Counter(v.cargo_id for v in datos.veredictos)
    errores = [f"asiento {a} citado por {n} veredictos" for a, n in sorted(citados.items()) if n > 1]
    errores += [f"{c}: {n} veredictos para un mismo cargo" for c, n in sorted(por_cargo.items()) if n > 1]
    for v in datos.veredictos:
        errores += _verificar_uno(v, expectativas.get(v.cargo_id), asientos, duenos)
    return errores
