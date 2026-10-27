"""Errores de la corrida: los que la detienen, con su código de salida, y la falla de un documento.

`InsumoInvalido` (código 2) cubre argumentos, config, insumos y entorno: cualquier cosa
que impide correr o confiar en la corrida; `AutenticacionRechazada` es el caso de una llave
que la API rechaza. `TopeExcedido` (código 3) es el límite de costo; lleva el consumo
acumulado hasta el punto en que se detuvo. `FallaApiDocumento` no detiene nada: la API no
respondió un documento y el pipeline lo manda a revisión humana con `error_api`.
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


class AutenticacionRechazada(InsumoInvalido):
    """La API rechazó la llave o sus permisos (401/403): ningún documento podría procesarse (código 2)."""


class FallaApiDocumento(ErrorExtraccion):
    """La API no respondió este documento: error no transitorio o reintentos agotados."""

    def __init__(self, documento_id: str, detalle: str, intentos: int) -> None:
        super().__init__(detalle)
        self.documento_id = documento_id
        self.intentos = intentos
