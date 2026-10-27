"""Modo vivo: la llave por variable de entorno, el import perezoso del SDK y el extractor con reintentos.

La llave nunca se lee ni se escribe: solo se verifica que exista y el SDK la toma del
entorno. `anthropic` es opcional (`requirements-llm.txt`) y se importa solo aquí, al crear
el cliente, con `max_retries=0`: los reintentos los hace este módulo (`reintentos.py`), con
una política de la config, jitter inyectable y avisos por reintento, y así no se duplican.

Ante un error de la API: transitorio (429, 5xx, conexión) se reintenta; si se agotan los
reintentos o no es transitorio, el documento falla (`FallaApiDocumento`) y el lote sigue;
una llave rechazada (401/403) detiene la corrida (código 2), igual que un error que no
tiene forma de error de la API.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, cast

from .config import Reintentos
from .documentos import Documento
from .errores import AutenticacionRechazada, FallaApiDocumento, InsumoInvalido
from .grabadas import ORIGEN_VIVO, Grabada, escribir_grabada
from .reintentos import AUTENTICACION, PERMANENTE, Reloj, clasificar, espera_exponencial, estado_http
from .reintentos import segundos_retry_after
from .respuesta import ClienteSdk, Extraida, RespuestaSdk, respuesta_desde_sdk

VARIABLE_API_KEY = "ANTHROPIC_API_KEY"
MODULO_SDK = "anthropic"
ARCHIVO_REQUISITOS = "requirements-llm.txt"
# El SDK no reintenta: lo hace este módulo.
OPCIONES_CLIENTE: Mapping[str, Any] = {"max_retries": 0}
LARGO_RESUMEN_ERROR = 200

Importador = Callable[[str], Any]
Avisar = Callable[[str], None]


def exigir_api_key(entorno: Mapping[str, str]) -> None:
    if not entorno.get(VARIABLE_API_KEY, "").strip():
        raise InsumoInvalido(f"el modo vivo requiere la variable de entorno {VARIABLE_API_KEY}; defínela o usa "
                             "--modo grabado (sin red ni llave)")


def crear_cliente_sdk(importar: Importador = importlib.import_module) -> ClienteSdk:
    """El cliente del SDK, importado en este momento y no antes, sin reintentos propios."""
    try:
        modulo = importar(MODULO_SDK)
    except ImportError:
        raise InsumoInvalido(f"el modo vivo requiere el SDK {MODULO_SDK}: "
                             f"pip install -r {ARCHIVO_REQUISITOS}") from None
    fabrica = getattr(modulo, "Anthropic", None)
    if not callable(fabrica):
        raise InsumoInvalido(f"el módulo {MODULO_SDK} instalado no ofrece Anthropic()")
    try:
        return cast(ClienteSdk, fabrica(**OPCIONES_CLIENTE))
    except Exception as exc:
        raise InsumoInvalido(f"no se pudo crear el cliente de {MODULO_SDK}: {type(exc).__name__}: {exc}") from exc


def _descripcion(error: BaseException) -> str:
    """Estado HTTP (si hay), clase y un resumen corto del mensaje del error."""
    estado = estado_http(error)
    prefijo = "" if estado is None else f"HTTP {estado}, "
    return f"{prefijo}{type(error).__name__}: {str(error)[:LARGO_RESUMEN_ERROR]}"


@dataclass(frozen=True)
class ExtractorVivo:
    """Llama a la API por documento, reintenta lo transitorio y, si se pidió, graba cada respuesta."""

    cliente: ClienteSdk
    reintentos: Reintentos
    grabar_en: Optional[Path] = None
    reloj: Reloj = field(default_factory=Reloj)
    avisar: Optional[Avisar] = None

    def extraer(self, documento: Documento, solicitud: Mapping[str, Any]) -> Extraida:
        respuesta = respuesta_desde_sdk(self._llamar(documento.documento_id, solicitud))
        if self.grabar_en is not None:
            escribir_grabada(self.grabar_en, Grabada(documento.documento_id, documento.sha256, ORIGEN_VIVO, respuesta))
        return Extraida(respuesta, ORIGEN_VIVO)

    def _llamar(self, documento_id: str, solicitud: Mapping[str, Any]) -> RespuestaSdk:
        intento = 1
        while True:
            try:
                return self.cliente.messages.create(**solicitud)
            except Exception as exc:
                espera = self._espera_tras_error(documento_id, exc, intento)
                self._avisar(f"{documento_id}: error transitorio de la API ({_descripcion(exc)}); "
                             f"reintento {intento}/{self.reintentos.max_reintentos} en {espera:.2f} s")
            self.reloj.dormir(espera)
            intento += 1

    def _avisar(self, mensaje: str) -> None:
        if self.avisar is not None:
            self.avisar(mensaje)

    def _espera_tras_error(self, documento_id: str, error: Exception, intento: int) -> float:
        """Los segundos antes del siguiente intento, o la excepción que corresponde si no se reintenta."""
        clase = clasificar(error)
        if clase is None:
            raise InsumoInvalido(f"{documento_id}: error inesperado del cliente ({type(error).__name__}: "
                                 f"{str(error)[:LARGO_RESUMEN_ERROR]}); no es un error de la API") from error
        if clase == AUTENTICACION:
            # Sin el texto del error: la corrida se detiene y el mensaje no debe arrastrar nada de la cuenta.
            raise AutenticacionRechazada(f"la API rechazó la autenticación (HTTP {estado_http(error)}, "
                                         f"{type(error).__name__}): revisa {VARIABLE_API_KEY} y sus permisos; "
                                         "ningún documento podría procesarse") from None
        if clase == PERMANENTE:
            raise FallaApiDocumento(documento_id, f"{documento_id}: la API rechazó la solicitud "
                                                  f"({_descripcion(error)}); no se reintenta", intento) from error
        if intento > self.reintentos.max_reintentos:
            raise FallaApiDocumento(documento_id, f"{documento_id}: error transitorio de la API "
                                                  f"({_descripcion(error)}) tras {intento} intentos; se agotaron los "
                                                  f"{self.reintentos.max_reintentos} reintentos", intento) from error
        return self._espera(documento_id, error, intento)

    def _espera(self, documento_id: str, error: Exception, intento: int) -> float:
        backoff = espera_exponencial(intento, self.reintentos, self.reloj.azar())
        pedido = segundos_retry_after(error, self.reloj.ahora())
        if pedido is None:
            return backoff
        if pedido > self.reintentos.espera_maxima_s:
            raise FallaApiDocumento(documento_id, f"{documento_id}: la API pidió esperar {pedido:.2f} s "
                                                  f"(retry-after) y la espera máxima es "
                                                  f"{self.reintentos.espera_maxima_s:.2f} s; no se reintenta",
                                    intento) from error
        return max(backoff, pedido)
