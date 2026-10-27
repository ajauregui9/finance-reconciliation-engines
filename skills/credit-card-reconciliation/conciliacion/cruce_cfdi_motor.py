"""Motor del cruce cargo ↔ CFDI: asignación greedy en dos fases y diagnóstico de los cargos sin cruce.

Fase 1 (uno a uno) termina por completo antes de la fase 2 (sumas): así un cruce
uno a uno siempre gana sobre una suma. Cada fase ordena sus propuestas con un
orden total y acepta una propuesta si su cargo sigue libre y todos sus CFDIs
también. Ver specs/cruce_cfdi.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from typing import AbstractSet, Any, Dict, Iterable, List, Mapping, Sequence, Set, Tuple

from .cruce_cfdi_candidatos import Pool, armar_pool, calificar, delta_dias, en_ventana
from .cruce_cfdi_config import ConfigCruce
from .cruce_cfdi_modelo import (
    ESTADO_OK,
    FILA_ININTERPRETABLE,
    FUERA_DE_TOLERANCIA,
    FUERA_DE_VENTANA,
    MONEDA_LOCAL,
    MOTIVOS,
    NO_APLICA,
    SIN_CANDIDATO,
    SOLO_RFC_GENERICO,
    SUMA,
    Cargo,
    Cfdi,
    Descarte,
    ResultadoCargo,
    ResultadoCruce,
)
from .cruce_cfdi_nombres import afinidad


@dataclass(frozen=True)
class _Propuesta:
    clave: Tuple[Any, ...]
    cargo: Cargo
    cfdis: Tuple[Cfdi, ...]
    evidencia: str
    diferencia: Decimal
    moneda: str
    afinidad: Fraction


def _propuestas_individuales(cargos: Sequence[Cargo], pool: Pool, config: ConfigCruce) -> List[_Propuesta]:
    propuestas = []
    for cargo in cargos:
        for cfdi, calificacion in pool.individuales(cargo, config):
            delta = delta_dias(cargo, cfdi)
            parecido = afinidad(cargo.descripcion, cfdi.nombre_emisor)
            clave = (calificacion.rango, -parecido, calificacion.diferencia, abs(delta), delta < 0,
                     cargo.cargo_id, cfdi.uuid)
            propuestas.append(_Propuesta(clave, cargo, (cfdi,), calificacion.evidencia,
                                         calificacion.diferencia, calificacion.moneda, parecido))
    return propuestas


def _acotar(cargo: Cargo, emisor: str, cfdis: Sequence[Cfdi], config: ConfigCruce) -> Tuple[Tuple[Cfdi, ...], str]:
    """Aplica el tope por emisor: conserva los N más cercanos en fecha y avisa si recortó."""
    tope = config.suma_max_candidatos
    if len(cfdis) <= tope:
        return tuple(cfdis), ""
    cercanos = sorted(cfdis, key=lambda c: (abs(delta_dias(cargo, c)), c.uuid))[:tope]
    aviso = f"tope_suma_truncado: emisor {emisor}, {len(cfdis)} candidatos, se usan {tope}"
    return tuple(sorted(cercanos, key=lambda c: c.uuid)), aviso


def _sumas(cargo: Cargo, cfdis: Iterable[Cfdi], config: ConfigCruce) -> Tuple[List[Tuple[Cfdi, ...]], List[str]]:
    """Combinaciones de un mismo RFC emisor cuyo valor firmado suma el monto del cargo."""
    por_emisor: Dict[str, List[Cfdi]] = {}
    for cfdi in sorted(cfdis, key=lambda c: c.uuid):
        por_emisor.setdefault(cfdi.rfc_emisor, []).append(cfdi)
    halladas: List[Tuple[Cfdi, ...]] = []
    avisos: List[str] = []
    for emisor in sorted(por_emisor):
        grupo, aviso = _acotar(cargo, emisor, por_emisor[emisor], config)
        if aviso:
            avisos.append(aviso)
        for tamano in range(config.suma_min_cfdis, config.suma_max_cfdis + 1):
            for combo in combinations(grupo, tamano):
                if abs(sum((c.valor_mxn for c in combo), Decimal(0)) - cargo.monto) <= config.tolerancia_suma:
                    halladas.append(combo)
    return halladas, avisos


def _con_afinidad(cargo: Cargo, cfdis: Iterable[Cfdi], config: ConfigCruce) -> List[Cfdi]:
    minima = Fraction(config.afinidad_minima)
    return [c for c in cfdis if afinidad(cargo.descripcion, c.nombre_emisor) >= minima]


def _propuestas_de_suma(
    cargos: Sequence[Cargo], pool: Pool, tomados: AbstractSet[str], config: ConfigCruce
) -> Tuple[List[_Propuesta], Dict[str, Tuple[str, ...]]]:
    propuestas: List[_Propuesta] = []
    avisos: Dict[str, Tuple[str, ...]] = {}
    for cargo in cargos:
        libres = [c for c in pool.validos_en_ventana(cargo, config) if c.uuid not in tomados]
        combos, avisos_cargo = _sumas(cargo, _con_afinidad(cargo, libres, config), config)
        if avisos_cargo:
            avisos[cargo.cargo_id] = tuple(avisos_cargo)
        for combo in combos:
            diferencia = abs(sum((c.valor_mxn for c in combo), Decimal(0)) - cargo.monto)
            parecido = min(afinidad(cargo.descripcion, c.nombre_emisor) for c in combo)
            lejania = max(abs(delta_dias(cargo, c)) for c in combo)
            clave = (len(combo), diferencia, -parecido, lejania, cargo.cargo_id, tuple(c.uuid for c in combo))
            propuestas.append(_Propuesta(clave, cargo, combo, SUMA, diferencia, MONEDA_LOCAL, parecido))
    return propuestas, avisos


def _aceptar(propuestas: Iterable[_Propuesta], tomados: AbstractSet[str]) -> Tuple[_Propuesta, ...]:
    """Recorrido greedy: la primera propuesta (por orden total) con cargo y CFDIs libres se queda."""
    resueltos: Set[str] = set()
    usados: Set[str] = set(tomados)
    aceptadas: List[_Propuesta] = []
    for propuesta in sorted(propuestas, key=lambda p: p.clave):
        uuids = {c.uuid for c in propuesta.cfdis}
        if propuesta.cargo.cargo_id in resueltos or uuids & usados:
            continue
        aceptadas.append(propuesta)
        resueltos.add(propuesta.cargo.cargo_id)
        usados |= uuids
    return tuple(aceptadas)


def _evidencia_generica(cargo: Cargo, pool: Pool, config: ConfigCruce) -> Tuple[Set[str], List[str]]:
    """CFDIs que respaldarían el monto si no fuera por un RFC genérico (uno a uno o en suma)."""
    cercanos = pool.genericos_en_ventana(cargo, config)
    hallados = {c.uuid for c in cercanos if calificar(cargo, c, config) is not None}
    combos, avisos = _sumas(cargo, cercanos, config)
    hallados.update(c.uuid for combo in combos for c in combo)
    return hallados, avisos


def _fuera_de_ventana(cargo: Cargo, pool: Pool, libres: AbstractSet[str], config: ConfigCruce) -> Set[str]:
    margen = config.margen_fuera_de_ventana_dias
    minimo, maximo = config.ventana_min - margen, config.ventana_max + margen
    cercanos = [c for c in pool.validos_por_monto(cargo, config, config.tolerancia_uno_a_uno)
                if c.uuid in libres and calificar(cargo, c, config) is not None]
    return {c.uuid for c in _con_afinidad(cargo, cercanos, config)
            if not en_ventana(delta_dias(cargo, c), config) and minimo <= delta_dias(cargo, c) <= maximo}


def _fuera_de_tolerancia(cargo: Cargo, pool: Pool, libres: AbstractSet[str], config: ConfigCruce) -> Set[str]:
    cercanos = [c for c in pool.validos_por_monto(cargo, config, config.banda_fuera_de_tolerancia)
                if c.uuid in libres and en_ventana(delta_dias(cargo, c), config)
                and config.tolerancia_uno_a_uno < abs(c.valor_mxn - cargo.monto) <= config.banda_fuera_de_tolerancia]
    return {c.uuid for c in _con_afinidad(cargo, cercanos, config)}


def _sin_cruce(cargo_id: str, motivo: str, descartes: Iterable[Descarte] = (),
               avisos: Iterable[str] = ()) -> ResultadoCargo:
    orden = sorted(descartes, key=lambda d: (d.uuid, d.motivo))
    return ResultadoCargo(cargo_id, (), None, motivo, None, None, (), None, tuple(orden), tuple(avisos))


def _diagnosticar(cargo: Cargo, pool: Pool, libres: AbstractSet[str], config: ConfigCruce,
                  avisos: Sequence[str]) -> ResultadoCargo:
    """El primer motivo que aplica, en el orden de la spec; los CFDIs de cada diagnóstico se listan."""
    if not cargo.cruzable:
        motivo = NO_APLICA if cargo.estado == ESTADO_OK and cargo.fecha is not None else FILA_ININTERPRETABLE
        return _sin_cruce(cargo.cargo_id, motivo)
    genericos, avisos_genericos = _evidencia_generica(cargo, pool, config)
    hallazgos = {
        SOLO_RFC_GENERICO: genericos,
        FUERA_DE_VENTANA: _fuera_de_ventana(cargo, pool, libres, config),
        FUERA_DE_TOLERANCIA: _fuera_de_tolerancia(cargo, pool, libres, config),
    }
    motivo = next((m for m in MOTIVOS if hallazgos.get(m)), SIN_CANDIDATO)
    descartes = [Descarte(u, m) for m, uuids in hallazgos.items() for u in uuids]
    return _sin_cruce(cargo.cargo_id, motivo, descartes, [*avisos, *avisos_genericos])


def _con_cruce(propuesta: _Propuesta, avisos: Sequence[str]) -> ResultadoCargo:
    orden = sorted(propuesta.cfdis, key=lambda c: c.uuid)
    return ResultadoCargo(
        cargo_id=propuesta.cargo.cargo_id,
        cfdis=tuple(c.uuid for c in orden),
        evidencia=propuesta.evidencia,
        motivo=None,
        diferencia=propuesta.diferencia,
        moneda_diferencia=propuesta.moneda,
        deltas=tuple(delta_dias(propuesta.cargo, c) for c in orden),
        afinidad=propuesta.afinidad,
        descartados=(),
        advertencias=tuple(avisos),
    )


def cruzar(cargos: Iterable[Cargo], cfdis: Iterable[Cfdi], config: ConfigCruce) -> ResultadoCruce:
    """Asigna CFDIs a cargos. Puro y determinista: no depende del orden de los insumos."""
    universo = sorted(cargos, key=lambda c: c.cargo_id)
    pool = armar_pool(cfdis, config)
    cruzables = [c for c in universo if c.cruzable]
    uno_a_uno = _aceptar(_propuestas_individuales(cruzables, pool, config), frozenset())
    tomados = frozenset(c.uuid for p in uno_a_uno for c in p.cfdis)
    resueltos = {p.cargo.cargo_id for p in uno_a_uno}
    pendientes = [c for c in cruzables if c.cargo_id not in resueltos]
    de_suma, avisos = _propuestas_de_suma(pendientes, pool, tomados, config)
    sumas = _aceptar(de_suma, tomados)
    asignadas: Mapping[str, _Propuesta] = {p.cargo.cargo_id: p for p in (*uno_a_uno, *sumas)}
    libres = frozenset(pool.todos) - {c.uuid for p in asignadas.values() for c in p.cfdis}
    resultados = tuple(
        _con_cruce(asignadas[c.cargo_id], avisos.get(c.cargo_id, ())) if c.cargo_id in asignadas
        else _diagnosticar(c, pool, libres, config, avisos.get(c.cargo_id, ()))
        for c in universo
    )
    return ResultadoCruce(resultados)
