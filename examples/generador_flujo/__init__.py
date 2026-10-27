"""Generador sintético determinista de insumos para el flujo de efectivo de 13 semanas.

    PYTHONPATH=examples python3 -m generador_flujo            # reescribe examples/synthetic_flujo/
    PYTHONPATH=examples python3 -m generador_flujo --salida /tmp/x --semilla 7

Uso como biblioteca:

    from generador_flujo import cargar_parametros, generar, escribir_salida
    escribir_salida(generar(cargar_parametros(ruta)), destino)
"""
from __future__ import annotations

from .escritura import ARCHIVOS, contenidos, escribir_salida
from .fabricas import DatosFlujo, generar
from .parametros import ErrorParametros, Parametros, cargar_parametros, parametros_desde_dict

__all__ = [
    "ARCHIVOS",
    "DatosFlujo",
    "ErrorParametros",
    "Parametros",
    "cargar_parametros",
    "contenidos",
    "escribir_salida",
    "generar",
    "parametros_desde_dict",
]
