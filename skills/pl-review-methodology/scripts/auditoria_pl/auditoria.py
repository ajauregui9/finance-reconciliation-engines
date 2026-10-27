"""Orquestación: una función pura que junta todas las reglas en un reporte."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Tuple

from .bandas import EvaluacionBanda, Metrica, calcular_metricas, evaluar_bandas
from .bloqueos import Bloqueo, ordenar_bloqueos
from .config import ConfigAuditoria, leer_config
from .exportacion import ExportacionPL, leer_exportacion
from .madurez import SeccionMadurez, evaluar_madurez
from .publicidad import SeccionPublicidad, evaluar_publicidad
from .rubros import BaseIngreso, TotalesRubro, calcular_base, totalizar
from .salida import a_json
from .validacion import ErrorEntrada, leer_periodo
from .variaciones import SeccionVariaciones, analizar_variaciones

ESQUEMA_REPORTE = "reporte_auditoria_pl/v1"


@dataclass(frozen=True)
class ReporteAuditoria:
    esquema: str
    periodo: str
    provisional: bool
    bloqueos: Tuple[Bloqueo, ...]
    madurez: SeccionMadurez
    base_ingreso: BaseIngreso
    rubros: TotalesRubro
    metricas: Mapping[str, Metrica]
    bandas: Tuple[EvaluacionBanda, ...]
    publicidad: SeccionPublicidad
    variaciones: SeccionVariaciones


def auditar(config: ConfigAuditoria, exportacion: ExportacionPL, periodo: str) -> ReporteAuditoria:
    """Audita `exportacion` para `periodo` (obligatorio, `AAAA-MM`, igual al de la exportación)."""
    solicitado = leer_periodo(periodo, "periodo solicitado")
    if solicitado != exportacion.periodo:
        raise ErrorEntrada(
            f"El periodo solicitado ({solicitado}) no coincide con el de la exportación ({exportacion.periodo})"
        )
    madurez, bloqueos_madurez = evaluar_madurez(config.madurez, exportacion, solicitado)
    totales, bloqueos_rubro = totalizar(exportacion.cuentas, config.rubros)
    base = calcular_base(totales, config.cuentas_sin_polizas_manuales, exportacion)
    metricas = calcular_metricas(totales, base.base)
    publicidad, bloqueos_publicidad = evaluar_publicidad(config.publicidad, exportacion)
    bloqueos = ordenar_bloqueos(bloqueos_madurez, bloqueos_rubro, bloqueos_publicidad)
    return ReporteAuditoria(
        esquema=ESQUEMA_REPORTE,
        periodo=solicitado,
        provisional=bool(bloqueos),
        bloqueos=bloqueos,
        madurez=madurez,
        base_ingreso=base,
        rubros=totales,
        metricas=metricas,
        bandas=evaluar_bandas(metricas, config.bandas),
        publicidad=publicidad,
        variaciones=analizar_variaciones(exportacion.cuentas, config.rubros, config.materialidad, base.base),
    )


def auditar_crudo(config_crudo: Any, exportacion_cruda: Any, periodo: str) -> Dict[str, Any]:
    """Atajo para JSON ya decodificado: valida, audita y devuelve el reporte como diccionario JSON."""
    reporte = auditar(leer_config(config_crudo), leer_exportacion(exportacion_cruda), periodo)
    resultado: Dict[str, Any] = a_json(reporte)
    return resultado
