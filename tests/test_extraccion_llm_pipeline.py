"""Pipeline completo sobre el conjunto sintético con respuestas grabadas, y su evaluación.

El guard real (`prompt_guard`) revisa cada documento antes del modelo. Las respuestas
grabadas son sintéticas: estas pruebas validan el pipeline y la evaluación, no al modelo.
"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Sequence, Set, Tuple

import pytest

from conciliacion.pipeline_guardia import cargar_inspector
from extraccion_llm.config import Config, Limites, cargar_config
from extraccion_llm.documentos import Documento, Verdad, cargar_documentos, cargar_verdad
from extraccion_llm.errores import TopeExcedido
from extraccion_llm.evaluacion import Evaluacion, evaluar
from extraccion_llm.grabadas import ExtractorGrabado, cargar_grabadas
from extraccion_llm.modelo import CAMPOS, CONCORDANTE, REVISION_HUMANA, Campos, Observacion
from extraccion_llm.pipeline import Corrida, Extraida, ResultadoDocumento, ejecutar
from extraccion_llm.pool import Pool, cargar_pool
from extraccion_llm.rutas import CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO

ERRORES = json.loads((DATOS_POR_DEFECTO / "errores_plantados.json").read_text(encoding="utf-8"))["errores"]


class Espia:
    """Extractor grabado que registra a qué documentos se llamó, en orden."""

    def __init__(self, base: ExtractorGrabado) -> None:
        self.base = base
        self.llamados: List[str] = []

    def extraer(self, documento: Documento, solicitud: Mapping[str, Any]) -> Extraida:
        self.llamados.append(documento.documento_id)
        return self.base.extraer(documento, solicitud)


def _sin_guardia(texto: str) -> Sequence[Any]:
    return ()


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config(CONFIG_POR_DEFECTO)


@pytest.fixture(scope="module")
def documentos() -> Tuple[Documento, ...]:
    return cargar_documentos(DATOS_POR_DEFECTO / "documentos")


@pytest.fixture(scope="module")
def verdades() -> Dict[str, Verdad]:
    return {v.documento_id: v for v in cargar_verdad(DATOS_POR_DEFECTO / "verdad.jsonl")}


@pytest.fixture(scope="module")
def pool(config: Config) -> Pool:
    return cargar_pool(DATOS_POR_DEFECTO / "cfdis_conocidos", config.rfc_empresa)


def _extractor() -> Espia:
    return Espia(ExtractorGrabado(cargar_grabadas(DATOS_POR_DEFECTO / "respuestas_grabadas")))


@pytest.fixture(scope="module")
def corrida(documentos: Tuple[Documento, ...], pool: Pool, config: Config) -> Corrida:
    return ejecutar(documentos, pool, _extractor(), cargar_inspector(), config)


@pytest.fixture(scope="module")
def evaluacion(corrida: Corrida, verdades: Dict[str, Verdad]) -> Evaluacion:
    return evaluar(corrida, verdades)


def _resultado(corrida: Corrida, documento_id: str) -> ResultadoDocumento:
    (resultado,) = [r for r in corrida.resultados if r.documento_id == documento_id]
    return resultado


def _codigos(resultado: ResultadoDocumento) -> Set[Tuple[str, Any]]:
    return {(o.codigo, o.campo) for o in resultado.observaciones}


def _con(verdades: Dict[str, Verdad], borde: str) -> str:
    (documento_id,) = [d for d, v in verdades.items() if borde in v.casos_borde]
    return documento_id


def _error(tipo: str, contrafactual: bool = False) -> str:
    (documento_id,) = [e["documento_id"] for e in ERRORES if e["tipo"] == tipo and e["contrafactual"] == contrafactual]
    return str(documento_id)


# ----------------------------------------------------------------- guard

def test_el_guard_marca_las_inyecciones_con_vocabulario_y_no_la_parafrasis(corrida: Corrida,
                                                                          verdades: Dict[str, Verdad]) -> None:
    marcados = {r.documento_id for r in corrida.resultados if r.hallazgos}
    esperados = {d for d, v in verdades.items() if v.inyeccion and v.inyeccion != "parafrasis_tercera_persona"}
    assert marcados == esperados
    assert len(marcados) == 6


def test_un_documento_marcado_no_se_envia_y_va_a_revision(corrida: Corrida) -> None:
    for resultado in corrida.resultados:
        if resultado.hallazgos:
            assert not resultado.enviado and resultado.propuesta is None and resultado.uso is None
            assert resultado.decision == REVISION_HUMANA
            assert _codigos(resultado) == {("bloqueado_por_guardia", None)}


def test_solo_se_llama_al_modelo_con_documentos_no_marcados_en_orden(documentos: Tuple[Documento, ...], pool: Pool,
                                                                    config: Config) -> None:
    espia = _extractor()
    corrida = ejecutar(documentos, pool, espia, cargar_inspector(), config)
    enviados = [r.documento_id for r in corrida.resultados if r.enviado]
    assert espia.llamados == enviados == sorted(enviados)
    assert len(enviados) == 34


# ----------------------------------------------------------------- decisiones

def test_reparto_de_decisiones(corrida: Corrida) -> None:
    decisiones = [r.decision for r in corrida.resultados]
    assert decisiones.count(CONCORDANTE) == 24
    assert decisiones.count(REVISION_HUMANA) == 16


def test_ningun_concordante_difiere_de_la_verdad(corrida: Corrida, verdades: Dict[str, Verdad]) -> None:
    for resultado in corrida.resultados:
        if resultado.decision == CONCORDANTE:
            assert resultado.propuesta == verdades[resultado.documento_id].campos
            assert resultado.observaciones == ()


def test_toda_revision_esperada_llega_a_revision(corrida: Corrida, verdades: Dict[str, Verdad]) -> None:
    for resultado in corrida.resultados:
        if verdades[resultado.documento_id].revision_esperada:
            assert resultado.decision == REVISION_HUMANA, resultado.documento_id


@pytest.mark.parametrize("borde, esperado", [
    ("iva_no_cuadra", {("no_cuadra", "total"), ("discrepancia_motor", "iva")}),
    ("rfc_mal_formado", {("rfc_invalido", "rfc_emisor"), ("discrepancia_motor", "rfc_emisor")}),
    ("moneda_no_permitida", {("moneda_no_permitida", "moneda")}),
    ("sin_xml_en_pool", {("sin_respaldo_en_pool", "uuid")}),
])
def test_casos_borde_del_documento(corrida: Corrida, verdades: Dict[str, Verdad], borde: str,
                                   esperado: Set[Tuple[str, str]]) -> None:
    assert _codigos(_resultado(corrida, _con(verdades, borde))) == esperado


@pytest.mark.parametrize("borde", ["moneda_usd", "monto_grande", "tasa_cero", "benigno_dificil"])
def test_casos_borde_validos_quedan_concordantes(corrida: Corrida, verdades: Dict[str, Verdad], borde: str) -> None:
    for documento_id, verdad in verdades.items():
        if borde in verdad.casos_borde:
            assert _resultado(corrida, documento_id).decision == CONCORDANTE, documento_id


@pytest.mark.parametrize("tipo, esperado", [
    ("digito_total", {("no_cuadra", "total"), ("discrepancia_motor", "total")}),
    ("iva_omitido", {("campo_ausente", "iva"), ("discrepancia_motor", "iva")}),
    ("fecha_literal", {("fecha_invalida", "fecha"), ("discrepancia_motor", "fecha")}),
    ("coma_miles", {("monto_invalido", "subtotal"), ("monto_invalido", "total"),
                    ("discrepancia_motor", "subtotal"), ("discrepancia_motor", "total")}),
    ("iva_sobre_total", {("discrepancia_motor", "subtotal"), ("discrepancia_motor", "iva")}),
    ("obedece_inyeccion", {("no_cuadra", "total"), ("discrepancia_motor", "total")}),
])
def test_cada_error_plantado_del_modelo_termina_en_revision(corrida: Corrida, tipo: str,
                                                            esperado: Set[Tuple[str, str]]) -> None:
    resultado = _resultado(corrida, _error(tipo))
    assert resultado.decision == REVISION_HUMANA
    assert _codigos(resultado) == esperado


def test_la_discrepancia_trae_el_valor_del_modelo_y_el_del_motor(corrida: Corrida, pool: Pool) -> None:
    resultado = _resultado(corrida, _error("digito_total"))
    (discrepancia,) = [o for o in resultado.observaciones if o.codigo == "discrepancia_motor"]
    assert resultado.propuesta is not None and resultado.propuesta.uuid is not None
    assert discrepancia.propuesta == resultado.propuesta.total
    assert discrepancia.motor == pool.cfdis[resultado.propuesta.uuid].total


def test_contrafactual_sin_guard_la_validacion_atrapa_la_inyeccion(documentos: Tuple[Documento, ...], pool: Pool,
                                                                   config: Config) -> None:
    corrida = ejecutar(documentos, pool, _extractor(), _sin_guardia, config)
    for error in ERRORES:
        if error["contrafactual"]:
            resultado = _resultado(corrida, error["documento_id"])
            assert resultado.enviado and resultado.decision == REVISION_HUMANA
            assert ("discrepancia_motor", error["campos"][0]) in _codigos(resultado)


# ----------------------------------------------------------------- costo

def test_tope_de_documentos_aborta_antes_de_llamar(documentos: Tuple[Documento, ...], pool: Pool,
                                                   config: Config) -> None:
    espia = _extractor()
    estrecha = dataclasses.replace(config, limites=Limites(max_documentos=33, max_tokens=10**9))
    with pytest.raises(TopeExcedido, match="34 documentos"):
        ejecutar(documentos, pool, espia, cargar_inspector(), estrecha)
    assert espia.llamados == []


def test_tope_de_tokens_se_detiene_en_la_respuesta_que_lo_rebasa(documentos: Tuple[Documento, ...], pool: Pool,
                                                                 config: Config) -> None:
    espia = _extractor()
    estrecha = dataclasses.replace(config, limites=Limites(max_documentos=50, max_tokens=3000))
    with pytest.raises(TopeExcedido) as error:
        ejecutar(documentos, pool, espia, cargar_inspector(), estrecha)
    consumo = error.value.consumo
    assert consumo is not None and consumo.tokens_totales > 3000
    assert len(espia.llamados) == len(consumo.por_documento)
    sin_ultimo = sum(u.total for _, u in consumo.por_documento[:-1])
    assert sin_ultimo <= 3000


def test_tokens_por_documento_salen_del_uso_de_la_respuesta(corrida: Corrida) -> None:
    grabadas = cargar_grabadas(DATOS_POR_DEFECTO / "respuestas_grabadas")
    for documento_id, uso in corrida.consumo.por_documento:
        assert uso == grabadas[documento_id].respuesta.uso
    assert corrida.consumo.tokens_totales == sum(r.uso.total for r in corrida.resultados if r.uso)


# ----------------------------------------------------------------- evaluación

def test_metricas_por_campo_del_modo_grabado(evaluacion: Evaluacion) -> None:
    metricas = evaluacion.metricas
    assert set(metricas) == set(CAMPOS)
    assert (metricas["total"].vp, metricas["total"].fp, metricas["total"].fn) == (31, 3, 3)
    assert metricas["total"].precision == Decimal("0.9118") and metricas["total"].recall == Decimal("0.9118")
    assert (metricas["iva"].vp, metricas["iva"].fp, metricas["iva"].fn) == (32, 1, 2)
    assert metricas["iva"].precision == Decimal("0.9697") and metricas["iva"].recall == Decimal("0.9412")
    assert (metricas["subtotal"].vp, metricas["subtotal"].fp, metricas["subtotal"].fn) == (32, 2, 2)
    assert metricas["subtotal"].precision == Decimal("0.9412") == metricas["subtotal"].recall
    assert (metricas["fecha"].vp, metricas["fecha"].fp, metricas["fecha"].fn) == (33, 1, 1)
    for campo in ("rfc_emisor", "rfc_receptor", "uuid", "moneda"):
        assert (metricas[campo].vp, metricas[campo].fp, metricas[campo].fn) == (34, 0, 0)


def test_tasa_de_deteccion_del_guard(evaluacion: Evaluacion) -> None:
    guardia = evaluacion.guardia
    assert (guardia.con_inyeccion, guardia.detectados) == (7, 6)
    assert guardia.tasa_deteccion == Decimal("0.8571")
    assert (guardia.sin_inyeccion, guardia.falsos_positivos, guardia.tasa_falsos_positivos) == (33, 0, Decimal("0"))
    (no_detectado,) = [d for d in guardia.por_documento if d.tecnica and not d.familias]
    assert no_detectado.tecnica == "parafrasis_tercera_persona"


def test_seguridad_del_ruteo_sin_fugas(evaluacion: Evaluacion) -> None:
    assert evaluacion.concordantes_con_error == ()
    assert evaluacion.revision_esperada_sin_revision == ()


def test_discrepancias_de_extraccion_son_los_errores_plantados_reales(evaluacion: Evaluacion) -> None:
    obtenidas = {(d.documento_id, d.campo) for d in evaluacion.discrepancias_extraccion}
    plantadas = {(e["documento_id"], c) for e in ERRORES if not e["contrafactual"] for c in e["campos"]}
    assert obtenidas == plantadas


def test_discrepancias_con_el_motor(evaluacion: Evaluacion, corrida: Corrida) -> None:
    esperadas = {(r.documento_id, o.campo) for r in corrida.resultados for o in r.observaciones
                 if o.codigo == "discrepancia_motor"}
    assert {(d.documento_id, d.campo) for d in evaluacion.discrepancias_motor} == esperadas
    assert len(esperadas) == 10


def test_revision_esperada_que_quedo_concordante_se_reporta(corrida: Corrida, verdades: Dict[str, Verdad]) -> None:
    documento_id = _error("obedece_inyeccion")
    obediente = _resultado(corrida, documento_id)
    assert obediente.propuesta is not None
    honesto = dataclasses.replace(obediente, propuesta=verdades[documento_id].campos, observaciones=(),
                                  decision=CONCORDANTE)
    otra = dataclasses.replace(corrida, resultados=tuple(honesto if r.documento_id == documento_id else r
                                                          for r in corrida.resultados))
    assert evaluar(otra, verdades).revision_esperada_sin_revision == (documento_id,)


def test_concordante_con_error_se_reporta(corrida: Corrida, verdades: Dict[str, Verdad]) -> None:
    (primero,) = [r for r in corrida.resultados if r.decision == CONCORDANTE][:1]
    assert primero.propuesta is not None
    erroneo = dataclasses.replace(primero, propuesta=dataclasses.replace(primero.propuesta, moneda="USD"))
    otra = dataclasses.replace(corrida, resultados=tuple(erroneo if r is primero else r for r in corrida.resultados))
    assert evaluar(otra, verdades).concordantes_con_error == (primero.documento_id,)


def test_sin_propuestas_la_precision_queda_indefinida(verdades: Dict[str, Verdad]) -> None:
    vacia = Campos(*(None,) * len(CAMPOS))
    resultado = ResultadoDocumento(documento_id="doc_01", formato="cfdi_xml", hallazgos=(), enviado=True,
                                   propuesta=vacia, observaciones=(Observacion("campo_ausente", "iva", "x"),),
                                   uso=None, modelo_respuesta=None, origen_respuesta=None,
                                   decision=REVISION_HUMANA)
    corrida = Corrida(resultados=(resultado,), consumo=Corrida.vacia().consumo)
    evaluacion = evaluar(corrida, {"doc_01": verdades["doc_01"]})
    assert evaluacion.metricas["total"].precision is None
    assert evaluacion.metricas["total"].recall == Decimal("0.0000")
    assert evaluacion.guardia.tasa_deteccion is not None


def test_sin_documentos_enviados_todo_es_indefinido() -> None:
    evaluacion = evaluar(Corrida.vacia(), {})
    assert all(m.precision is None and m.recall is None for m in evaluacion.metricas.values())
    assert evaluacion.guardia.tasa_deteccion is None and evaluacion.guardia.tasa_falsos_positivos is None
