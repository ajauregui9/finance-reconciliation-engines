"""Fábricas de registros sintéticos para los cinco insumos del flujo de efectivo.

Una sola instancia de `random.Random`, sembrada con `parametros.semilla`, se consume
en un orden fijo (saldos, cxc, cxp, nómina, impuestos y al final los casos especiales):
misma semilla, mismos datos. Primero se plantan los casos borde que piden los
parámetros y luego el relleno aleatorio hasta completar los conteos. Los casos
especiales (CxC con saldo acreedor o en cero y pagos a proveedor vencidos) se sortean
al final, así agregarlos no altera los registros ordinarios.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Tuple

from .fechas import (
    etiqueta_mes,
    etiqueta_mes_anterior,
    fecha_de_mes,
    habil_anterior,
    habil_siguiente,
    meses_en_ventana,
    ultimo_dia,
)
from .parametros import ParamCxc, Parametros, RangoMonto

CENTAVO = Decimal("0.01")
CENTAVOS_POR_PESO = 100
QUINCENAS = ("Q1", "Q2")
SALDO_CERO = Decimal("0.00")
PREFIJO_FACTURA_VENTA = "FV"
PREFIJO_SALDO_ACREEDOR = "NC"


@dataclass(frozen=True)
class SaldoBancario:
    cuenta: str
    banco: str
    saldo: Decimal


@dataclass(frozen=True)
class FacturaVenta:
    cliente_id: str
    cliente: str
    factura: str
    fecha_factura: date
    fecha_vencimiento: date
    saldo: Decimal


@dataclass(frozen=True)
class FacturaProveedor:
    proveedor_id: str
    proveedor: str
    factura: str
    fecha_programada: date
    monto: Decimal


@dataclass(frozen=True)
class PagoNomina:
    periodo: str
    descripcion: str
    fecha_pago: date
    monto: Decimal


@dataclass(frozen=True)
class PagoImpuesto:
    impuesto: str
    periodo_fiscal: str
    fecha_limite: date
    monto: Decimal


@dataclass(frozen=True)
class DatosFlujo:
    parametros: Parametros
    saldos: Tuple[SaldoBancario, ...]
    cxc: Tuple[FacturaVenta, ...]
    cxp: Tuple[FacturaProveedor, ...]
    nomina: Tuple[PagoNomina, ...]
    impuestos: Tuple[PagoImpuesto, ...]


def _monto(azar: random.Random, rango: RangoMonto) -> Decimal:
    minimo = int(rango.minimo * CENTAVOS_POR_PESO)
    maximo = int(rango.maximo * CENTAVOS_POR_PESO)
    return (Decimal(azar.randint(minimo, maximo)) / CENTAVOS_POR_PESO).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _saldos(azar: random.Random, p: Parametros) -> Tuple[SaldoBancario, ...]:
    return tuple(SaldoBancario(c.cuenta, c.banco, _monto(azar, p.saldos.rango)) for c in p.saldos.cuentas)


def _fechas_por_antiguedad(azar: random.Random, c: ParamCxc, corte: date, antiguedad: int) -> Tuple[date, date]:
    """(emisión, vencimiento) con la antigüedad pedida y emisión nunca posterior al corte."""
    vencimiento = corte - timedelta(days=antiguedad)
    plazo = azar.choice([d for d in c.plazos_dias if d >= -antiguedad])
    return vencimiento - timedelta(days=plazo), vencimiento


def _fechas_aleatorias(azar: random.Random, c: ParamCxc, corte: date) -> Tuple[date, date]:
    emision = corte - timedelta(days=azar.randint(0, c.emision_dias_atras_max))
    return emision, emision + timedelta(days=azar.choice(c.plazos_dias))


def _registro_cxc(cliente: int, factura: str, emision: date, vencimiento: date, saldo: Decimal) -> FacturaVenta:
    return FacturaVenta(
        cliente_id=f"CLI-{cliente:03d}", cliente=f"CLIENTE DEMO {cliente:03d}", factura=factura,
        fecha_factura=emision, fecha_vencimiento=vencimiento, saldo=saldo,
    )


def _factura_venta(azar: random.Random, c: ParamCxc, folio: int, emision: date, vencimiento: date) -> FacturaVenta:
    cliente = azar.randint(1, c.clientes)
    factura = f"{PREFIJO_FACTURA_VENTA}-{folio:05d}"
    return _registro_cxc(cliente, factura, emision, vencimiento, _monto(azar, c.rango))


def _cxc(azar: random.Random, p: Parametros) -> Tuple[FacturaVenta, ...]:
    c = p.cxc
    borde = tuple(_fechas_por_antiguedad(azar, c, p.corte, a) for a in c.antiguedades_borde)
    relleno = tuple(_fechas_aleatorias(azar, c, p.corte) for _ in range(c.facturas - len(borde)))
    return tuple(
        _factura_venta(azar, c, folio, emision, vencimiento)
        for folio, (emision, vencimiento) in enumerate(borde + relleno, start=1)
    )


def _cxc_especiales(azar: random.Random, p: Parametros) -> Tuple[FacturaVenta, ...]:
    """Saldos acreedores (anticipos o notas de crédito, saldo negativo) y facturas con saldo cero."""
    c = p.cxc
    acreedores = tuple(
        _registro_cxc(azar.randint(1, c.clientes), f"{PREFIJO_SALDO_ACREEDOR}-{numero:05d}",
                      *_fechas_aleatorias(azar, c, p.corte), -_monto(azar, c.saldos_acreedores.rango))
        for numero in range(1, c.saldos_acreedores.registros + 1)
    )
    en_cero = tuple(
        _registro_cxc(azar.randint(1, c.clientes), f"{PREFIJO_FACTURA_VENTA}-{c.facturas + numero:05d}",
                      *_fechas_aleatorias(azar, c, p.corte), SALDO_CERO)
        for numero in range(1, c.saldos_cero + 1)
    )
    return acreedores + en_cero


def _factura_proveedor(azar: random.Random, p: Parametros, folio: int, dia: int) -> FacturaProveedor:
    proveedor = azar.randint(1, p.cxp.proveedores)
    return FacturaProveedor(
        proveedor_id=f"PRV-{proveedor:03d}", proveedor=f"PROVEEDOR DEMO {proveedor:03d}",
        factura=f"FP-{folio:05d}", fecha_programada=p.corte + timedelta(days=dia), monto=_monto(azar, p.cxp.rango),
    )


def _cxp(azar: random.Random, p: Parametros) -> Tuple[FacturaProveedor, ...]:
    c = p.cxp
    relleno = tuple(azar.randint(0, p.dias_programacion) for _ in range(c.facturas - len(c.dias_borde)))
    return tuple(_factura_proveedor(azar, p, folio, dia) for folio, dia in enumerate(c.dias_borde + relleno, start=1))


def _cxp_vencidas(azar: random.Random, p: Parametros) -> Tuple[FacturaProveedor, ...]:
    """Pagos programados antes del corte que siguen pendientes (vencidos)."""
    primero = p.cxp.facturas + 1
    return tuple(
        _factura_proveedor(azar, p, folio, dia) for folio, dia in enumerate(p.cxp.dias_vencidos, start=primero)
    )


def _nomina(azar: random.Random, p: Parametros) -> Tuple[PagoNomina, ...]:
    """Dos pagos por mes (día fijo y fin de mes); en fin de semana se adelantan al viernes."""
    fin = p.corte + timedelta(days=p.dias_programacion)
    candidatos = tuple(
        (f"{etiqueta_mes(anio, mes)}-{quincena}", habil_anterior(fecha_de_mes(anio, mes, dia)))
        for anio, mes in meses_en_ventana(p.corte, fin)
        for quincena, dia in zip(QUINCENAS, (p.nomina.dia_quincena, ultimo_dia(anio, mes)))
    )
    return tuple(
        PagoNomina(periodo=periodo, descripcion=p.nomina.descripcion, fecha_pago=fecha,
                   monto=_monto(azar, p.nomina.rango))
        for periodo, fecha in candidatos if p.corte <= fecha <= fin
    )


def _impuestos(azar: random.Random, p: Parametros) -> Tuple[PagoImpuesto, ...]:
    """Un pago por impuesto y mes, del periodo anterior; en fin de semana pasa al lunes."""
    fin = p.corte + timedelta(days=p.dias_programacion)
    limites = tuple(
        (etiqueta_mes_anterior(anio, mes), habil_siguiente(fecha_de_mes(anio, mes, p.impuestos.dia_limite)))
        for anio, mes in meses_en_ventana(p.corte, fin)
    )
    return tuple(
        PagoImpuesto(impuesto=concepto.impuesto, periodo_fiscal=periodo, fecha_limite=fecha,
                     monto=_monto(azar, concepto.rango))
        for periodo, fecha in limites if p.corte <= fecha <= fin
        for concepto in p.impuestos.conceptos
    )


def generar(parametros: Parametros) -> DatosFlujo:
    azar = random.Random(parametros.semilla)
    saldos = _saldos(azar, parametros)
    cxc = _cxc(azar, parametros)
    cxp = _cxp(azar, parametros)
    nomina = _nomina(azar, parametros)
    impuestos = _impuestos(azar, parametros)
    return DatosFlujo(
        parametros=parametros, saldos=saldos,
        cxc=cxc + _cxc_especiales(azar, parametros), cxp=cxp + _cxp_vencidas(azar, parametros),
        nomina=nomina, impuestos=impuestos,
    )
