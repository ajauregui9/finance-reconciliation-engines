"""Candados del cruce cargo ↔ CFDI: se recalculan sobre el resultado, sin confiar en el algoritmo.

Cada invariante produce una lista de problemas; si alguna no está vacía, la CLI
no escribe la salida y termina con código 3.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

from .cruce_cfdi_candidatos import (
    Pool,
    afinidad_de,
    alcanza_afinidad,
    armar_pool,
    calificar,
    delta_dias,
    en_ventana,
    es_valido,
)
from .cruce_cfdi_config import ConfigCruce
from .cruce_cfdi_modelo import (
    EVIDENCIAS_INDIVIDUALES,
    EVIDENCIAS_POR_REVISAR,
    MONTO_SIN_AFINIDAD,
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


def _problema_de_suma(cargo: Cargo, cfdis: Sequence[Cfdi], config: ConfigCruce) -> str:
    total = sum((c.valor_mxn for c in cfdis), Decimal(0))
    if not config.suma_min_cfdis <= len(cfdis) <= config.suma_max_cfdis:
        return f"suma de {len(cfdis)} CFDIs fuera de límites"
    if len({c.rfc_emisor for c in cfdis}) != 1:
        return "suma con emisores distintos"
    if abs(total - cargo.monto) > config.tolerancia_suma:
        return f"suma {total} no cuadra con {cargo.monto}"
    return ""


def _problema_de_monto(cargo: Cargo, r: ResultadoCargo, cfdis: Sequence[Cfdi], config: ConfigCruce) -> str:
    """Condiciones de monto del tier; `monto_sin_afinidad` exige las de algún tier uno a uno o las de suma."""
    individual = r.evidencia in EVIDENCIAS_INDIVIDUALES or (r.evidencia == MONTO_SIN_AFINIDAD and len(cfdis) == 1)
    if individual:
        calificacion = calificar(cargo, cfdis[0], config) if len(cfdis) == 1 else None
        if calificacion is None or (r.evidencia != MONTO_SIN_AFINIDAD and calificacion.evidencia != r.evidencia):
            return f"no califica como {r.evidencia}"
        return ""
    if r.evidencia in (SUMA, MONTO_SIN_AFINIDAD):
        return _problema_de_suma(cargo, cfdis, config)
    return f"tier desconocido {r.evidencia}"


def _problema_de_afinidad(cargo: Cargo, r: ResultadoCargo, cfdis: Sequence[Cfdi], config: ConfigCruce) -> str:
    """La afinidad publicada es la menor del grupo, y alcanza el mínimo si y solo si el tier respalda."""
    parecido = min(afinidad_de(cargo, c) for c in cfdis)
    if r.afinidad != parecido:
        return f"afinidad publicada {r.afinidad} distinta de la recalculada {parecido}"
    if alcanza_afinidad(parecido, config) == (r.evidencia in EVIDENCIAS_POR_REVISAR):
        estado = "alcanza" if alcanza_afinidad(parecido, config) else "no alcanza"
        return f"la afinidad {parecido} {estado} el mínimo {config.afinidad_minima} y el tier es {r.evidencia}"
    return ""


def _problema_de_tier(cargo: Cargo, r: ResultadoCargo, cfdis: Sequence[Cfdi], config: ConfigCruce) -> str:
    """Texto del problema, o cadena vacía si el cruce cumple las condiciones de su tier."""
    if not cargo.cruzable:
        return "el cargo no es cruzable"
    if not all(es_valido(c, config) and en_ventana(delta_dias(cargo, c), config) for c in cfdis):
        return "incluye un CFDI no candidato o fuera de ventana"
    return _problema_de_monto(cargo, r, cfdis, config) or _problema_de_afinidad(cargo, r, cfdis, config)


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
    """Ningún par uno a uno con afinidad quedó fuera de la fase con afinidad, ni ningún par uno a uno
    (con o sin afinidad) entre un cargo sin cruce y un CFDI sin asignar."""
    afines = [r for r in ctx.resultado.cargos if r.evidencia in EVIDENCIAS_INDIVIDUALES]
    resueltos_afines = {r.cargo_id for r in afines}
    tomados_afines = {u for r in afines for u in r.cfdis}
    con_cruce = {r.cargo_id for r in ctx.resultado.cargos if r.evidencia is not None}
    asignados = ctx.resultado.cfdis_asignados()
    problemas: List[str] = []
    for cid in sorted(ctx.cargos):
        cargo = ctx.cargos[cid]
        if cid in resueltos_afines or not cargo.cruzable:
            continue
        for cfdi, _ in ctx.pool.individuales(cargo, ctx.config):
            if alcanza_afinidad(afinidad_de(cargo, cfdi), ctx.config) and cfdi.uuid not in tomados_afines:
                problemas.append(f"{cid}: {cfdi.uuid} quedó fuera y califica uno a uno con afinidad")
            elif cid not in con_cruce and cfdi.uuid not in asignados:
                problemas.append(f"{cid}: {cfdi.uuid} quedó libre y califica uno a uno")
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
