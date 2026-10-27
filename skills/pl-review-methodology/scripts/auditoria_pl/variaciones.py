"""Variaciones de mes contra mes por cuenta, separadas por materialidad.

Cada cuenta cae en exactamente una clase; los conteos de las cuatro clases
suman el número de cuentas, así que ninguna fila se pierde sin dejar rastro.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Sequence, Tuple

from .config import CatalogoRubros, ReglasMaterialidad
from .dinero import CERO, porcentaje, proporcion
from .exportacion import LineaCuenta

BAJO_MONTO = "bajo_monto"
BAJO_VARIACION_PCT = "bajo_variacion_pct"
MENCION = "mencion"
MATERIAL = "material"


@dataclass(frozen=True)
class Variacion:
    cuenta: str
    nombre: str
    rubro: Optional[str]
    anterior: Decimal
    actual: Decimal
    delta: Decimal
    variacion_pct: Optional[Decimal]
    cuenta_nueva: bool


@dataclass(frozen=True)
class ConteosVariacion:
    bajo_monto: int
    bajo_variacion_pct: int
    menciones: int
    materiales: int
    omitidas_por_tope: int


@dataclass(frozen=True)
class SeccionVariaciones:
    piso_material: Decimal
    piso_mencion: Decimal
    variacion_pct_minima: Decimal
    conteos: ConteosVariacion
    materiales: Tuple[Variacion, ...]
    menciones: Tuple[Variacion, ...]


def _variacion(linea: LineaCuenta, catalogo: CatalogoRubros) -> Variacion:
    delta = linea.actual - linea.anterior
    sin_base = linea.anterior == CERO
    return Variacion(
        cuenta=linea.cuenta,
        nombre=linea.nombre,
        rubro=catalogo.rubro_de(linea.cuenta),
        anterior=linea.anterior,
        actual=linea.actual,
        delta=delta,
        variacion_pct=None if sin_base else porcentaje(abs(delta), abs(linea.anterior)),
        cuenta_nueva=sin_base and linea.actual != CERO,
    )


def _clase(variacion: Variacion, reglas: ReglasMaterialidad, piso_material: Decimal) -> str:
    magnitud = abs(variacion.delta)
    if magnitud < reglas.piso_mencion:
        return BAJO_MONTO
    if variacion.variacion_pct is not None and variacion.variacion_pct < reglas.variacion_pct_minima:
        return BAJO_VARIACION_PCT
    return MATERIAL if magnitud >= piso_material else MENCION


def _por_magnitud(variaciones: Sequence[Variacion]) -> Tuple[Variacion, ...]:
    return tuple(sorted(variaciones, key=lambda v: (-abs(v.delta), v.cuenta)))


def analizar_variaciones(
    cuentas: Sequence[LineaCuenta], catalogo: CatalogoRubros, reglas: ReglasMaterialidad, base: Decimal
) -> SeccionVariaciones:
    piso_material = max(reglas.piso_monto, proporcion(base, reglas.piso_pct_ingreso))
    clasificadas = [(_clase(v, reglas, piso_material), v) for v in (_variacion(c, catalogo) for c in cuentas)]

    def de_clase(clase: str) -> Tuple[Variacion, ...]:
        return _por_magnitud([v for c, v in clasificadas if c == clase])

    materiales = de_clase(MATERIAL)
    menciones = de_clase(MENCION)
    conteos = ConteosVariacion(
        bajo_monto=len(de_clase(BAJO_MONTO)),
        bajo_variacion_pct=len(de_clase(BAJO_VARIACION_PCT)),
        menciones=len(menciones),
        materiales=len(materiales),
        omitidas_por_tope=max(0, len(materiales) - reglas.tope_materiales),
    )
    return SeccionVariaciones(
        piso_material=piso_material,
        piso_mencion=reglas.piso_mencion,
        variacion_pct_minima=reglas.variacion_pct_minima,
        conteos=conteos,
        materiales=materiales[: reglas.tope_materiales],
        menciones=menciones,
    )
