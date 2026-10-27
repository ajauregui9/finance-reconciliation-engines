"""Generador sintético determinista para el demo de extracción de CFDI con un LLM.

    PYTHONPATH=examples python3 -m generador_llm            # reescribe examples/synthetic_llm/
    PYTHONPATH=examples python3 -m generador_llm --salida /ruta --semilla 7

Escribe 40 documentos (CFDI XML y representaciones impresas en texto) con verdad
conocida, el pool de CFDIs conocidos, respuestas grabadas sintéticas con errores
plantados y la lista de esos errores.
"""
from __future__ import annotations

from .escritura import (
    ARCHIVO_ERRORES,
    ARCHIVO_VERDAD,
    DIR_DOCUMENTOS,
    DIR_GRABADAS,
    DIR_POOL,
    contenidos,
    escribir_salida,
    texto_documento,
)
from .fabricas import DatosLlm, DocumentoSintetico, generar

CAMPOS = ("rfc_emisor", "rfc_receptor", "uuid", "fecha", "subtotal", "iva", "total", "moneda")

__all__ = [
    "ARCHIVO_ERRORES",
    "ARCHIVO_VERDAD",
    "CAMPOS",
    "DIR_DOCUMENTOS",
    "DIR_GRABADAS",
    "DIR_POOL",
    "DatosLlm",
    "DocumentoSintetico",
    "contenidos",
    "escribir_salida",
    "generar",
    "texto_documento",
]
