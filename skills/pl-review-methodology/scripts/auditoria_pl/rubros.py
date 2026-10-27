"""Totales por rubro y base de ingreso sobre la que se calculan las razones."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from .bloqueos import CUENTA_SIN_RUBRO, Bloqueo
from .config import CatalogoRubros
from .dinero import CERO, texto
from .exportacion import ExportacionPL, LineaCuenta
from .validacion import ErrorEntrada


@dataclass(frozen=True)
class TotalesRubro:
    ingreso: Decimal
    costo: Decimal
    gasto_venta: Decimal
    gasto_admin: Decimal
    bajo_ebitda: Decimal
    sin_rubro: Decimal


@dataclass(frozen=True)
class MontoAislado:
    cuenta: str
    monto: Decimal


@dataclass(frozen=True)
class BaseIngreso:
    ingreso_rubro: Decimal
    polizas_aisladas: Decimal
    base: Decimal
    aislado_por_cuenta: Tuple[MontoAislado, ...]


def _suma(clasificadas: Sequence[Tuple[Optional[str], LineaCuenta]], rubro: Optional[str]) -> Decimal:
    return sum((linea.actual for asignado, linea in clasificadas if asignado == rubro), CERO)


def totalizar(cuentas: Sequence[LineaCuenta], catalogo: CatalogoRubros) -> Tuple[TotalesRubro, Tuple[Bloqueo, ...]]:
    """Suma `actual` por rubro. Una cuenta sin rubro no se descarta: se suma aparte y bloquea."""
    clasificadas = [(catalogo.rubro_de(linea.cuenta), linea) for linea in cuentas]
    totales = TotalesRubro(
        ingreso=_suma(clasificadas, "ingreso"),
        costo=_suma(clasificadas, "costo"),
        gasto_venta=_suma(clasificadas, "gasto_venta"),
        gasto_admin=_suma(clasificadas, "gasto_admin"),
        bajo_ebitda=_suma(clasificadas, "bajo_ebitda"),
        sin_rubro=_suma(clasificadas, None),
    )
    bloqueos = tuple(
        Bloqueo(CUENTA_SIN_RUBRO, linea.cuenta, f"La cuenta {linea.cuenta} ({linea.nombre}) no cae en ningún rubro.")
        for asignado, linea in clasificadas
        if asignado is None
    )
    return totales, bloqueos


def _polizas_de(exportacion: ExportacionPL, cuenta: str) -> Decimal:
    """Parte de pólizas manuales de una cuenta; una cuenta ausente aparta cero."""
    linea = exportacion.linea(cuenta)
    return CERO if linea is None else linea.polizas_manuales_actual


def calcular_base(totales: TotalesRubro, cuentas_sin_polizas: Sequence[str], exportacion: ExportacionPL) -> BaseIngreso:
    """Aparta de la base la parte de pólizas manuales de las cuentas configuradas."""
    aislados = tuple(MontoAislado(cuenta, _polizas_de(exportacion, cuenta)) for cuenta in cuentas_sin_polizas)
    polizas = sum((a.monto for a in aislados), CERO)
    base = totales.ingreso - polizas
    if base <= CERO:
        raise ErrorEntrada(f"La base de ingreso debe ser positiva para calcular razones; resultó {texto(base)}")
    return BaseIngreso(ingreso_rubro=totales.ingreso, polizas_aisladas=polizas, base=base, aislado_por_cuenta=aislados)
