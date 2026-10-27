"""Caminos de error y bordes del demo de extracción con LLM que no ejercita la corrida completa."""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

import pytest

from extraccion_llm.config import Config, cargar_config
from extraccion_llm.documentos import cargar_verdad, documento_desde_texto, huella_archivo
from extraccion_llm.errores import InsumoInvalido
from extraccion_llm.evaluacion import evaluar
from extraccion_llm.grabadas import grabada_desde_dict
from extraccion_llm.modelo import REVISION_HUMANA, Campos, Uso
from extraccion_llm.pipeline import Corrida, Extraida, ejecutar
from extraccion_llm.pool import cargar_pool
from extraccion_llm.reporte import (
    ADVERTENCIA_REGRABADA,
    ADVERTENCIA_SIN_ENVIOS,
    ADVERTENCIA_SINTETICA,
    ADVERTENCIA_VIVO,
    advertencia,
    armar_reporte,
    celda,
    texto_markdown,
)
from extraccion_llm.respuesta import Bloque, RespuestaModelo, respuesta_a_dict, respuesta_desde_dict
from extraccion_llm.respuesta import respuesta_desde_sdk
from extraccion_llm.rutas import CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO
from extraccion_llm.vivo import crear_cliente_sdk

POOL = DATOS_POR_DEFECTO / "cfdis_conocidos"


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config(CONFIG_POR_DEFECTO)


# ----------------------------------------------------------------- documentos y verdad

def test_documento_con_formato_o_id_invalido() -> None:
    with pytest.raises(InsumoInvalido, match="formato desconocido"):
        documento_desde_texto("d1", "pdf", "x")
    with pytest.raises(InsumoInvalido, match="id de documento"):
        documento_desde_texto("../fuera", "cfdi_xml", "x")


def test_verdad_con_id_invalido_o_no_utf8(tmp_path: Path) -> None:
    ruta = tmp_path / "verdad.jsonl"
    linea = ('{"documento_id": "a/b", "campos": {}, "inyeccion": null, "casos_borde": [], '
             '"revision_esperada": false}')
    ruta.write_text(linea, encoding="utf-8")
    with pytest.raises(InsumoInvalido, match="documento_id inválido"):
        cargar_verdad(ruta)
    ruta.write_bytes(b"\xff\xfe")
    with pytest.raises(InsumoInvalido, match="UTF-8"):
        cargar_verdad(ruta)


def test_verdad_sin_salto_final_se_lee_completa(tmp_path: Path) -> None:
    original = (DATOS_POR_DEFECTO / "verdad.jsonl").read_text(encoding="utf-8")
    ruta = tmp_path / "verdad.jsonl"
    ruta.write_text(original.rstrip("\n"), encoding="utf-8")
    assert len(cargar_verdad(ruta)) == 40


def test_huella_de_archivo_inexistente(tmp_path: Path) -> None:
    with pytest.raises(InsumoInvalido, match="no se puede leer"):
        huella_archivo(tmp_path / "nada")


def test_campo_desconocido() -> None:
    with pytest.raises(KeyError, match="desconocido"):
        Campos(*(None,) * 8).valor("estado")


# ----------------------------------------------------------------- respuestas

def _cruda(**cambios: Any) -> Mapping[str, Any]:
    base = {"model": "m", "stop_reason": "tool_use", "usage": {"input_tokens": 1, "output_tokens": 1}, "content": []}
    base.update(cambios)
    return base


def test_stop_reason_que_no_es_texto() -> None:
    with pytest.raises(InsumoInvalido, match="stop_reason"):
        respuesta_desde_dict(_cruda(stop_reason=3))


def test_entrada_de_herramienta_que_no_es_json() -> None:
    bloque = SimpleNamespace(type="tool_use", name="registrar_cfdi", input={"total": object()})
    falsa = SimpleNamespace(content=[bloque], usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                            stop_reason="tool_use", model="m")
    with pytest.raises(InsumoInvalido, match="no es JSON"):
        respuesta_desde_sdk(falsa)  # type: ignore[arg-type]


def test_respuesta_del_sdk_con_texto_y_bloques_desconocidos() -> None:
    bloques = [SimpleNamespace(type="text", text="hola"), SimpleNamespace(type="thinking")]
    falsa = SimpleNamespace(content=bloques, usage=SimpleNamespace(input_tokens=2, output_tokens=3),
                            stop_reason="end_turn", model="m")
    respuesta = respuesta_desde_sdk(falsa)  # type: ignore[arg-type]
    assert respuesta.bloques == (Bloque("text", texto="hola"), Bloque("thinking"))
    assert respuesta_a_dict(respuesta)["content"] == [{"type": "text", "text": "hola"}, {"type": "thinking"}]


