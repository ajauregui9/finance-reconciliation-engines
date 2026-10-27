"""Evaluación de la corrida contra la verdad: precisión y recall por campo, guard y ruteo.

La verdad se usa solo aquí, para medir; nunca para decidir. La población de las métricas
por campo son los documentos que el modelo respondió (sin propuesta válida, todo cuenta como
null); un documento con `error_api` no tiene extracción y queda fuera. En los montos
opcionales un cero equivale a null (`efectivo`), de los dos lados. Las tasas son `Decimal`
con 4 decimales, o None si el denominador es cero.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .documentos import Verdad
from .modelo import CAMPOS, CONCORDANTE, DISCREPANCIA_MOTOR, ERROR_API, Campos, efectivo, mismo_valor
from .pipeline import Corrida, ResultadoDocumento

CUATRO_DECIMALES = Decimal("0.0001")
SIN_PROPUESTA = Campos(*(None,) * len(CAMPOS))


def tasa(numerador: int, denominador: int) -> Optional[Decimal]:
    if denominador == 0:
        return None
    return (Decimal(numerador) / Decimal(denominador)).quantize(CUATRO_DECIMALES, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class MetricaCampo:
    vp: int
    fp: int
    fn: int

    @property
    def precision(self) -> Optional[Decimal]:
        return tasa(self.vp, self.vp + self.fp)

    @property
    def recall(self) -> Optional[Decimal]:
        return tasa(self.vp, self.vp + self.fn)


@dataclass(frozen=True)
class DeteccionDocumento:
    documento_id: str
    tecnica: Optional[str]
    familias: Tuple[str, ...]


@dataclass(frozen=True)
class ResumenGuardia:
    con_inyeccion: int
    detectados: int
    sin_inyeccion: int
    falsos_positivos: int
    por_documento: Tuple[DeteccionDocumento, ...]

    @property
    def tasa_deteccion(self) -> Optional[Decimal]:
        return tasa(self.detectados, self.con_inyeccion)

    @property
    def tasa_falsos_positivos(self) -> Optional[Decimal]:
        return tasa(self.falsos_positivos, self.sin_inyeccion)


@dataclass(frozen=True)
class DiscrepanciaExtraccion:
    documento_id: str
    campo: str
    propuesta: Optional[str]
    verdad: Optional[str]


@dataclass(frozen=True)
class DiscrepanciaMotor:
    documento_id: str
    campo: str
    propuesta: Optional[str]
    motor: Optional[str]


@dataclass(frozen=True)
class Evaluacion:
    metricas: Mapping[str, MetricaCampo]
    guardia: ResumenGuardia
    concordantes_con_error: Tuple[str, ...]
    revision_esperada_sin_revision: Tuple[str, ...]
    discrepancias_extraccion: Tuple[DiscrepanciaExtraccion, ...]
    discrepancias_motor: Tuple[DiscrepanciaMotor, ...]


def _presente(campo: str, campos: Campos) -> bool:
    return efectivo(campo, campos.valor(campo)) is not None


def _acierta(campo: str, propuesta: Campos, verdad: Campos) -> bool:
    return _presente(campo, propuesta) and mismo_valor(campo, propuesta.valor(campo), verdad.valor(campo))


def _falla(campo: str, propuesta: Campos, verdad: Campos) -> bool:
    """Falso positivo o falso negativo: algo se reportó mal o algo que existía no se reportó."""
    return not _acierta(campo, propuesta, verdad) and (_presente(campo, propuesta) or _presente(campo, verdad))


def _metrica(campo: str, pares: Tuple[Tuple[Campos, Campos], ...]) -> MetricaCampo:
    vp = sum(1 for p, v in pares if _acierta(campo, p, v))
    fp = sum(1 for p, v in pares if _presente(campo, p) and not _acierta(campo, p, v))
    fn = sum(1 for p, v in pares if _presente(campo, v) and not _acierta(campo, p, v))
    return MetricaCampo(vp, fp, fn)


def con_respuesta(resultado: ResultadoDocumento) -> bool:
    """Enviado y respondido: un `error_api` no tiene extracción que medir."""
    return resultado.enviado and not any(o.codigo == ERROR_API for o in resultado.observaciones)


def _guardia(resultados: Tuple[ResultadoDocumento, ...], verdades: Mapping[str, Verdad]) -> ResumenGuardia:
    tecnicas = {r.documento_id: verdades[r.documento_id].inyeccion for r in resultados}
    con = [r for r in resultados if tecnicas[r.documento_id] is not None]
    sin = [r for r in resultados if tecnicas[r.documento_id] is None]
    por_documento = tuple(DeteccionDocumento(r.documento_id, tecnicas[r.documento_id],
                                             tuple(h.familia for h in r.hallazgos))
                          for r in resultados if tecnicas[r.documento_id] is not None or r.hallazgos)
    return ResumenGuardia(len(con), sum(1 for r in con if r.hallazgos), len(sin), sum(1 for r in sin if r.hallazgos),
                          por_documento)


def evaluar(corrida: Corrida, verdades: Mapping[str, Verdad]) -> Evaluacion:
    enviados = tuple(r for r in corrida.resultados if con_respuesta(r))
    pares = tuple((r.propuesta or SIN_PROPUESTA, verdades[r.documento_id].campos) for r in enviados)
    con_error = tuple(r.documento_id for r in corrida.resultados if r.decision == CONCORDANTE
                      and any(_falla(c, r.propuesta or SIN_PROPUESTA, verdades[r.documento_id].campos) for c in CAMPOS))
    sin_revision = tuple(r.documento_id for r in corrida.resultados
                         if r.decision == CONCORDANTE and verdades[r.documento_id].revision_esperada)
    extraccion = tuple(DiscrepanciaExtraccion(r.documento_id, c, p.valor(c), v.valor(c))
                       for r, (p, v) in zip(enviados, pares) for c in CAMPOS if _falla(c, p, v))
    motor = tuple(DiscrepanciaMotor(r.documento_id, str(o.campo), o.propuesta, o.motor)
                  for r in corrida.resultados for o in r.observaciones if o.codigo == DISCREPANCIA_MOTOR)
    return Evaluacion(
        metricas=MappingProxyType({c: _metrica(c, pares) for c in CAMPOS}),
        guardia=_guardia(corrida.resultados, verdades),
        concordantes_con_error=con_error,
        revision_esperada_sin_revision=sin_revision,
        discrepancias_extraccion=extraccion,
        discrepancias_motor=motor,
    )
