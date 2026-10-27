"""Métricas del estado de resultados y su evaluación contra corredores declarados."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Tuple

from .config import METRICAS, Banda
from .dinero import CERO, porcentaje
from .rubros import TotalesRubro

DENTRO = "dentro"
FUERA_FAVORABLE = "fuera_favorable"
FUERA_DESFAVORABLE = "fuera_desfavorable"


@dataclass(frozen=True)
class Metrica:
    monto: Decimal
    pct: Decimal


@dataclass(frozen=True)
class EvaluacionBanda:
    metrica: str
    monto: Decimal
    valor_pct: Decimal
    minimo_pct: Decimal
    maximo_pct: Decimal
    favorable: str
    estado: str
    desvio_pct: Decimal


def calcular_metricas(totales: TotalesRubro, base: Decimal) -> Mapping[str, Metrica]:
    """Las cuatro métricas sobre la base de ingreso; `bajo_ebitda` no entra en ninguna."""
    utilidad_bruta = base - totales.costo
    ebitda = utilidad_bruta - totales.gasto_venta - totales.gasto_admin
    montos = {
        "margen_bruto": utilidad_bruta,
        "gasto_venta": totales.gasto_venta,
        "gasto_admin": totales.gasto_admin,
        "ebitda": ebitda,
    }
    return MappingProxyType({m: Metrica(monto=montos[m], pct=porcentaje(montos[m], base)) for m in METRICAS})


def _fuera_hacia(lado: str, banda: Banda) -> str:
    return FUERA_FAVORABLE if lado == banda.favorable else FUERA_DESFAVORABLE


def _estado_y_desvio(valor: Decimal, banda: Banda) -> Tuple[str, Decimal]:
    """Extremos incluidos; el desvío es la distancia al extremo más cercano."""
    if valor < banda.minimo_pct:
        return _fuera_hacia("bajo", banda), banda.minimo_pct - valor
    if valor > banda.maximo_pct:
        return _fuera_hacia("alto", banda), valor - banda.maximo_pct
    return DENTRO, CERO


def _evaluar(nombre: str, metrica: Metrica, banda: Banda) -> EvaluacionBanda:
    estado, desvio = _estado_y_desvio(metrica.pct, banda)
    return EvaluacionBanda(
        metrica=nombre,
        monto=metrica.monto,
        valor_pct=metrica.pct,
        minimo_pct=banda.minimo_pct,
        maximo_pct=banda.maximo_pct,
        favorable=banda.favorable,
        estado=estado,
        desvio_pct=desvio,
    )


def evaluar_bandas(metricas: Mapping[str, Metrica], bandas: Mapping[str, Banda]) -> Tuple[EvaluacionBanda, ...]:
    """Evalúa solo las métricas que tienen banda, en el orden de un estado de resultados."""
    return tuple(_evaluar(m, metricas[m], bandas[m]) for m in METRICAS if m in bandas)
