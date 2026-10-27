"""Lado cargo <-> libro mayor para los cargos que ningún caso diseñó ya.

Reparto (sobre los cargos elegibles, en orden barajado con la semilla):
- `libro_cubeta`: registrado bajo el proveedor-cubeta, mismo monto y fecha cercana.
- `libro_cubeta_fecha_lejana`: no registrado; existe un asiento de la cubeta con el
  mismo monto pero a 20-30 días (pertenece a otro periodo).
- `libro_registrado`: registrado bajo su propio proveedor (la mayoría).
- `libro_no_registrado`: sin asiento.
"""
from __future__ import annotations

from dataclasses import replace
from typing import List, Tuple

from .config import CUBETA_LEJANA_MAX, CUBETA_LEJANA_MIN, LIBRO_DESFASE_MAX, LIBRO_DESFASE_MIN
from .contexto import Contexto
from .fabricas import Escenario, asiento_tarjeta, dias, periodo_de
from .modelo import Asiento, Cargo, Expectativa, ExpectativaLibro

CUOTA_CUBETA = 8
CUOTA_CUBETA_LEJANA = 3
PCT_REGISTRADO = 72


def _desfase(ctx: Contexto) -> int:
    return ctx.entero(LIBRO_DESFASE_MIN, LIBRO_DESFASE_MAX)


def _con_libro(exp: Expectativa, caso: str, libro: ExpectativaLibro) -> Expectativa:
    return replace(exp, casos=exp.casos + (caso,), libro=libro)


def _registrar(ctx: Contexto, cargo: Cargo, exp: Expectativa, cubeta: bool) -> Tuple[Asiento, Expectativa]:
    asiento = asiento_tarjeta(ctx, cargo, cargo.fecha + dias(_desfase(ctx)), cubeta=cubeta)
    caso = "libro_cubeta" if cubeta else "libro_registrado"
    return asiento, _con_libro(exp, caso, ExpectativaLibro(esperado=asiento.clave, riesgo_cubeta=cubeta))


def _cubeta_lejana(ctx: Contexto, cargo: Cargo, exp: Expectativa) -> Tuple[Asiento, Expectativa]:
    desfase = ctx.entero(CUBETA_LEJANA_MIN, CUBETA_LEJANA_MAX) * (1 if ctx.probable(50) else -1)
    fecha = cargo.fecha + dias(desfase)
    asiento = asiento_tarjeta(ctx, cargo, fecha, cubeta=True, periodo_estado=periodo_de(fecha))
    libro = ExpectativaLibro(prohibidos=(asiento.clave,), motivo="cubeta_evidencia_insuficiente")
    return asiento, _con_libro(exp, "libro_cubeta_fecha_lejana", libro)


def completar_libro(ctx: Contexto, base: Escenario) -> Escenario:
    """Devuelve el escenario con asientos y expectativas de libro para todo cargo pendiente."""
    cargos = {c.clave: c for c in base.cargos}
    pendientes = [e for e in base.expectativas if e.libro is None]
    listas = {e.clave_cargo: e for e in base.expectativas if e.libro is not None}
    asientos: List[Asiento] = []
    cubetas = lejanas = 0
    for exp in ctx.barajar(pendientes):
        cargo = cargos[exp.clave_cargo]
        if cargo.tipo_movimiento == "cargo" and cubetas < CUOTA_CUBETA:
            asiento, nueva = _registrar(ctx, cargo, exp, cubeta=True)
            cubetas += 1
        elif cargo.tipo_movimiento == "cargo" and lejanas < CUOTA_CUBETA_LEJANA:
            asiento, nueva = _cubeta_lejana(ctx, cargo, exp)
            lejanas += 1
        elif ctx.probable(PCT_REGISTRADO):
            asiento, nueva = _registrar(ctx, cargo, exp, cubeta=False)
        else:
            asiento, nueva = None, _con_libro(exp, "libro_no_registrado",
                                              ExpectativaLibro(motivo="sin_candidato"))
        if asiento is not None:
            asientos.append(asiento)
        listas[exp.clave_cargo] = nueva
    expectativas = tuple(listas[e.clave_cargo] for e in base.expectativas)
    return replace(base, asientos=base.asientos + tuple(asientos), expectativas=expectativas)
