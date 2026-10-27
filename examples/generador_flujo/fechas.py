"""Utilidades de calendario del generador: meses de una ventana y días hábiles."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Tuple

SABADO = 5
MESES_POR_ANIO = 12


def meses_en_ventana(inicio: date, fin: date) -> Tuple[Tuple[int, int], ...]:
    """(año, mes) de cada mes que toca la ventana [inicio, fin], en orden."""
    primero = inicio.year * MESES_POR_ANIO + inicio.month - 1
    ultimo = fin.year * MESES_POR_ANIO + fin.month - 1
    return tuple(divmod(n, MESES_POR_ANIO) for n in range(primero, ultimo + 1))


def fecha_de_mes(anio: int, indice_mes: int, dia: int) -> date:
    """Fecha a partir del índice de mes base 0 que devuelve `meses_en_ventana`."""
    return date(anio, indice_mes + 1, dia)


def ultimo_dia(anio: int, indice_mes: int) -> int:
    return calendar.monthrange(anio, indice_mes + 1)[1]


def etiqueta_mes(anio: int, indice_mes: int) -> str:
    return f"{anio:04d}-{indice_mes + 1:02d}"


def etiqueta_mes_anterior(anio: int, indice_mes: int) -> str:
    previo_anio, previo_mes = divmod(anio * MESES_POR_ANIO + indice_mes - 1, MESES_POR_ANIO)
    return etiqueta_mes(previo_anio, previo_mes)


def habil_anterior(fecha: date) -> date:
    """El mismo día si es hábil; si cae en fin de semana, el viernes anterior."""
    while fecha.weekday() >= SABADO:
        fecha -= timedelta(days=1)
    return fecha


def habil_siguiente(fecha: date) -> date:
    """El mismo día si es hábil; si cae en fin de semana, el lunes siguiente."""
    while fecha.weekday() >= SABADO:
        fecha += timedelta(days=1)
    return fecha
