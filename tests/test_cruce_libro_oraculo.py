"""Prueba de aceptación del cruce con libro mayor contra el oráculo sintético."""
from __future__ import annotations

import json
import sys
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAIZ_SKILL = ROOT / "skills" / "credit-card-reconciliation"
for ruta in (RAIZ_SKILL, ROOT / "examples"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

import generador_sintetico as gs  # noqa: E402
from conciliacion import cruce_libro  # noqa: E402
from conciliacion.cruce_libro_modelo import ConfigCruceLibro  # noqa: E402

SINTETICO = ROOT / "examples" / "synthetic"


def _correr(carpeta: Path) -> Dict[str, Any]:
    return cruce_libro.ejecutar(carpeta / "universo_cargos_esperado.jsonl", carpeta / "libro_mayor.csv",
                                carpeta / "veredictos_libro.csv", ConfigCruceLibro())


def _grupos(oraculo: Dict[str, Any]) -> Dict[str, set]:
    return {c: set(g["asientos"]) for g in oraculo["grupos_empate"] for c in g["cargos"]}


def _diferencias_con_oraculo(reporte: Dict[str, Any], oraculo: Dict[str, Any]) -> list:
    """Cargos cuya propuesta no es una respuesta correcta según el oráculo."""
    salida = {c["cargo_id"]: c for c in reporte["cargos"]}
    grupos = _grupos(oraculo)
    malos = []
    for esperado in oraculo["cargos"]:
        cid, lm = esperado["cargo_id"], esperado["libro_mayor"]
        prop = salida[cid]["propuesta"]
        permitidos = grupos.get(cid, set()) | ({lm["esperado"]} if lm["esperado"] else set())
        asiento_ok = prop["asiento_id"] in permitidos if lm["esperado"] else prop["asiento_id"] is None
        if not (asiento_ok and prop["riesgo_cubeta"] == lm["riesgo_cubeta"]
                and prop["motivo_sin_cruce"] == lm["motivo_sin_cruce"]
                and prop["asiento_id"] not in lm["prohibidos"]):
            malos.append((cid, esperado["casos"], lm, prop))
    return malos


@pytest.fixture(scope="module")
def oraculo() -> Dict[str, Any]:
    return json.loads((SINTETICO / "oraculo.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def reporte() -> Dict[str, Any]:
    return _correr(SINTETICO)


@pytest.fixture(scope="module")
def por_cargo(reporte: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {c["cargo_id"]: c for c in reporte["cargos"]}


def _con_caso(oraculo: Dict[str, Any], caso: str) -> list:
    return [o for o in oraculo["cargos"] if caso in o["casos"]]


class TestPropuestaContraOraculo:
    def test_cada_cargo_tiene_una_respuesta_correcta(self, reporte: Dict[str, Any], oraculo: Dict[str, Any]) -> None:
        assert [c["cargo_id"] for c in reporte["cargos"]] == [o["cargo_id"] for o in oraculo["cargos"]]
        assert _diferencias_con_oraculo(reporte, oraculo) == []

    def test_conteo_de_motivos_es_el_del_oraculo(self, reporte: Dict[str, Any], oraculo: Dict[str, Any]) -> None:
        esperados = Counter(o["libro_mayor"]["motivo_sin_cruce"] for o in oraculo["cargos"])
        obtenidos = Counter(c["propuesta"]["motivo_sin_cruce"] for c in reporte["cargos"])
        assert obtenidos == esperados

    def test_sin_candidato_y_descartado_por_nombre_se_distinguen(
            self, oraculo: Dict[str, Any], por_cargo: Dict[str, Dict[str, Any]]) -> None:
        for o in oraculo["cargos"]:
            motivo, candidatos = o["libro_mayor"]["motivo_sin_cruce"], por_cargo[o["cargo_id"]]["candidatos"]
            if motivo == "sin_candidato":
                assert candidatos["total"] == 0, o["cargo_id"]
            elif motivo == "descartado_por_nombre":
                assert candidatos["descartados_por_nombre"] >= 1, o["cargo_id"]
                assert candidatos["elegibles"] == 0
                (prohibido,) = o["libro_mayor"]["prohibidos"]
                assert prohibido in {m["asiento_id"] for m in candidatos["muestra"]}

    def test_cubeta_exige_monto_y_fecha_y_queda_marcada(
            self, oraculo: Dict[str, Any], por_cargo: Dict[str, Dict[str, Any]]) -> None:
        for o in _con_caso(oraculo, "libro_cubeta"):
            prop = por_cargo[o["cargo_id"]]["propuesta"]
            assert (prop["riesgo_cubeta"], prop["evidencia"]) == (True, "monto_y_fecha_cubeta")
            assert prop["similitud"] is None
        for o in _con_caso(oraculo, "libro_cubeta_fecha_lejana"):
            cargo = por_cargo[o["cargo_id"]]
            assert cargo["propuesta"]["motivo_sin_cruce"] == "cubeta_evidencia_insuficiente"
            assert cargo["candidatos"]["cubeta_fuera_de_fecha"] >= 1
        assert not any(c["propuesta"]["riesgo_cubeta"] for c in por_cargo.values()
                       if c["propuesta"]["evidencia"] == "monto_y_nombre")

    def test_registros_propios_vienen_con_nombre_sobre_el_umbral(self, por_cargo: Dict[str, Dict[str, Any]]) -> None:
        umbral = ConfigCruceLibro().umbral_similitud
        for c in por_cargo.values():
            if c["propuesta"]["evidencia"] == "monto_y_nombre":
                assert Decimal(c["propuesta"]["similitud"]) >= umbral, c["cargo_id"]


class TestVeredictosContraOraculo:
    def test_conflictos_reportados_son_los_plantados(self, reporte: Dict[str, Any], oraculo: Dict[str, Any],
                                                     por_cargo: Dict[str, Dict[str, Any]]) -> None:
        for o in oraculo["cargos"]:
            assert por_cargo[o["cargo_id"]]["conflicto"] == o["libro_mayor"]["conflicto"], o["cargo_id"]
        esperados = sorted((o["cargo_id"], o["libro_mayor"]["conflicto"]) for o in oraculo["cargos"]
                           if o["libro_mayor"]["conflicto"])
        assert [(c["cargo_id"], c["tipo"]) for c in reporte["conflictos"]] == esperados
        assert reporte["resumen"]["veredictos"]["conflictos"] == oraculo["veredictos_libro"]["conflictos"]

    def test_veredicto_humano_nunca_se_sobrescribe(self, oraculo: Dict[str, Any],
                                                  por_cargo: Dict[str, Dict[str, Any]]) -> None:
        con_veredicto = [o for o in oraculo["cargos"] if o["libro_mayor"]["veredicto"]]
        assert len(con_veredicto) == oraculo["veredictos_libro"]["filas"]
        for o in con_veredicto:
            final = por_cargo[o["cargo_id"]]["final"]
            assert final["origen"] == "veredicto_humano"
            assert final["asiento_id"] == o["libro_mayor"]["veredicto"]["asiento_id"]

    def test_cargos_sin_veredicto_conservan_la_propuesta(self, por_cargo: Dict[str, Dict[str, Any]]) -> None:
        for c in por_cargo.values():
            if c["veredicto"] is None:
                assert c["final"]["origen"] == "motor"
                assert c["final"]["asiento_id"] == c["propuesta"]["asiento_id"]
                assert c["final"]["motivo_sin_cruce"] == c["propuesta"]["motivo_sin_cruce"]
                assert c["final"]["reasignado_por_veredicto"] is False

    def test_candados_en_verde(self, reporte: Dict[str, Any]) -> None:
        assert {k: v["ok"] for k, v in reporte["candados"].items()} == {
            "cobertura": True, "exclusividad": True, "partida_doble": True}


@pytest.mark.parametrize("semilla", [1, 2, 3])
def test_otras_semillas_tambien_coinciden_con_su_oraculo(tmp_path: Path, semilla: int) -> None:
    gs.escribir_salida(gs.generar(gs.ConfigGenerador(semilla=semilla)), tmp_path)
    reporte = _correr(tmp_path)
    oraculo = json.loads((tmp_path / "oraculo.json").read_text(encoding="utf-8"))
    assert _diferencias_con_oraculo(reporte, oraculo) == []
    conflictos = {c["cargo_id"]: c["conflicto"] for c in reporte["cargos"]}
    assert conflictos == {o["cargo_id"]: o["libro_mayor"]["conflicto"] for o in oraculo["cargos"]}
