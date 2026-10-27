"""CLI del demo de extracción con LLM: modos, códigos de salida 0/2/3 y determinismo.

El modo vivo se prueba con un cliente falso inyectado que responde con las respuestas
grabadas: sin red, sin SDK y sin una llave real.
"""
from __future__ import annotations

import hashlib
import json
import re
import runpy
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

import pytest

from conciliacion.pipeline_modelo import InsumoPipeline
from extraccion_llm.cli import ARCHIVO_JSON, ARCHIVO_MD, main
from extraccion_llm.rutas import CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO, RAIZ_SKILL
from extraccion_llm.vivo import VARIABLE_API_KEY

GRABADAS = DATOS_POR_DEFECTO / "respuestas_grabadas"
ENTORNO_CON_LLAVE = {VARIABLE_API_KEY: "valor-de-prueba"}
SIN_ENTORNO: Dict[str, str] = {}


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _reporte(carpeta: Path) -> Dict[str, Any]:
    datos: Dict[str, Any] = json.loads((carpeta / ARCHIVO_JSON).read_text(encoding="utf-8"))
    return datos


@dataclass(frozen=True)
class UsoFalso:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class RespuestaFalsa:
    content: Sequence[object]
    usage: UsoFalso
    stop_reason: Optional[str]
    model: str


@dataclass
class MensajesDeFixtures:
    """Responde con la respuesta grabada del documento que viene en la solicitud."""

    pedidos: List[Dict[str, Any]] = field(default_factory=list)

    def create(self, **kwargs: Any) -> RespuestaFalsa:
        self.pedidos.append(kwargs)
        contenido = kwargs["messages"][0]["content"]
        texto = re.search(r"<documento>\n(.*)</documento>", contenido, re.S)
        assert texto is not None
        sha = hashlib.sha256(texto.group(1).encode("utf-8")).hexdigest()
        for ruta in sorted(GRABADAS.glob("*.json")):
            grabada = json.loads(ruta.read_text(encoding="utf-8"))
            if grabada["sha256_documento"] == sha:
                cruda = grabada["respuesta"]
                bloques = [SimpleNamespace(**b) for b in cruda["content"]]
                return RespuestaFalsa(bloques, UsoFalso(**cruda["usage"]), cruda["stop_reason"], cruda["model"])
        raise AssertionError("documento sin respuesta grabada")


@dataclass
class ClienteDeFixtures:
    messages: MensajesDeFixtures = field(default_factory=MensajesDeFixtures)


class Fabrica:
    def __init__(self) -> None:
        self.clientes: List[ClienteDeFixtures] = []

    def __call__(self) -> ClienteDeFixtures:
        cliente = ClienteDeFixtures()
        self.clientes.append(cliente)
        return cliente


def _correr(argv: List[str], entorno: Optional[Dict[str, str]] = None, fabrica: Any = None, **extra: Any) -> int:
    return main(argv, entorno=SIN_ENTORNO if entorno is None else entorno, fabrica_cliente=fabrica, **extra)


# ----------------------------------------------------------------- modo grabado

def test_modo_grabado_por_omision_escribe_json_y_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _correr(["--salida", str(tmp_path)]) == 0
    reporte = _reporte(tmp_path)
    assert reporte["esquema"] == "evaluacion_extraccion_llm/v1"
    assert reporte["modo"] == "grabado" and reporte["modelo"] == "claude-opus-5-5"
    assert reporte["origenes_respuesta"] == ["sintetico"]
    assert reporte["modelos_respuesta"] == ["fixture-sintetico"]
    assert "validan el pipeline de evaluación, no la exactitud de Claude" in reporte["advertencia"]
    markdown = (tmp_path / ARCHIVO_MD).read_text(encoding="utf-8")
    assert reporte["advertencia"] in markdown
    resumen = json.loads(capsys.readouterr().out)
    assert resumen["decisiones"] == {"concordante": 24, "revision_humana": 16}


def test_contenido_del_reporte(tmp_path: Path) -> None:
    assert _correr(["--salida", str(tmp_path)]) == 0
    reporte = _reporte(tmp_path)
    assert reporte["decisiones"]["concordante"] == 24
    assert reporte["decisiones"]["por_motivo"]["bloqueado_por_guardia"] == 6
    assert reporte["guardia"]["tasa_deteccion"] == "0.8571"
    assert reporte["metricas"]["total"] == {"vp": 31, "fp": 3, "fn": 3, "precision": "0.9118", "recall": "0.9118"}
    assert reporte["seguridad"] == {"concordantes_con_error": [], "revision_esperada_sin_revision": []}
    consumo = reporte["consumo"]
    assert consumo["documentos_enviados"] == 34 == len(consumo["por_documento"])
    assert consumo["tokens_totales"] == consumo["tokens_entrada"] + consumo["tokens_salida"]
    assert re.fullmatch(r"\d+\.\d{6}", consumo["usd_estimado"])
    assert len(reporte["grabadas_sin_usar"]) == 6
    assert len(reporte["discrepancias_motor"]) == 10
    assert {d["documento_id"] for d in reporte["documentos"]} == {f"doc_{n:02d}" for n in range(1, 41)}
    assert reporte["insumos"]["pool"]["registros"] == 39
    assert reporte["parametros"]["precios_usd_por_millon"] == {"entrada": "5.00", "salida": "25.00"}
    texto = (tmp_path / ARCHIVO_JSON).read_text(encoding="utf-8")
    assert str(tmp_path) not in texto and str(DATOS_POR_DEFECTO) not in texto


