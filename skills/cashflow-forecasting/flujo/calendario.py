"""Calendario del horizonte: 13 semanas de siete días que arrancan en la fecha de corte."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Tuple

SEMANAS_HORIZONTE = 13
DIAS_POR_SEMANA = 7


@dataclass(frozen=True)
class Semana:
    numero: int
    inicio: date
    fin: date

    def contiene(self, fecha: date) -> bool:
        return self.inicio <= fecha <= self.fin


def inicio_semana(corte: date, numero: int) -> date:
    """Primer día de la semana `numero` (base 1)."""
    return corte + timedelta(days=DIAS_POR_SEMANA * (numero - 1))


def semanas_del_horizonte(corte: date) -> Tuple[Semana, ...]:
    return tuple(
        Semana(numero=n, inicio=inicio_semana(corte, n), fin=inicio_semana(corte, n + 1) - timedelta(days=1))
        for n in range(1, SEMANAS_HORIZONTE + 1)
    )


def fin_horizonte(corte: date) -> date:
    return inicio_semana(corte, SEMANAS_HORIZONTE + 1) - timedelta(days=1)


def indice_semana(fecha: date, corte: date) -> int:
    """Número de semana (base 1) en que cae `fecha`; mayor que 13 si queda fuera."""
    if fecha < corte:
        raise ValueError(f"la fecha {fecha.isoformat()} es anterior al corte {corte.isoformat()}")
    return (fecha - corte).days // DIAS_POR_SEMANA + 1
