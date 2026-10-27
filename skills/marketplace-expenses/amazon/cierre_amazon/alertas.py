"""Alertas (no bloquean) y candados (bloquean) del cierre."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Alerta:
    """Algo que una persona debe revisar; no invalida el cierre."""

    codigo: str
    mes: Optional[str]
    mensaje: str
    datos: Tuple[Tuple[str, str], ...] = ()


def alerta(codigo: str, mes: Optional[str], mensaje: str, **datos: str) -> Alerta:
    """Construye una alerta con sus datos ordenados por clave."""
    return Alerta(codigo=codigo, mes=mes, mensaje=mensaje, datos=tuple(sorted(datos.items())))


@dataclass(frozen=True)
class Candado:
    """Cuadre recalculado desde las filas; si falla, el cierre no se publica."""

    nombre: str
    ok: bool
    detalle: str
