"""Adaptador del reporte de antigüedad de cuentas por cobrar.

El signo del saldo decide el trato de cada factura:
  - positivo: se reparte en semanas con la curva de cobranza de su tramo; lo que cae
    después de la semana 13 y la estimación no cobrable quedan en la conciliación;
  - negativo (anticipo de cliente o nota de crédito): resta completo en la semana 1,
    sin curva ni estimación no cobrable, con marca `saldo_acreedor`;
  - cero: no genera fila y se cuenta en `registros_en_cero`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

from ..calendario import inicio_semana
from ..config import CurvaCobranza
from ..contrato import (
    CONCEPTO_COBRANZA,
    FUENTE_CXC,
    MARCA_SALDO_ACREEDOR,
    FilaContrato,
    ResultadoFuente,
    ordenar_filas,
)
from ..curva import PlanCobro, planear_cobro
from ..dinero import CERO
from ..lectura import Registro, exigir_unicas, leer_tabla

COLUMNAS = ("cliente_id", "cliente", "factura", "fecha_factura", "fecha_vencimiento", "moneda", "saldo")
SEMANA_SALDO_ACREEDOR = 1


@dataclass(frozen=True)
class FacturaPorCobrar:
    factura: str
    cliente: str
    vencimiento: date
    saldo: Decimal

    def fila(self, semana: int, fecha: date, monto: Decimal, marca: Optional[str] = None) -> FilaContrato:
        return FilaContrato(
            fuente=FUENTE_CXC, concepto=CONCEPTO_COBRANZA, semana=semana, fecha=fecha,
            referencia=self.factura, contraparte=self.cliente, monto=monto, marca=marca,
        )


def _factura(registro: Registro, corte: date, moneda: str) -> FacturaPorCobrar:
    """Valida el registro completo (también si su saldo es cero o negativo)."""
    registro.exigir_moneda("moneda", moneda)
    registro.texto("cliente_id")
    saldo = registro.monto("saldo")
    emitida = registro.fecha("fecha_factura")
    if emitida > corte:
        raise registro.falla_en("fecha_factura", f"la factura es posterior al corte {corte.isoformat()}")
    vence = registro.fecha("fecha_vencimiento")
    if vence < emitida:
        raise registro.falla_en("fecha_vencimiento", "el vencimiento es anterior a la fecha_factura")
    return FacturaPorCobrar(
        factura=registro.texto("factura"), cliente=registro.texto("cliente"), vencimiento=vence, saldo=saldo,
    )


def _filas_de_cobro(factura: FacturaPorCobrar, plan: PlanCobro, corte: date) -> Tuple[FilaContrato, ...]:
    return tuple(factura.fila(semana, inicio_semana(corte, semana), monto) for semana, monto in plan.piezas)


def _fila_acreedora(factura: FacturaPorCobrar, corte: date) -> FilaContrato:
    return factura.fila(SEMANA_SALDO_ACREEDOR, corte, factura.saldo, MARCA_SALDO_ACREEDOR)


def leer_cxc(ruta: Path, corte: date, moneda: str, curva: CurvaCobranza) -> ResultadoFuente:
    tabla = leer_tabla(ruta, COLUMNAS)
    facturas = tuple(_factura(r, corte, moneda) for r in tabla.registros)
    exigir_unicas(tabla.registros, [f.factura for f in facturas], "la factura")
    por_cobrar = tuple(f for f in facturas if f.saldo > CERO)
    acreedoras = tuple(f for f in facturas if f.saldo < CERO)
    planes = tuple(planear_cobro(f.saldo, f.vencimiento, corte, curva) for f in por_cobrar)
    filas = tuple(fila for f, plan in zip(por_cobrar, planes) for fila in _filas_de_cobro(f, plan, corte))
    return ResultadoFuente(
        fuente=FUENTE_CXC, archivo=tabla.archivo, sha256=tabla.sha256, registros=len(tabla.registros),
        total_insumo=sum((f.saldo for f in facturas), CERO),
        filas=ordenar_filas(filas + tuple(_fila_acreedora(f, corte) for f in acreedoras)),
        fuera_horizonte=sum((p.fuera_horizonte for p in planes), CERO),
        no_cobrable=sum((p.no_cobrable for p in planes), CERO),
        registros_en_cero=len(facturas) - len(por_cobrar) - len(acreedoras),
    )
