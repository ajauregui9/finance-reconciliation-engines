"""Límite de costo por corrida: tope de documentos, tope de tokens y estimación en USD.

Los precios por millón de tokens vienen de la config; aquí no hay ningún precio fijo.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

from .config import Limites, Precios
from .errores import TopeExcedido
from .modelo import Uso

UN_MILLON = Decimal(1_000_000)
MICRODOLAR = Decimal("0.000001")


@dataclass(frozen=True)
class Consumo:
    """Uso por documento, en el orden en que se llamó al modelo."""

    por_documento: Tuple[Tuple[str, Uso], ...] = ()

    def sumar(self, documento_id: str, uso: Uso) -> "Consumo":
        return Consumo(self.por_documento + ((documento_id, uso),))

    @property
    def tokens_entrada(self) -> int:
        return sum(uso.tokens_entrada for _, uso in self.por_documento)

    @property
    def tokens_salida(self) -> int:
        return sum(uso.tokens_salida for _, uso in self.por_documento)

    @property
    def tokens_totales(self) -> int:
        return self.tokens_entrada + self.tokens_salida


def verificar_documentos(cantidad: int, limites: Limites) -> None:
    """Antes de la primera llamada: la corrida no puede enviar más documentos que el tope."""
    if cantidad > limites.max_documentos:
        raise TopeExcedido(f"tope de documentos excedido: la corrida enviaría {cantidad} documentos al modelo y el "
                           f"tope es {limites.max_documentos}")


def verificar_tokens(consumo: Consumo, limites: Limites) -> None:
    """Después de cada respuesta: el acumulado de tokens no puede rebasar el tope."""
    if consumo.tokens_totales > limites.max_tokens:
        raise TopeExcedido(f"tope de tokens excedido: {consumo.tokens_totales} tokens usados (entrada "
                           f"{consumo.tokens_entrada}, salida {consumo.tokens_salida}) y el tope es "
                           f"{limites.max_tokens}", consumo)


def usd_estimado(consumo: Consumo, precios: Precios) -> Decimal:
    costo = (Decimal(consumo.tokens_entrada) * precios.entrada_por_millon
             + Decimal(consumo.tokens_salida) * precios.salida_por_millon) / UN_MILLON
    return costo.quantize(MICRODOLAR, rounding=ROUND_HALF_UP)
