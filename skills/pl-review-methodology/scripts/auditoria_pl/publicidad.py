"""Publicidad por marca: cuadre contra la cuenta del estado de resultados y alertas."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .bloqueos import PUBLICIDAD_SIN_CUADRE, Bloqueo
from .config import ReglasPublicidad
from .dinero import CERO, porcentaje, proporcion, texto
from .exportacion import ExportacionPL, VentaMarca

SOBRE_UMBRAL = "sobre_umbral"
PUBLICIDAD_SIN_VENTA = "publicidad_sin_venta"


@dataclass(frozen=True)
class AlertaPublicidad:
    marca: str
    motivo: str
    venta: Decimal
    publicidad: Decimal
    publicidad_pct: Optional[Decimal]
    exceso_sobre_objetivo: Decimal


@dataclass(frozen=True)
class SeccionPublicidad:
    cuenta: str
    objetivo_pct: Decimal
    alerta_pct: Decimal
    total_cuenta: Decimal
    total_marcas: Decimal
    alertas: Tuple[AlertaPublicidad, ...]


def _alerta(marca: VentaMarca, reglas: ReglasPublicidad) -> Optional[AlertaPublicidad]:
    if marca.venta <= CERO:
        # Sin venta no hay proporción: todo el gasto es exceso.
        if marca.publicidad == CERO:
            return None
        return AlertaPublicidad(
            marca.marca, PUBLICIDAD_SIN_VENTA, marca.venta, marca.publicidad, None, marca.publicidad
        )
    pct = porcentaje(marca.publicidad, marca.venta)
    if pct <= reglas.alerta_pct:
        return None
    exceso = marca.publicidad - proporcion(marca.venta, reglas.objetivo_pct)
    return AlertaPublicidad(marca.marca, SOBRE_UMBRAL, marca.venta, marca.publicidad, pct, exceso)


def evaluar_publicidad(
    reglas: ReglasPublicidad, exportacion: ExportacionPL
) -> Tuple[SeccionPublicidad, Tuple[Bloqueo, ...]]:
    linea = exportacion.linea(reglas.cuenta)
    total_cuenta = CERO if linea is None else linea.actual
    total_marcas = sum((m.publicidad for m in exportacion.marcas), CERO)
    bloqueos: Tuple[Bloqueo, ...] = ()
    if total_marcas != total_cuenta:
        detalle = (
            f"La publicidad por marca suma {texto(total_marcas)} y la cuenta {reglas.cuenta} trae "
            f"{texto(total_cuenta)}: diferencia {texto(total_marcas - total_cuenta)}."
        )
        bloqueos = (Bloqueo(PUBLICIDAD_SIN_CUADRE, reglas.cuenta, detalle),)
    alertas = tuple(a for a in (_alerta(m, reglas) for m in exportacion.marcas) if a is not None)
    seccion = SeccionPublicidad(
        cuenta=reglas.cuenta,
        objetivo_pct=reglas.objetivo_pct,
        alerta_pct=reglas.alerta_pct,
        total_cuenta=total_cuenta,
        total_marcas=total_marcas,
        alertas=alertas,
    )
    return seccion, bloqueos
