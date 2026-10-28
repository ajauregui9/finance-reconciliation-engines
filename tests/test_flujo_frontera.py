"""Contrato de la frontera de entrada del flujo de 13 semanas.

Montos de los CSV: texto con signo opcional y hasta dos decimales, dígitos ASCII, sin
separador de miles; nada se redondea. Un insumo fuera de contrato sale con código 3, un
argumento o una config fuera de contrato con código 2 (spec, sección 9).
"""
from __future__ import annotations

import csv
import json
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

import pytest

from flujo.cli import fecha_corte, main
from flujo.config import ErrorConfig, validar_curva
from flujo.dinero import CERO, a_monto
from flujo.errores import ErrorInsumo
from flujo.fuentes import leer_saldos
from flujo.lectura import Registro

RAIZ = Path(__file__).resolve().parents[1]
CONFIG_EJEMPLO = RAIZ / "skills" / "cashflow-forecasting" / "config" / "flujo_ejemplo.json"
CORTE = "2026-11-02"
COLS_SALDOS = ("cuenta", "banco", "fecha_saldo", "moneda", "saldo")


def _saldos(tmp_path: Path, saldo: str, fecha: str = CORTE) -> Path:
    ruta = tmp_path / "saldos.csv"
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, lineterminator="\n")
        escritor.writerow(COLS_SALDOS)
        escritor.writerow(["CTA-1", "BANCO UNO", fecha, "MXN", saldo])
    return ruta


def _config_con(tmp_path: Path, **cambios: Any) -> Path:
    datos = json.loads(CONFIG_EJEMPLO.read_text(encoding="utf-8"))
    datos["insumos"] = {k: str((CONFIG_EJEMPLO.parent / v).resolve()) for k, v in datos["insumos"].items()}
    datos.update(cambios)
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    return ruta


# ------------------------------------------------------------------- a_monto
@pytest.mark.parametrize("texto, esperado", [("1234.5", "1234.50"), (" 10.01 ", "10.01"), ("-0.00", "0.00"),
                                             ("7", "7.00")])
def test_monto_valido(texto: str, esperado: str) -> None:
    resultado = a_monto(texto)
    assert str(resultado) == esperado
    assert resultado != CERO or not resultado.is_signed()


@pytest.mark.parametrize("valor, mensaje", [
    ("١٠٠.٠٠", "no ASCII"), ("100.005", "a lo más 2 decimales"), ("1 000.00", "espacios"),
    ("1,000.00", "separador de miles"), ("1,00.00", "separador de miles"), (0.1 + 0.2, "se espera texto"),
    (100, "se espera texto"), (Decimal("1.00"), "se espera texto"), ("1e3", "no es un importe"),
])
def test_monto_fuera_de_contrato(valor: object, mensaje: str) -> None:
    with pytest.raises(ValueError, match=mensaje):
        a_monto(valor)


# ---------------------------------------------------------------- insumos CSV
@pytest.mark.parametrize("saldo", ["100.005", "١٠٠.٠٠", "1 000.00", "1,000.00"])
def test_csv_con_monto_fuera_de_contrato(tmp_path: Path, saldo: str) -> None:
    with pytest.raises(ErrorInsumo, match=r"saldos\.csv, fila 1, columna 'saldo'"):
        leer_saldos(_saldos(tmp_path, saldo), fecha_corte(CORTE), "MXN")


@pytest.mark.parametrize("fecha", ["٢٠٢٦-١١-٠٢", "20261102", "2026-W45-1"])
def test_csv_con_fecha_no_ascii_o_no_calendario(tmp_path: Path, fecha: str) -> None:
    with pytest.raises(ErrorInsumo, match="columna 'fecha_saldo'"):
        leer_saldos(_saldos(tmp_path, "1.00", fecha=fecha), fecha_corte(CORTE), "MXN")


def test_registro_monto_nombra_la_columna() -> None:
    registro = Registro(archivo="x.csv", numero=3, valores={"monto": "1.005"})
    with pytest.raises(ErrorInsumo, match=r"x\.csv, fila 3, columna 'monto'.*a lo más 2 decimales"):
        registro.monto("monto")


def test_cli_insumo_fuera_de_contrato_sale_con_3(tmp_path: Path) -> None:
    datos = tmp_path / "datos"
    shutil.copytree(RAIZ / "examples" / "synthetic_flujo", datos)
    _saldos(datos, "100.005").replace(datos / "saldos_bancarios.csv")
    insumos = {k: str(datos / Path(v).name) for k, v in json.loads(
        CONFIG_EJEMPLO.read_text(encoding="utf-8"))["insumos"].items()}
    salida = tmp_path / "out"
    assert main(["--config", str(_config_con(tmp_path, insumos=insumos)), "--corte", CORTE,
                 "--salida", str(salida)]) == 3
    assert not salida.exists() or not any(salida.iterdir())


# ------------------------------------------------------------- corte y config
@pytest.mark.parametrize("texto", ["٢٠٢٦-١١-٠٢", "20261102", "2026-11-02 "])
def test_corte_solo_ascii(texto: str, capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as salida:
        main(["--config", str(CONFIG_EJEMPLO), "--corte", texto, "--salida", "x"])
    assert salida.value.code == 2
    assert "AAAA-MM-DD" in capsys.readouterr().err


@pytest.mark.parametrize("pesos", [["٠.٥٠", "0.50"], ["0.5 0", "0.50"], ["0,50", "0.50"]])
def test_peso_de_curva_solo_ascii(pesos: Sequence[str]) -> None:
    with pytest.raises(ErrorConfig, match="peso"):
        validar_curva([{"tramo": "unico", "dias_desde": None, "dias_hasta": None, "pesos": list(pesos)}])


def test_cli_config_con_peso_no_ascii_sale_con_2(tmp_path: Path) -> None:
    curva = [{"tramo": "unico", "dias_desde": None, "dias_hasta": None, "pesos": ["١", "0"]}]
    assert main(["--config", str(_config_con(tmp_path, curva_cobranza=curva)), "--corte", CORTE,
                 "--salida", str(tmp_path / "out")]) == 2
