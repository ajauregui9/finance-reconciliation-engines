"""Filas de liquidación del generador: ventas, reembolsos, cargos, publicidad y pagos."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence, Tuple

from .montos import CERO, q2
from .parametros import ParametrosGenerador
from .pedidos import Reembolso, Venta
from .tiempo import momento

COLUMNAS = (
    "venta_productos", "iva_venta", "envio_cobrado", "iva_envio", "descuento_promocional",
    "iva_descuento", "retencion", "comision", "logistica", "otras_tarifas",
)
_SE_DEVUELVEN = ("venta_productos", "iva_venta", "envio_cobrado", "iva_envio", "descuento_promocional",
                 "iva_descuento", "retencion")
DIAS_PUBLICIDAD = (9, 17, 25)
DIAS_TRANSFERENCIA = (14, 28)


@dataclass(frozen=True)
class Fila:
    periodo: str
    instante: datetime
    tipo: str
    pedido: str
    pedido_en: Optional[datetime]
    sku: str
    descripcion: str
    cantidad: Optional[int]
    montos: Tuple[Decimal, ...]
    caso_borde: Optional[int] = None

    def monto(self, columna: str) -> Decimal:
        return self.montos[COLUMNAS.index(columna)]

    @property
    def total(self) -> Decimal:
        return sum(self.montos, CERO)

    @property
    def es_de_pedido(self) -> bool:
        return self.tipo in ("Pedido", "Reembolso")


def _tupla(montos: Dict[str, Decimal]) -> Tuple[Decimal, ...]:
    return tuple(montos.get(c, CERO) for c in COLUMNAS)


def montos_venta(venta: Venta, p: ParametrosGenerador) -> Dict[str, Decimal]:
    bruto = q2(venta.producto.precio * venta.cantidad)
    descuento = -q2(bruto * p.descuento) if venta.con_descuento else CERO
    base = bruto + descuento
    envio = p.envio if venta.con_envio else CERO
    return {
        "venta_productos": bruto, "iva_venta": q2(bruto * p.tasa_iva),
        "envio_cobrado": envio, "iva_envio": q2(envio * p.tasa_iva),
        "descuento_promocional": descuento, "iva_descuento": q2(descuento * p.tasa_iva),
        "retencion": -q2(base * venta.tasa_retencion),
        "comision": -q2(base * venta.producto.tasa_comision),
        "logistica": -q2(venta.producto.logistica_unidad * venta.cantidad),
        "otras_tarifas": -p.otra_tarifa if venta.con_otra_tarifa else CERO,
    }


def fila_venta(venta: Venta, p: ParametrosGenerador) -> Fila:
    if venta.liquidada_en is None or venta.periodo_archivo is None:
        raise ValueError(f"{venta.pedido} no tiene liquidación")
    return Fila(periodo=venta.periodo_archivo, instante=venta.liquidada_en, tipo="Pedido", pedido=venta.pedido,
                pedido_en=venta.pedido_en, sku=venta.producto.sku, descripcion=venta.producto.descripcion,
                cantidad=venta.cantidad, montos=_tupla(montos_venta(venta, p)), caso_borde=venta.caso_borde)


def fila_reembolso(reembolso: Reembolso, p: ParametrosGenerador) -> Fila:
    original = montos_venta(reembolso.venta, p)
    devuelto = {c: -original[c] for c in _SE_DEVUELVEN}
    devuelto["comision"] = q2(-original["comision"] * p.comision_que_se_devuelve)
    venta = reembolso.venta
    return Fila(periodo=reembolso.periodo_archivo, instante=reembolso.liquidado_en, tipo="Reembolso",
                pedido=venta.pedido, pedido_en=venta.pedido_en, sku=venta.producto.sku,
                descripcion=venta.producto.descripcion, cantidad=venta.cantidad, montos=_tupla(devuelto))


def _cargo(periodo: str, instante: datetime, tipo: str, descripcion: str, monto: Decimal) -> Fila:
    return Fila(periodo=periodo, instante=instante, tipo=tipo, pedido="", pedido_en=None, sku="",
                descripcion=descripcion, cantidad=None, montos=_tupla({"otras_tarifas": monto}))


def filas_cargos(rng: random.Random, periodo: str, zona: timezone, p: ParametrosGenerador) -> List[Fila]:
    filas = [
        _cargo(periodo, momento(periodo, 3, 10, 0, 0, zona), "Suscripción", "Suscripción de vendedor profesional",
               -p.suscripcion),
        _cargo(periodo, momento(periodo, 6, 10, 0, 0, zona), "Almacenaje", "Almacenaje mensual de inventario",
               -Decimal(rng.randint(30, 90) * 10)),
    ]
    if len(p.meses) > 1 and periodo == p.meses[1]:
        filas.append(_cargo(periodo, momento(periodo, 12, 10, 0, 0, zona), "Ajuste",
                            "Bonificación por inventario dañado", Decimal("150.00")))
    return filas


def partes_publicidad(total: Decimal) -> Tuple[Decimal, ...]:
    """Reparte el gasto sin IVA del mes en tres cargos que suman exacto."""
    tercio = q2(total / len(DIAS_PUBLICIDAD))
    return (tercio,) * (len(DIAS_PUBLICIDAD) - 1) + (total - tercio * (len(DIAS_PUBLICIDAD) - 1),)


def filas_publicidad(periodo: str, zona: timezone, gasto_sin_iva: Decimal, p: ParametrosGenerador) -> List[Fila]:
    """La liquidación cobra la publicidad con IVA, en varios cargos."""
    return [
        _cargo(periodo, momento(periodo, dia, 11, 0, 0, zona), "Publicidad", "Cargo de publicidad patrocinada",
               -q2(parte * (1 + p.tasa_iva)))
        for dia, parte in zip(DIAS_PUBLICIDAD, partes_publicidad(gasto_sin_iva))
    ]


def orden(fila: Fila) -> Tuple[datetime, str, str]:
    return fila.instante, fila.tipo, fila.pedido


def con_transferencias(filas: Sequence[Fila], periodo: str, zona: timezone) -> List[Fila]:
    """Agrega los pagos al banco: cada uno transfiere el saldo positivo acumulado."""
    resultado = sorted(filas, key=orden)
    for dia in DIAS_TRANSFERENCIA:
        corte = momento(periodo, dia, 12, 0, 0, zona)
        saldo = sum((f.total for f in resultado if f.instante < corte), CERO)
        if saldo > 0:
            resultado = sorted(resultado + [_cargo(periodo, corte, "Transferencia", "Pago a la cuenta bancaria",
                                                   -saldo)], key=orden)
    return resultado
