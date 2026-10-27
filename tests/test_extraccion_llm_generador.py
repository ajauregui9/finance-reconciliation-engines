"""Pruebas del generador sintético de documentos para la extracción con LLM.

Leen los archivos que escribe el generador, que son su contrato público: documentos,
pool de CFDIs conocidos, verdad, respuestas grabadas sintéticas y errores plantados.
"""
from __future__ import annotations

import hashlib
import json
import re
import runpy
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Set

import pytest

from conciliacion.cruce_cfdi_xml import cargar_cfdis_xml, cargar_cfdis_xml_con_montos
from extraccion_llm.modelo import CAMPOS as CAMPOS_DEL_SKILL
from generador_llm import (
    ARCHIVO_ERRORES,
    ARCHIVO_VERDAD,
    CAMPOS,
    DIR_DOCUMENTOS,
    DIR_GRABADAS,
    DIR_POOL,
    contenidos,
    escribir_salida,
    generar,
)
from generador_llm.__main__ import main as main_generador
from generador_llm.catalogo import RFC_EMPRESA, SEMILLA_POR_DEFECTO

RAIZ = Path(__file__).resolve().parents[1]
VERSIONADO = RAIZ / "examples" / "synthetic_llm"
UUID_SINTETICO = re.compile(r"^00000000-0000-0000-0000-0000000000\d{2}$")
RFC_PERMITIDO = re.compile(r"^(?:RFC_[A-Z0-9_]+|XAXX010101000|XEXX010101000)$")
D = Decimal
CERO = D("0.00")
OPCIONALES = ("descuento", "ieps", "isr_retenido", "iva_retenido")
MONTOS = ("subtotal", "descuento", "iva", "ieps", "isr_retenido", "iva_retenido", "total")


def _m(campos: Dict[str, Any], campo: str) -> Decimal:
    """Un monto de la verdad; los opcionales en null valen cero."""
    valor = campos[campo]
    return CERO if valor is None else D(valor)


def _calculado(campos: Dict[str, Any]) -> Decimal:
    """subtotal − descuento + IVA + IEPS − ISR retenido − IVA retenido."""
    return (_m(campos, "subtotal") - _m(campos, "descuento") + _m(campos, "iva") + _m(campos, "ieps")
            - _m(campos, "isr_retenido") - _m(campos, "iva_retenido"))


@pytest.fixture(scope="module")
def textos() -> Dict[str, str]:
    return contenidos(generar(SEMILLA_POR_DEFECTO))


def _verdades(textos: Dict[str, str]) -> List[Dict[str, Any]]:
    return [json.loads(linea) for linea in textos[ARCHIVO_VERDAD].splitlines()]


