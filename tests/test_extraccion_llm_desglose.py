"""Subtotal e IVA se cruzan contra el CFDI conocido: un desglose alterado con la misma suma se detecta.

La regla `no_cuadra` solo ve la suma; el cruce con el pool ve cada monto. El fixture
grabado `iva_sobre_total` es un modelo que aplica la tasa al total y deduce el subtotal:
la suma queda igual al total impreso y, aun así, el documento va a revisión.
"""
from __future__ import annotations

import dataclasses
import json
from decimal import Decimal
from typing import Any, Dict, Set, Tuple

import pytest

from conciliacion.pipeline_guardia import cargar_inspector
from extraccion_llm.config import Config, cargar_config
from extraccion_llm.cruce import cruzar
from extraccion_llm.documentos import Verdad, cargar_documentos, cargar_verdad
from extraccion_llm.grabadas import ExtractorGrabado, cargar_grabadas
from extraccion_llm.modelo import REVISION_HUMANA, Campos, Observacion, monto_estricto, texto_monto
from extraccion_llm.pipeline import Corrida, ResultadoDocumento, ejecutar
from extraccion_llm.pool import Pool, cargar_pool
from extraccion_llm.reglas import validar
from extraccion_llm.rutas import CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO

UUID_A = "00000000-0000-0000-0000-000000000007"
TRASPASO = Decimal("10.00")
ERRORES = json.loads((DATOS_POR_DEFECTO / "errores_plantados.json").read_text(encoding="utf-8"))["errores"]


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config(CONFIG_POR_DEFECTO)


@pytest.fixture(scope="module")
def pool(config: Config) -> Pool:
    return cargar_pool(DATOS_POR_DEFECTO / "cfdis_conocidos", config.rfc_empresa)


@pytest.fixture(scope="module")
def verdades() -> Dict[str, Verdad]:
    return {v.documento_id: v for v in cargar_verdad(DATOS_POR_DEFECTO / "verdad.jsonl")}


@pytest.fixture(scope="module")
def corrida(pool: Pool, config: Config) -> Corrida:
    extractor = ExtractorGrabado(cargar_grabadas(DATOS_POR_DEFECTO / "respuestas_grabadas"))
    documentos = cargar_documentos(DATOS_POR_DEFECTO / "documentos")
    return ejecutar(documentos, pool, extractor, cargar_inspector(), config)


def _monto(texto: Any) -> Decimal:
    monto = monto_estricto(texto)
    assert monto is not None, texto
    return monto


def _compensado(campos: Campos) -> Campos:
    """Mueve un traslado fijo del IVA al subtotal: la suma no cambia."""
    return dataclasses.replace(campos, subtotal=texto_monto(_monto(campos.subtotal) + TRASPASO),
                               iva=texto_monto(_monto(campos.iva) - TRASPASO))


def _codigos(observaciones: Tuple[Observacion, ...]) -> Tuple[Tuple[str, Any], ...]:
    return tuple((o.codigo, o.campo) for o in observaciones)


def _error_iva_sobre_total() -> Dict[str, Any]:
    (error,) = [e for e in ERRORES if e["tipo"] == "iva_sobre_total"]
    return dict(error)


def _resultado(corrida: Corrida, documento_id: str) -> ResultadoDocumento:
    (resultado,) = [r for r in corrida.resultados if r.documento_id == documento_id]
    return resultado


# ----------------------------------------------------------------- pool

def test_el_pool_trae_subtotal_e_iva_del_lector_del_motor(pool: Pool, verdades: Dict[str, Verdad]) -> None:
    comparados = 0
    for verdad in verdades.values():
        motor = pool.cfdis.get(str(verdad.campos.uuid).upper())
        if motor is None:
            continue
        comparados += 1
        assert _monto(motor.subtotal) == _monto(verdad.campos.subtotal), verdad.documento_id
        if "iva_no_cuadra" not in verdad.casos_borde:
            assert _monto(motor.iva) == _monto(verdad.campos.iva), verdad.documento_id
    assert comparados == len(pool.cfdis) == 39


