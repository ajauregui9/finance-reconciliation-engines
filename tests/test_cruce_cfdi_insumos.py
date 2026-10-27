"""Pruebas de lectura y validación de insumos y config del cruce cargo ↔ CFDI."""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion.cruce_cfdi_config import (  # noqa: E402
    ConfigCruce,
    cargar_config,
    config_a_dict,
    config_desde_dict,
)
from conciliacion.cruce_cfdi_insumos import (  # noqa: E402
    a_monto,
    cargo_desde_dict,
    cfdi_desde_dict,
    leer_cargos,
    leer_cfdis,
)
from conciliacion.cruce_cfdi_modelo import ConfigInvalida, InsumoInvalido  # noqa: E402

SINTETICOS = RAIZ / "examples" / "synthetic"
EJEMPLO = SKILL / "config" / "cruce_cfdi.example.json"


def registro_cargo(**cambios: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "cargo_id": "ALFA-0001", "fecha": "2026-07-10", "descripcion": "CAFE LUNA AZUL",
        "monto": "100.00", "moneda_original": "MXN", "monto_original": "100.00",
        "tipo_movimiento": "cargo", "estado": "ok", "titular": "ANA DEMO",
    }
    base.update(cambios)
    return base


def registro_cfdi(**cambios: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "uuid": "U-1", "fecha_emision": "2026-07-10", "tipo_comprobante": "I",
        "direccion": "recibido", "rfc_emisor": "RFC_COM_01", "nombre_emisor": "CAFETERIA",
        "rfc_receptor": "RFC_EMPRESA_DEMO", "moneda": "MXN", "total": "100.00",
        "total_mxn": "100.00", "uuid_relacionado": None,
    }
    base.update(cambios)
    return base


def escribir(ruta: Path, lineas: Any) -> Path:
    ruta.write_text("".join(f"{x}\n" for x in lineas), encoding="utf-8")
    return ruta


class TestMonto:
    @pytest.mark.parametrize(
        "valor,esperado",
        [("100", "100.00"), ("-1234.565", "-1234.57"), (100, "100.00"), (100.005, "100.01"), ("0.004", "0.00")],
    )
    def test_frontera_decimal(self, valor: Any, esperado: str) -> None:
        assert a_monto(valor, "monto") == Decimal(esperado)

    @pytest.mark.parametrize("valor", [True, None, "abc", "", "NaN", "Infinity", [1]])
    def test_valores_invalidos(self, valor: Any) -> None:
        with pytest.raises(InsumoInvalido, match="monto"):
            a_monto(valor, "monto")


class TestCargo:
    def test_registro_valido(self) -> None:
        c = cargo_desde_dict(registro_cargo())
        assert (c.cargo_id, c.fecha, c.monto, c.tipo_movimiento) == (
            "ALFA-0001", date(2026, 7, 10), Decimal("100.00"), "cargo")

    def test_ininterpretable_admite_fecha_nula(self) -> None:
        c = cargo_desde_dict(registro_cargo(estado="ininterpretable", fecha=None))
        assert c.fecha is None

    @pytest.mark.parametrize(
        "cambios,mensaje",
        [
            ({"estado": "ok", "fecha": None}, "fecha"),
            ({"fecha": "2026-02-30"}, "fecha"),
            ({"estado": "dudoso"}, "estado"),
            ({"tipo_movimiento": "retiro"}, "tipo_movimiento"),
            ({"descripcion": 7}, "descripcion"),
            ({"cargo_id": ""}, "cargo_id"),
            ({"monto": "1,000.00"}, "monto"),
        ],
    )
    def test_registros_invalidos(self, cambios: Dict[str, Any], mensaje: str) -> None:
        with pytest.raises(InsumoInvalido, match=mensaje):
            cargo_desde_dict(registro_cargo(**cambios))

    def test_campo_faltante(self) -> None:
        datos = registro_cargo()
        del datos["monto_original"]
        with pytest.raises(InsumoInvalido, match="monto_original"):
            cargo_desde_dict(datos)