def _por_id(textos: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
    return {v["documento_id"]: v for v in _verdades(textos)}


def _documento(textos: Dict[str, str], documento_id: str) -> str:
    for extension in (".xml", ".txt"):
        clave = f"{DIR_DOCUMENTOS}/{documento_id}{extension}"
        if clave in textos:
            return textos[clave]
    raise AssertionError(f"no existe el documento {documento_id}")


def _grabada(textos: Dict[str, str], documento_id: str) -> Dict[str, Any]:
    datos: Dict[str, Any] = json.loads(textos[f"{DIR_GRABADAS}/{documento_id}.json"])
    return datos


def _con_borde(textos: Dict[str, str], borde: str) -> List[Dict[str, Any]]:
    return [v for v in _verdades(textos) if borde in v["casos_borde"]]


def test_dos_corridas_dan_los_mismos_bytes(tmp_path: Path) -> None:
    rutas_a = escribir_salida(generar(SEMILLA_POR_DEFECTO), tmp_path / "a")
    rutas_b = escribir_salida(generar(SEMILLA_POR_DEFECTO), tmp_path / "b")
    assert [r.relative_to(tmp_path / "a") for r in rutas_a] == [r.relative_to(tmp_path / "b") for r in rutas_b]
    for ruta_a, ruta_b in zip(rutas_a, rutas_b):
        assert hashlib.sha256(ruta_a.read_bytes()).hexdigest() == hashlib.sha256(ruta_b.read_bytes()).hexdigest()


def test_los_archivos_versionados_coinciden_con_el_generador(textos: Dict[str, str]) -> None:
    for relativa, texto in textos.items():
        assert (VERSIONADO / relativa).read_text(encoding="utf-8") == texto, relativa
    escritos = {p.relative_to(VERSIONADO).as_posix() for p in VERSIONADO.rglob("*") if p.is_file()}
    assert escritos - set(textos) == {"README.md"}


def test_otra_semilla_cambia_los_valores_pero_no_la_estructura() -> None:
    a, b = contenidos(generar(1)), contenidos(generar(2))
    assert a != b
    assert len([k for k in a if k.startswith(DIR_DOCUMENTOS)]) == len([k for k in b if k.startswith(DIR_DOCUMENTOS)])


def test_hay_cincuenta_documentos_mitad_xml_mitad_texto(textos: Dict[str, str]) -> None:
    documentos = [k for k in textos if k.startswith(DIR_DOCUMENTOS + "/")]
    assert len(documentos) == 50
    assert sum(1 for k in documentos if k.endswith(".xml")) == 25
    assert sum(1 for k in documentos if k.endswith(".txt")) == 25
    assert sorted(v["documento_id"] for v in _verdades(textos)) == sorted(Path(k).stem for k in documentos)


def test_los_campos_del_generador_son_los_del_skill() -> None:
    assert CAMPOS == CAMPOS_DEL_SKILL


def test_la_verdad_trae_los_doce_campos_en_formato_canonico(textos: Dict[str, str]) -> None:
    for verdad in _verdades(textos):
        assert tuple(sorted(verdad["campos"])) == tuple(sorted(CAMPOS))
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", verdad["campos"]["fecha"])
        for campo in ("subtotal", "iva", "total"):
            assert re.fullmatch(r"\d+\.\d{2}", verdad["campos"][campo]), (verdad["documento_id"], campo)
        for campo in OPCIONALES:
            valor = verdad["campos"][campo]
            # Un opcional que no aplica es null, nunca "0.00".
            assert valor is None or (re.fullmatch(r"\d+\.\d{2}", valor) and D(valor) > 0), verdad["documento_id"]


def test_al_menos_cinco_documentos_traen_inyecciones_en_texto_libre(textos: Dict[str, str]) -> None:
    inyectados = [v for v in _verdades(textos) if v["inyeccion"] is not None]
    assert len(inyectados) >= 5
    assert all(v["revision_esperada"] for v in inyectados)
    formatos = {Path(k).suffix for k in textos for v in inyectados if Path(k).stem == v["documento_id"]
                and k.startswith(DIR_DOCUMENTOS)}
    assert formatos == {".xml", ".txt"}
    assert "parafrasis_tercera_persona" in {v["inyeccion"] for v in inyectados}


def test_las_inyecciones_xml_viven_en_la_descripcion_del_concepto(textos: Dict[str, str]) -> None:
    for verdad in _verdades(textos):
        clave = f"{DIR_DOCUMENTOS}/{verdad['documento_id']}.xml"
        if verdad["inyeccion"] is None or clave not in textos:
            continue
        descripcion = re.search(r'Descripcion="([^"]*)"', textos[clave])
        assert descripcion is not None and len(descripcion.group(1)) > 40


def test_estan_los_casos_borde_pedidos(textos: Dict[str, str]) -> None:
    for borde in ("iva_no_cuadra", "rfc_mal_formado", "moneda_usd", "coma_miles", "moneda_no_permitida",
                  "sin_xml_en_pool", "monto_grande", "tasa_cero", "benigno_dificil", "honorarios", "flete",
                  "descuento", "ieps"):
        assert _con_borde(textos, borde), borde


@pytest.mark.parametrize("borde, presentes", [
    ("honorarios", {"isr_retenido", "iva_retenido"}),
    ("flete", {"iva_retenido"}),
    ("descuento", {"descuento"}),
    ("ieps", {"ieps"}),
])
def test_cada_borde_fiscal_trae_solo_sus_montos_opcionales(textos: Dict[str, str], borde: str,
                                                           presentes: Set[str]) -> None:
    casos = _con_borde(textos, borde)
    assert len(casos) >= 2
    formatos = {Path(k).suffix for k in textos for v in casos if k.startswith(DIR_DOCUMENTOS)
                and Path(k).stem == v["documento_id"]}
    assert formatos == {".xml", ".txt"}, borde
    for caso in casos:
        assert {c for c in OPCIONALES if caso["campos"][c] is not None} == presentes, caso["documento_id"]
        assert not caso["revision_esperada"]


def test_honorarios_retienen_isr_10_y_dos_tercios_del_iva(textos: Dict[str, str]) -> None:
    for caso in _con_borde(textos, "honorarios"):
        campos = caso["campos"]
        base = _m(campos, "subtotal")
        assert _m(campos, "isr_retenido") == (base * D("0.10")).quantize(D("0.01"))
        assert _m(campos, "iva_retenido") == (_m(campos, "iva") * 2 / 3).quantize(D("0.01"))


def test_flete_retiene_iva_al_4(textos: Dict[str, str]) -> None:
    for caso in _con_borde(textos, "flete"):
        campos = caso["campos"]
        assert _m(campos, "iva_retenido") == (_m(campos, "subtotal") * D("0.04")).quantize(D("0.01"))


def test_descuento_e_ieps_cambian_la_base_del_iva(textos: Dict[str, str]) -> None:
    for caso in _con_borde(textos, "descuento"):
        campos = caso["campos"]
        base = _m(campos, "subtotal") - _m(campos, "descuento")
        assert _m(campos, "iva") == (base * D("0.16")).quantize(D("0.01"))
    for caso in _con_borde(textos, "ieps"):
        campos = caso["campos"]
        assert _m(campos, "ieps") == (_m(campos, "subtotal") * D("0.08")).quantize(D("0.01"))
        assert _m(campos, "iva") == ((_m(campos, "subtotal") + _m(campos, "ieps")) * D("0.16")).quantize(D("0.01"))


def test_los_montos_fiscales_aparecen_impresos(textos: Dict[str, str]) -> None:
    for borde in ("honorarios", "flete", "descuento", "ieps"):
        for caso in _con_borde(textos, borde):
            documento = _documento(textos, caso["documento_id"])
            for campo in OPCIONALES:
                valor = caso["campos"][campo]
                if valor is not None:
                    assert valor in documento or f"{D(valor):,.2f}" in documento, (caso["documento_id"], campo)


@pytest.mark.parametrize("plantilla", ["texto_a", "texto_b"])
def test_cada_plantilla_impresa_muestra_todo_el_desglose(plantilla: str) -> None:
    import dataclasses

    from generador_llm import plantillas
    from generador_llm.fabricas import Desglose

    base = generar(SEMILLA_POR_DEFECTO).documentos[0].impreso
    desglose = Desglose(descuento=D("100.00"), tasa_ieps=D("0.08"), ieps=D("72.00"), tasa_isr_retenido=D("0.10"),
                        isr_retenido=D("90.00"), tasa_iva_retenido=D("0.106667"), iva_retenido=D("103.68"))
    # 1000 − 100 + 72 + 155.52 − 90 − 103.68 = 933.84
    comprobante = dataclasses.replace(base, subtotal=D("1000.00"), iva=D("155.52"), total=D("933.84"),
                                      desglose=desglose)
    texto = getattr(plantillas, plantilla)(comprobante)
    for monto in ("1,000.00" if plantilla == "texto_a" else "1000.00", "100.00", "72.00", "155.52", "90.00",
                  "103.68", "933.84"):
        assert monto in texto, (plantilla, monto)
    assert texto.index("72.00") < texto.index("155.52") < texto.index("90.00")


def test_el_lector_del_motor_lee_el_desglose_fiscal_del_pool(tmp_path: Path, textos: Dict[str, str]) -> None:
    escribir_salida(generar(SEMILLA_POR_DEFECTO), tmp_path)
    verdades = {v["campos"]["uuid"]: v for v in _verdades(textos)}
    for leido in cargar_cfdis_xml_con_montos(tmp_path / DIR_POOL, RFC_EMPRESA):
        campos = verdades[leido.cfdi.uuid]["campos"]
        if "iva_no_cuadra" in verdades[leido.cfdi.uuid]["casos_borde"]:
            continue
        assert (leido.descuento, leido.ieps_trasladado, leido.isr_retenido, leido.iva_retenido) == tuple(
            _m(campos, c) for c in OPCIONALES), leido.cfdi.uuid
        assert leido.total_trasladados == leido.iva_trasladado + leido.ieps_trasladado
        assert leido.total_retenidos == leido.isr_retenido + leido.iva_retenido
        assert (leido.subtotal - leido.descuento + leido.total_trasladados - leido.total_retenidos
                == leido.cfdi.total == D(campos["total"])), leido.cfdi.uuid


def test_iva_que_no_cuadra_esta_impreso_y_el_pool_trae_el_correcto(textos: Dict[str, str]) -> None:
    (caso,) = _con_borde(textos, "iva_no_cuadra")
    campos = caso["campos"]
    assert _calculado(campos) != D(campos["total"])
    assert caso["revision_esperada"]
    pool = textos[f"{DIR_POOL}/{campos['uuid']}.xml"]
    assert f'TotalImpuestosTrasladados="{campos["iva"]}"' not in pool


def test_los_demas_documentos_cuadran_al_centavo(textos: Dict[str, str]) -> None:
    for verdad in _verdades(textos):
        if "iva_no_cuadra" in verdad["casos_borde"]:
            continue
        assert _calculado(verdad["campos"]) == D(verdad["campos"]["total"]), verdad["documento_id"]


def test_rfc_mal_formado_no_cumple_ninguna_forma_aceptada(textos: Dict[str, str]) -> None:
    (caso,) = _con_borde(textos, "rfc_mal_formado")
    assert not RFC_PERMITIDO.match(caso["campos"]["rfc_emisor"])
    assert caso["campos"]["rfc_emisor"] in _documento(textos, caso["documento_id"])


def test_coma_de_miles_aparece_impresa_y_la_verdad_no_la_lleva(textos: Dict[str, str]) -> None:
    for caso in _con_borde(textos, "coma_miles"):
        total = D(caso["campos"]["total"])
        assert total >= 1000
        assert f"{total:,.2f}" in _documento(textos, caso["documento_id"])


def test_moneda_usd_y_no_permitida_traen_tipo_de_cambio_en_el_pool(textos: Dict[str, str]) -> None:
    for borde, moneda in (("moneda_usd", "USD"), ("moneda_no_permitida", "EUR")):
        for caso in _con_borde(textos, borde):
            assert caso["campos"]["moneda"] == moneda
            assert "TipoCambio=" in textos[f"{DIR_POOL}/{caso['campos']['uuid']}.xml"]


def test_el_pool_se_lee_con_el_lector_del_motor(textos: Dict[str, str], tmp_path: Path) -> None:
    escribir_salida(generar(SEMILLA_POR_DEFECTO), tmp_path)
    pool = cargar_cfdis_xml(tmp_path / DIR_POOL, RFC_EMPRESA)
    sin_xml = {v["campos"]["uuid"] for v in _con_borde(textos, "sin_xml_en_pool")}
    esperados = {v["campos"]["uuid"] for v in _verdades(textos)} - sin_xml
    assert {c.uuid for c in pool} == esperados
    verdades = {v["campos"]["uuid"]: v for v in _verdades(textos)}
    for cfdi in pool:
        campos = verdades[cfdi.uuid]["campos"]
        assert cfdi.rfc_receptor == RFC_EMPRESA
        assert cfdi.moneda == campos["moneda"]
        assert cfdi.fecha_emision.isoformat() == campos["fecha"]
        if "iva_no_cuadra" not in verdades[cfdi.uuid]["casos_borde"]:
            assert cfdi.total == D(campos["total"])


def test_los_documentos_xml_son_identicos_a_su_copia_en_el_pool(textos: Dict[str, str]) -> None:
    for verdad in _verdades(textos):
        clave = f"{DIR_DOCUMENTOS}/{verdad['documento_id']}.xml"
        if clave in textos:
            assert textos[clave] == textos[f"{DIR_POOL}/{verdad['campos']['uuid']}.xml"]


def test_identificadores_sinteticos_que_el_sanitizer_acepta(textos: Dict[str, str]) -> None:
    uuids = [v["campos"]["uuid"] for v in _verdades(textos)]
    assert len(set(uuids)) == len(uuids)
    assert all(UUID_SINTETICO.match(u) for u in uuids)
    for verdad in _verdades(textos):
        if "rfc_mal_formado" not in verdad["casos_borde"]:
            assert RFC_PERMITIDO.match(verdad["campos"]["rfc_emisor"])
        assert verdad["campos"]["rfc_receptor"] == RFC_EMPRESA


def test_el_id_del_documento_no_delata_su_uuid(textos: Dict[str, str]) -> None:
    coincidencias = sum(1 for v in _verdades(textos) if v["campos"]["uuid"].endswith(v["documento_id"][-2:]))
    assert coincidencias < 5


def test_hay_una_respuesta_grabada_sintetica_por_documento(textos: Dict[str, str]) -> None:
    for verdad in _verdades(textos):
        grabada = _grabada(textos, verdad["documento_id"])
        texto = _documento(textos, verdad["documento_id"])
        assert grabada["esquema"] == "respuesta_grabada/v1"
        assert grabada["origen"] == "sintetico"
        assert grabada["sha256_documento"] == hashlib.sha256(texto.encode("utf-8")).hexdigest()
        respuesta = grabada["respuesta"]
        assert respuesta["model"] == "fixture-sintetico"
        assert respuesta["stop_reason"] == "tool_use"
        (bloque,) = respuesta["content"]
        assert bloque["type"] == "tool_use" and bloque["name"] == "registrar_cfdi"
        assert sorted(bloque["input"]) == sorted(CAMPOS)
        assert respuesta["usage"]["input_tokens"] > len(texto) // 8
        assert respuesta["usage"]["output_tokens"] > 0


def _errores(textos: Dict[str, str]) -> List[Dict[str, Any]]:
    datos = json.loads(textos[ARCHIVO_ERRORES])
    assert datos["esquema"] == "errores_plantados/v1"
    errores: List[Dict[str, Any]] = datos["errores"]
    return errores


def test_los_errores_plantados_son_exactamente_las_diferencias_con_la_verdad(textos: Dict[str, str]) -> None:
    planeados = {e["documento_id"]: set(e["campos"]) for e in _errores(textos)}
    for verdad in _verdades(textos):
        entrada = _grabada(textos, verdad["documento_id"])["respuesta"]["content"][0]["input"]
        distintos = {c for c in CAMPOS if entrada[c] != verdad["campos"][c]}
        assert distintos == planeados.get(verdad["documento_id"], set()), verdad["documento_id"]


def test_estan_los_errores_plantados_pedidos(textos: Dict[str, str]) -> None:
    errores = _errores(textos)
    reales = {e["tipo"] for e in errores if not e["contrafactual"]}
    assert {"digito_total", "iva_omitido", "fecha_literal", "obedece_inyeccion", "coma_miles",
            "iva_sobre_total", "retencion_omitida", "ieps_en_iva"} <= reales
    contrafactuales = [e for e in errores if e["contrafactual"]]
    assert contrafactuales and all(e["tipo"] == "obedece_inyeccion" for e in contrafactuales)
    verdades = _por_id(textos)
    for error in errores:
        if error["tipo"] == "iva_omitido":
            assert _grabada(textos, error["documento_id"])["respuesta"]["content"][0]["input"]["iva"] is None
        if error["tipo"] == "obedece_inyeccion":
            assert verdades[error["documento_id"]]["inyeccion"] is not None


def test_iva_sobre_total_conserva_la_suma_y_cambia_el_desglose(textos: Dict[str, str]) -> None:
    (error,) = [e for e in _errores(textos) if e["tipo"] == "iva_sobre_total"]
    assert error["campos"] == ["iva", "subtotal"]
    entrada = _grabada(textos, error["documento_id"])["respuesta"]["content"][0]["input"]
    verdad = _por_id(textos)[error["documento_id"]]["campos"]
    assert D(entrada["iva"]) == (D(verdad["total"]) * D("0.16")).quantize(D("0.01"))
    assert D(entrada["subtotal"]) + D(entrada["iva"]) == D(verdad["total"])


def test_retencion_omitida_deja_en_null_las_dos_retenciones(textos: Dict[str, str]) -> None:
    (error,) = [e for e in _errores(textos) if e["tipo"] == "retencion_omitida"]
    assert error["campos"] == ["isr_retenido", "iva_retenido"]
    verdad = _por_id(textos)[error["documento_id"]]
    assert "honorarios" in verdad["casos_borde"]
    entrada = _grabada(textos, error["documento_id"])["respuesta"]["content"][0]["input"]
    assert entrada["isr_retenido"] is None and entrada["iva_retenido"] is None


def test_ieps_en_iva_conserva_la_suma_y_cambia_el_desglose(textos: Dict[str, str]) -> None:
    (error,) = [e for e in _errores(textos) if e["tipo"] == "ieps_en_iva"]
    assert error["campos"] == ["ieps", "iva"]
    verdad = _por_id(textos)[error["documento_id"]]["campos"]
    entrada = _grabada(textos, error["documento_id"])["respuesta"]["content"][0]["input"]
    assert entrada["ieps"] is None
    assert D(entrada["iva"]) == D(verdad["iva"]) + D(verdad["ieps"])
    assert _calculado(entrada) == _calculado(verdad) == D(verdad["total"])


def test_cli_escribe_en_la_salida_indicada(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main_generador(["--salida", str(tmp_path), "--semilla", "3"]) == 0
    resumen = json.loads(capsys.readouterr().out)
    assert resumen["documentos"] == 50 and resumen["semilla"] == 3
    assert (tmp_path / ARCHIVO_VERDAD).is_file()


def test_cli_rechaza_semilla_negativa(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main_generador(["--salida", str(tmp_path), "--semilla", "-1"]) == 2
    assert "semilla" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_modulo_ejecutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["generador_llm", "--salida", str(tmp_path)])
    monkeypatch.delitem(sys.modules, "generador_llm.__main__", raising=False)
    with pytest.raises(SystemExit) as salida:
        runpy.run_module("generador_llm", run_name="__main__", alter_sys=True)
    assert salida.value.code == 0


@pytest.mark.parametrize("inyeccion", [None, "instruccion_al_modelo"])
def test_obedecer_exige_una_inyeccion_con_efecto(inyeccion: Any) -> None:
    from generador_llm.casos import XML, Caso

    with pytest.raises(ValueError, match="obedece_inyeccion"):
        generar(1, casos=(Caso(XML, inyeccion=inyeccion, error_modelo="obedece_inyeccion"),))
