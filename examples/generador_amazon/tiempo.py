"""Husos y fechas del generador. Solo desfases fijos `UTC±HH:MM`."""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone

_PATRON = re.compile(r"UTC([+-])(\d{2}):(\d{2})")
FORMATO = "%Y-%m-%d %H:%M:%S"


def huso(texto_huso: str) -> timezone:
    coincidencia = _PATRON.fullmatch(texto_huso)
    if coincidencia is None:
        raise ValueError(f"huso inválido: {texto_huso!r}")
    signo, horas, minutos = coincidencia.groups()
    desfase = timedelta(hours=int(horas), minutes=int(minutos))
    return timezone(desfase if signo == "+" else -desfase)


def desde_local(texto_local: str, zona: timezone) -> datetime:
    return datetime.strptime(texto_local, FORMATO).replace(tzinfo=zona)


def a_local(instante: datetime, zona: timezone) -> str:
    return instante.astimezone(zona).strftime(FORMATO)


def mes_de(instante: datetime, zona: timezone) -> str:
    return instante.astimezone(zona).strftime("%Y-%m")


def partes_mes(mes: str) -> tuple[int, int]:
    anio, numero = mes.split("-")
    return int(anio), int(numero)


def dias_del_mes(mes: str) -> int:
    anio, numero = partes_mes(mes)
    return calendar.monthrange(anio, numero)[1]


def mes_siguiente(mes: str) -> str:
    anio, numero = partes_mes(mes)
    return f"{anio + 1:04d}-01" if numero == 12 else f"{anio:04d}-{numero + 1:02d}"


def mes_previo(mes: str) -> str:
    anio, numero = partes_mes(mes)
    return f"{anio - 1:04d}-12" if numero == 1 else f"{anio:04d}-{numero - 1:02d}"


def momento(mes: str, dia: int, hora: int, minuto: int, segundo: int, zona: timezone) -> datetime:
    anio, numero = partes_mes(mes)
    return datetime(anio, numero, dia, hora, minuto, segundo, tzinfo=zona)