def test_dos_corridas_grabadas_dan_el_mismo_sha256(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert _correr(["--salida", str(a)]) == 0
    assert _correr(["--salida", str(b), "--modo", "grabado"]) == 0
    for nombre in (ARCHIVO_JSON, ARCHIVO_MD):
        assert _sha(a / nombre) == _sha(b / nombre)


def test_el_markdown_escapa_texto_de_terceros(tmp_path: Path) -> None:
    assert _correr(["--salida", str(tmp_path)]) == 0
    markdown = (tmp_path / ARCHIVO_MD).read_text(encoding="utf-8")
    assert "<!--" not in markdown and "\u200b" not in markdown
    tablas: List[List[str]] = []
    previa = ""
    for linea in markdown.splitlines():
        if linea.startswith("|"):
            if not previa.startswith("|"):
                tablas.append([])
            tablas[-1].append(linea)
        previa = linea
    assert len(tablas) >= 6
    for tabla in tablas:
        columnas = {len(re.findall(r"(?<!\\)\|", fila)) for fila in tabla}
        assert len(columnas) == 1, tabla[0]


def test_modelo_por_bandera(tmp_path: Path) -> None:
    assert _correr(["--salida", str(tmp_path), "--modelo", "claude-otro"]) == 0
    assert _reporte(tmp_path)["modelo"] == "claude-otro"


# ----------------------------------------------------------------- código 2

def test_salida_inexistente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _correr(["--salida", str(tmp_path / "no")]) == 2
    assert "no existe" in capsys.readouterr().err


def test_grabar_solo_en_modo_vivo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as salida:
        _correr(["--salida", str(tmp_path), "--grabar", str(tmp_path)])
    assert salida.value.code == 2
    assert "--grabar" in capsys.readouterr().err


def test_modo_vivo_sin_llave_falla_claro_y_no_crea_cliente(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    fabrica = Fabrica()
    assert _correr(["--salida", str(tmp_path), "--modo", "vivo"], fabrica=fabrica) == 2
    error = capsys.readouterr().err
    assert VARIABLE_API_KEY in error and "--modo grabado" in error
    assert fabrica.clientes == [] and not any(tmp_path.iterdir())


def test_modo_vivo_sin_sdk(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def sin_sdk() -> Any:
        from extraccion_llm.vivo import crear_cliente_sdk

        def importador(nombre: str) -> Any:
            raise ImportError(nombre)

        return crear_cliente_sdk(importador)

    assert _correr(["--salida", str(tmp_path), "--modo", "vivo"], ENTORNO_CON_LLAVE, sin_sdk) == 2
    assert "requirements-llm.txt" in capsys.readouterr().err


@pytest.mark.parametrize("bandera", ["--config", "--verdad"])
def test_archivo_inexistente(tmp_path: Path, bandera: str) -> None:
    assert _correr(["--salida", str(tmp_path), bandera, str(tmp_path / "nada.json")]) == 2


def test_config_invalida(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    datos = json.loads(CONFIG_POR_DEFECTO.read_text(encoding="utf-8"))
    datos["sorpresa"] = True
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps(datos), encoding="utf-8")
    assert _correr(["--salida", str(tmp_path), "--config", str(ruta)]) == 2
    assert "sorpresa" in capsys.readouterr().err


def test_bandera_de_tope_invalida(tmp_path: Path) -> None:
    assert _correr(["--salida", str(tmp_path), "--max-tokens", "0"]) == 2


def _copia_datos(destino: Path) -> Path:
    shutil.copytree(DATOS_POR_DEFECTO, destino)
    return destino


def _con_datos(datos: Path, salida: Path, *extra: str) -> List[str]:
    return ["--salida", str(salida), "--documentos", str(datos / "documentos"), "--pool",
            str(datos / "cfdis_conocidos"), "--verdad", str(datos / "verdad.jsonl"), "--grabadas",
            str(datos / "respuestas_grabadas"), *extra]


def test_falta_una_respuesta_grabada(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    datos = _copia_datos(tmp_path / "datos")
    (datos / "respuestas_grabadas" / "doc_02.json").unlink()
    salida = tmp_path / "salida"
    salida.mkdir()
    assert _correr(_con_datos(datos, salida)) == 2
    assert "doc_02" in capsys.readouterr().err
    assert not any(salida.iterdir())


def test_documento_alterado_no_usa_una_respuesta_vieja(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    datos = _copia_datos(tmp_path / "datos")
    with (datos / "documentos" / "doc_02.xml").open("a", encoding="utf-8") as archivo:
        archivo.write(" \n")
    salida = tmp_path / "salida"
    salida.mkdir()
    assert _correr(_con_datos(datos, salida)) == 2
    assert "no corresponde" in capsys.readouterr().err


def test_verdad_y_documentos_deben_coincidir(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    datos = _copia_datos(tmp_path / "datos")
    lineas = (datos / "verdad.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
    (datos / "verdad.jsonl").write_text("".join(lineas[1:]), encoding="utf-8")
    salida = tmp_path / "salida"
    salida.mkdir()
    assert _correr(_con_datos(datos, salida)) == 2
    assert "doc_01" in capsys.readouterr().err


def test_guard_que_no_carga_invalida_la_corrida(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def sin_guardia() -> Any:
        raise InsumoPipeline("revision: no se pudo cargar prompt_guard: prueba")

    assert _correr(["--salida", str(tmp_path)], cargar_guardia=sin_guardia) == 2
    assert "prompt_guard" in capsys.readouterr().err


# ----------------------------------------------------------------- código 3

def test_tope_de_documentos_sale_con_3_sin_reporte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _correr(["--salida", str(tmp_path), "--max-documentos", "10"]) == 3
    error = capsys.readouterr().err
    assert "tope" in error and "34 documentos" in error
    assert not any(tmp_path.iterdir())


def test_tope_de_tokens_sale_con_3_y_reporta_el_consumo(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _correr(["--salida", str(tmp_path), "--max-tokens", "5000"]) == 3
    error = capsys.readouterr().err
    assert "tokens" in error and "USD" in error
    assert not any(tmp_path.iterdir())


# ----------------------------------------------------------------- modo vivo con cliente falso

def test_modo_vivo_con_cliente_falso_y_regrabado(tmp_path: Path) -> None:
    vivo, regrabadas, replay = tmp_path / "vivo", tmp_path / "grabadas", tmp_path / "replay"
    for carpeta in (vivo, regrabadas, replay):
        carpeta.mkdir()
    fabrica = Fabrica()
    argv = ["--salida", str(vivo), "--modo", "vivo", "--grabar", str(regrabadas)]
    assert _correr(argv, ENTORNO_CON_LLAVE, fabrica) == 0
    (cliente,) = fabrica.clientes
    assert len(cliente.messages.pedidos) == 34
    assert all(p["tool_choice"]["type"] == "tool" for p in cliente.messages.pedidos)
    reporte_vivo = _reporte(vivo)
    assert reporte_vivo["modo"] == "vivo" and reporte_vivo["origenes_respuesta"] == ["vivo"]
    assert "no la exactitud de Claude" not in reporte_vivo["advertencia"]
    assert len(list(regrabadas.glob("*.json"))) == 34
    assert _correr(["--salida", str(replay), "--grabadas", str(regrabadas)]) == 0
    reporte_replay = _reporte(replay)
    assert reporte_replay["origenes_respuesta"] == ["vivo"] and reporte_replay["grabadas_sin_usar"] == []
    for seccion in ("metricas", "decisiones", "guardia", "seguridad", "consumo", "discrepancias_motor"):
        assert reporte_replay[seccion] == reporte_vivo[seccion], seccion


def test_modo_vivo_con_carpeta_de_grabado_inexistente(tmp_path: Path) -> None:
    fabrica = Fabrica()
    argv = ["--salida", str(tmp_path), "--modo", "vivo", "--grabar", str(tmp_path / "no")]
    assert _correr(argv, ENTORNO_CON_LLAVE, fabrica) == 2
    assert fabrica.clientes == []


def test_el_entorno_real_se_usa_por_omision(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(VARIABLE_API_KEY, raising=False)
    assert main(["--salida", str(tmp_path), "--modo", "vivo"]) == 2


# ----------------------------------------------------------------- script de entrada

def test_script_de_entrada(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = RAIZ_SKILL / "run_llm_extraction.py"
    monkeypatch.setattr(sys, "argv", [str(script), "--salida", str(tmp_path)])
    with pytest.raises(SystemExit) as salida:
        runpy.run_path(str(script), run_name="__main__")
    assert salida.value.code == 0
    assert (tmp_path / ARCHIVO_JSON).is_file()
