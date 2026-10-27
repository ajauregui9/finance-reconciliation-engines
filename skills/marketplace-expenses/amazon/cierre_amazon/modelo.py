"""Registros inmutables que salen de los lectores."""
from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping, Optional, Tuple

from .dinero import CERO


@dataclass(frozen=True)
class Montos:
    """Las diez columnas de montos de una fila de liquidación, con su signo original."""

    venta_productos: Decimal = CERO
    iva_venta: Decimal = CERO
    envio_cobrado: Decimal = CERO
    iva_envio: Decimal = CERO
    descuento_promocional: Decimal = CERO
    iva_descuento: Decimal = CERO
    retencion: Decimal = CERO
    comision: Decimal = CERO
    logistica: Decimal = CERO
    otras_tarifas: Decimal = CERO

    def mas(self, otro: Montos) -> Montos:
        """Suma columna por columna y devuelve un registro nuevo."""
        sumas = {campo.name: getattr(self, campo.name) + getattr(otro, campo.name) for campo in fields(self)}
        return Montos(**sumas)

    def suma_columnas(self) -> Decimal:
        """Lo que debería valer `Total` si la fila cuadra."""
        return sum((getattr(self, campo.name) for campo in fields(self)), CERO)

    @property
    def venta_neta(self) -> Decimal:
        """Venta de productos más descuento promocional (el descuento ya es negativo)."""
        return self.venta_productos + self.descuento_promocional


COLUMNAS_MONTO: Tuple[str, ...] = tuple(campo.name for campo in fields(Montos))


@dataclass(frozen=True)
class FilaLiquidacion:
    """Una fila de datos de un archivo de liquidación."""

    archivo: str
    numero: int
    instante: datetime
    tipo: str
    pedido: str
    instante_pedido: Optional[datetime]
    sku: str
    descripcion: str
    cantidad: int
    montos: Montos
    total: Decimal


@dataclass(frozen=True)
class ArchivoLiquidacion:
    """Un archivo de liquidación ya validado."""

    nombre: str
    periodo: str
    huso_texto: str
    huso: timezone
    moneda: str
    filas: Tuple[FilaLiquidacion, ...]

    @property
    def total(self) -> Decimal:
        return sum((f.total for f in self.filas), CERO)


@dataclass(frozen=True)
class GastoConsola:
    """Gasto diario de una campaña según la consola de publicidad (sin IVA)."""

    fecha: date
    campana: str
    gasto: Decimal

    @property
    def mes(self) -> str:
        return self.fecha.strftime("%Y-%m")


@dataclass(frozen=True)
class FacturaPublicidad:
    """Factura mensual de publicidad."""

    mes: str
    folio: str
    subtotal: Decimal
    iva: Decimal
    total: Decimal


@dataclass(frozen=True)
class Insumos:
    """Todo lo que lee una corrida. Una fuente opcional ausente vale `None`."""

    archivos: Tuple[ArchivoLiquidacion, ...]
    consola: Optional[Tuple[GastoConsola, ...]]
    facturas: Optional[Tuple[FacturaPublicidad, ...]]
    venta_erp: Optional[Mapping[str, Decimal]]
