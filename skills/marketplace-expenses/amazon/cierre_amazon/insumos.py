"""Descubre y lee todos los insumos de un directorio (spec, sección 2)."""
from __future__ import annotations

from pathlib import Path
from typing import Dict

from .config import Config
from .errores import ErrorInsumo
from .lector_fuentes import leer_consola, leer_facturas, leer_venta_erp
from .lector_liquidacion import leer_liquidacion
from .modelo import ArchivoLiquidacion, Insumos

PATRON_LIQUIDACION = "liquidacion_*.csv"
ARCHIVO_CONSOLA = "publicidad_consola.csv"
ARCHIVO_FACTURAS = "facturas_publicidad.json"
ARCHIVO_VENTA_ERP = "venta_erp.json"


def _liquidaciones(directorio: Path, config: Config) -> tuple[ArchivoLiquidacion, ...]:
    rutas = sorted(directorio.glob(PATRON_LIQUIDACION))
    if not rutas:
        raise ErrorInsumo(f"no hay archivos {PATRON_LIQUIDACION} en el directorio de datos")
    por_periodo: Dict[str, ArchivoLiquidacion] = {}
    for ruta in rutas:
        archivo = leer_liquidacion(ruta, config.moneda)
        previo = por_periodo.get(archivo.periodo)
        if previo is not None:
            raise ErrorInsumo(
                f"{previo.nombre} y {archivo.nombre} declaran el mismo Periodo {archivo.periodo}; "
                "se contaría dos veces la liquidación")
        por_periodo[archivo.periodo] = archivo
    return tuple(por_periodo[periodo] for periodo in sorted(por_periodo))


def cargar_insumos(directorio: Path, config: Config) -> Insumos:
    """Lee las liquidaciones (obligatorias) y las fuentes opcionales que existan."""
    if not directorio.is_dir():
        raise ErrorInsumo(f"el directorio de datos no existe: {directorio.name}")
    consola = directorio / ARCHIVO_CONSOLA
    facturas = directorio / ARCHIVO_FACTURAS
    venta_erp = directorio / ARCHIVO_VENTA_ERP
    return Insumos(
        archivos=_liquidaciones(directorio, config),
        consola=leer_consola(consola) if consola.is_file() else None,
        facturas=leer_facturas(facturas) if facturas.is_file() else None,
        venta_erp=leer_venta_erp(venta_erp) if venta_erp.is_file() else None,
    )
