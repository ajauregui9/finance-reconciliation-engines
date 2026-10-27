"""Etapas del pipeline: lectura de insumos, candados del universo y adaptación a cada motor."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from conciliacion import cruce_libro_insumos
from conciliacion import universo as uv
from conciliacion.pipeline_etapas import (
    OpcionesPipeline,
    adaptar_universo,
    candados_universo,
    emisor_de_cargo,
    leer_insumos,
    motivos_provisional,
)
from conciliacion.pipeline_modelo import InsumoPipeline

RAIZ = Path(__file__).resolve().parents[1]
SINTETICO = RAIZ / "examples" / "synthetic"
UNIVERSO_ESPERADO = SINTETICO / "universo_cargos_esperado.jsonl"


@pytest.fixture(scope="module")
def universo() -> uv.Universo:
    return uv.construir_universo(SINTETICO)


def test_el_lector_del_libro_acepta_el_universo_como_texto() -> None:
    texto = UNIVERSO_ESPERADO.read_text(encoding="utf-8")
    desde_texto = cruce_libro_insumos.universo_desde_texto(texto, "universo.jsonl")
    assert desde_texto == cruce_libro_insumos.leer_universo(UNIVERSO_ESPERADO)
    with pytest.raises(cruce_libro_insumos.ErrorInsumo, match="universo.jsonl, línea 1"):
        cruce_libro_insumos.universo_desde_texto("[]\n", "universo.jsonl")


def test_adaptar_universo_entrega_el_mismo_texto_a_ambos_motores(universo: uv.Universo) -> None:
    adaptado = adaptar_universo(universo)
    assert adaptado.texto == UNIVERSO_ESPERADO.read_text(encoding="utf-8")
    assert adaptado.sha256 == hashlib.sha256(UNIVERSO_ESPERADO.read_bytes()).hexdigest()
    ids = [c.cargo_id for c in universo.cargos]
    assert [c.cargo_id for c in adaptado.cargos_cfdi] == ids
    assert [c.cargo_id for c in adaptado.cargos_libro] == ids


def test_candados_del_universo_con_nombre_por_emisor(universo: uv.Universo) -> None:
    candados = candados_universo(universo)
    assert {c.etapa for c in candados} == {"universo"} and all(c.cumple for c in candados)
    nombres = [c.nombre for c in candados]
    assert nombres[:2] == ["ALFA.num_movimientos", "ALFA.montos_legibles"]
    assert "BETA.saldo_al_corte" in nombres
    alfa_neto = next(c for c in candados if c.nombre == "ALFA.total_neto")
    assert alfa_neto.detalle == "esperado 94460.23, calculado 94460.23"


def test_emisor_de_cargo() -> None:
    assert emisor_de_cargo("BETA-0105") == "BETA"
    assert emisor_de_cargo("EMISOR_2-0001") == "EMISOR_2"


class TestLecturaDeInsumos:
    def test_corrida_completa_sin_motivos(self) -> None:
        insumos = leer_insumos(OpcionesPipeline(datos=SINTETICO))
        assert len(insumos.veredictos) == 12 and insumos.en_espera == ()
        assert motivos_provisional(OpcionesPipeline(datos=SINTETICO), insumos) == ()
        assert insumos.huellas["cfdis"]["registros"] == len(insumos.cfdis) == 254

    def test_universo_parcial_separa_los_veredictos_en_espera(self) -> None:
        opciones = OpcionesPipeline(datos=SINTETICO, estados_omitidos=("BETA",))
        insumos = leer_insumos(opciones)
        assert {emisor_de_cargo(v.cargo_id) for v in insumos.veredictos} == {"ALFA"}
        assert insumos.en_espera and {emisor_de_cargo(v.cargo_id) for v in insumos.en_espera} == {"BETA"}
        assert [(m.etapa, m.motivo) for m in motivos_provisional(opciones, insumos)] == [
            ("universo", "estado_omitido"), ("cruce_libro", "veredictos_en_espera")]

    def test_emisor_sin_cuenta_de_tarjeta_en_la_config_del_libro(self, tmp_path: Path) -> None:
        config = json.loads((RAIZ / "skills" / "credit-card-reconciliation" / "config" /
                             "cruce_libro.example.json").read_text(encoding="utf-8"))
        config["cuentas_tarjeta"] = {"ALFA": "2105-001"}
        ruta = tmp_path / "libro.json"
        ruta.write_text(json.dumps(config), encoding="utf-8")
        with pytest.raises(InsumoPipeline, match="^cruce_libro: .*BETA"):
            leer_insumos(OpcionesPipeline(datos=SINTETICO, config_libro=ruta))

    def test_veredictos_de_estados_omitidos_con_columnas_faltantes(self, tmp_path: Path) -> None:
        for nombre in ("resumen_estados_cuenta.json", "estado_cuenta_alfa.csv", "cfdis.jsonl", "libro_mayor.csv"):
            shutil.copyfile(SINTETICO / nombre, tmp_path / nombre)
        (tmp_path / "veredictos_libro.csv").write_text("cargo,veredicto\nBETA-0001,registrado\n", encoding="utf-8")
        with pytest.raises(InsumoPipeline, match="^cruce_libro: .*columnas obligatorias"):
            leer_insumos(OpcionesPipeline(datos=tmp_path, estados_omitidos=("BETA",)))

    def test_error_del_universo_lleva_el_prefijo_de_su_etapa(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoPipeline, match="^universo: "):
            leer_insumos(OpcionesPipeline(datos=tmp_path))
