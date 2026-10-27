"""Motor del cruce cargo ↔ CFDI: asignación greedy en cuatro fases y diagnóstico de los cargos sin cruce.

La evidencia con afinidad de nombre siempre gana sobre la que solo coincide por
monto y, dentro de cada nivel, un cruce uno a uno gana sobre una suma. Por eso las
fases corren en este orden y cada una termina por completo antes de la siguiente:

1. uno a uno con afinidad (`monto_exacto`, `moneda_original`, `monto_tolerancia`);
2. sumas con afinidad (`suma`);
3. uno a uno sin afinidad (`monto_sin_afinidad`);
4. sumas sin afinidad (`monto_sin_afinidad`).

Cada fase ordena sus propuestas con un orden total y acepta una propuesta si su
cargo sigue libre y todos sus CFDIs también. Un cruce `monto_sin_afinidad` ocupa sus
CFDIs como cualquier otro, pero no respalda al cargo: queda para revisión humana.
Ver specs/cruce_cfdi.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from itertools import combinations
from typing import AbstractSet, Any, Dict, FrozenSet, Iterable, List, Mapping, Sequence, Set, Tuple

from .cruce_cfdi_candidatos import (
    Pool,
    afinidad_de,
    alcanza_afinidad,
    armar_pool,
    calificar,
    delta_dias,
    en_ventana,
)
from .cruce_cfdi_config import ConfigCruce
from .cruce_cfdi_modelo import (
    ESTADO_OK,
    FILA_ININTERPRETABLE,
    FUERA_DE_TOLERANCIA,
    FUERA_DE_VENTANA,
    MONEDA_LOCAL,
    MONTO_SIN_AFINIDAD,
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

Avisos = Mapping[str, Tuple[str, ...]]
# (¿es fase de sumas?, ¿exige afinidad?) en el orden en que corren las fases.
FASES: Tuple[Tuple[bool, bool], ...] = ((False, True), (True, True), (False, False), (True, False))


@dataclass(frozen=True)
class _Propuesta:
    clave: Tuple[Any, ...]
    cargo: Cargo
    cfdis: Tuple[Cfdi, ...]
    evidencia: str
    diferencia: Decimal
    moneda: str
    afinidad: Fraction


def _propuestas_individuales(cargos: Sequence[Cargo], pool: Pool, tomados: AbstractSet[str],
                             config: ConfigCruce, con_afinidad: bool) -> List[_Propuesta]:
    """Pares uno a uno con CFDI libre cuya afinidad alcanza (o no alcanza) el mínimo, según la fase."""
    propuestas = []
    for cargo in cargos:
        for cfdi, calificacion in pool.individuales(cargo, config):
            parecido = afinidad_de(cargo, cfdi)
            if cfdi.uuid in tomados or alcanza_afinidad(parecido, config) != con_afinidad:
                continue
            delta = delta_dias(cargo, cfdi)
            clave = (calificacion.rango, -parecido, calificacion.diferencia, abs(delta), delta < 0,
                     cargo.cargo_id, cfdi.uuid)
            evidencia = calificacion.evidencia if con_afinidad else MONTO_SIN_AFINIDAD
            propuestas.append(_Propuesta(clave, cargo, (cfdi,), evidencia,
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
    return [c for c in cfdis if alcanza_afinidad(afinidad_de(cargo, c), config)]


def _propuestas_de_suma(
    cargos: Sequence[Cargo], pool: Pool, tomados: AbstractSet[str], config: ConfigCruce, con_afinidad: bool
) -> Tuple[List[_Propuesta], Avisos]:
    """Sumas de CFDIs libres de un emisor. Con afinidad, solo entran CFDIs que la alcanzan cada uno;
    sin afinidad entran todos, y el tier lo decide la menor afinidad del grupo."""
    propuestas: List[_Propuesta] = []
    avisos: Dict[str, Tuple[str, ...]] = {}
    for cargo in cargos:
        libres = [c for c in pool.validos_en_ventana(cargo, config) if c.uuid not in tomados]
        combos, avisos_cargo = _sumas(cargo, _con_afinidad(cargo, libres, config) if con_afinidad else libres, config)
        if avisos_cargo:
            avisos[cargo.cargo_id] = tuple(avisos_cargo)
        for combo in combos:
            diferencia = abs(sum((c.valor_mxn for c in combo), Decimal(0)) - cargo.monto)
            parecido = min(afinidad_de(cargo, c) for c in combo)
            lejania = max(abs(delta_dias(cargo, c)) for c in combo)
            clave = (len(combo), diferencia, -parecido, lejania, cargo.cargo_id, tuple(c.uuid for c in combo))
            evidencia = SUMA if alcanza_afinidad(parecido, config) else MONTO_SIN_AFINIDAD
            propuestas.append(_Propuesta(clave, cargo, combo, evidencia, diferencia, MONEDA_LOCAL, parecido))
    return propuestas, avisos


def _propuestas(fase: Tuple[bool, bool], cargos: Sequence[Cargo], pool: Pool, tomados: AbstractSet[str],
                config: ConfigCruce) -> Tuple[List[_Propuesta], Avisos]:
    es_suma, con_afinidad = fase
    if es_suma:
        return _propuestas_de_suma(cargos, pool, tomados, config, con_afinidad)
    return _propuestas_individuales(cargos, pool, tomados, config, con_afinidad), {}


def _unir_avisos(previos: Avisos, nuevos: Avisos) -> Dict[str, Tuple[str, ...]]:
    """Avisos por cargo de todas las fases, sin repetir un mismo texto y en el orden en que aparecieron."""
    salida = {cid: tuple(avisos) for cid, avisos in previos.items()}
    for cid, avisos in nuevos.items():
        actuales = salida.get(cid, ())
        salida[cid] = actuales + tuple(a for a in dict.fromkeys(avisos) if a not in actuales)
    return salida


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
    pendientes = [c for c in universo if c.cruzable]
    tomados: FrozenSet[str] = frozenset()
    aceptadas: List[_Propuesta] = []
    avisos: Avisos = {}
    for fase in FASES:
        propuestas, avisos_fase = _propuestas(fase, pendientes, pool, tomados, config)
        nuevas = _aceptar(propuestas, tomados)
        aceptadas.extend(nuevas)
        tomados = tomados | {c.uuid for p in nuevas for c in p.cfdis}
        resueltos = {p.cargo.cargo_id for p in nuevas}
        pendientes = [c for c in pendientes if c.cargo_id not in resueltos]
        avisos = _unir_avisos(avisos, avisos_fase)
    asignadas: Mapping[str, _Propuesta] = {p.cargo.cargo_id: p for p in aceptadas}
    libres = frozenset(pool.todos) - {c.uuid for p in asignadas.values() for c in p.cfdis}
    resultados = tuple(
        _con_cruce(asignadas[c.cargo_id], avisos.get(c.cargo_id, ())) if c.cargo_id in asignadas
        else _diagnosticar(c, pool, libres, config, avisos.get(c.cargo_id, ()))
        for c in universo
    )
    return ResultadoCruce(resultados)
