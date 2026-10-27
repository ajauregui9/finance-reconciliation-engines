"""Errores que detienen la corrida, con su código de salida.

`InsumoInvalido` (código 2) cubre argumentos, config, insumos y entorno: cualquier cosa
que impide correr o confiar en la corrida. `TopeExcedido` (código 3) es el límite de
costo; lleva el consumo acumulado hasta el punto en que se detuvo.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - solo para anotaciones
    from .costo import Consumo


class ErrorExtraccion(Exception):
    """Base de los errores de este skill."""


class InsumoInvalido(ErrorExtraccion):
    """Argumento, config, insumo o entorno inválido (código de salida 2)."""


class TopeExcedido(ErrorExtraccion):
    """Se rebasó el tope de documentos o de tokens de la corrida (código de salida 3)."""

    def __init__(self, mensaje: str, consumo: Optional["Consumo"] = None) -> None:
        super().__init__(mensaje)
        self.consumo = consumo