def test_respuesta_del_sdk_sin_lista_de_contenido() -> None:
    falsa = SimpleNamespace(content=None, usage=SimpleNamespace(input_tokens=1, output_tokens=1),
                            stop_reason="end_turn", model="m")
    with pytest.raises(InsumoInvalido, match="content"):
        respuesta_desde_sdk(falsa)  # type: ignore[arg-type]


def test_grabada_que_no_es_objeto() -> None:
    with pytest.raises(InsumoInvalido, match="objeto"):
        grabada_desde_dict([], "doc_01")


# ----------------------------------------------------------------- modo vivo

def test_sdk_sin_clase_anthropic() -> None:
    with pytest.raises(InsumoInvalido, match="no ofrece Anthropic"):
        crear_cliente_sdk(lambda nombre: SimpleNamespace())


def test_cliente_que_no_se_puede_crear() -> None:
    def falla() -> Any:
        raise RuntimeError("sin red")

    with pytest.raises(InsumoInvalido, match="no se pudo crear el cliente.*sin red"):
        crear_cliente_sdk(lambda nombre: SimpleNamespace(Anthropic=falla))


# ----------------------------------------------------------------- pool

def test_pool_copiado_da_la_misma_huella(tmp_path: Path) -> None:
    copia = tmp_path / "pool"
    shutil.copytree(POOL, copia)
    assert cargar_pool(copia, "RFC_EMPRESA_DEMO").sha256 == cargar_pool(POOL, "RFC_EMPRESA_DEMO").sha256


# ----------------------------------------------------------------- pipeline

@dataclass(frozen=True)
class SoloTexto:
    """Un modelo que contesta con texto en vez de llamar a la herramienta."""

    def extraer(self, documento: Any, solicitud: Mapping[str, Any]) -> Extraida:
        respuesta = RespuestaModelo("m", "end_turn", Uso(5, 5), (Bloque("text", texto="no puedo"),))
        return Extraida(respuesta, "vivo")


def test_respuesta_sin_herramienta_va_a_revision_sin_reglas(config: Config) -> None:
    documento = documento_desde_texto("d1", "representacion_impresa", "Factura sin datos\n")
    pool = cargar_pool(POOL, config.rfc_empresa)
    (resultado,) = ejecutar((documento,), pool, SoloTexto(), lambda texto: (), config).resultados
    assert resultado.decision == REVISION_HUMANA and resultado.propuesta is None
    assert [o.codigo for o in resultado.observaciones] == ["respuesta_sin_herramienta"]


# ----------------------------------------------------------------- reporte

def test_advertencia_segun_origen_de_las_respuestas() -> None:
    assert advertencia("grabado", ["sintetico"]) == ADVERTENCIA_SINTETICA
    assert advertencia("vivo", ["sintetico", "vivo"]) == ADVERTENCIA_SINTETICA
    assert advertencia("grabado", ["vivo"]) == ADVERTENCIA_REGRABADA
    assert advertencia("vivo", ["vivo"]) == ADVERTENCIA_VIVO
    assert advertencia("grabado", []) == ADVERTENCIA_SIN_ENVIOS


@pytest.mark.parametrize("valor, esperado", [
    (None, "—"), (True, "sí"), (False, "no"), (3, "3"),
    ("a|b", "a\\|b"), ("`x`", "'x'"), ("<!-- y -->", "&lt;!-- y --&gt;"), ("a\\|b", "a\\\\\\|b"),
    ("A\u200bB", "A\\u200bB"), ("línea\nnueva", "línea\\u000anueva"), ("&", "&amp;"),
])
def test_celda_escapa_texto_de_terceros(valor: object, esperado: str) -> None:
    assert celda(valor) == esperado


def test_celda_recorta_antes_de_escapar() -> None:
    texto = celda("x" * 80 + "|")
    assert texto == "x" * 77 + "..."


def test_reporte_sin_documentos(config: Config) -> None:
    corrida = Corrida.vacia()
    reporte = armar_reporte(modo="grabado", config=config, corrida=corrida, evaluacion=evaluar(corrida, {}),
                            insumos={"grabadas": None}, grabadas_sin_usar=[])
    assert reporte["advertencia"] == ADVERTENCIA_SIN_ENVIOS
    markdown = texto_markdown(reporte)
    assert "Ninguna." in markdown and "Modelos en las respuestas: ninguno" in markdown
    assert "Respuestas grabadas sin usar: ninguna" in markdown
