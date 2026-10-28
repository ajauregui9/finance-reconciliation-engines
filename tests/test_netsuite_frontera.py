"""Contrato de la frontera de entrada del módulo NetSuite (CFDIs, CSV de carga y fechas).

Los CFDIs traen montos como texto con hasta dos decimales y dígitos ASCII: nada se
redondea. El JSON de carga se lee exacto para que la validación previa reporte
`importe_invalido` con más de dos decimales; los dígitos no ASCII se rechazan al leer.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

from netsuite_gl.carga_modelo import ErrorEntrada, asientos_desde_json
from netsuite_gl.cfdis import ErrorInsumo, leer_cfdis
from netsuite_gl.cli import main
from netsuite_gl.fechas import fecha_iso
from netsuite_gl.montos import ErrorMonto, a_decimal

ROOT = Path(__file__).resolve().parents[1]
CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"
EMPRESA = "RFC_EMPRESA_DEMO"


def _registro(**cambios: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = json.loads(CFDIS.read_text(encoding="utf-8").splitlines()[0])
    return {**base, **cambios}


def _cfdis(tmp_path: Path, **cambios: Any) -> Path:
    ruta = tmp_path / "cfdis.jsonl"
    ruta.write_text(json.dumps(_registro(**cambios), ensure_ascii=False) + "\n", encoding="utf-8")
    return ruta


def _asientos(debito: str) -> str:
    lineas = [{"cuenta": "6110-001", "debito": debito, "credito": "0.00", "clase": None, "entidad": None, "memo": ""},
              {"cuenta": "6120-001", "debito": "0.00", "credito": "1.00", "clase": None, "entidad": None, "memo": ""}]
    return json.dumps({"asientos": [{"id_externo": "AJ-1", "fecha": "2026-07-31", "periodo": "Jul 2026",
                                     "memo": "m", "referencia": None, "lineas": lineas}]}, ensure_ascii=False)


# ------------------------------------------------------------------ a_decimal
@pytest.mark.parametrize("crudo, esperado", [("10.01", "10.01"), (" 7.1 ", "7.10"), (100, "100.00"),
                                             (Decimal("-2.5"), "-2.50"), ("-0.00", "0.00")])
def test_monto_valido(crudo: Any, esperado: str) -> None:
    assert str(a_decimal(crudo)) == esperado


@pytest.mark.parametrize("crudo", ["١٠.٠٠", "10.005", "-0.001", "1 000.00", "1,000.00", "1,00.00", "1e2",
                                   0.1 + 0.2, 10.0, Decimal("2.345")])
def test_monto_fuera_de_contrato(crudo: Any) -> None:
    with pytest.raises(ErrorMonto):
        a_decimal(crudo)


# ------------------------------------------------------------------- CFDIs
@pytest.mark.parametrize("campo", ["subtotal", "iva", "total", "total_mxn"])
@pytest.mark.parametrize("valor", ["8488.375", "٨٤٨٨.٣٧"])
def test_cfdi_con_monto_fuera_de_contrato(tmp_path: Path, campo: str, valor: str) -> None:
    with pytest.raises(ErrorInsumo, match=rf"línea 1: {campo} inválido"):
        leer_cfdis(_cfdis(tmp_path, **{campo: valor}), EMPRESA)


@pytest.mark.parametrize("tipo_cambio", ["١٨.٨١٢٥", "18.8125001", "-18.81", "0", "18,81"])
def test_cfdi_tipo_de_cambio_fuera_de_contrato(tmp_path: Path, tipo_cambio: str) -> None:
    ruta = _cfdis(tmp_path, moneda="USD", tipo_cambio=tipo_cambio, total_mxn="185232.19")
    with pytest.raises(ErrorInsumo, match="tipo_cambio"):
        leer_cfdis(ruta, EMPRESA)


@pytest.mark.parametrize("fecha", ["٢٠٢٦-٠٦-٢٠", "20260620", "2026-06-20\n"])
def test_fecha_solo_ascii(fecha: str) -> None:
    with pytest.raises(ValueError, match="AAAA-MM-DD"):
        fecha_iso(fecha)


# ----------------------------------------------------------- JSON de carga
@pytest.mark.parametrize("debito", ["١.٠٠", "1 .00", "1,0.00", "1e0"])
def test_carga_con_texto_no_decimal_ascii(debito: str) -> None:
    with pytest.raises(ErrorEntrada, match="debito"):
        asientos_desde_json(_asientos(debito))


def test_carga_conserva_decimales_para_la_validacion() -> None:
    (asiento,) = asientos_desde_json(_asientos("1.005"))
    assert asiento.lineas[0].debito == Decimal("1.005")


def test_cli_cfdi_fuera_de_contrato_sale_con_2(tmp_path: Path) -> None:
    assert main(["discrepancias", "--cfdis", str(_cfdis(tmp_path, total="9846.515"))]) == 2


def test_cli_carga_con_digitos_no_ascii_sale_con_2(tmp_path: Path) -> None:
    entrada = tmp_path / "asientos.json"
    entrada.write_text(_asientos("١.٠٠"), encoding="utf-8")
    salida = tmp_path / "carga.csv"
    assert main(["generar-csv", "--asientos", str(entrada), "--formato", "journal", "--salida", str(salida)]) == 2
    assert not salida.exists()
