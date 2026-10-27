"""Curva de cobranza: cómo se reparte en semanas el saldo de una cuenta por cobrar.

El reparto usa diferencias de acumulados redondeados, así la suma de las piezas es
exactamente el redondeo del saldo por el peso total y nunca aparece ni se pierde un
centavo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import accumulate
from typing import Sequence, Tuple

from .calendario import SEMANAS_HORIZONTE, indice_semana
from .config import CurvaCobranza, TramoCurva
from .dinero import CERO, centavos
from .errores import ErrorConfig


@dataclass(frozen=True)
class PlanCobro:
    """Piezas (semana, monto) dentro del horizonte y lo que queda fuera de él."""

    tramo: str
    piezas: Tuple[Tuple[int, Decimal], ...]
    fuera_horizonte: Decimal
    no_cobrable: Decimal


def tramo_para(curva: CurvaCobranza, antiguedad: int) -> TramoCurva:
    for tramo in curva.tramos:
        if tramo.contiene(antiguedad):
            return tramo
    raise ErrorConfig(f"ningún tramo de la curva cubre una antigüedad de {antiguedad} días")


def repartir(saldo: Decimal, pesos: Sequence[Decimal]) -> Tuple[Decimal, ...]:
    """Monto de cada pieza: r(S·P_k) - r(S·P_{k-1}), con P_k el peso acumulado."""
    acumulados = tuple(centavos(saldo * peso) for peso in accumulate(pesos))
    return tuple(actual - previo for previo, actual in zip((CERO,) + acumulados, acumulados))


def planear_cobro(saldo: Decimal, fecha_vencimiento: date, corte: date, curva: CurvaCobranza) -> PlanCobro:
    """Ubica en semanas la cobranza esperada de una factura según su antigüedad al corte.

    Una factura vencida empieza a cobrarse en la semana 1; una por vencer, en la
    semana de su vencimiento. Las piezas en cero no se listan.
    """
    tramo = tramo_para(curva, (corte - fecha_vencimiento).days)
    ancla = indice_semana(max(fecha_vencimiento, corte), corte)
    piezas = repartir(saldo, tramo.pesos)
    ubicadas = tuple((ancla + desfase, monto) for desfase, monto in enumerate(piezas))
    return PlanCobro(
        tramo=tramo.tramo,
        piezas=tuple((s, m) for s, m in ubicadas if s <= SEMANAS_HORIZONTE and m != CERO),
        fuera_horizonte=sum((m for s, m in ubicadas if s > SEMANAS_HORIZONTE), CERO),
        no_cobrable=saldo - sum(piezas, CERO),
    )
