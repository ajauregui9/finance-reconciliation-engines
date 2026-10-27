"""Casos de montos repetidos, diseñados en ambos lados (CFDI y libro mayor).

- Grupo de empate: mismo comercio, monto y fecha; cualquier asignación uno a uno
  dentro del grupo es correcta.
- Mismo monto con fechas distintas: gana el CFDI/asiento de la misma fecha.
- Mismo monto y fecha en comercios distintos: decide la identidad del emisor.
- Descartado por nombre: el único candidato en el libro es de otro comercio.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from typing import List, Sequence, Tuple

from .catalogo import COMERCIOS, COMERCIOS_SIN_FACTURA
from .contexto import Contexto, periodo_emisor
from .fabricas import (Escenario, asiento_tarjeta, cfdi_comercio, dias, esperar, nuevo_cargo,
                       tarjeta_al_azar)
from .modelo import Asiento, Cargo, Cfdi, Expectativa, ExpectativaLibro, GrupoEmpate

TAMANOS_EMPATE = (2, 2, 2, 3)
PARES_FECHAS_DISTINTAS = 2
PARES_DESCARTADOS = 3
SEPARACION_DIAS = 4
MONTO_MAXIMO_EMPATE = 1800


def _fecha_comun(ctx: Contexto, emisor: str) -> date:
    inicio, fin = periodo_emisor(ctx.config, emisor)
    return ctx.fecha_entre(inicio, fin - dias(SEPARACION_DIAS + 2))


def _grupo(ctx: Contexto, numero: int, tamano: int) -> Escenario:
    comercio = ctx.elegir([c for c in COMERCIOS if c.rango[1] <= MONTO_MAXIMO_EMPATE])
    emisor = ctx.elegir(("ALFA", "BETA"))
    primero = nuevo_cargo(ctx, comercio, ctx.monto(*comercio.rango),
                          tarjeta=tarjeta_al_azar(ctx, emisor), fecha=_fecha_comun(ctx, emisor))
    # El primer grupo repite la fila completa (misma tarjeta): no debe deduplicarse.
    cargos = (primero,) + tuple(
        replace(primero, clave=ctx.clave("K"),
                tarjeta=primero.tarjeta if numero == 1 else tarjeta_al_azar(ctx, emisor))
        for _ in range(tamano - 1))
    fecha_cfdi = primero.fecha + dias(ctx.delta_en_ventana(1, 1))
    cfdis = tuple(cfdi_comercio(ctx, comercio, primero.monto, fecha_cfdi) for _ in cargos)
    asientos = tuple(asiento_tarjeta(ctx, c, primero.fecha + dias(1)) for c in cargos)
    grupo = f"EMP-{numero:02d}"
    exps = tuple(
        esperar(c, ("empate_grupo", "libro_registrado"), (u.uuid,), "monto_exacto",
                libro=ExpectativaLibro(esperado=a.clave), grupo=grupo)
        for c, u, a in zip(cargos, cfdis, asientos))
    registro = GrupoEmpate(grupo, tuple(c.clave for c in cargos), tuple(u.uuid for u in cfdis),
                           tuple(a.clave for a in asientos))
    return Escenario(cargos=cargos, cfdis=cfdis, asientos=asientos, expectativas=exps, grupos=(registro,))


def _par_cruzado(cargos: Sequence[Cargo], cfdis: Sequence[Cfdi], asientos: Sequence[Asiento],
                 caso: str) -> Tuple[Expectativa, ...]:
    """Cada cargo espera su CFDI y su asiento, y tiene prohibidos los del otro."""
    return tuple(
        esperar(cargo, (caso, "libro_registrado"), (cfdis[i].uuid,), "monto_exacto", (cfdis[1 - i].uuid,),
                libro=ExpectativaLibro(esperado=asientos[i].clave, prohibidos=(asientos[1 - i].clave,)))
        for i, cargo in enumerate(cargos))


def _fechas_distintas(ctx: Contexto) -> Escenario:
    comercio = ctx.elegir(COMERCIOS)
    tarjeta = tarjeta_al_azar(ctx)
    fecha = _fecha_comun(ctx, tarjeta.emisor)
    monto = ctx.monto(*comercio.rango)
    cargos = tuple(nuevo_cargo(ctx, comercio, monto, tarjeta=tarjeta, fecha=fecha + dias(k))
                   for k in (0, SEPARACION_DIAS))
    cfdis = tuple(cfdi_comercio(ctx, comercio, monto, c.fecha) for c in cargos)
    asientos = tuple(asiento_tarjeta(ctx, c, c.fecha) for c in cargos)
    return Escenario(cargos=cargos, cfdis=cfdis, asientos=asientos,
                     expectativas=_par_cruzado(cargos, cfdis, asientos, "empate_monto_fechas_distintas"))


def _comercios_distintos(ctx: Contexto) -> Escenario:
    uno, otro = ctx.barajar(COMERCIOS)[:2]
    tarjeta = tarjeta_al_azar(ctx)
    fecha = _fecha_comun(ctx, tarjeta.emisor)
    monto = ctx.monto(max(uno.rango[0], otro.rango[0]), max(uno.rango[1], otro.rango[1]))
    cargos = tuple(nuevo_cargo(ctx, c, monto, tarjeta=tarjeta, fecha=fecha) for c in (uno, otro))
    fecha_cfdi = fecha + dias(ctx.delta_en_ventana(1, 1))
    cfdis = tuple(cfdi_comercio(ctx, c.comercio_requerido(), monto, fecha_cfdi) for c in cargos)
    asientos = tuple(asiento_tarjeta(ctx, c, fecha + dias(1)) for c in cargos)
    return Escenario(cargos=cargos, cfdis=cfdis, asientos=asientos,
                     expectativas=_par_cruzado(cargos, cfdis, asientos,
                                               "empate_monto_fecha_comercios_distintos"))


def _descartado(ctx: Contexto) -> Escenario:
    """Cargo A sin registro; el libro tiene un asiento de igual monto y fecha, pero del comercio B."""
    uno, otro = ctx.barajar(COMERCIOS_SIN_FACTURA)[:2]
    tarjeta = tarjeta_al_azar(ctx)
    a = nuevo_cargo(ctx, uno, ctx.monto(*uno.rango), tarjeta=tarjeta)
    b = nuevo_cargo(ctx, otro, a.monto, tarjeta=tarjeta_al_azar(ctx, tarjeta.emisor),
                    fecha=a.fecha + dias(ctx.entero(0, 1)))
    asiento_b = asiento_tarjeta(ctx, b, b.fecha + dias(ctx.entero(0, 1)))
    exps = (
        esperar(a, ("sin_cfdi", "libro_descartado_por_nombre"), motivo="sin_candidato",
                libro=ExpectativaLibro(prohibidos=(asiento_b.clave,), motivo="descartado_por_nombre")),
        esperar(b, ("sin_cfdi", "libro_registrado"), motivo="sin_candidato",
                libro=ExpectativaLibro(esperado=asiento_b.clave)),
    )
    return Escenario(cargos=(a, b), asientos=(asiento_b,), expectativas=exps)


def todos(ctx: Contexto) -> List[Escenario]:
    return ([_grupo(ctx, n, t) for n, t in enumerate(TAMANOS_EMPATE, 1)]
            + [_fechas_distintas(ctx) for _ in range(PARES_FECHAS_DISTINTAS)]
            + [_comercios_distintos(ctx)]
            + [_descartado(ctx) for _ in range(PARES_DESCARTADOS)])
