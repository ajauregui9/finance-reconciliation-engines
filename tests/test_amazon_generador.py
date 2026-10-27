"""Pruebas del generador sintético de liquidaciones de Amazon (examples/generador_amazon)."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path
from typing import Dict

import pytest

import test_amazon_soporte as soporte
from generador_amazon import ParametrosGenerador, escribir, generar
from generador_amazon.__main__ import main as main_generador

ARCHIVOS_ESPERADOS = {
    "liquidacion_2026-04.csv", "liquidacion_2026-05.csv", "liquidacion_2026-06.csv", "liquidacion_2026-07.csv",
    "publicidad_consola.csv", "facturas_publicidad.json", "venta_erp.json", "oraculo.json",
}


def _huella(archivos: Dict[str, str]) -> str:
    sha = hashlib.sha256()
    for nombre in sorted(archivos):
        sha.update(nombre.encode("utf-8"))
        sha.update(archivos[nombre].encode("utf-8"))
    return sha.hexdigest()


@pytest.fixture(scope="module")
def archivos() -> Dict[str, str]:
    return generar(ParametrosGenerador())


@pytest.fixture(scope="module")
def oraculo(archivos: Dict[str, str]) -> Dict[str, object]:
    return json.loads(archivos["oraculo.json"])  # type: ignore[no-any-return]


class TestDeterminismo:
    def test_produce_los_archivos_esperados(self, archivos: Dict[str, str]) -> None:
        assert set(archivos) == ARCHIVOS_ESPERADOS

    def test_misma_semilla_mismos_bytes(self, archivos: Dict[str, str]) -> None:
        assert _huella(generar(ParametrosGenerador())) == _huella(archivos)

    def test_otra_semilla_otros_datos(self, archivos: Dict[str, str]) -> None:
        otros = generar(ParametrosGenerador(semilla=7))
        assert otros["liquidacion_2026-05.csv"] != archivos["liquidacion_2026-05.csv"]

    def test_los_archivos_versionados_son_los_regenerados(self, archivos: Dict[str, str]) -> None:
        for nombre, contenido in archivos.items():
            versionado = (soporte.DIR_SINTETICO / nombre).read_bytes()
            assert versionado == contenido.encode("utf-8"), f"{nombre} difiere: corre el generador"

    def test_salida_sin_bom_ni_retornos_de_carro(self, archivos: Dict[str, str]) -> None:
        for nombre, contenido in archivos.items():
            assert not contenido.startswith("﻿"), nombre
            assert "\r" not in contenido, nombre
            assert contenido.endswith("\n"), nombre


class TestEscenarios:
    def test_un_mes_con_retencion_fuera_de_banda(self, oraculo: Dict[str, object]) -> None:
        assert oraculo["meses_retencion_fuera_de_banda"] == ["2026-06"]

    def test_cola_en_varios_meses_y_una_negativa(self, oraculo: Dict[str, object]) -> None:
        meses = oraculo["meses"]
        assert isinstance(meses, dict)
        con_cola = [m for m, datos in meses.items() if datos["venta_neta_cola"]]
        assert con_cola == ["2026-05", "2026-06", "2026-07"]
        assert oraculo["meses_cola_negativa"] == ["2026-06"]

    def test_publicidad_en_tres_fuentes_cada_mes(self, oraculo: Dict[str, object]) -> None:
        meses = oraculo["meses"]
        assert isinstance(meses, dict)
        for mes, datos in meses.items():
            fuentes = datos["publicidad_sin_iva"]
            assert set(fuentes) == {"consola", "factura", "liquidacion"}, mes
            assert Decimal(fuentes["consola"]) > 0
            assert abs(Decimal(fuentes["liquidacion"]) - Decimal(fuentes["consola"])) <= Decimal("0.02")
            assert datos["filas_publicidad_liquidacion"] >= 2

    def test_casos_borde_cubren_varios_husos_y_ambos_sentidos(self, oraculo: Dict[str, object]) -> None:
        casos = oraculo["casos_borde"]
        assert isinstance(casos, list)
        husos = {c["huso"] for c in casos}
        assert {"UTC-07:00", "UTC-08:00", "UTC+00:00"} <= husos
        adelante = [c for c in casos if c["mes_liquidacion"] > c["fecha_hora_local"][:7]]
        atras = [c for c in casos if c["mes_liquidacion"] < c["fecha_hora_local"][:7]]
        assert adelante and atras
        assert any(c["desfase_fijo_de_una_hora_falla"] for c in casos)

    def test_parametros_invalidos(self) -> None:
        with pytest.raises(ValueError, match="semilla"):
            ParametrosGenerador(semilla=-1)
        with pytest.raises(ValueError, match="pedidos_por_mes"):
            ParametrosGenerador(pedidos_por_mes=1)


class TestCli:
    def test_escribe_en_el_directorio_pedido(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert main_generador(["--salida", str(tmp_path / "x")]) == 0
        assert {p.name for p in (tmp_path / "x").iterdir()} == ARCHIVOS_ESPERADOS
        assert json.loads(capsys.readouterr().out)["archivos"] == sorted(ARCHIVOS_ESPERADOS)

    def test_parametro_invalido_sale_con_2(self, tmp_path: Path) -> None:
        assert main_generador(["--salida", str(tmp_path / "x"), "--semilla", "-3"]) == 2

    def test_escribir_devuelve_rutas_ordenadas(self, tmp_path: Path, archivos: Dict[str, str]) -> None:
        rutas = escribir(archivos, tmp_path / "y")
        assert [r.name for r in rutas] == sorted(ARCHIVOS_ESPERADOS)
