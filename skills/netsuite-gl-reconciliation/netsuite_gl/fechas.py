"""Fechas de entrada estrictas `AAAA-MM-DD`, iguales en Python 3.9 a 3.12.

Desde 3.11, `date.fromisoformat` también acepta formas como `2026-W28-5` o `20260710`;
aquí solo pasa la forma de calendario con dígitos ASCII.
"""
from __future__ import annotations

import re
from datetime import date

_RE_FECHA = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")


def fecha_iso(valor: object) -> date:
    """La fecha de un texto `AAAA-MM-DD`; `ValueError` con el motivo en cualquier otro caso."""
    if not isinstance(valor, str) or _RE_FECHA.match(valor) is None:
        raise ValueError(f"se esperaba texto AAAA-MM-DD, no {valor!r}")
    return date.fromisoformat(valor)  # rechaza fechas imposibles como 2026-02-30
