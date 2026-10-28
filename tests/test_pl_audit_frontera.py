"""Contrato de la frontera de entrada de la revisión del estado de resultados.

Montos y porcentajes: texto o número JSON con hasta dos decimales y dígitos ASCII; un
float pasa por su `repr` y uno ambiguo es error. Nada se redondea al leer. Un insumo
fuera de contrato termina la CLI con código 2.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from test_pl_audit_fixtures import RUTA_CONFIG_EJEMPLO, con_cuenta, con_valor, config_base, exportacion_base

import run_pl_audit
from auditoria_pl import ErrorEntrada, leer_config, leer_exportacion
from auditoria_pl.validacion import leer_fecha, leer_monto, leer_porcentaje

FUERA_DE_CONTRATO = ["١٠٠.٠٠", "100.005", "1 000.00", "1,000.00", "1,00.00", "1e2", 0.1 + 0.2, 100.005,
                     Decimal("1.00")]


@pytest.mark.parametrize("valor, esperado", [("1234.5", "1234.50"), ("+7", "7.00"), (7, "7.00"),
                                             (100.25, "100.25"), ("-0.01", "-0.01")])
def test_monto_valido(valor: object, esperado: str) -> None:
    assert str(leer_monto(valor, "x")) == esperado


@pytest.mark.parametrize("valor", FUERA_DE_CONTRATO)
def test_monto_fuera_de_contrato(valor: object) -> None:
    with pytest.raises(ErrorEntrada, match="cuentas"):
        leer_monto(valor, "cuentas[0].actual")


@pytest.mark.parametrize("valor", ["12.345", "١٢", 0.1 + 0.2])
def test_porcentaje_fuera_de_contrato(valor: object) -> None:
    with pytest.raises(ErrorEntrada, match="p"):
        leer_porcentaje(valor, "p")


@pytest.mark.parametrize("valor", ["٢٠٢٦-١٠-٠٦", "20261006", "2026-10-6"])
def test_fecha_solo_ascii(valor: str) -> None:
    with pytest.raises(ErrorEntrada, match="AAAA-MM-DD"):
        leer_fecha(valor, "fecha_extraccion")


def test_exportacion_con_monto_de_tres_decimales_nombra_la_ruta() -> None:
    exportacion = con_cuenta(exportacion_base(), "4010", actual="2370000.005")
    with pytest.raises(ErrorEntrada, match=r"cuentas\[\d+\]\.actual.*a lo más 2 decimales"):
        leer_exportacion(exportacion)


def test_config_con_porcentaje_no_ascii() -> None:
    config = con_valor(config_base(), "publicidad.objetivo_pct", "٨")
    with pytest.raises(ErrorEntrada, match="publicidad.objetivo_pct"):
        leer_config(config)


def test_cli_exportacion_fuera_de_contrato_sale_con_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exportacion = con_cuenta(exportacion_base(), "4010", actual=0.1 + 0.2)
    entrada = tmp_path / "exportacion.json"
    entrada.write_text(json.dumps(exportacion), encoding="utf-8")
    salida = tmp_path / "pl.json"
    codigo = run_pl_audit.main(["--periodo", exportacion["periodo"], "--config", str(RUTA_CONFIG_EJEMPLO),
                                "--entrada", str(entrada), "--salida", str(salida)])
    assert codigo == 2
    assert not salida.exists()
    assert "decimales significativos" in capsys.readouterr().err
