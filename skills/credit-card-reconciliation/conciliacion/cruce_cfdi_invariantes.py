"""Candados del cruce cargo ↔ CFDI: se recalculan sobre el resultado, sin confiar en el algoritmo.

Cada invariante produce una lista de problemas; si alguna no está vacía, la CLI
no escribe la salida y termina con código 3.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

from .cruce_cfdi_candidatos import Pool, armar_pool, calificar, delta_dias, en_ventana, es_valido
from .cruce_cfdi_config import ConfigCruce
from .cruce_cfdi_modelo import (
    EVIDENCIAS_INDIVIDUALES,
    MOTIVOS,
    SUMA,
    Cargo,
    Cfdi,
    ResultadoCargo,
    ResultadoCruce,
)

NOMBRES_INVARIANTES: Tuple[str, ...] = (
    "cobertura", "exclusividad", "cfdis_conocidos", "evidencia_o_motivo", "coherencia_tier",
    "maximalidad_uno_a_uno",
)
SIN_OBSERVACIONES = "sin observaciones"
MAX_EJEMPLOS = 5


@dataclass(frozen=True)
class Invariante:
    nombre: str
    cumple: bool
    detalle: str


@dataclass(frozen=True)
class _Contexto:
    cargos: Mapping[str, Cargo]
    pool: Pool
    config: ConfigCruce
    resultado: ResultadoCruce


def _cobertura(ctx: _Contexto) -> List[str]:
    vistos = Counter(r.cargo_id for r in ctx.resultado.cargos)
    faltan = [f"{cid}: falta en el resultado" for cid in ctx.cargos if cid not in vistos]
    sobran = [f"{cid}: no está en el universo" for cid in vistos if cid not in ctx.cargos]
    repetidos = [f"{cid}: aparece {n} veces" for cid, n in vistos.items() if n > 1]
    return faltan + sobran + repetidos


def _exclusividad(ctx: _Contexto) -> List[str]:
    duenos: Dict[str, List[str]] = {}
    for r in ctx.resultado.cargos:
        for uuid in r.cfdis:
            duenos.setdefault(uuid, []).append(r.cargo_id)
    return [f"{u}: asignado a {', '.join(sorted(c))}" for u, c in sorted(duenos.items()) if len(c) > 1]


def _cfdis_conocidos(ctx: _Contexto) -> List[str]:
    return [f"{r.cargo_id}: CFDI desconocido {u}" for r in ctx.resultado.cargos for u in r.cfdis
            if u not in ctx.pool.todos]


def _evidencia_o_motivo(ctx: _Contexto) -> List[str]:
    problemas: List[str] = []
    for r in ctx.resultado.cargos:
        if (r.evidencia is None) == (r.motivo is None):
            problemas.append(f"{r.cargo_id}: evidencia={r.evidencia} y motivo={r.motivo}")
        if bool(r.cfdis) != (r.evidencia is not None):
            problemas.append(f"{r.cargo_id}: {len(r.cfdis)} CFDIs con evidencia={r.evidencia}")
        if r.motivo is not None and r.motivo not in MOTIVOS:
            problemas.append(f"{r.cargo_id}: motivo desconocido {r.motivo}")
    return problemas


def _problema_de_tier(cargo: Cargo, r: ResultadoCargo, cfdis: Sequence[Cfdi], config: ConfigCruce) -> str:
    """Texto del problema, o cadena vacía si el cruce cumple las condiciones de su tier."""
    if not cargo.cruzable:
        return "el cargo no es cruzable"
    if not all(es_valido(c, config) and en_ventana(delta_dias(cargo, c), config) for c in cfdis):
        return "incluye un CFDI no candidato o fuera de ventana"
    if r.evidencia in EVIDENCIAS_INDIVIDUALES:
        calificacion = calificar(cargo, cfdis[0], config) if len(cfdis) == 1 else None
        if calificacion is None or calificacion.evidencia != r.evidencia:
            return f"no califica como {r.evidencia}"
        return ""
    if r.evidencia == SUMA:
        total = sum((c.valor_mxn for c in cfdis), Decimal(0))
        if not config.suma_min_cfdis <= len(cfdis) <= config.suma_max_cfdis:
            return f"suma de {len(cfdis)} CFDIs fuera de límites"
        if len({c.rfc_emisor for c in cfdis}) != 1:
            return "suma con emisores distintos"
        if abs(total - cargo.monto) > config.tolerancia_suma:
            return f"suma {total} no cuadra con {cargo.monto}"
        return ""
    return f"tier desconocido {r.evidencia}"


def _coherencia_tier(ctx: _Contexto) -> List[str]:
    problemas: List[str] = []
    for r in ctx.resultado.cargos:
        cargo = ctx.cargos.get(r.cargo_id)
        if r.evidencia is None or cargo is None:
            continue
        cfdis = [ctx.pool.todos[u] for u in r.cfdis if u in ctx.pool.todos]
        problema = "CFDIs sin verificar" if len(cfdis) != len(r.cfdis) else _problema_de_tier(
            cargo, r, cfdis, ctx.config)
        if problema:
            problemas.append(f"{r.cargo_id}: {problema}")
    return problemas


def _maximalidad(ctx: _Contexto) -> List[str]:
    individuales = [r for r in ctx.resultado.cargos if r.evidencia in EVIDENCIAS_INDIVIDUALES]
    resueltos = {r.cargo_id for r in individuales}
    tomados = {u for r in individuales for u in r.cfdis}
    problemas: List[str] = []
    for cid in sorted(ctx.cargos):
        cargo = ctx.cargos[cid]
        if cid in resueltos or not cargo.cruzable:
            continue
        problemas.extend(f"{cid}: {c.uuid} quedó libre y califica uno a uno"
                         for c, _ in ctx.pool.individuales(cargo, ctx.config) if c.uuid not in tomados)
    return problemas


_REGLAS: Tuple[Callable[[_Contexto], List[str]], ...] = (
    _cobertura, _exclusividad, _cfdis_conocidos, _evidencia_o_motivo, _coherencia_tier, _maximalidad,
)


def _detalle(problemas: Sequence[str]) -> str:
    if not problemas:
        return SIN_OBSERVACIONES
    ejemplos = "; ".join(sorted(problemas)[:MAX_EJEMPLOS])
    return f"{len(problemas)} casos: {ejemplos}"


def verificar_invariantes(
    cargos: Iterable[Cargo], cfdis: Iterable[Cfdi], config: ConfigCruce, resultado: ResultadoCruce
) -> Tuple[Invariante, ...]:
    ctx = _Contexto({c.cargo_id: c for c in cargos}, armar_pool(cfdis, config), config, resultado)
    salida = []
    for nombre, regla in zip(NOMBRES_INVARIANTES, _REGLAS):
        problemas = regla(ctx)
        salida.append(Invariante(nombre, not problemas, _detalle(problemas)))
    return tuple(salida)
