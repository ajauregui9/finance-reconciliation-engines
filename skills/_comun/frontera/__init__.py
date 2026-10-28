"""Frontera de entrada compartida: importes, enteros, fechas y horas externos.

Todo motor que lee un archivo, un argumento o una config convierte aquí sus valores
numéricos y de fecha. Los motores solo eligen la forma (`FormaImporte`) que fija su spec
y envuelven `ErrorFrontera` en su propio error, con archivo, fila y campo.
"""
from __future__ import annotations

from .errores import ErrorFrontera
from .fechas import leer_desfase_utc, leer_fecha, leer_fecha_hora, leer_mes
from .importes import CENTAVO, IMPORTE, FormaImporte, leer_entero, leer_importe

__all__ = [
    "CENTAVO",
    "IMPORTE",
    "ErrorFrontera",
    "FormaImporte",
    "leer_desfase_utc",
    "leer_entero",
    "leer_fecha",
    "leer_fecha_hora",
    "leer_importe",
    "leer_mes",
]
