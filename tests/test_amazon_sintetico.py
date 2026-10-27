"""Prueba de punta a punta: el cierre sobre examples/synthetic_amazon contra su oráculo."""
from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

import test_amazon_soporte as soporte
from cierre_amazon.cierre import CierreMes, ResultadoCorrida, cerrar
from cierre_amazon.cli import main
from cierre_amazon.config import CONCEPTOS_TARIFA, cargar_config, con_fuente_publicidad
from cierre_amazon.huso import mes_en_huso
from cierre_amazon.insumos import cargar_insumos
from cierre_amazon.ubicacion import ubicar

D = Decimal


@pytest.fixture(scope="module")
def oraculo() -> Dict[str, Any]:
    return json.loads((soporte.DIR_SINTETICO / "oraculo.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@pytest.fixture(scope="module")
def resultado() -> ResultadoCorrida:
    config = cargar_config(soporte.CONFIG_EJEMPLO)
    return cerrar(cargar_insumos(soporte.DIR_SINTETICO, config), config)


def _mes(resultado: ResultadoCorrida, mes: str) -> CierreMes:
    return next(c for c in resultado.meses if c.mes == mes)


class TestContraElOraculo:
    def test_cierra_los_cuatro_meses_sin_candados_en_falla(self, resultado: ResultadoCorrida) -> None:
        assert [c.mes for c in resultado.meses] == ["2026-04", "2026-05", "2026-06", "2026-07"]
        assert resultado.ok
        assert dict(resultado.fuera_de_meses) == {} and resultado.alertas == ()

    def test_filas_totales_y_cohortes(self, resultado: ResultadoCorrida, oraculo: Dict[str, Any]) -> None:
        for mes, esperado in oraculo["meses"].items():
            grupos = _mes(resultado, mes).grupos
            assert grupos.todas.filas == esperado["filas"], mes
            assert grupos.todas.total == D(esperado["total_liquidado"]), mes
            assert grupos.cohorte_mes.venta_neta == D(esperado["venta_neta_cohorte_mes"]), mes
            assert {o: a.venta_neta for o, a in grupos.colas.items()} == {
                o: D(v) for o, v in esperado["venta_neta_cola"].items()}, mes

    def test_tarifas_y_cargos(self, resultado: ResultadoCorrida, oraculo: Dict[str, Any]) -> None:
        for mes, esperado in oraculo["meses"].items():
            gasto = _mes(resultado, mes).gasto
            for concepto in CONCEPTOS_TARIFA:
                assert gasto.tarifas[concepto].cohorte_mes == D(esperado["tarifas_cohorte_mes"][concepto]), mes
                assert gasto.tarifas[concepto].cola_real == D(esperado["tarifas_cola"][concepto]), mes
            assert dict(gasto.cargos_periodo) == {t: D(v) for t, v in esperado["cargos_periodo"].items()}, mes

    def test_publicidad_por_fuente(self, resultado: ResultadoCorrida, oraculo: Dict[str, Any]) -> None:
        for mes, esperado in oraculo["meses"].items():
            publicidad = _mes(resultado, mes).publicidad
            fuentes = esperado["publicidad_sin_iva"]
            assert publicidad.liquidacion_sin_iva == D(fuentes["liquidacion"]), mes
            assert publicidad.consola == D(fuentes["consola"]), mes
            assert publicidad.factura is not None and publicidad.factura.subtotal == D(fuentes["factura"]), mes
            assert publicidad.filas_liquidacion == esperado["filas_publicidad_liquidacion"], mes
            assert _mes(resultado, mes).gasto.publicidad == D(fuentes["consola"]), mes

    def test_retencion_y_su_alerta(self, resultado: ResultadoCorrida, oraculo: Dict[str, Any]) -> None:
        for mes, esperado in oraculo["meses"].items():
            cierre = _mes(resultado, mes)
            assert cierre.retencion.base == D(esperado["retencion"]["base"]), mes
            assert cierre.retencion.retenida == D(esperado["retencion"]["retenida"]), mes
        fuera = [c.mes for c in resultado.meses for a in c.alertas if a.codigo == "retencion_fuera_de_banda"]
        assert fuera == oraculo["meses_retencion_fuera_de_banda"]

    def test_unica_alerta_es_la_de_retencion(self, resultado: ResultadoCorrida) -> None:
        codigos = sorted({a.codigo for c in resultado.meses for a in c.alertas})
        assert codigos == ["retencion_fuera_de_banda"]

    def test_venta_pendiente_igual_a_la_cola_que_llega(self, resultado: ResultadoCorrida,
                                                      oraculo: Dict[str, Any]) -> None:
        for anterior, siguiente in zip(resultado.meses, resultado.meses[1:]):
            assert anterior.venta_erp == D(oraculo["venta_erp"][anterior.mes])
            assert anterior.venta_pendiente == siguiente.grupos.cola.venta_neta, anterior.mes

    def test_cola_negativa_conserva_el_signo(self, resultado: ResultadoCorrida, oraculo: Dict[str, Any]) -> None:
        for mes in oraculo["meses_cola_negativa"]:
            cierre = _mes(resultado, mes)
            assert cierre.grupos.cola.venta_neta < 0
            assert cierre.gasto.tarifas["comision"].cola_real < 0
            anterior = _mes(resultado, "2026-05")
            assert anterior.provision is not None and anterior.provision.comision < 0

    def test_suma_de_la_corrida_es_gasto_real_mas_ultima_provision(self, resultado: ResultadoCorrida) -> None:
        ultima = resultado.meses[-1].provision
        assert ultima is not None
        for concepto in CONCEPTOS_TARIFA:
            devengado = sum((c.gasto.tarifas[concepto].total for c in resultado.meses), D("0"))
            real = sum((c.gasto.tarifas[concepto].cohorte_mes + c.gasto.tarifas[concepto].cola_real
                        for c in resultado.meses), D("0"))
            assert devengado == real + ultima.concepto(concepto), concepto


class TestCorteHorario:
    def test_casos_borde_caen_donde_dice_el_oraculo(self, oraculo: Dict[str, Any]) -> None:
        config = cargar_config(soporte.CONFIG_EJEMPLO)
        insumos = cargar_insumos(soporte.DIR_SINTETICO, config)
        por_lugar = {(u.fila.archivo, u.fila.numero): u for u in ubicar(insumos.archivos, config)}
        for caso in oraculo["casos_borde"]:
            ubicada = por_lugar[(caso["archivo"], caso["fila"])]
            assert ubicada.fila.pedido == caso["pedido"]
            assert (ubicada.mes, ubicada.cohorte) == (caso["mes_liquidacion"], caso["mes_pedido"]), caso["nota"]

    def test_un_desfase_fijo_de_una_hora_se_equivocaria(self, oraculo: Dict[str, Any]) -> None:
        config = cargar_config(soporte.CONFIG_EJEMPLO)
        insumos = cargar_insumos(soporte.DIR_SINTETICO, config)
        por_lugar = {(f.archivo, f.numero): f for a in insumos.archivos for f in a.filas}
        fallan = [c for c in oraculo["casos_borde"] if c["desfase_fijo_de_una_hora_falla"]]
        assert {c["huso"] for c in fallan} == {"UTC-08:00", "UTC+00:00"}
        for caso in fallan:
            fila = por_lugar[(caso["archivo"], caso["fila"])]
            ingenuo = (fila.instante.replace(tzinfo=None) + timedelta(hours=1)).strftime("%Y-%m")
            assert ingenuo != caso["mes_liquidacion"]
            assert mes_en_huso(fila.instante, config.huso_cierre) == caso["mes_liquidacion"]


class TestFuentesYCli:
    @pytest.mark.parametrize("fuente", ["liquidacion", "factura"])
    def test_otra_fuente_autoritativa_cambia_solo_centavos(self, resultado: ResultadoCorrida, fuente: str) -> None:
        config = con_fuente_publicidad(cargar_config(soporte.CONFIG_EJEMPLO), fuente)
        otro = cerrar(cargar_insumos(soporte.DIR_SINTETICO, config), config)
        assert otro.ok
        for base, alterno in zip(resultado.meses, otro.meses):
            assert abs(base.gasto.total - alterno.gasto.total) <= D("0.02")
            assert base.gasto.total - base.gasto.publicidad == alterno.gasto.total - alterno.gasto.publicidad

    def test_cli_determinista_y_xlsx_verificado(self, tmp_path: Path) -> None:
        huellas = []
        for intento in range(2):
            salida = tmp_path / f"cierre_{intento}.json"
            codigo = main(["--datos", str(soporte.DIR_SINTETICO), "--salida", str(salida),
                           "--xlsx", str(tmp_path / f"cierre_{intento}.xlsx")])
            assert codigo == 0
            huellas.append(hashlib.sha256(salida.read_bytes()).hexdigest())
        assert huellas[0] == huellas[1]


class TestPuntosDeEntrada:
    """La CLI real, como la corre una persona: `python3 -m cierre_amazon` y por ruta."""

    def _correr(self, *argumentos: str) -> "subprocess.CompletedProcess[str]":
        entorno = {**os.environ, "PYTHONPATH": str(soporte.DIR_AMAZON)}
        return subprocess.run([sys.executable, *argumentos], capture_output=True, text=True, env=entorno,
                              cwd=str(soporte.RAIZ), check=False)

    def test_como_modulo(self) -> None:
        proceso = self._correr("-m", "cierre_amazon", "--datos", str(soporte.DIR_SINTETICO), "--mes", "2026-06")
        assert proceso.returncode == 0, proceso.stderr
        documento = json.loads(proceso.stdout)
        assert [m["mes"] for m in documento["meses"]] == ["2026-06"]
        assert "retencion_fuera_de_banda" in [a["codigo"] for a in documento["meses"][0]["alertas"]]

    def test_por_ruta_y_generador_por_ruta(self, tmp_path: Path) -> None:
        datos = tmp_path / "datos"
        generador = self._correr(str(soporte.DIR_EJEMPLOS / "generador_amazon"), "--salida", str(datos))
        assert generador.returncode == 0, generador.stderr
        proceso = self._correr(str(soporte.DIR_AMAZON / "cierre_amazon"), "--datos", str(datos),
                               "--salida", str(tmp_path / "c.json"))
        assert proceso.returncode == 0, proceso.stderr
        esperado = (soporte.DIR_SINTETICO / "oraculo.json").read_bytes()
        assert (datos / "oraculo.json").read_bytes() == esperado

    def test_main_del_paquete(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        monkeypatch.setattr(sys, "argv", ["cierre_amazon", "--datos", str(soporte.DIR_SINTETICO), "--mes", "2026-04"])
        with pytest.raises(SystemExit) as salida:
            runpy.run_module("cierre_amazon", run_name="__main__")
        assert salida.value.code == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True
