"""Reintentos del modo vivo: solo errores transitorios, backoff con jitter determinista y `retry-after`.

El cliente del SDK es falso (sus errores imitan los nombres y atributos de las clases del SDK)
y el reloj se inyecta: ninguna prueba usa red, una llave ni una espera real.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from email.utils import formatdate
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

import pytest

from extraccion_llm.cli import ARCHIVO_JSON, main
from extraccion_llm.config import Config, Reintentos, cargar_config
from extraccion_llm.documentos import Documento, cargar_documentos, cargar_verdad, documento_desde_texto
from extraccion_llm.errores import AutenticacionRechazada, FallaApiDocumento, InsumoInvalido, TopeExcedido
from extraccion_llm.evaluacion import evaluar
from extraccion_llm.grabadas import cargar_grabadas
from extraccion_llm.herramienta import solicitud
from extraccion_llm.modelo import ERROR_API, REVISION_HUMANA
from extraccion_llm.pipeline import Extraida, ejecutar
from extraccion_llm.pool import cargar_pool
from extraccion_llm.reintentos import (
    AUTENTICACION,
    PERMANENTE,
    TRANSITORIO,
    Reloj,
    clasificar,
    espera_exponencial,
    segundos_retry_after,
)
from extraccion_llm.rutas import CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO
from extraccion_llm.vivo import VARIABLE_API_KEY, ExtractorVivo, crear_cliente_sdk

GRABADAS = DATOS_POR_DEFECTO / "respuestas_grabadas"
ENTORNO_CON_LLAVE = {VARIABLE_API_KEY: "valor-de-prueba"}
POLITICA = Reintentos(max_reintentos=3, espera_inicial_s=1.0, espera_maxima_s=30.0)
INSTANTE = 1_800_000_000.0
MARCA_PRIVADA = "dato-privado-del-error"


# ----------------------------------------------------------------- errores con la forma del SDK

class APIStatusError(Exception):
    """Como el error del SDK: `status_code` y `response.headers`."""

    def __init__(self, mensaje: str, status_code: int, headers: Optional[Mapping[str, str]] = None) -> None:
        super().__init__(mensaje)
        self.status_code = status_code
        self.response = SimpleNamespace(headers=dict(headers or {}))


class RateLimitError(APIStatusError):
    pass


class APIError(Exception):
    """La base del SDK, sin estado HTTP."""


class APIConnectionError(APIError):
    pass


class APITimeoutError(APIConnectionError):
    pass


def _limite(headers: Optional[Mapping[str, str]] = None) -> RateLimitError:
    return RateLimitError("rate_limit_error: demasiadas solicitudes", 429, headers)


# ----------------------------------------------------------------- cliente y reloj falsos

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


def _como_sdk(cruda: Mapping[str, Any]) -> RespuestaFalsa:
    bloques = [SimpleNamespace(**b) for b in cruda["content"]]
    return RespuestaFalsa(bloques, UsoFalso(**cruda["usage"]), cruda["stop_reason"], cruda["model"])


def _respuesta_de(documento: Documento) -> RespuestaFalsa:
    return _como_sdk(json.loads((GRABADAS / f"{documento.documento_id}.json").read_text(encoding="utf-8"))["respuesta"])


Paso = Union[BaseException, RespuestaFalsa]


@dataclass
class MensajesGuionados:
    """Contesta (o falla) según un guion, en orden."""

    guion: List[Paso]
    llamadas: int = 0

    def create(self, **kwargs: Any) -> RespuestaFalsa:
        paso = self.guion[self.llamadas]
        self.llamadas += 1
        if isinstance(paso, BaseException):
            raise paso
        return paso


@dataclass
class ClienteGuionado:
    messages: MensajesGuionados


@dataclass
class RelojFalso:
    """Registra las esperas en vez de dormir; el azar del jitter es fijo."""

    azar_fijo: float = 0.5
    esperas: List[float] = field(default_factory=list)

    def reloj(self) -> Reloj:
        return Reloj(dormir=self.esperas.append, azar=lambda: self.azar_fijo, ahora=lambda: INSTANTE)


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config(CONFIG_POR_DEFECTO)


@pytest.fixture(scope="module")
def documento() -> Documento:
    return cargar_documentos(DATOS_POR_DEFECTO / "documentos")[0]


def _extractor(guion: List[Paso], reloj: RelojFalso, politica: Reintentos = POLITICA,
               avisos: Optional[List[str]] = None, grabar_en: Optional[Path] = None) -> ExtractorVivo:
    avisar = None if avisos is None else avisos.append
    return ExtractorVivo(ClienteGuionado(MensajesGuionados(guion)), politica, grabar_en=grabar_en,
                         reloj=reloj.reloj(), avisar=avisar)


def _llamadas(extractor: ExtractorVivo) -> int:
    cliente: Any = extractor.cliente
    return int(cliente.messages.llamadas)


# ----------------------------------------------------------------- clasificación

@pytest.mark.parametrize("error, clase", [
    (_limite(), TRANSITORIO),
    (APIStatusError("api_error", 500), TRANSITORIO),
    (APIStatusError("bad gateway", 502), TRANSITORIO),
    (APIStatusError("unavailable", 503), TRANSITORIO),
    (APIStatusError("overloaded_error", 529), TRANSITORIO),
    (APITimeoutError("se agotó el tiempo"), TRANSITORIO),
    (APIConnectionError("sin conexión"), TRANSITORIO),
    (TimeoutError("socket"), TRANSITORIO),
    (ConnectionResetError("reset"), TRANSITORIO),
    (APIStatusError("invalid_request_error", 400), PERMANENTE),
    (APIStatusError("not_found_error", 404), PERMANENTE),
    (APIStatusError("request_too_large", 413), PERMANENTE),
    (APIStatusError("unprocessable", 422), PERMANENTE),
    (APIError("error de la API sin estado"), PERMANENTE),
    (APIStatusError("authentication_error", 401), AUTENTICACION),
    (APIStatusError("permission_error", 403), AUTENTICACION),
    (ValueError("no es de la API"), None),
    (KeyError("tampoco"), None),
])
def test_clasificacion_de_errores(error: BaseException, clase: Optional[str]) -> None:
    assert clasificar(error) == clase


def test_un_estado_que_no_es_entero_no_cuenta_como_http() -> None:
    error = ValueError("raro")
    error.status_code = True  # type: ignore[attr-defined]
    assert clasificar(error) is None


# ----------------------------------------------------------------- espera

@pytest.mark.parametrize("reintento, azar, esperada", [
    (1, 0.0, 0.5), (1, 0.5, 0.75), (1, 1.0, 1.0),
    (2, 0.5, 1.5), (3, 0.5, 3.0),
    (6, 0.0, 15.0), (6, 1.0, 30.0), (20, 1.0, 30.0),
])
def test_backoff_exponencial_con_jitter_y_tope(reintento: int, azar: float, esperada: float) -> None:
    assert espera_exponencial(reintento, POLITICA, azar) == pytest.approx(esperada)


@pytest.mark.parametrize("encabezados, esperada", [
    ({"retry-after": "7"}, 7.0),
    ({"retry-after": " 1.5 "}, 1.5),
    ({"retry-after": formatdate(INSTANTE + 12, usegmt=True)}, 12.0),
    ({"retry-after": formatdate(INSTANTE - 60, usegmt=True)}, 0.0),
    ({"retry-after": "pronto"}, None),
    ({"retry-after": "-3"}, None),
    ({}, None),
])
def test_retry_after_en_segundos_o_fecha_http(encabezados: Dict[str, str], esperada: Optional[float]) -> None:
    assert segundos_retry_after(_limite(encabezados), INSTANTE) == esperada


def test_retry_after_sin_respuesta_o_sin_encabezados() -> None:
    assert segundos_retry_after(APITimeoutError("x"), INSTANTE) is None
    sin_encabezados = APIStatusError("x", 429)
    sin_encabezados.response = SimpleNamespace()  # type: ignore[assignment]
    assert segundos_retry_after(sin_encabezados, INSTANTE) is None


# ----------------------------------------------------------------- extractor vivo

def test_reintenta_429_y_529_con_backoff_y_luego_responde(config: Config, documento: Documento) -> None:
    reloj = RelojFalso()
    extractor = _extractor([_limite(), APIStatusError("overloaded_error", 529), _respuesta_de(documento)], reloj)
    extraida = extractor.extraer(documento, solicitud(documento, config))
    assert extraida.origen == "vivo" and _llamadas(extractor) == 3
    assert reloj.esperas == [pytest.approx(0.75), pytest.approx(1.5)]


def test_reintenta_un_timeout_de_conexion(config: Config, documento: Documento) -> None:
    reloj = RelojFalso(azar_fijo=0.0)
    extractor = _extractor([APITimeoutError("se agotó el tiempo"), _respuesta_de(documento)], reloj)
    extractor.extraer(documento, solicitud(documento, config))
    assert reloj.esperas == [0.5]


def test_agotar_los_reintentos_es_una_falla_del_documento(config: Config, documento: Documento) -> None:
    reloj = RelojFalso()
    politica = Reintentos(max_reintentos=2, espera_inicial_s=1.0, espera_maxima_s=30.0)
    extractor = _extractor([APIStatusError("unavailable", 503)] * 3, reloj, politica)
    with pytest.raises(FallaApiDocumento) as falla:
        extractor.extraer(documento, solicitud(documento, config))
    assert _llamadas(extractor) == 3 and len(reloj.esperas) == 2
    assert falla.value.documento_id == documento.documento_id and falla.value.intentos == 3
    assert "503" in str(falla.value) and "2 reintentos" in str(falla.value)


def test_sin_reintentos_un_429_falla_de_inmediato(config: Config, documento: Documento) -> None:
    reloj = RelojFalso()
    politica = Reintentos(max_reintentos=0, espera_inicial_s=1.0, espera_maxima_s=1.0)
    extractor = _extractor([_limite()], reloj, politica)
    with pytest.raises(FallaApiDocumento):
        extractor.extraer(documento, solicitud(documento, config))
    assert reloj.esperas == []


@pytest.mark.parametrize("estado", [400, 404, 413, 422])
def test_un_4xx_de_validacion_no_se_reintenta(config: Config, documento: Documento, estado: int) -> None:
    reloj = RelojFalso()
    extractor = _extractor([APIStatusError("invalid_request_error", estado)], reloj)
    with pytest.raises(FallaApiDocumento, match=str(estado)) as falla:
        extractor.extraer(documento, solicitud(documento, config))
    assert _llamadas(extractor) == 1 and reloj.esperas == [] and falla.value.intentos == 1


@pytest.mark.parametrize("estado", [401, 403])
def test_autenticacion_rechazada_aborta_sin_reintentar(config: Config, documento: Documento, estado: int) -> None:
    reloj = RelojFalso()
    extractor = _extractor([APIStatusError(f"authentication_error {MARCA_PRIVADA}", estado)], reloj)
    with pytest.raises(AutenticacionRechazada) as error:
        extractor.extraer(documento, solicitud(documento, config))
    assert isinstance(error.value, InsumoInvalido)
    assert VARIABLE_API_KEY in str(error.value) and str(estado) in str(error.value)
    assert MARCA_PRIVADA not in str(error.value)
    assert _llamadas(extractor) == 1 and reloj.esperas == []


def test_se_respeta_retry_after_cuando_pide_mas_que_el_backoff(config: Config, documento: Documento) -> None:
    reloj = RelojFalso()
    extractor = _extractor([_limite({"retry-after": "7"}), _respuesta_de(documento)], reloj)
    extractor.extraer(documento, solicitud(documento, config))
    assert reloj.esperas == [7.0]


def test_retry_after_menor_que_el_backoff_no_acorta_la_espera(config: Config, documento: Documento) -> None:
    reloj = RelojFalso()
    extractor = _extractor([_limite({"retry-after": "0"}), _respuesta_de(documento)], reloj)
    extractor.extraer(documento, solicitud(documento, config))
    assert reloj.esperas == [pytest.approx(0.75)]


def test_retry_after_mayor_que_la_espera_maxima_no_se_espera(config: Config, documento: Documento) -> None:
    reloj = RelojFalso()
    extractor = _extractor([_limite({"retry-after": "120"}), _respuesta_de(documento)], reloj)
    with pytest.raises(FallaApiDocumento, match="retry-after"):
        extractor.extraer(documento, solicitud(documento, config))
    assert reloj.esperas == [] and _llamadas(extractor) == 1


def test_un_error_que_no_es_de_la_api_detiene_la_corrida(config: Config, documento: Documento) -> None:
    extractor = _extractor([TypeError("argumento inesperado")], RelojFalso())
    with pytest.raises(InsumoInvalido, match="inesperado.*TypeError") as error:
        extractor.extraer(documento, solicitud(documento, config))
    assert not isinstance(error.value, FallaApiDocumento)


def test_cada_reintento_se_avisa(config: Config, documento: Documento) -> None:
    avisos: List[str] = []
    extractor = _extractor([_limite(), _respuesta_de(documento)], RelojFalso(), avisos=avisos)
    extractor.extraer(documento, solicitud(documento, config))
    (aviso,) = avisos
    assert documento.documento_id in aviso and "429" in aviso and "reintento 1/3" in aviso


def test_tras_un_reintento_se_graba_una_sola_respuesta(tmp_path: Path, config: Config, documento: Documento) -> None:
    extractor = _extractor([_limite(), _respuesta_de(documento)], RelojFalso(), grabar_en=tmp_path)
    extractor.extraer(documento, solicitud(documento, config))
    assert [p.name for p in tmp_path.iterdir()] == [f"{documento.documento_id}.json"]


def test_el_cliente_del_sdk_se_crea_sin_reintentos_propios() -> None:
    def importador(nombre: str) -> Any:
        return SimpleNamespace(Anthropic=lambda **opciones: opciones)

    assert crear_cliente_sdk(importador) == {"max_retries": 0}  # type: ignore[comparison-overlap]


def test_el_reloj_por_omision_es_el_real() -> None:
    import random
    import time

    reloj = Reloj()
    assert (reloj.dormir, reloj.azar, reloj.ahora) == (time.sleep, random.random, time.time)


# ----------------------------------------------------------------- pipeline

@dataclass
class ExtractorConFallas:
    """Responde con la grabada salvo para los ids indicados, que fallan con la excepción dada."""

    fallas: Mapping[str, BaseException]
    llamados: List[str] = field(default_factory=list)

    def extraer(self, documento: Documento, pedido: Mapping[str, Any]) -> Extraida:
        self.llamados.append(documento.documento_id)
        falla = self.fallas.get(documento.documento_id)
        if falla is not None:
            raise falla
        grabada = cargar_grabadas(GRABADAS)[documento.documento_id]
        return Extraida(grabada.respuesta, "vivo")


def _sin_guardia(texto: str) -> Sequence[Any]:
    return ()


def _documentos(*ids: str) -> Tuple[Documento, ...]:
    return tuple(d for d in cargar_documentos(DATOS_POR_DEFECTO / "documentos") if d.documento_id in ids)


def test_un_documento_con_error_api_va_a_revision_y_el_lote_sigue(config: Config) -> None:
    pool = cargar_pool(DATOS_POR_DEFECTO / "cfdis_conocidos", config.rfc_empresa)
    documentos = _documentos("doc_08", "doc_09", "doc_15")
    falla = FallaApiDocumento("doc_09", "doc_09: la API rechazó la solicitud (HTTP 400)", 1)
    extractor = ExtractorConFallas({"doc_09": falla})
    corrida = ejecutar(documentos, pool, extractor, _sin_guardia, config)
    assert extractor.llamados == ["doc_08", "doc_09", "doc_15"]
    fallido = next(r for r in corrida.resultados if r.documento_id == "doc_09")
    assert fallido.enviado and fallido.decision == REVISION_HUMANA and fallido.propuesta is None
    assert [(o.codigo, o.detalle) for o in fallido.observaciones] == [(ERROR_API, str(falla))]
    assert fallido.uso is None and fallido.modelo_respuesta is None
    assert [d for d, _ in corrida.consumo.por_documento] == ["doc_08", "doc_15"]
    verdades = {v.documento_id: v for v in cargar_verdad(DATOS_POR_DEFECTO / "verdad.jsonl")}
    evaluacion = evaluar(corrida, verdades)
    # Sin respuesta no hay extracción: el documento no entra a las métricas por campo.
    assert evaluacion.metricas["uuid"].vp == 2 and evaluacion.metricas["uuid"].fn == 0


def test_la_autenticacion_rechazada_detiene_el_pipeline(config: Config) -> None:
    pool = cargar_pool(DATOS_POR_DEFECTO / "cfdis_conocidos", config.rfc_empresa)
    extractor = ExtractorConFallas({"doc_08": AutenticacionRechazada("la API rechazó la autenticación")})
    with pytest.raises(AutenticacionRechazada):
        ejecutar(_documentos("doc_08", "doc_09"), pool, extractor, _sin_guardia, config)
    assert extractor.llamados == ["doc_08"]


def test_el_tope_de_tokens_sigue_deteniendo_despues_de_un_error_api(config: Config) -> None:
    import dataclasses

    from extraccion_llm.config import Limites

    pool = cargar_pool(DATOS_POR_DEFECTO / "cfdis_conocidos", config.rfc_empresa)
    estrecha = dataclasses.replace(config, limites=Limites(max_documentos=50, max_tokens=1000))
    extractor = ExtractorConFallas({"doc_08": FallaApiDocumento("doc_08", "falla", 4)})
    with pytest.raises(TopeExcedido):
        ejecutar(_documentos("doc_08", "doc_09", "doc_15"), pool, extractor, _sin_guardia, estrecha)


# ----------------------------------------------------------------- CLI

@dataclass
class MensajesPorDocumento:
    """Responde con la grabada del documento de la solicitud; ciertos ids fallan según su guion."""

    guiones: Dict[str, List[BaseException]]
    pedidos: List[str] = field(default_factory=list)

    def create(self, **kwargs: Any) -> RespuestaFalsa:
        contenido = kwargs["messages"][0]["content"]
        texto = re.search(r"<documento>\n(.*)</documento>", contenido, re.S)
        assert texto is not None
        sha = hashlib.sha256(texto.group(1).encode("utf-8")).hexdigest()
        grabadas = {g.sha256_documento: g for g in cargar_grabadas(GRABADAS).values()}
        grabada = grabadas[sha]
        self.pedidos.append(grabada.documento_id)
        guion = self.guiones.get(grabada.documento_id)
        if guion:
            raise guion.pop(0)
        datos = json.loads((GRABADAS / f"{grabada.documento_id}.json").read_text(encoding="utf-8"))
        return _como_sdk(datos["respuesta"])


def _cliente(guiones: Dict[str, List[BaseException]]) -> Any:
    return SimpleNamespace(messages=MensajesPorDocumento(guiones))


def test_cli_vivo_con_un_400_y_un_429_escribe_el_reporte(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    reloj = RelojFalso()
    cliente = _cliente({"doc_08": [APIStatusError("invalid_request_error", 400)], "doc_09": [_limite()]})
    codigo = main(["--salida", str(tmp_path), "--modo", "vivo"], entorno=ENTORNO_CON_LLAVE,
                  fabrica_cliente=lambda: cliente, reloj=reloj.reloj())
    assert codigo == 0
    reporte = json.loads((tmp_path / ARCHIVO_JSON).read_text(encoding="utf-8"))
    documentos = {d["documento_id"]: d for d in reporte["documentos"]}
    assert documentos["doc_08"]["motivos"] == [ERROR_API] and documentos["doc_08"]["decision"] == REVISION_HUMANA
    assert documentos["doc_09"]["decision"] == "concordante"
    assert reporte["decisiones"]["por_motivo"][ERROR_API] == 1
    assert reporte["consumo"]["documentos_enviados"] == 43
    assert reloj.esperas == [pytest.approx(0.75)]
    error = capsys.readouterr().err
    assert "doc_09" in error and "reintento 1/3" in error


def test_cli_vivo_con_autenticacion_rechazada_sale_con_2_sin_reporte(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cliente = _cliente({"doc_01": [APIStatusError(f"authentication_error {MARCA_PRIVADA}", 401)]})
    codigo = main(["--salida", str(tmp_path), "--modo", "vivo"], entorno=ENTORNO_CON_LLAVE,
                  fabrica_cliente=lambda: cliente, reloj=RelojFalso().reloj())
    assert codigo == 2
    error = capsys.readouterr().err
    assert VARIABLE_API_KEY in error and MARCA_PRIVADA not in error
    assert not any(tmp_path.iterdir())
    assert cliente.messages.pedidos == ["doc_01"]


def test_cli_vivo_el_tope_de_tokens_sigue_saliendo_con_3(tmp_path: Path) -> None:
    cliente = _cliente({"doc_02": [_limite()]})
    codigo = main(["--salida", str(tmp_path), "--modo", "vivo", "--max-tokens", "5000"],
                  entorno=ENTORNO_CON_LLAVE, fabrica_cliente=lambda: cliente, reloj=RelojFalso().reloj())
    assert codigo == 3 and not any(tmp_path.iterdir())


def test_un_documento_sin_texto_igual_falla_cerrado(config: Config) -> None:
    documento = documento_desde_texto("d1", "representacion_impresa", "Factura\n")
    extractor = _extractor([APIStatusError("invalid_request_error", 400)], RelojFalso())
    with pytest.raises(FallaApiDocumento) as falla:
        extractor.extraer(documento, solicitud(documento, config))
    assert falla.value.documento_id == "d1"
