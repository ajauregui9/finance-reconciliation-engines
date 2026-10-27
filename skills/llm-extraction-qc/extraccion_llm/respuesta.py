"""Frontera con el SDK de Anthropic: Protocols propios y la forma interna de una respuesta.

El código no depende de los stubs del SDK: se tipa contra `ClienteSdk` (lo único que se usa
es `messages.create(**kwargs)`) y la respuesta se lee por atributos (`content`, `usage`,
`stop_reason`, `model`). Tanto la respuesta del SDK como la grabada en JSON pasan por la
misma validación (`respuesta_desde_dict`): una forma inesperada es `InsumoInvalido`, porque
sin `usage` no se puede llevar el costo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Protocol, Sequence, Tuple

from .errores import InsumoInvalido
from .modelo import Uso

TIPO_HERRAMIENTA = "tool_use"
TIPO_TEXTO = "text"


class UsoSdk(Protocol):
    @property
    def input_tokens(self) -> int: ...

    @property
    def output_tokens(self) -> int: ...


class RespuestaSdk(Protocol):
    @property
    def content(self) -> Sequence[object]: ...

    @property
    def usage(self) -> UsoSdk: ...

    @property
    def stop_reason(self) -> Optional[str]: ...

    @property
    def model(self) -> str: ...


class MensajesSdk(Protocol):
    def create(self, **kwargs: Any) -> RespuestaSdk: ...


class ClienteSdk(Protocol):
    @property
    def messages(self) -> MensajesSdk: ...


@dataclass(frozen=True)
class Bloque:
    """Un bloque de contenido. La entrada de `tool_use` se guarda como JSON canónico (inmutable)."""

    tipo: str
    nombre: Optional[str] = None
    entrada_json: Optional[str] = None
    texto: Optional[str] = None

    def entrada(self) -> Any:
        return None if self.entrada_json is None else json.loads(self.entrada_json)


@dataclass(frozen=True)
class RespuestaModelo:
    modelo: str
    stop_reason: Optional[str]
    uso: Uso
    bloques: Tuple[Bloque, ...]


@dataclass(frozen=True)
class Extraida:
    """Lo que devuelve un extractor: la respuesta y su origen (`sintetico` o `vivo`)."""

    respuesta: RespuestaModelo
    origen: str


def _tokens(uso: Any, llave: str, contexto: str) -> int:
    valor = uso.get(llave) if isinstance(uso, dict) else None
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 0:
        raise InsumoInvalido(f"{contexto}: usage.{llave} debe ser un entero no negativo; llegó {valor!r}")
    return valor


def _canonico(valor: Any, contexto: str) -> str:
    try:
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise InsumoInvalido(f"{contexto}: la entrada de tool_use no es JSON ({exc})") from None


def _bloque(datos: Any, contexto: str) -> Bloque:
    tipo = datos.get("type") if isinstance(datos, dict) else None
    if not isinstance(tipo, str) or not tipo:
        raise InsumoInvalido(f"{contexto}: bloque de content sin type")
    if tipo == TIPO_HERRAMIENTA:
        nombre = datos.get("name")
        if not isinstance(nombre, str) or "input" not in datos:
            raise InsumoInvalido(f"{contexto}: bloque tool_use sin name o sin input")
        return Bloque(tipo, nombre=nombre, entrada_json=_canonico(datos["input"], contexto))
    if tipo == TIPO_TEXTO:
        texto = datos.get("text")
        if not isinstance(texto, str):
            raise InsumoInvalido(f"{contexto}: bloque text sin text")
        return Bloque(tipo, texto=texto)
    return Bloque(tipo)


def respuesta_desde_dict(datos: Any, contexto: str = "respuesta") -> RespuestaModelo:
    if not isinstance(datos, dict):
        raise InsumoInvalido(f"{contexto}: se esperaba un objeto JSON")
    modelo, motivo, contenido = datos.get("model"), datos.get("stop_reason"), datos.get("content")
    if not isinstance(modelo, str) or not modelo:
        raise InsumoInvalido(f"{contexto}: model debe ser texto no vacío")
    if motivo is not None and not isinstance(motivo, str):
        raise InsumoInvalido(f"{contexto}: stop_reason debe ser texto o null")
    if "usage" not in datos or not isinstance(datos["usage"], dict):
        raise InsumoInvalido(f"{contexto}: falta usage (sin uso no se puede llevar el costo)")
    uso = Uso(_tokens(datos["usage"], "input_tokens", contexto), _tokens(datos["usage"], "output_tokens", contexto))
    if not isinstance(contenido, list):
        raise InsumoInvalido(f"{contexto}: content debe ser una lista")
    return RespuestaModelo(modelo, motivo, uso, tuple(_bloque(b, contexto) for b in contenido))


def _bloque_sdk(bloque: object) -> Dict[str, Any]:
    tipo = getattr(bloque, "type", None)
    datos: Dict[str, Any] = {"type": tipo}
    if tipo == TIPO_HERRAMIENTA:
        datos.update(name=getattr(bloque, "name", None), input=getattr(bloque, "input", None))
    elif tipo == TIPO_TEXTO:
        datos["text"] = getattr(bloque, "text", None)
    return datos


def respuesta_desde_sdk(respuesta: RespuestaSdk) -> RespuestaModelo:
    """Traduce el objeto del SDK por atributos y lo valida igual que una respuesta grabada."""
    uso = getattr(respuesta, "usage", None)
    contenido = getattr(respuesta, "content", None)
    datos: Dict[str, Any] = {
        "model": getattr(respuesta, "model", None),
        "stop_reason": getattr(respuesta, "stop_reason", None),
        "content": [_bloque_sdk(b) for b in contenido] if isinstance(contenido, (list, tuple)) else contenido,
    }
    if uso is not None:
        datos["usage"] = {"input_tokens": getattr(uso, "input_tokens", None),
                          "output_tokens": getattr(uso, "output_tokens", None)}
    return respuesta_desde_dict(datos, "respuesta de la API")


def _bloque_a_dict(bloque: Bloque) -> Dict[str, Any]:
    if bloque.tipo == TIPO_HERRAMIENTA:
        return {"type": bloque.tipo, "name": bloque.nombre, "input": bloque.entrada()}
    if bloque.tipo == TIPO_TEXTO:
        return {"type": bloque.tipo, "text": bloque.texto}
    return {"type": bloque.tipo}


def respuesta_a_dict(respuesta: RespuestaModelo) -> Dict[str, Any]:
    contenido: List[Dict[str, Any]] = [_bloque_a_dict(b) for b in respuesta.bloques]
    return {"model": respuesta.modelo, "stop_reason": respuesta.stop_reason,
            "usage": {"input_tokens": respuesta.uso.tokens_entrada, "output_tokens": respuesta.uso.tokens_salida},
            "content": contenido}
