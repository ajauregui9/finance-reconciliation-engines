"""Adaptadores de fuente: cada insumo de la config se traduce a filas contrato."""
from __future__ import annotations

from datetime import date
from typing import Tuple

from ..config import ConfigFlujo
from ..contrato import FUENTE_CXC, FUENTE_CXP, FUENTE_IMPUESTOS, FUENTE_NOMINA, FUENTE_SALDOS, ResultadoFuente
from .cxc import leer_cxc
from .egresos import leer_cxp, leer_impuestos, leer_nomina
from .saldos import leer_saldos

__all__ = ["leer_cxc", "leer_cxp", "leer_fuentes", "leer_impuestos", "leer_nomina", "leer_saldos"]


def leer_fuentes(config: ConfigFlujo, corte: date) -> Tuple[ResultadoFuente, ...]:
    """Lee las cinco rutas de la config, en el orden canónico de `FUENTES`."""
    moneda = config.moneda
    return (
        leer_saldos(config.ruta(FUENTE_SALDOS), corte, moneda),
        leer_cxc(config.ruta(FUENTE_CXC), corte, moneda, config.curva),
        leer_cxp(config.ruta(FUENTE_CXP), corte, moneda),
        leer_nomina(config.ruta(FUENTE_NOMINA), corte, moneda),
        leer_impuestos(config.ruta(FUENTE_IMPUESTOS), corte, moneda),
    )
