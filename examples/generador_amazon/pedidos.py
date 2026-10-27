"""Eventos de venta y de reembolso, con su instante absoluto y el archivo que los trae."""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import List, Optional, Sequence

from .montos import q2
from .parametros import CATALOGO, ParametrosGenerador, Producto
from .tiempo import dias_del_mes, huso, mes_de, mes_previo, mes_siguiente, momento

PROBABILIDAD_DESCUENTO = 0.20
PROBABILIDAD_ENVIO = 0.30
PROBABILIDAD_OTRA_TARIFA = 0.25
PROBABILIDAD_REEMBOLSO = 0.08
REEMBOLSOS_COLA_NEGATIVA = 3


@dataclass(frozen=True)
class Venta:
    pedido: str
    producto: Producto
    cantidad: int
    pedido_en: datetime
    liquidada_en: Optional[datetime]
    periodo_archivo: Optional[str]
    con_descuento: bool
    con_envio: bool
    con_otra_tarifa: bool
    tasa_retencion: Decimal
    caso_borde: Optional[int] = None

    def venta_neta(self, descuento: Decimal) -> Decimal:
        bruto = q2(self.producto.precio * self.cantidad)
        return bruto - q2(bruto * descuento) if self.con_descuento else bruto


@dataclass(frozen=True)
class Reembolso:
    venta: Venta
    liquidado_en: datetime
    periodo_archivo: str


def _producto(sku: str) -> Producto:
    return next(p for p in CATALOGO if p.sku == sku)


def _lejos_del_corte(instante: datetime, cierre: timezone) -> datetime:
    """Las ventas aleatorias nunca caen el primer ni el último día del mes de cierre."""
    local = instante.astimezone(cierre)
    mes = local.strftime("%Y-%m")
    if local.day == dias_del_mes(mes):
        return momento(mes_siguiente(mes), 2, local.hour, local.minute, local.second, cierre)
    if local.day == 1:
        return local.replace(day=2)
    return local


def _ventas_del_mes(rng: random.Random, mes: str, p: ParametrosGenerador, cierre: timezone) -> List[Venta]:
    ventas = []
    ultimo = dias_del_mes(mes)
    sin_cruce = mes == mes_previo(p.mes_cola_negativa)
    for indice in range(1, p.pedidos_por_mes + 1):
        pedido_en = momento(mes, rng.randint(2, ultimo - 1), rng.randint(9, 16), rng.randint(0, 59),
                            rng.randint(0, 59), cierre)
        retraso = timedelta(days=rng.randint(0, 6), hours=rng.randint(1, 3), minutes=rng.randint(0, 59))
        liquidada: Optional[datetime] = _lejos_del_corte(pedido_en + retraso, cierre)
        if sin_cruce and liquidada is not None and mes_de(liquidada, cierre) != mes:
            liquidada = momento(mes, ultimo - 1, 18, 0, 0, cierre)
        periodo = None if liquidada is None else mes_de(liquidada, cierre)
        if periodo not in p.meses:
            liquidada, periodo = None, None
        ventas.append(Venta(
            pedido=f"PED-{mes.replace('-', '')}-{indice:03d}", producto=rng.choice(CATALOGO),
            cantidad=rng.randint(1, 3), pedido_en=pedido_en, liquidada_en=liquidada, periodo_archivo=periodo,
            con_descuento=rng.random() < PROBABILIDAD_DESCUENTO, con_envio=rng.random() < PROBABILIDAD_ENVIO,
            con_otra_tarifa=rng.random() < PROBABILIDAD_OTRA_TARIFA, tasa_retencion=p.tasa_retencion))
    return ventas


def _ventas_de_borde(p: ParametrosGenerador) -> List[Venta]:
    ventas = []
    husos = p.huso_de
    for indice, caso in enumerate(p.casos_borde):
        zona = huso(husos[caso.periodo])
        ventas.append(Venta(
            pedido=f"PED-BORDE-{indice + 1:02d}", producto=_producto(caso.sku), cantidad=1,
            pedido_en=datetime.strptime(caso.fecha_pedido_local, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zona),
            liquidada_en=datetime.strptime(caso.fecha_hora_local, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zona),
            periodo_archivo=caso.periodo, con_descuento=False, con_envio=False, con_otra_tarifa=False,
            tasa_retencion=p.tasa_retencion, caso_borde=indice))
    return ventas


def _con_retencion_anomala(ventas: Sequence[Venta], p: ParametrosGenerador) -> List[Venta]:
    """En el archivo anómalo, una de cada dos ventas aleatorias retiene a la tasa anómala."""
    afectadas = sorted((v for v in ventas if v.periodo_archivo == p.mes_retencion_anomala and v.caso_borde is None),
                       key=lambda v: v.pedido)
    dobles = {v.pedido for v in afectadas[::2]}
    return [replace(v, tasa_retencion=p.tasa_retencion_anomala) if v.pedido in dobles else v for v in ventas]


def generar_ventas(rng: random.Random, p: ParametrosGenerador) -> List[Venta]:
    cierre = huso(p.huso_cierre)
    aleatorias = [v for mes in p.meses for v in _ventas_del_mes(rng, mes, p, cierre)]
    return _con_retencion_anomala(aleatorias, p) + _ventas_de_borde(p)


def _reembolsos_aleatorios(rng: random.Random, ventas: Sequence[Venta], p: ParametrosGenerador,
                           cierre: timezone) -> List[Reembolso]:
    reembolsos = []
    for venta in ventas:
        if venta.liquidada_en is None or venta.periodo_archivo is None or venta.caso_borde is not None:
            continue
        if rng.random() >= PROBABILIDAD_REEMBOLSO:
            continue
        instante = _lejos_del_corte(venta.liquidada_en + timedelta(days=rng.randint(2, 8)), cierre)
        periodo = mes_de(instante, cierre)
        if periodo in p.meses and periodo <= mes_siguiente(venta.periodo_archivo):
            reembolsos.append(Reembolso(venta, instante, periodo))
    return reembolsos


def _reembolsos_cola_negativa(ventas: Sequence[Venta], ya: Sequence[Reembolso], p: ParametrosGenerador,
                              cierre: timezone) -> List[Reembolso]:
    """Las ventas más grandes del mes previo se devuelven al inicio del mes de cola negativa."""
    origen = mes_previo(p.mes_cola_negativa)
    devueltas = {r.venta.pedido for r in ya}
    candidatas = sorted(
        (v for v in ventas if v.periodo_archivo == origen and v.caso_borde is None and v.pedido not in devueltas
         and mes_de(v.pedido_en, cierre) == origen),
        key=lambda v: (-v.venta_neta(p.descuento), v.pedido))
    return [Reembolso(v, momento(p.mes_cola_negativa, 3 + i, 11, 0, 0, cierre), p.mes_cola_negativa)
            for i, v in enumerate(candidatas[:REEMBOLSOS_COLA_NEGATIVA])]


def generar_reembolsos(rng: random.Random, ventas: Sequence[Venta], p: ParametrosGenerador) -> List[Reembolso]:
    cierre = huso(p.huso_cierre)
    aleatorios = _reembolsos_aleatorios(rng, ventas, p, cierre)
    return aleatorios + _reembolsos_cola_negativa(ventas, aleatorios, p, cierre)
