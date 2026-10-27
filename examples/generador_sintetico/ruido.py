"""Ruido realista: CFDIs y asientos que no respaldan ningún cargo de tarjeta.

- Proveedores pagados por transferencia (CFDI + asiento de cuentas por pagar).
- Notas de crédito de esos proveedores.
- Nómina quincenal (CFDI tipo N emitido por la empresa + asiento de nómina).
"""
from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from typing import List, Tuple

from .catalogo import (CONCEPTOS, CUENTA_BANCO, CUENTA_ISR_NOMINA, CUENTA_PROVEEDORES,
                       CUENTA_SUELDOS, CUENTAS_GASTO, EMPLEADOS, PROVEEDORES_RUIDO)
from .config import NOMBRE_EMPRESA, RFC_EMPRESA
from .contexto import Contexto, periodo_emisor
from .dinero import CERO, q2
from .fabricas import Escenario, asiento_simple, dias, lineas_gasto, nuevo_cfdi
from .modelo import Asiento, Cfdi, LineaMayor

CFDIS_PROVEEDORES = 35
NOTAS_PROVEEDORES = 3
EMPLEADOS_QUINCENA = 6
PCT_CXP_REGISTRADO = 80
TASA_NETO_NOMINA = Decimal("0.85")


def asiento_nomina(ctx: Contexto, empleado: Tuple[str, str, str], neto: Decimal, fecha: date) -> Asiento:
    """Sueldo bruto a gasto, ISR retenido y neto pagado por banco; siempre cuadra."""
    bruto = q2(neto / TASA_NETO_NOMINA)
    lineas = (
        LineaMayor(CUENTA_SUELDOS[0], CUENTA_SUELDOS[1], bruto, CERO),
        LineaMayor(CUENTA_ISR_NOMINA[0], CUENTA_ISR_NOMINA[1], CERO, bruto - neto),
        LineaMayor(CUENTA_BANCO[0], CUENTA_BANCO[1], CERO, neto),
    )
    return asiento_simple(ctx, fecha=fecha, origen="NOMINA", proveedor=empleado,
                          memo="PAGO DE NOMINA", lineas=lineas)


def cfdi_nomina(ctx: Contexto, empleado: Tuple[str, str, str], neto: Decimal, fecha: date, concepto: str) -> Cfdi:
    return nuevo_cfdi(ctx, rfc_emisor=RFC_EMPRESA, nombre_emisor=NOMBRE_EMPRESA, serie="NOM",
                      total=neto, fecha=fecha, concepto=concepto, tipo="N", direccion="emitido",
                      rfc_receptor=empleado[2], nombre_receptor=empleado[1], con_iva=False,
                      forma_pago="99")


def _rango_global(ctx: Contexto) -> Tuple[date, date]:
    inicio = min(periodo_emisor(ctx.config, e)[0] for e in ("ALFA", "BETA"))
    fin = max(periodo_emisor(ctx.config, e)[1] for e in ("ALFA", "BETA"))
    return inicio - dias(10), fin + dias(15)


def proveedores(ctx: Contexto) -> Escenario:
    inicio, fin = _rango_global(ctx)
    cfdis, asientos = [], []
    for _ in range(CFDIS_PROVEEDORES):
        prv = ctx.elegir(PROVEEDORES_RUIDO)
        total = ctx.monto(*prv.rango)
        cfdi = nuevo_cfdi(ctx, rfc_emisor=prv.rfc, nombre_emisor=prv.nombre, serie=prv.serie,
                          total=total, fecha=ctx.fecha_entre(inicio, fin), concepto=CONCEPTOS[prv.categoria],
                          forma_pago="03" if ctx.probable(90) else "04")
        cfdis.append(cfdi)
        if ctx.probable(PCT_CXP_REGISTRADO):
            asientos.append(asiento_simple(
                ctx, fecha=cfdi.fecha_emision, origen="CXP",
                proveedor=(prv.proveedor_id, prv.nombre, prv.rfc),
                memo=CONCEPTOS[prv.categoria],
                lineas=lineas_gasto(CUENTAS_GASTO[prv.categoria], total, True, CUENTA_PROVEEDORES)))
    for factura in ctx.barajar(cfdis)[:NOTAS_PROVEEDORES]:
        nota = nuevo_cfdi(ctx, rfc_emisor=factura.rfc_emisor, nombre_emisor=factura.nombre_emisor,
                          serie=factura.serie, total=ctx.porcion(factura.total, 5, 20),
                          fecha=factura.fecha_emision + dias(ctx.entero(5, 20)),
                          concepto="DEVOLUCION O BONIFICACION", tipo="E", forma_pago="03",
                          relacionado=factura.uuid)
        cfdis.append(nota)
    return Escenario(cfdis=tuple(cfdis), asientos=tuple(asientos))


def nomina(ctx: Contexto) -> Escenario:
    ultimo = calendar.monthrange(ctx.config.anio, ctx.config.mes)[1]
    quincenas = (date(ctx.config.anio, ctx.config.mes, 15), date(ctx.config.anio, ctx.config.mes, ultimo))
    cfdis, asientos = [], []
    for fecha in quincenas:
        for empleado in EMPLEADOS[:EMPLEADOS_QUINCENA]:
            neto = ctx.monto(6000, 28000)
            cfdis.append(cfdi_nomina(ctx, empleado, neto, fecha, "PAGO DE NOMINA"))
            asientos.append(asiento_nomina(ctx, empleado, neto, fecha))
    return Escenario(cfdis=tuple(cfdis), asientos=tuple(asientos))


def todo(ctx: Contexto) -> List[Escenario]:
    return [proveedores(ctx), nomina(ctx)]
