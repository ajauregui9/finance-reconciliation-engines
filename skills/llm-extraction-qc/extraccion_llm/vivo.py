"""Modo vivo: la llave por variable de entorno, el import perezoso del SDK y el extractor.

La llave nunca se lee ni se escribe: solo se verifica que exista y el SDK la toma del
entorno. `anthropic` es opcional (`requirements-llm.txt`) y se importa solo aquí, al crear
el cliente. Un error de la API detiene la corrida (código 2).
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, cast

from .documentos import Documento
from .errores import InsumoInvalido
from .grabadas import ORIGEN_VIVO, Grabada, escribir_grabada
from .respuesta import ClienteSdk, Extraida, respuesta_desde_sdk

VARIABLE_API_KEY = "ANTHROPIC_API_KEY"
MODULO_SDK = "anthropic"
ARCHIVO_REQUISITOS = "requirements-llm.txt"

Importador = Callable[[str], Any]


def exigir_api_key(entorno: Mapping[str, str]) -> None:
    if not entorno.get(VARIABLE_API_KEY, "").strip():
        raise InsumoInvalido(f"el modo vivo requiere la variable de entorno {VARIABLE_API_KEY}; defínela o usa "
                             "--modo grabado (sin red ni llave)")


def crear_cliente_sdk(importar: Importador = importlib.import_module) -> ClienteSdk:
    """El cliente del SDK, importado en este momento y no antes."""
    try:
        modulo = importar(MODULO_SDK)
    except ImportError:
        raise InsumoInvalido(f"el modo vivo requiere el SDK {MODULO_SDK}: "
                             f"pip install -r {ARCHIVO_REQUISITOS}") from None
    fabrica = getattr(modulo, "Anthropic", None)
    if not callable(fabrica):
        raise InsumoInvalido(f"el módulo {MODULO_SDK} instalado no ofrece Anthropic()")
    try:
        return cast(ClienteSdk, fabrica())
    except Exception as exc:
        raise InsumoInvalido(f"no se pudo crear el cliente de {MODULO_SDK}: {type(exc).__name__}: {exc}") from exc


@dataclass(frozen=True)
class ExtractorVivo:
    """Llama a la API por documento y, si se pidió, graba cada respuesta recibida."""

    cliente: ClienteSdk
    grabar_en: Optional[Path] = None

    def extraer(self, documento: Documento, solicitud: Mapping[str, Any]) -> Extraida:
        try:
            cruda = self.cliente.messages.create(**solicitud)
        except Exception as exc:
            raise InsumoInvalido(f"{documento.documento_id}: la API respondió con error "
                                 f"({type(exc).__name__}: {exc})") from exc
        respuesta = respuesta_desde_sdk(cruda)
        if self.grabar_en is not None:
            escribir_grabada(self.grabar_en, Grabada(documento.documento_id, documento.sha256, ORIGEN_VIVO, respuesta))
        return Extraida(respuesta, ORIGEN_VIVO)
