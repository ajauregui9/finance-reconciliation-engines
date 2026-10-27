"""Candidatura, evaluación y asignación greedy exclusiva cargo ↔ asiento.

Funciones puras: reciben tuplas inmutables y devuelven objetos nuevos. Las reglas
están en `specs/cruce_libro.md` ("Candidatos", "Evaluación", "Asignación").
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .cruce_libro_modelo import (
    EVAL_CUBETA_FECHA,
    EVAL_ELEGIBLE,
    EVAL_NOMBRE,
    ESTADO_OK,
    MOTIVO_CUBETA,
    MOTIVO_ININTERPRETABLE,
    MOTIVO_NO_APLICA,
    MOTIVO_NOMBRE,
    MOTIVO_OCUPADO,
    MOTIVO_SIN_CANDIDATO,
    TIPO_PAGO,
    Candidato,
    Cargo,
    ConfigCruceLibro,
    Cruce,
    EvaluacionCargo,
    LineaLibro,
)
from .nombres import ComparadorNombres

LlavePar = Tuple[object, ...]


def _motivo_previo(cargo: Cargo) -> Optional[str]:
    """Motivo de los cargos que no se buscan; la fila ilegible va primero."""
    if cargo.estado != ESTADO_OK or cargo.fecha is None:
        return MOTIVO_ININTERPRETABLE
    if cargo.tipo_movimiento == TIPO_PAGO:
        return MOTIVO_NO_APLICA
    return None


def _lineas_por_cuenta(lineas: Iterable[LineaLibro]) -> Dict[str, Tuple[LineaLibro, ...]]:
    agrupadas: Dict[str, List[LineaLibro]] = {}
    for linea in sorted(lineas, key=lambda x: (x.cuenta, x.asiento_id, x.linea)):
        agrupadas.setdefault(linea.cuenta, []).append(linea)
    return {cuenta: tuple(grupo) for cuenta, grupo in agrupadas.items()}


def _comparador(cargos: Sequence[Cargo], lineas_tarjeta: Iterable[LineaLibro],
                config: ConfigCruceLibro) -> ComparadorNombres:
    izquierda = [c.descripcion for c in cargos if _motivo_previo(c) is None]
    derecha = [x.proveedor_nombre for x in lineas_tarjeta]
    return ComparadorNombres.desde_vocabularios(izquierda, derecha, config.nombres)


def _evaluar_linea(cargo: Cargo, linea: LineaLibro, config: ConfigCruceLibro,
                   comparador: ComparadorNombres) -> Optional[Candidato]:
    """Devuelve el candidato evaluado, o None si la línea no cumple la candidatura."""
    assert cargo.fecha is not None  # garantizado por _motivo_previo
    importe = linea.haber if cargo.monto > 0 else linea.debe
    if importe <= 0:
        return None
    diferencia = abs(importe - abs(cargo.monto))
    delta = (linea.fecha - cargo.fecha).days
    if diferencia > config.tolerancia_monto or not config.ventana_busqueda.contiene(delta):
        return None
    if linea.proveedor_id in config.proveedores_cubeta:
        evaluacion = EVAL_ELEGIBLE if config.ventana_cubeta.contiene(delta) else EVAL_CUBETA_FECHA
        return Candidato(linea, delta, diferencia, True, None, evaluacion)
    similitud = comparador.similitud(cargo.descripcion, linea.proveedor_nombre)
    evaluacion = EVAL_ELEGIBLE if similitud >= config.umbral_fraccion else EVAL_NOMBRE
    return Candidato(linea, delta, diferencia, False, similitud, evaluacion)


def _validar_emisores(cargos: Sequence[Cargo], config: ConfigCruceLibro) -> None:
    faltantes = sorted({c.emisor for c in cargos} - set(config.cuenta_por_emisor))
    if faltantes:
        raise ValueError(f"Emisores sin cuenta de tarjeta en la config: {', '.join(faltantes)}.")


def evaluar_cargos(cargos: Tuple[Cargo, ...], lineas: Tuple[LineaLibro, ...],
                   config: ConfigCruceLibro) -> Tuple[EvaluacionCargo, ...]:
    """Evalúa cada cargo contra las líneas de la cuenta de su tarjeta, sin asignar nada."""
    _validar_emisores(cargos, config)
    por_cuenta = _lineas_por_cuenta(lineas)
    cuentas = config.cuenta_por_emisor
    tarjeta = [x for cuenta in sorted(set(cuentas.values())) for x in por_cuenta.get(cuenta, ())]
    comparador = _comparador(cargos, tarjeta, config)
    salida = []
    for cargo in sorted(cargos, key=lambda c: c.cargo_id):
        motivo = _motivo_previo(cargo)
        evaluados: Tuple[Candidato, ...] = ()
        if motivo is None:
            posibles = (_evaluar_linea(cargo, x, config, comparador) for x in por_cuenta.get(cuentas[cargo.emisor], ()))
            evaluados = tuple(sorted((c for c in posibles if c is not None),
                                     key=lambda c: (not c.elegible, c.prioridad())))
        salida.append(EvaluacionCargo(cargo, evaluados, motivo))
    return tuple(salida)


def _llave(cargo_id: str, candidato: Candidato) -> LlavePar:
    prioridad = candidato.prioridad()
    return prioridad[:5] + (cargo_id,) + prioridad[5:]


def _motivo_sin_cruce(evaluacion: EvaluacionCargo) -> str:
    if evaluacion.motivo_previo is not None:
        return evaluacion.motivo_previo
    evaluaciones = {c.evaluacion for c in evaluacion.candidatos}
    if not evaluaciones:
        return MOTIVO_SIN_CANDIDATO
    if EVAL_ELEGIBLE in evaluaciones:
        return MOTIVO_OCUPADO
    if EVAL_NOMBRE in evaluaciones:
        return MOTIVO_NOMBRE
    return MOTIVO_CUBETA


def _greedy(activas: Sequence[EvaluacionCargo], reservados: frozenset[str]) -> Mapping[str, Candidato]:
    pares = sorted(((_llave(e.cargo.cargo_id, c), e.cargo.cargo_id, c)
                    for e in activas for c in e.candidatos if c.elegible), key=lambda p: p[0])
    elegidos: Dict[str, Candidato] = {}
    ocupados = set(reservados)
    for _, cargo_id, candidato in pares:
        if cargo_id in elegidos or candidato.linea.asiento_id in ocupados:
            continue
        elegidos[cargo_id] = candidato
        ocupados.add(candidato.linea.asiento_id)
    return elegidos


def asignar(evaluaciones: Sequence[EvaluacionCargo], *, excluidos: frozenset[str] = frozenset(),
            reservados: frozenset[str] = frozenset()) -> Dict[str, Cruce]:
    """Asignación greedy exclusiva; `excluidos` no compiten y `reservados` no se ofrecen."""
    activas = [e for e in evaluaciones if e.cargo.cargo_id not in excluidos]
    elegidos = _greedy(activas, reservados)
    salida = {}
    for evaluacion in sorted(activas, key=lambda e: e.cargo.cargo_id):
        cargo_id = evaluacion.cargo.cargo_id
        candidato = elegidos.get(cargo_id)
        motivo = None if candidato else _motivo_sin_cruce(evaluacion)
        salida[cargo_id] = Cruce(cargo_id, candidato, motivo)
    return salida
