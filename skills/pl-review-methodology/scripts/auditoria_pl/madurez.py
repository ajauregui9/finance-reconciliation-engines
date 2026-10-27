"""Madurez del mes: ¿la exportación ya refleja un mes completo?

Tres pruebas independientes: días transcurridos desde el fin del periodo hasta
la extracción, nómina con movimiento y provisiones creadas.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Tuple

from .bloqueos import MES_INMADURO, NOMINA_SIN_REGISTRAR, PROVISION_SIN_CREAR, Bloqueo
from .config import ReglasMadurez
from .dinero import CERO
from .exportacion import ExportacionPL
from .validacion import fin_de_periodo


@dataclass(frozen=True)
class SeccionMadurez:
    fin_periodo: date
    fecha_extraccion: date
    dias_tras_cierre: int
    dias_minimos: int
    provisiones_no_exigidas: Tuple[str, ...]


def _actual(exportacion: ExportacionPL, cuenta: str) -> Decimal:
    """Monto del mes de una cuenta; una cuenta ausente cuenta como cero."""
    linea = exportacion.linea(cuenta)
    return CERO if linea is None else linea.actual


def _creado(exportacion: ExportacionPL, cuenta: str) -> Decimal:
    """Monto creado de una provisión; una provisión ausente cuenta como cero."""
    provision = exportacion.provision(cuenta)
    return CERO if provision is None else provision.creado


def _bloqueo_por_dias(dias: int, reglas: ReglasMadurez, periodo: str) -> Tuple[Bloqueo, ...]:
    if dias >= reglas.dias_minimos_tras_cierre:
        return ()
    detalle = (
        f"La exportación se tomó {dias} día(s) después del fin del periodo; "
        f"se piden al menos {reglas.dias_minimos_tras_cierre}."
    )
    return (Bloqueo(MES_INMADURO, periodo, detalle),)


def _bloqueos_de_nomina(reglas: ReglasMadurez, exportacion: ExportacionPL) -> Tuple[Bloqueo, ...]:
    return tuple(
        Bloqueo(NOMINA_SIN_REGISTRAR, cuenta, f"La cuenta de nómina {cuenta} no trae movimiento en el periodo.")
        for cuenta in reglas.cuentas_nomina
        if _actual(exportacion, cuenta) == CERO
    )


def _bloqueos_de_provisiones(reglas: ReglasMadurez, exportacion: ExportacionPL) -> Tuple[Bloqueo, ...]:
    return tuple(
        Bloqueo(PROVISION_SIN_CREAR, cuenta, f"La provisión {cuenta} no tiene un monto creado en el periodo.")
        for cuenta in reglas.provisiones_obligatorias
        if _creado(exportacion, cuenta) <= CERO
    )


def evaluar_madurez(
    reglas: ReglasMadurez, exportacion: ExportacionPL, periodo: str
) -> Tuple[SeccionMadurez, Tuple[Bloqueo, ...]]:
    fin = fin_de_periodo(periodo)
    dias = (exportacion.fecha_extraccion - fin).days
    seccion = SeccionMadurez(
        fin_periodo=fin,
        fecha_extraccion=exportacion.fecha_extraccion,
        dias_tras_cierre=dias,
        dias_minimos=reglas.dias_minimos_tras_cierre,
        provisiones_no_exigidas=tuple(
            p.cuenta for p in exportacion.provisiones if p.cuenta not in reglas.provisiones_obligatorias
        ),
    )
    bloqueos = (
        _bloqueo_por_dias(dias, reglas, periodo)
        + _bloqueos_de_nomina(reglas, exportacion)
        + _bloqueos_de_provisiones(reglas, exportacion)
    )
    return seccion, bloqueos
