"""Exportación mensual del estado de resultados (`exportacion_pl/v1`).

Se valida fila por fila con la ruta exacta de cada dato y se ordena por llave
(cuenta, marca), de modo que el orden del archivo no cambia el reporte.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable, Optional, Sequence, Tuple, TypeVar

from .dinero import CERO
from .validacion import (
    ErrorEntrada,
    exigir_llaves,
    exigir_objeto,
    exigir_sin_repetidos,
    leer_codigo,
    leer_fecha,
    leer_lista,
    leer_monto,
    leer_periodo,
    leer_texto,
)

ESQUEMA_EXPORTACION = "exportacion_pl/v1"

T = TypeVar("T")


@dataclass(frozen=True)
class LineaCuenta:
    cuenta: str
    nombre: str
    anterior: Decimal
    actual: Decimal
    # Parte de `actual` registrada con pólizas manuales (no con documentos).
    polizas_manuales_actual: Decimal


@dataclass(frozen=True)
class VentaMarca:
    marca: str
    venta: Decimal
    publicidad: Decimal


@dataclass(frozen=True)
class ProvisionDelMes:
    cuenta: str
    creado: Decimal


@dataclass(frozen=True)
class ExportacionPL:
    periodo: str
    fecha_extraccion: date
    cuentas: Tuple[LineaCuenta, ...]
    marcas: Tuple[VentaMarca, ...]
    provisiones: Tuple[ProvisionDelMes, ...]

    def linea(self, cuenta: str) -> Optional[LineaCuenta]:
        return next((linea for linea in self.cuentas if linea.cuenta == cuenta), None)

    def provision(self, cuenta: str) -> Optional[ProvisionDelMes]:
        return next((p for p in self.provisiones if p.cuenta == cuenta), None)


def _leer_linea(crudo: Any, ruta: str) -> LineaCuenta:
    fila = exigir_objeto(crudo, ruta)
    exigir_llaves(fila, ruta, ("cuenta", "nombre", "anterior", "actual"), opcionales=("polizas_manuales_actual",))
    # La llave es opcional, pero si viene debe ser un monto: un null no se lee como cero.
    polizas = (
        leer_monto(fila["polizas_manuales_actual"], f"{ruta}.polizas_manuales_actual")
        if "polizas_manuales_actual" in fila
        else CERO
    )
    return LineaCuenta(
        cuenta=leer_codigo(fila["cuenta"], f"{ruta}.cuenta"),
        nombre=leer_texto(fila["nombre"], f"{ruta}.nombre"),
        anterior=leer_monto(fila["anterior"], f"{ruta}.anterior"),
        actual=leer_monto(fila["actual"], f"{ruta}.actual"),
        polizas_manuales_actual=polizas,
    )


def _leer_marca(crudo: Any, ruta: str) -> VentaMarca:
    fila = exigir_objeto(crudo, ruta)
    exigir_llaves(fila, ruta, ("marca", "venta", "publicidad"))
    return VentaMarca(
        marca=leer_codigo(fila["marca"], f"{ruta}.marca"),
        venta=leer_monto(fila["venta"], f"{ruta}.venta"),
        publicidad=leer_monto(fila["publicidad"], f"{ruta}.publicidad"),
    )


def _leer_provision(crudo: Any, ruta: str) -> ProvisionDelMes:
    fila = exigir_objeto(crudo, ruta)
    exigir_llaves(fila, ruta, ("cuenta", "creado"))
    return ProvisionDelMes(
        cuenta=leer_codigo(fila["cuenta"], f"{ruta}.cuenta"),
        creado=leer_monto(fila["creado"], f"{ruta}.creado"),
    )


def _leer_filas(
    crudo: Any, ruta: str, lector: Callable[[Any, str], T], llave: Callable[[T], str], que: str
) -> Tuple[T, ...]:
    filas: Sequence[T] = [lector(item, f"{ruta}[{i}]") for i, item in enumerate(leer_lista(crudo, ruta))]
    exigir_sin_repetidos([llave(fila) for fila in filas], ruta, que)
    return tuple(sorted(filas, key=llave))


def leer_exportacion(crudo: Any) -> ExportacionPL:
    """Valida el JSON decodificado de la exportación y devuelve su forma tipada e inmutable."""
    objeto = exigir_objeto(crudo, "")
    exigir_llaves(objeto, "", ("esquema", "periodo", "fecha_extraccion", "cuentas", "marcas", "provisiones"))
    if objeto["esquema"] != ESQUEMA_EXPORTACION:
        raise ErrorEntrada(f"esquema: se esperaba {ESQUEMA_EXPORTACION!r}, llegó {objeto['esquema']!r}")
    cuentas = _leer_filas(objeto["cuentas"], "cuentas", _leer_linea, lambda c: c.cuenta, "cuenta")
    if not cuentas:
        raise ErrorEntrada("cuentas: la lista no puede ir vacía")
    return ExportacionPL(
        periodo=leer_periodo(objeto["periodo"], "periodo"),
        fecha_extraccion=leer_fecha(objeto["fecha_extraccion"], "fecha_extraccion"),
        cuentas=cuentas,
        marcas=_leer_filas(objeto["marcas"], "marcas", _leer_marca, lambda m: m.marca, "marca"),
        provisiones=_leer_filas(
            objeto["provisiones"], "provisiones", _leer_provision, lambda p: p.cuenta, "cuenta de provisión"
        ),
    )
