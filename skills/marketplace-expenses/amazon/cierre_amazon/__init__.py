"""Cierre mensual de Amazon por devengo, con montos `Decimal`.

Spec: `specs/cierre_amazon.md`. Uso típico desde código::

    config = cargar_config(ruta_config)
    resultado = cerrar(cargar_insumos(directorio_datos, config), config)
    texto = a_json(resultado)
"""
from .cierre import CierreMes, ResultadoCorrida, cerrar
from .config import Config, cargar_config, con_fuente_publicidad
from .errores import ErrorCierre, ErrorConfig, ErrorInsumo
from .insumos import cargar_insumos
from .salida_json import a_dict, a_json
from .salida_xlsx import escribir_xlsx, verificar_xlsx

__all__ = [
    "CierreMes", "Config", "ErrorCierre", "ErrorConfig", "ErrorInsumo", "ResultadoCorrida", "a_dict", "a_json",
    "cargar_config", "cargar_insumos", "cerrar", "con_fuente_publicidad", "escribir_xlsx", "verificar_xlsx",
]