def test_el_pool_usa_el_iva_impreso_en_el_xml_y_no_el_recalculado(pool: Pool,
                                                                  verdades: Dict[str, Verdad]) -> None:
    (verdad,) = [v for v in verdades.values() if "iva_no_cuadra" in v.casos_borde]
    motor = pool.cfdis[str(verdad.campos.uuid).upper()]
    assert _monto(motor.subtotal) + _monto(motor.iva) == _monto(motor.total)
    assert _monto(motor.iva) - _monto(verdad.campos.iva) == Decimal("1.00")


# ----------------------------------------------------------------- reglas y cruce

def test_las_reglas_solas_no_ven_un_desglose_compensado(pool: Pool, config: Config) -> None:
    assert validar(_compensado(pool.cfdis[UUID_A]), config) == ()


def test_el_cruce_detecta_subtotal_e_iva_compensados(pool: Pool) -> None:
    motor = pool.cfdis[UUID_A]
    propuesta = _compensado(motor)
    observaciones = cruzar(propuesta, pool)
    assert _codigos(observaciones) == (("discrepancia_motor", "subtotal"), ("discrepancia_motor", "iva"))
    subtotal, iva = observaciones
    assert (subtotal.propuesta, subtotal.motor) == (propuesta.subtotal, motor.subtotal)
    assert (iva.propuesta, iva.motor) == (propuesta.iva, motor.iva)


def test_el_cruce_compara_subtotal_e_iva_como_decimal(pool: Pool) -> None:
    motor = pool.cfdis[UUID_A]
    sin_ceros = dataclasses.replace(motor, subtotal=str(_monto(motor.subtotal).normalize()),
                                    iva=str(_monto(motor.iva).normalize()))
    assert cruzar(sin_ceros, pool) == ()


@pytest.mark.parametrize("campo", ["subtotal", "iva"])
def test_subtotal_o_iva_omitido_tambien_discrepa_con_el_motor(pool: Pool, campo: str) -> None:
    propuesta = dataclasses.replace(pool.cfdis[UUID_A], **{campo: None})
    assert _codigos(cruzar(propuesta, pool)) == (("discrepancia_motor", campo),)


# ----------------------------------------------------------------- fixture grabado

def test_el_fixture_grabado_cambia_subtotal_e_iva_y_conserva_la_suma(verdades: Dict[str, Verdad]) -> None:
    error = _error_iva_sobre_total()
    assert error["campos"] == ["iva", "subtotal"] and not error["contrafactual"]
    grabada = cargar_grabadas(DATOS_POR_DEFECTO / "respuestas_grabadas")[error["documento_id"]]
    (bloque,) = grabada.respuesta.bloques
    assert bloque.tipo == "tool_use" and bloque.entrada_json is not None
    propuesta: Dict[str, Any] = json.loads(bloque.entrada_json)
    verdad = verdades[error["documento_id"]].campos
    assert _monto(propuesta["subtotal"]) + _monto(propuesta["iva"]) == _monto(verdad.total)
    assert _monto(propuesta["subtotal"]) != _monto(verdad.subtotal)
    assert _monto(propuesta["iva"]) != _monto(verdad.iva)
    assert not verdades[error["documento_id"]].revision_esperada


def test_el_fixture_grabado_compensado_ahora_va_a_revision(corrida: Corrida) -> None:
    resultado = _resultado(corrida, _error_iva_sobre_total()["documento_id"])
    assert resultado.enviado and not resultado.hallazgos
    assert resultado.decision == REVISION_HUMANA
    codigos: Set[Tuple[str, Any]] = set(_codigos(resultado.observaciones))
    assert codigos == {("discrepancia_motor", "subtotal"), ("discrepancia_motor", "iva")}
