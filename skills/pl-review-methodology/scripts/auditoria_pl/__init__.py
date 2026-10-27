"""Revisor del estado de resultados previo al cierre (spec: specs/auditoria_pl.md del skill).

Uso como biblioteca:

    from auditoria_pl import auditar, leer_config, leer_exportacion, serializar
    reporte = auditar(leer_config(config_json), leer_exportacion(exportacion_json), periodo)
    texto = serializar(reporte)
"""

from __future__ import annotations

from .auditoria import ESQUEMA_REPORTE, ReporteAuditoria, auditar, auditar_crudo
from .config import ESQUEMA_CONFIG, ConfigAuditoria, leer_config
from .exportacion import ESQUEMA_EXPORTACION, ExportacionPL, leer_exportacion
from .salida import a_json, serializar
from .validacion import ErrorEntrada

__all__ = [
    "ESQUEMA_CONFIG",
    "ESQUEMA_EXPORTACION",
    "ESQUEMA_REPORTE",
    "ConfigAuditoria",
    "ErrorEntrada",
    "ExportacionPL",
    "ReporteAuditoria",
    "a_json",
    "auditar",
    "auditar_crudo",
    "leer_config",
    "leer_exportacion",
    "serializar",
]
