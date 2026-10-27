"""Orquestación por documento: guard → modelo → esquema → reglas → cruce → decisión.

1. `prompt_guard` revisa el texto completo de cada documento. Un documento marcado no se
   envía al modelo y va a `revision_humana` (ver la spec: decisión del guard).
2. Antes de la primera llamada se verifica el tope de documentos.
3. Se llama al modelo en orden de id; después de cada respuesta se suma su uso y se
   verifica el tope de tokens. Si la API no responde un documento (`FallaApiDocumento`),
   ese documento va a `revision_humana` con `error_api` y el lote sigue.
4. La propuesta pasa por las reglas y por el cruce con el pool. Sin ninguna observación
   queda `concordante`; con cualquiera, `revision_humana`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Sequence, Tuple

from conciliacion.pipeline_guardia import HallazgoGuardia

from .config import Config
from .costo import Consumo, verificar_documentos, verificar_tokens
from .cruce import cruzar
from .documentos import Documento
from .errores import FallaApiDocumento
from .herramienta import interpretar, solicitud
from .modelo import BLOQUEADO_POR_GUARDIA, CONCORDANTE, ERROR_API, REVISION_HUMANA, Campos, Hallazgo, Observacion
from .modelo import Uso
from .pool import Pool
from .reglas import validar
from .respuesta import Extraida

Inspector = Callable[[str], Sequence[HallazgoGuardia]]

__all__ = ["Corrida", "Extractor", "Extraida", "Inspector", "ResultadoDocumento", "ejecutar"]


class Extractor(Protocol):
    def extraer(self, documento: Documento, solicitud: Mapping[str, Any]) -> Extraida: ...


@dataclass(frozen=True)
class ResultadoDocumento:
    documento_id: str
    formato: str
    hallazgos: Tuple[Hallazgo, ...]
    enviado: bool
    propuesta: Optional[Campos]
    observaciones: Tuple[Observacion, ...]
    uso: Optional[Uso]
    modelo_respuesta: Optional[str]
    origen_respuesta: Optional[str]
    decision: str


@dataclass(frozen=True)
class Corrida:
    resultados: Tuple[ResultadoDocumento, ...]
    consumo: Consumo

    @classmethod
    def vacia(cls) -> "Corrida":
        return cls((), Consumo())


def _bloqueado(documento: Documento, hallazgos: Tuple[Hallazgo, ...]) -> ResultadoDocumento:
    familias = ", ".join(h.familia for h in hallazgos)
    observacion = Observacion(BLOQUEADO_POR_GUARDIA, None, f"prompt_guard marcó: {familias}; no se envió al modelo")
    return ResultadoDocumento(documento.documento_id, documento.formato, hallazgos, False, None, (observacion,),
                              None, None, None, REVISION_HUMANA)


def _fallido(documento: Documento, falla: FallaApiDocumento) -> ResultadoDocumento:
    """Enviado sin respuesta: no hay propuesta ni uso, y una persona lo captura."""
    observacion = Observacion(ERROR_API, None, str(falla))
    return ResultadoDocumento(documento.documento_id, documento.formato, (), True, None, (observacion,), None, None,
                              None, REVISION_HUMANA)


def _decidido(documento: Documento, extraida: Extraida, pool: Pool, config: Config) -> ResultadoDocumento:
    propuesta, observaciones = interpretar(extraida.respuesta)
    if propuesta is not None:
        observaciones = validar(propuesta, config) + cruzar(propuesta, pool)
    decision = REVISION_HUMANA if observaciones else CONCORDANTE
    respuesta = extraida.respuesta
    return ResultadoDocumento(documento.documento_id, documento.formato, (), True, propuesta, observaciones,
                              respuesta.uso, respuesta.modelo, extraida.origen, decision)


def ejecutar(documentos: Sequence[Documento], pool: Pool, extractor: Extractor, inspector: Inspector,
             config: Config) -> Corrida:
    ordenados = sorted(documentos, key=lambda d: d.documento_id)
    hallazgos = {d.documento_id: tuple(Hallazgo(h.familia, h.fragmento) for h in inspector(d.texto))
                 for d in ordenados}
    a_enviar = [d for d in ordenados if not hallazgos[d.documento_id]]
    verificar_documentos(len(a_enviar), config.limites)
    resultados: Dict[str, ResultadoDocumento] = {d.documento_id: _bloqueado(d, hallazgos[d.documento_id])
                                                 for d in ordenados if hallazgos[d.documento_id]}
    consumo = Consumo()
    for documento in a_enviar:
        try:
            extraida = extractor.extraer(documento, solicitud(documento, config))
        except FallaApiDocumento as falla:
            resultados[documento.documento_id] = _fallido(documento, falla)
            continue
        consumo = consumo.sumar(documento.documento_id, extraida.respuesta.uso)
        verificar_tokens(consumo, config.limites)
        resultados[documento.documento_id] = _decidido(documento, extraida, pool, config)
    return Corrida(tuple(resultados[d.documento_id] for d in ordenados), consumo)
