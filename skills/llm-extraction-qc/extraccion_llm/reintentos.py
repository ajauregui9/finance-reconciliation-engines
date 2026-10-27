"""Reintentos de la API: qué error se reintenta, cuánto se espera y cómo se respeta `retry-after`.

Los errores se clasifican por su forma, no por las clases del SDK (que es opcional): un
`status_code` entero o el nombre de la clase. Transitorios (se reintentan): 429, cualquier
5xx (incluye 529, sobrecarga) y los errores de conexión o de tiempo agotado sin respuesta.
Autenticación (detienen la corrida): 401 y 403. Permanentes (el documento va a revisión sin
reintentar): cualquier otro estado y los errores de la API sin estado. Lo que no tiene forma
de error de la API no se clasifica: es un defecto y quien llama detiene la corrida.

La espera es exponencial con jitter "igual": la mitad del tope es fija y la otra mitad al azar,
así nunca es cero. Si el servidor manda `retry-after`, nunca se reintenta antes de ese plazo.
El azar y el reloj se inyectan (`Reloj`) para que las pruebas sean deterministas.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable, FrozenSet, Optional

from .config import Reintentos

TRANSITORIO = "transitorio"
AUTENTICACION = "autenticacion"
PERMANENTE = "permanente"

ESTADO_LIMITE_DE_TASA = 429
ESTADOS_AUTENTICACION: FrozenSet[int] = frozenset({401, 403})
PRIMER_ESTADO_SERVIDOR, ULTIMO_ESTADO_SERVIDOR = 500, 599
# Nombres de las clases del SDK: conexión o tiempo agotado (sin respuesta) y la base de sus errores.
CLASES_CONEXION: FrozenSet[str] = frozenset({"APIConnectionError", "APITimeoutError"})
CLASE_ERROR_API = "APIError"
ENCABEZADO_RETRY_AFTER = "retry-after"
_FORMA_SEGUNDOS = re.compile(r"[0-9]+(?:\.[0-9]+)?")


@dataclass(frozen=True)
class Reloj:
    """Lo que el reintento toma del mundo: esperar, azar para el jitter y la hora (para `retry-after`)."""

    dormir: Callable[[float], None] = time.sleep
    azar: Callable[[], float] = random.random
    ahora: Callable[[], float] = time.time


def estado_http(error: BaseException) -> Optional[int]:
    estado = getattr(error, "status_code", None)
    return estado if isinstance(estado, int) and not isinstance(estado, bool) else None


def _nombres_de_clase(error: BaseException) -> FrozenSet[str]:
    return frozenset(clase.__name__ for clase in type(error).__mro__)


def clasificar(error: BaseException) -> Optional[str]:
    """TRANSITORIO, AUTENTICACION o PERMANENTE; None si no es un error de la API."""
    estado = estado_http(error)
    if estado is not None:
        if estado in ESTADOS_AUTENTICACION:
            return AUTENTICACION
        servidor = PRIMER_ESTADO_SERVIDOR <= estado <= ULTIMO_ESTADO_SERVIDOR
        return TRANSITORIO if estado == ESTADO_LIMITE_DE_TASA or servidor else PERMANENTE
    nombres = _nombres_de_clase(error)
    if isinstance(error, (TimeoutError, ConnectionError)) or nombres & CLASES_CONEXION:
        return TRANSITORIO
    return PERMANENTE if CLASE_ERROR_API in nombres else None


def espera_exponencial(reintento: int, politica: Reintentos, azar: float) -> float:
    """Segundos antes del reintento número `reintento` (1 es el primero), con `azar` en [0, 1]."""
    tope = min(politica.espera_maxima_s, politica.espera_inicial_s * 2.0 ** (reintento - 1))
    return tope / 2 + azar * tope / 2


def segundos_retry_after(error: BaseException, ahora: float) -> Optional[float]:
    """El plazo de `retry-after` (segundos o fecha HTTP) o None si no viene o no se puede leer."""
    encabezados = getattr(getattr(error, "response", None), "headers", None)
    obtener = getattr(encabezados, "get", None)
    if not callable(obtener):
        return None
    valor = obtener(ENCABEZADO_RETRY_AFTER)
    if not isinstance(valor, str):
        return None
    texto = valor.strip()
    if _FORMA_SEGUNDOS.fullmatch(texto):
        return float(texto)
    try:
        fecha = parsedate_to_datetime(texto)
    except (TypeError, ValueError, IndexError):
        return None
    return max(0.0, fecha.timestamp() - ahora)
