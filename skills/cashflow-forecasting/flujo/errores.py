"""Jerarquía de errores del flujo de efectivo.

Cada clase sabe con qué código debe terminar el CLI, así el punto de entrada no
necesita traducir mensajes ni adivinar la causa.
"""
from __future__ import annotations

from typing import ClassVar

CODIGO_EXITO = 0
CODIGO_ESCRITURA = 1
CODIGO_CONFIG = 2
CODIGO_INSUMO = 3
CODIGO_INVARIANTE = 4


class ErrorFlujo(Exception):
    """Base de los errores esperados; ninguno se silencia."""

    codigo_salida: ClassVar[int] = CODIGO_ESCRITURA


class ErrorConfig(ErrorFlujo):
    """La config (o la curva de cobranza) no cumple su esquema."""

    codigo_salida: ClassVar[int] = CODIGO_CONFIG


class ErrorInsumo(ErrorFlujo):
    """Un archivo de insumo falta, no se puede leer o trae valores inválidos."""

    codigo_salida: ClassVar[int] = CODIGO_INSUMO


class ErrorInvariante(ErrorFlujo):
    """El ensamblador encontró filas contrato inválidas o un descuadre."""

    codigo_salida: ClassVar[int] = CODIGO_INVARIANTE
