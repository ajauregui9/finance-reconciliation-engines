"""Frontera de entrada de fechas y horas: formas fijas con dígitos ASCII.

`\\d` acepta dígitos de cualquier alfabeto, y desde Python 3.11 `date.fromisoformat`
acepta además formas como `20260710` o `2026-W28-5`; `strptime` acepta campos de un solo
dígito (`2026-4-3 1:2:3`). Aquí cada forma se valida con `[0-9]` y longitud fija antes de
construir la fecha, así que el resultado es el mismo en Python 3.9 a 3.13.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from .errores import ErrorFrontera

HORAS_DESFASE_MAX = 14
MINUTOS_POR_HORA = 60
_FECHA = r"([0-9]{4})-([0-9]{2})-([0-9]{2})"
_HORA = r"([0-9]{2}):([0-9]{2}):([0-9]{2})"
_PATRON_FECHA = re.compile(_FECHA)
_PATRONES_FECHA_HORA = {sep: re.compile(_FECHA + sep + _HORA) for sep in (" ", "T")}
_PATRON_MES = re.compile(r"[0-9]{4}-(?:0[1-9]|1[0-2])")
_PATRON_DESFASE = re.compile(r"UTC([+-])([0-9]{2}):([0-9]{2})")


def _texto(valor: object, forma: str) -> str:
    if not isinstance(valor, str):
        raise ErrorFrontera(f"se espera texto {forma}; llegó {type(valor).__name__} ({valor!r})")
    return valor


def leer_fecha(valor: object) -> date:
    """`AAAA-MM-DD` exacto (sin espacios) a `date`."""
    texto = _texto(valor, "AAAA-MM-DD")
    partes = _PATRON_FECHA.fullmatch(texto)
    if partes is None:
        raise ErrorFrontera(f"{texto!r} no es una fecha AAAA-MM-DD con dígitos ASCII")
    anio, mes, dia = (int(p) for p in partes.groups())
    try:
        return date(anio, mes, dia)
    except ValueError:
        raise ErrorFrontera(f"la fecha {texto!r} no existe") from None


def leer_fecha_hora(valor: object, separador: str = " ") -> datetime:
    """`AAAA-MM-DD HH:MM:SS` (o con `T`) a `datetime` sin huso; sin fracciones ni zona."""
    patron = _PATRONES_FECHA_HORA.get(separador)
    if patron is None:
        raise ValueError(f"separador de fecha y hora no admitido: {separador!r}")
    forma = f"AAAA-MM-DD{separador}HH:MM:SS"
    texto = _texto(valor, forma)
    partes = patron.fullmatch(texto)
    if partes is None:
        raise ErrorFrontera(f"{texto!r} no tiene la forma {forma} con dígitos ASCII")
    anio, mes, dia, hora, minuto, segundo = (int(p) for p in partes.groups())
    try:
        return datetime(anio, mes, dia, hora, minuto, segundo)
    except ValueError:
        raise ErrorFrontera(f"la fecha y hora {texto!r} no existe") from None


def leer_mes(valor: object) -> str:
    """`AAAA-MM` con mes de 01 a 12; devuelve el mismo texto."""
    texto = _texto(valor, "AAAA-MM")
    if _PATRON_MES.fullmatch(texto) is None:
        raise ErrorFrontera(f"{texto!r} no es un mes AAAA-MM (01 a 12, dígitos ASCII)")
    return texto


def leer_desfase_utc(valor: object, horas_max: int = HORAS_DESFASE_MAX) -> timezone:
    """`UTC-07:00` -> `timezone(-7 h)`. Solo desfases fijos; un nombre de zona se rechaza."""
    texto = _texto(valor, "UTC±HH:MM")
    partes = _PATRON_DESFASE.fullmatch(texto)
    if partes is None:
        raise ErrorFrontera(f"se espera un desfase fijo UTC±HH:MM con dígitos ASCII, llegó {texto!r}")
    signo, horas, minutos = partes.groups()
    if int(horas) > horas_max or int(minutos) >= MINUTOS_POR_HORA:
        raise ErrorFrontera(f"desfase fijo fuera de rango: {texto!r}")
    desfase = timedelta(hours=int(horas), minutes=int(minutos))
    return timezone(-desfase if signo == "-" else desfase)
