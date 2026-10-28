"""Corte horario: del huso que declara el archivo al mes del huso de cierre.

Solo se aceptan desfases fijos (`UTC±HH:MM`). No hay ningún desfase supuesto entre la
plataforma y el cierre: cada instante se convierte con el huso que trae su archivo. Husos,
fechas y meses se leen con la frontera compartida (`frontera.fechas`): forma fija y
dígitos ASCII.
"""
from __future__ import annotations

from datetime import datetime, timezone

from frontera import leer_desfase_utc
from frontera import leer_fecha_hora as _leer_fecha_hora
from frontera import leer_mes

_MAX_HORAS = 14


def interpretar_huso(texto: str) -> timezone:
    """`UTC-07:00` -> `timezone(-7 h)`. Cualquier otra forma es un `ValueError`."""
    return leer_desfase_utc(texto.strip(), horas_max=_MAX_HORAS)


def leer_fecha_hora(texto: str, huso: timezone) -> datetime:
    """Lee `AAAA-MM-DD HH:MM:SS` como hora local del huso dado."""
    return _leer_fecha_hora(texto.strip()).replace(tzinfo=huso)


def mes_en_huso(instante: datetime, huso: timezone) -> str:
    """Mes `AAAA-MM` de un instante visto desde el huso dado."""
    return instante.astimezone(huso).strftime("%Y-%m")


def validar_mes(texto: str) -> str:
    """Devuelve el mes si tiene forma `AAAA-MM` válida."""
    return leer_mes(texto)


def mes_anterior(mes: str) -> str:
    """`2026-01` -> `2025-12`."""
    anio, numero = (int(parte) for parte in validar_mes(mes).split("-"))
    if numero == 1:
        return f"{anio - 1:04d}-12"
    return f"{anio:04d}-{numero - 1:02d}"