class TestCfdi:
    def test_registro_valido_con_fecha_y_hora(self) -> None:
        f = cfdi_desde_dict(registro_cfdi(fecha_emision="2026-07-10T12:30:00", uuid_relacionado="U-0"))
        assert (f.fecha_emision, f.total, f.uuid_relacionado) == (date(2026, 7, 10), Decimal("100.00"), "U-0")

    def test_uuid_relacionado_es_opcional(self) -> None:
        datos = registro_cfdi()
        del datos["uuid_relacionado"]
        assert cfdi_desde_dict(datos).uuid_relacionado is None

    def test_valor_firmado_de_nota_de_credito(self) -> None:
        f = cfdi_desde_dict(registro_cfdi(tipo_comprobante="E", total="40.00", total_mxn="40.00"))
        assert (f.valor_mxn, f.valor_original) == (Decimal("-40.00"), Decimal("-40.00"))

    @pytest.mark.parametrize(
        "cambios,mensaje",
        [
            ({"total": "-5.00"}, "total"),
            ({"total_mxn": "-5.00"}, "total_mxn"),
            ({"tipo_comprobante": "X"}, "tipo_comprobante"),
            ({"direccion": "ajena"}, "direccion"),
            ({"fecha_emision": "10/07/2026"}, "fecha_emision"),
            ({"rfc_emisor": None}, "rfc_emisor"),
            ({"uuid_relacionado": 5}, "uuid_relacionado"),
        ],
    )
    def test_registros_invalidos(self, cambios: Dict[str, Any], mensaje: str) -> None:
        with pytest.raises(InsumoInvalido, match=mensaje):
            cfdi_desde_dict(registro_cfdi(**cambios))


class TestArchivos:
    def test_lee_los_insumos_sinteticos(self) -> None:
        cargos = leer_cargos(SINTETICOS / "universo_cargos_esperado.jsonl")
        cfdis = leer_cfdis(SINTETICOS / "cfdis.jsonl")
        assert (len(cargos), len(cfdis)) == (199, 254)
        assert sum(1 for c in cargos if c.fecha is None) == 2
        assert all(isinstance(c.monto, Decimal) for c in cargos)

    def test_linea_ilegible_indica_numero(self, tmp_path: Path) -> None:
        ruta = escribir(tmp_path / "u.jsonl", [json.dumps(registro_cargo()), "{no es json"])
        with pytest.raises(InsumoInvalido, match="línea 2"):
            leer_cargos(ruta)

    def test_linea_vacia_no_se_salta(self, tmp_path: Path) -> None:
        otro = registro_cargo(cargo_id="ALFA-0002")
        ruta = escribir(tmp_path / "u.jsonl", [json.dumps(registro_cargo()), "", json.dumps(otro)])
        with pytest.raises(InsumoInvalido, match="línea 2"):
            leer_cargos(ruta)

    def test_linea_que_no_es_objeto(self, tmp_path: Path) -> None:
        ruta = escribir(tmp_path / "u.jsonl", ["[1, 2]"])
        with pytest.raises(InsumoInvalido, match="objeto"):
            leer_cargos(ruta)

    def test_error_de_campo_incluye_la_linea(self, tmp_path: Path) -> None:
        ruta = escribir(tmp_path / "u.jsonl", [json.dumps(registro_cargo(monto="x"))])
        with pytest.raises(InsumoInvalido, match="línea 1.*monto"):
            leer_cargos(ruta)

    def test_cargo_duplicado(self, tmp_path: Path) -> None:
        ruta = escribir(tmp_path / "u.jsonl", [json.dumps(registro_cargo())] * 2)
        with pytest.raises(InsumoInvalido, match="duplicado"):
            leer_cargos(ruta)

    def test_uuid_duplicado(self, tmp_path: Path) -> None:
        ruta = escribir(tmp_path / "c.jsonl", [json.dumps(registro_cfdi())] * 2)
        with pytest.raises(InsumoInvalido, match="duplicado"):
            leer_cfdis(ruta)

    def test_archivo_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="no se puede leer"):
            leer_cargos(tmp_path / "no-existe.jsonl")

    def test_utf8_invalido(self, tmp_path: Path) -> None:
        ruta = tmp_path / "u.jsonl"
        ruta.write_bytes(b'{"cargo_id": "\xff"}\n')
        with pytest.raises(InsumoInvalido, match="UTF-8"):
            leer_cargos(ruta)

    def test_archivo_vacio_da_cero_registros(self, tmp_path: Path) -> None:
        ruta = tmp_path / "u.jsonl"
        ruta.write_text("", encoding="utf-8")
        assert leer_cargos(ruta) == ()


