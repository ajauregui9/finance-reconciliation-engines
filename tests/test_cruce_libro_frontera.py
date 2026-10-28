"""Contrato de la frontera de entrada del cruce con libro mayor.

Los casos que hoy pasaban en silencio (dígitos no ASCII, más de dos decimales, floats)
ahora detienen la corrida con un error que nombra archivo, fila y campo (código 2).
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest

from conciliacion import cruce_libro
from conciliacion import cruce_libro_config as cfg
from conciliacion import cruce_libro_insumos as ins
from conciliacion.cruce_libro_insumos import ErrorInsumo

ROOT = Path(__file__).resolve().parents[1]
LIBRO = ROOT / "examples" / "synthetic" / "libro_mayor.csv"
ENCABEZADO_LIBRO = ("asiento_id,linea,fecha,periodo,origen,cuenta,nombre_cuenta,proveedor_id,"
                    "proveedor_nombre,proveedor_rfc,referencia,memo,debe,haber,moneda")
FUERA_DE_CONTRATO = ["١٠.٠٠", "10.005", "1 000.00", "1,000.00", "1,00.00", "1e3", ""]


def _cargo(**cambios: object) -> Dict[str, object]:
    base: Dict[str, object] = {"cargo_id": "ALFA-0001", "emisor": "ALFA", "estado": "ok", "fecha": "2026-07-01",
                               "descripcion": "CAFE LUNA", "monto": "10.00", "tipo_movimiento": "cargo"}
    return {**base, **cambios}


def _jsonl(tmp_path: Path, filas: List[Dict[str, object]]) -> Path:
    ruta = tmp_path / "universo.jsonl"
    ruta.write_text("".join(json.dumps(f, ensure_ascii=False) + "\n" for f in filas), encoding="utf-8")
    return ruta


def _libro(tmp_path: Path, linea: str = "1", fecha: str = "2026-07-02", debe: str = "0.00") -> Path:
    fila = (f"AS-1,{linea},{fecha},2026-07,TARJETA,2105-001,TARJETA,PRV-1,CAFETERIA LUNA,RFC_X,"
            f"EDC,MEMO,\"{debe}\",10.00,MXN")
    ruta = tmp_path / "libro.csv"
    ruta.write_text(f"{ENCABEZADO_LIBRO}\n{fila}\n", encoding="utf-8")
    return ruta


# ------------------------------------------------------------------- a_monto
@pytest.mark.parametrize("valor, esperado", [("10.00", "10.00"), ("-1234.5", "-1234.50"), (" 3.10\t", "3.10"),
                                             ("7", "7.00")])
def test_monto_valido(valor: str, esperado: str) -> None:
    assert str(ins.a_monto(valor, "prueba")) == esperado


@pytest.mark.parametrize("valor", FUERA_DE_CONTRATO + [0.1 + 0.2, 10.5, 7, Decimal("2.34")])
def test_monto_fuera_de_contrato(valor: object) -> None:
    with pytest.raises(ErrorInsumo, match="prueba"):
        ins.a_monto(valor, "prueba")


def test_monto_con_tres_decimales_dice_por_que() -> None:
    with pytest.raises(ErrorInsumo, match="a lo más 2 decimales"):
        ins.a_monto("100.005", "prueba")


@pytest.mark.parametrize("valor", ["١.٠", "0.5 0", 0.5, "0,5"])
def test_decimal_exacto_solo_ascii_y_texto(valor: object) -> None:
    with pytest.raises(ErrorInsumo, match="prueba"):
        ins.a_decimal_exacto(valor, "prueba")


def test_decimal_exacto_conserva_decimales() -> None:
    assert str(ins.a_decimal_exacto(" 0.125 ", "prueba")) == "0.125"


@pytest.mark.parametrize("valor", ["٢٠٢٦-٠٧-٠١", "20260701", "2026-7-1", " 2026-07-01"])
def test_fecha_solo_ascii(valor: str) -> None:
    with pytest.raises(ErrorInsumo, match="AAAA-MM-DD"):
        ins.a_fecha(valor, "prueba")


# ---------------------------------------------------------------- archivos
@pytest.mark.parametrize("monto", ["10.005", "١٠.٠٠", 0.1 + 0.2, 10.0])
def test_universo_con_monto_fuera_de_contrato(tmp_path: Path, monto: object) -> None:
    with pytest.raises(ErrorInsumo, match=r"universo\.jsonl, línea 1, campo monto"):
        ins.leer_universo(_jsonl(tmp_path, [_cargo(monto=monto)]))


@pytest.mark.parametrize("debe", ["10.005", "١٠.٠٠", "1,000.00", "1 0.00"])
def test_libro_con_importe_fuera_de_contrato(tmp_path: Path, debe: str) -> None:
    with pytest.raises(ErrorInsumo, match=r"libro\.csv, fila 2, campo debe"):
        ins.leer_libro(_libro(tmp_path, debe=debe), "MXN")


@pytest.mark.parametrize("linea", ["١", "+1", "1.0", "1_0"])
def test_libro_con_linea_que_no_es_entero_ascii(tmp_path: Path, linea: str) -> None:
    with pytest.raises(ErrorInsumo, match="campo linea"):
        ins.leer_libro(_libro(tmp_path, linea=linea), "MXN")


def test_libro_con_fecha_no_ascii(tmp_path: Path) -> None:
    with pytest.raises(ErrorInsumo, match="campo fecha"):
        ins.leer_libro(_libro(tmp_path, fecha="٢٠٢٦-٠٧-٠٢"), "MXN")


@pytest.mark.parametrize("cambio, llave", [({"tolerancia_monto": "1.005"}, "tolerancia_monto"),
                                           ({"tolerancia_monto": "١.٠٠"}, "tolerancia_monto"),
                                           ({"umbral_similitud": "٠.٥٠"}, "umbral_similitud")])
def test_config_fuera_de_contrato(cambio: Dict[str, object], llave: str) -> None:
    with pytest.raises(ErrorInsumo, match=llave):
        cfg.config_desde_dict({"esquema": "cruce_libro_config/v1", **cambio})


def test_cli_sale_con_2_y_no_escribe(tmp_path: Path) -> None:
    salida = tmp_path / "salida.json"
    universo = _jsonl(tmp_path, [_cargo(monto="100.005")])
    codigo = cruce_libro.main(["--universo", str(universo), "--libro", str(LIBRO), "--salida", str(salida)])
    assert codigo == 2
    assert not salida.exists()
