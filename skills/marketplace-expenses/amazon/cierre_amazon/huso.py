"""Corte horario: del huso que declara el archivo al mes del huso de cierre.

Solo se aceptan desfases fijos (`UTC±HH:MM`). No hay ningún desfase supuesto entre la
plataforma y el cierre: cada instante se convierte con el huso que trae su archivo.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_PATRON_HUSO = re.compile(r"UTC([+-])(\d{2}):(\d{2})")
_PATRON_MES = re.compile(r"(\d{4})-(\d{2})")
_FORMATO_FECHA_HORA = "%Y-%m-%d %H:%M:%S"
_MAX_HORAS = 14


def interpretar_huso(texto: str) -> timezone:
    """`UTC-07:00` -> `timezone(-7 h)`. Cualquier otra forma es un `ValueError`."""
    coincidencia = _PATRON_HUSO.fullmatch(texto.strip())
    if coincidencia is None:
        raise ValueError(f"se espera un desfase fijo UTC±HH:MM, llegó {texto!r}")
    signo, horas, minutos = coincidencia.groups()
    if int(horas) > _MAX_HORAS or int(minutos) >= 60:
        raise ValueError(f"desfase fijo fuera de rango: {texto!r}")
    desfase = timedelta(hours=int(horas), minutes=int(minutos))
    return timezone(-desfase if signo == "-" else desfase)


def leer_fecha_hora(texto: str, huso: timezone) -> datetime:
    """Lee `AAAA-MM-DD HH:MM:SS` como hora local del huso dado."""
    try:
        local = datetime.strptime(texto.strip(), _FORMATO_FECHA_HORA)
    except ValueError as exc:
        raise ValueError(f"fecha y hora inválida (AAAA-MM-DD HH:MM:SS): {texto!r}") from exc
    return local.replace(tzinfo=huso)


def mes_en_huso(instante: datetime, huso: timezone) -> str:
    """Mes `AAAA-MM` de un instante visto desde el huso dado."""
    return instante.astimezone(huso).strftime("%Y-%m")


def validar_mes(texto: str) -> str:
    """Devuelve el mes si tiene forma `AAAA-MM` válida."""
    coincidencia = _PATRON_MES.fullmatch(texto)
    if coincidencia is None or not 1 <= int(coincidencia.group(2)) <= 12:
        raise ValueError(f"mes inválido (AAAA-MM): {texto!r}")
    return texto


def mes_anterior(mes: str) -> str:
    """`2026-01` -> `2025-12`."""
    anio, numero = (int(parte) for parte in validar_mes(mes).split("-"))
    if numero == 1:
        return f"{anio - 1:04d}-12"
    return f"{anio:04d}-{numero - 1:02d}"