class TestConfig:
    def test_ejemplo_coincide_con_los_valores_por_defecto(self) -> None:
        datos = json.loads(EJEMPLO.read_text(encoding="utf-8"))
        assert config_desde_dict(datos) == ConfigCruce()
        assert config_a_dict(ConfigCruce()) == datos

    def test_config_parcial_conserva_el_resto(self) -> None:
        cfg = config_desde_dict({"ventana_dias": {"min": -2}, "tolerancias": {"suma": "0.50"}})
        assert (cfg.ventana_min, cfg.ventana_max) == (-2, 10)
        assert cfg.tolerancia_suma == Decimal("0.50")
        assert cfg.tolerancia_uno_a_uno == Decimal("1.00")

    def test_numeros_se_convierten_en_la_frontera(self) -> None:
        assert config_desde_dict({"tolerancias": {"uno_a_uno": 0.5}}).tolerancia_uno_a_uno == Decimal("0.50")

    @pytest.mark.parametrize(
        "datos,mensaje",
        [
            ({"extra": 1}, "extra"),
            ({"suma": {"maximo": 3}}, "maximo"),
            ({"esquema": "otro/v9"}, "esquema"),
            ({"ventana_dias": {"min": 5, "max": 1}}, "ventana"),
            ({"ventana_dias": {"min": "a"}}, "min"),
            ({"ventana_dias": {"min": True}}, "min"),
            ({"suma": {"max_cfdis": 5}}, "max_cfdis"),
            ({"suma": {"min_cfdis": 1}}, "min_cfdis"),
            ({"suma": {"min_cfdis": 3, "max_cfdis": 2}}, "min_cfdis"),
            ({"suma": {"max_candidatos_por_emisor": 21}}, "max_candidatos_por_emisor"),
            ({"tolerancias": {"uno_a_uno": "-0.01"}}, "uno_a_uno"),
            ({"tolerancias": {"suma": True}}, "suma"),
            ({"afinidad_minima": "1.50"}, "afinidad_minima"),
            ({"diagnostico": {"margen_fuera_de_ventana_dias": -1}}, "margen"),
            ({"diagnostico": {"banda_fuera_de_tolerancia": "0.50"}}, "banda"),
            ({"rfc_empresa": ""}, "rfc_empresa"),
            ({"rfcs_genericos": "XAXX010101000"}, "rfcs_genericos"),
            ({"tolerancias": []}, "tolerancias"),
            ([], "objeto"),
        ],
    )
    def test_config_invalida(self, datos: Any, mensaje: str) -> None:
        with pytest.raises(ConfigInvalida, match=mensaje):
            config_desde_dict(datos)

    def test_config_invalida_es_insumo_invalido(self) -> None:
        assert issubclass(ConfigInvalida, InsumoInvalido)

    def test_cargar_config_desde_archivo(self, tmp_path: Path) -> None:
        ruta = tmp_path / "c.json"
        ruta.write_text(json.dumps({"afinidad_minima": "0.75"}), encoding="utf-8")
        assert cargar_config(ruta).afinidad_minima == Decimal("0.75")

    def test_cargar_config_ilegible(self, tmp_path: Path) -> None:
        ruta = tmp_path / "c.json"
        ruta.write_text("{", encoding="utf-8")
        with pytest.raises(ConfigInvalida, match="JSON"):
            cargar_config(ruta)
        with pytest.raises(ConfigInvalida, match="no se puede leer"):
            cargar_config(tmp_path / "falta.json")
