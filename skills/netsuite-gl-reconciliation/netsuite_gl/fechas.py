"""Fechas de entrada estrictas `AAAA-MM-DD`, iguales en Python 3.9 a 3.13.

Desde 3.11, `date.fromisoformat` también acepta formas como `2026-W28-5` o `20260710`;
aquí solo pasa la forma de calendario con dígitos ASCII, vía la frontera compartida.
"""
from __future__ import annotations

from datetime import date

from frontera import leer_fecha


def fecha_iso(valor: object) -> date:
    """La fecha de un texto `AAAA-MM-DD`; `ValueError` con el motivo en cualquier otro caso."""
    return leer_fecha(valor)
