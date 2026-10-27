"""Orquesta una corrida: casos -> libro -> ruido -> ids finales -> veredictos -> inyecciones -> autoverificación.

Si la autoverificación encuentra una coincidencia accidental (por ejemplo, una suma
de CFDIs que por azar iguala otro cargo), se reintenta con una sub-semilla derivada
de la semilla y del número de intento. Todo sigue siendo determinista.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from . import escenarios_cfdi, escenarios_empates, ruido
from .config import MAX_INTENTOS, ConfigGenerador
from .contexto import Contexto
from .escenarios_libro import completar_libro
from .fabricas import Escenario, unir
from .inyecciones import plantar_inyecciones
from .modelo import Asiento, Cargo, Cfdi, Datos, ExpectativaLibro, GrupoEmpate
from .verificacion import verificar
from .veredictos import plantar_veredictos

FOLIO_INICIAL = 1001


def _ids_cargos(cargos: Tuple[Cargo, ...]) -> Tuple[Cargo, ...]:
    """Orden del estado de cuenta: fecha de aplicación, fecha de operación, creación."""
    salida: List[Cargo] = []
    for emisor in sorted({c.emisor for c in cargos}):
        propios = sorted((c for c in cargos if c.emisor == emisor),
                         key=lambda c: (c.fecha_aplicacion, c.fecha, c.clave))
        salida.extend(replace(c, fila=n, cargo_id=f"{emisor}-{n:04d}") for n, c in enumerate(propios, 1))
    return tuple(salida)


def _ids_asientos(asientos: Tuple[Asiento, ...]) -> Tuple[Asiento, ...]:
    ordenados = sorted(asientos, key=lambda a: (a.fecha, a.origen, a.clave))
    return tuple(replace(a, asiento_id=f"AS-{n:04d}") for n, a in enumerate(ordenados, 1))


def _folios(cfdis: Tuple[Cfdi, ...]) -> Tuple[Cfdi, ...]:
    """Folio consecutivo por emisor y serie, en orden de fecha; salida ordenada por UUID."""
    salida: List[Cfdi] = []
    llaves = sorted({(c.rfc_emisor, c.nombre_emisor, c.serie) for c in cfdis})
    for llave in llaves:
        propios = sorted((c for c in cfdis if (c.rfc_emisor, c.nombre_emisor, c.serie) == llave),
                         key=lambda c: (c.fecha_emision, c.uuid))
        salida.extend(replace(c, folio=str(FOLIO_INICIAL + n)) for n, c in enumerate(propios))
    return tuple(sorted(salida, key=lambda c: c.uuid))


def _mapear_libro(libro: ExpectativaLibro, ids: Dict[str, str]) -> ExpectativaLibro:
    return replace(libro, esperado=ids.get(libro.esperado) if libro.esperado else None,
                   prohibidos=tuple(ids[a] for a in libro.prohibidos))


def _finalizar(config: ConfigGenerador, intento: int, base: Escenario) -> Datos:
    cargos = _ids_cargos(base.cargos)
    asientos = _ids_asientos(base.asientos)
    id_cargo = {c.clave: c.cargo_id for c in cargos}
    id_asiento = {a.clave: a.asiento_id for a in asientos}
    expectativas = tuple(sorted(
        (replace(e, clave_cargo=id_cargo[e.clave_cargo], libro=_mapear_libro(e.libro_requerido(), id_asiento))
         for e in base.expectativas), key=lambda e: e.clave_cargo))
    grupos = tuple(GrupoEmpate(g.grupo, tuple(sorted(id_cargo[c] for c in g.cargos)), tuple(sorted(g.cfdis)),
                               tuple(sorted(id_asiento[a] for a in g.asientos))) for g in base.grupos)
    veredictos = plantar_veredictos(config, intento, expectativas, asientos)
    cfdis, inyecciones = plantar_inyecciones(config, intento, expectativas, _folios(base.cfdis), veredictos)
    return Datos(config=config, intento=intento, cargos=tuple(sorted(cargos, key=lambda c: c.cargo_id)),
                 cfdis=cfdis, asientos=asientos, expectativas=expectativas, grupos=grupos,
                 veredictos=veredictos, inyecciones=inyecciones)


def construir(config: ConfigGenerador, intento: int) -> Datos:
    """Un intento de generación, sin autoverificación."""
    ctx = Contexto(config, intento)
    casos = unir(escenarios_cfdi.todos(ctx) + escenarios_empates.todos(ctx))
    completo = unir([completar_libro(ctx, casos)] + ruido.todo(ctx))
    return _finalizar(config, intento, completo)


def generar(config: Optional[ConfigGenerador] = None) -> Datos:
    """Genera el conjunto completo; garantiza que la autoverificación pase."""
    config = config or ConfigGenerador()
    ultimo = "sin intentos"
    for intento in range(MAX_INTENTOS):
        try:
            datos = construir(config, intento)
        except RuntimeError as exc:
            ultimo = str(exc)
            continue
        violaciones = verificar(datos)
        if not violaciones:
            return datos
        ultimo = f"{len(violaciones)} violaciones, la primera: {violaciones[0]}"
    raise RuntimeError(f"No se generó un conjunto válido en {MAX_INTENTOS} intentos ({ultimo}).")

