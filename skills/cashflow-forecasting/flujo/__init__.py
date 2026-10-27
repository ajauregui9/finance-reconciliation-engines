"""Flujo de efectivo de 13 semanas: adaptadores por fuente, filas contrato y ensamblador.

Uso como biblioteca:

    from flujo import cargar_config, ensamblar, leer_fuentes
    config = cargar_config(Path("config/flujo_ejemplo.json"))
    flujo = ensamblar(leer_fuentes(config, corte), corte, config.moneda)

La spec está en `skills/cashflow-forecasting/specs/flujo-13-semanas.md`.
"""
from __future__ import annotations

from .avisos import Aviso, avisos
from .config import ConfigFlujo, CurvaCobranza, TramoCurva, cargar_config, validar_curva
from .contrato import FUENTES, FilaContrato, ResultadoFuente
from .ensamblador import Flujo, SemanaFlujo, ensamblar, verificar_invariantes
from .errores import ErrorConfig, ErrorFlujo, ErrorInsumo, ErrorInvariante
from .fuentes import leer_fuentes

__all__ = [
    "FUENTES",
    "Aviso",
    "ConfigFlujo",
    "CurvaCobranza",
    "ErrorConfig",
    "ErrorFlujo",
    "ErrorInsumo",
    "ErrorInvariante",
    "FilaContrato",
    "Flujo",
    "ResultadoFuente",
    "SemanaFlujo",
    "TramoCurva",
    "avisos",
    "cargar_config",
    "ensamblar",
    "leer_fuentes",
    "validar_curva",
    "verificar_invariantes",
]
