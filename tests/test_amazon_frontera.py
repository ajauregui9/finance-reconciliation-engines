"""Pruebas de la frontera de entrada del cierre de Amazon: montos, husos y config."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

import test_amazon_soporte as soporte
from cierre_amazon import dinero, huso
from cierre_amazon.config import cargar_config, con_fuente_publicidad, config_desde_dict
from cierre_amazon.errores import ErrorConfig


class TestADecimal:
    def test_texto_con_separador_de_miles(self) -> None:
        assert dinero.a_decimal("1,234.56") == Decimal("1234.56")

    def test_vacio_es_cero(self) -> None:
        assert dinero.a_decimal("") == Decimal("0.00")
        assert dinero.a_decimal("   ") == Decimal("0.00")

    def test_float_pasa_por_str_y_se_cuantiza_half_up(self) -> None:
        assert dinero.a_decimal(0.1 + 0.2) == Decimal("0.30")
        assert dinero.a_decimal(2.675) == Decimal("2.68")
        assert dinero.a_decimal("2.345") == Decimal("2.35")
        assert dinero.a_decimal("-2.345") == Decimal("-2.35")

    def test_entero_y_decimal(self) -> None:
        assert dinero.a_decimal(7) == Decimal("7.00")
        assert dinero.a_decimal(Decimal("1.005")) == Decimal("1.01")

    @pytest.mark.parametrize("valor", ["abc", "1.2.3", "NaN", "Infinity", "--5", True, None, [1]])
    def test_rechaza_valores_invalidos(self, valor: object) -> None:
        with pytest.raises(ValueError):
            dinero.a_decimal(valor)

    def test_resultado_siempre_tiene_dos_decimales(self) -> None:
        assert str(dinero.a_decimal("5")) == "5.00"

    def test_texto_monto_normaliza_cero_negativo(self) -> None:
        assert dinero.texto_monto(-Decimal("0.00")) == "0.00"
        assert dinero.texto_monto(Decimal("-12.5")) == "-12.50"

    def test_texto_tasa_seis_decimales(self) -> None:
        assert dinero.texto_tasa(Decimal("0.08")) == "0.080000"
        assert dinero.texto_tasa(Decimal("1") / Decimal("3")) == "0.333333"

    def test_a_tasa_no_cuantiza_a_centavos(self) -> None:
        assert dinero.a_tasa("0.0825") == Decimal("0.0825")
        with pytest.raises(ValueError):
            dinero.a_tasa(0.08)
        with pytest.raises(ValueError):
            dinero.a_tasa("ocho")


class TestHuso:
    @pytest.mark.parametrize("texto,horas", [
        ("UTC-07:00", -7), ("UTC-08:00", -8), ("UTC+00:00", 0), ("UTC+05:30", 5.5),
    ])
    def test_interpreta_desfases_fijos(self, texto: str, horas: float) -> None:
        assert huso.interpretar_huso(texto).utcoffset(None) == timedelta(hours=horas)

    @pytest.mark.parametrize("texto", [
        "GMT-7", "UTC-7", "America/Los_Angeles", "UTC-15:00", "UTC+03:75", "", "UTC−07:00",
    ])
    def test_rechaza_husos_no_fijos_o_mal_formados(self, texto: str) -> None:
        with pytest.raises(ValueError):
            huso.interpretar_huso(texto)

    def test_mismo_reloj_en_dos_husos_cae_en_meses_distintos(self) -> None:
        cierre = huso.interpretar_huso("UTC-06:00")
        en_menos7 = huso.leer_fecha_hora("2026-06-30 22:30:00", huso.interpretar_huso("UTC-07:00"))
        en_menos8 = huso.leer_fecha_hora("2026-06-30 22:30:00", huso.interpretar_huso("UTC-08:00"))
        assert huso.mes_en_huso(en_menos7, cierre) == "2026-06"
        assert huso.mes_en_huso(en_menos8, cierre) == "2026-07"

    def test_huso_al_este_mueve_la_fila_al_mes_anterior(self) -> None:
        cierre = huso.interpretar_huso("UTC-06:00")
        instante = huso.leer_fecha_hora("2026-07-01 03:00:00", huso.interpretar_huso("UTC+00:00"))
        assert huso.mes_en_huso(instante, cierre) == "2026-06"

    def test_instante_es_consciente_del_huso(self) -> None:
        instante = huso.leer_fecha_hora("2026-04-30 23:20:00", huso.interpretar_huso("UTC-07:00"))
        assert instante == datetime(2026, 5, 1, 6, 20, tzinfo=timezone.utc)

    @pytest.mark.parametrize("texto", ["2026-02-30 10:00:00", "30/04/2026 10:00", "2026-04-30", ""])
    def test_rechaza_fechas_invalidas(self, texto: str) -> None:
        with pytest.raises(ValueError):
            huso.leer_fecha_hora(texto, timezone.utc)

    def test_mes_valido(self) -> None:
        assert huso.validar_mes("2026-07") == "2026-07"
        for malo in ("2026-13", "2026-7", "julio", "2026-00"):
            with pytest.raises(ValueError):
                huso.validar_mes(malo)

    def test_mes_anterior(self) -> None:
        assert huso.mes_anterior("2026-01") == "2025-12"
        assert huso.mes_anterior("2026-07") == "2026-06"


class TestConfig:
    def test_carga_la_config_de_ejemplo(self) -> None:
        config = cargar_config(soporte.CONFIG_EJEMPLO)
        assert config.tasa_iva == Decimal("0.16")
        assert config.tasa_retencion == Decimal("0.08")
        assert config.banda_retencion == Decimal("0.01")
        assert config.fuente_publicidad == "consola"
        assert config.tolerancia_publicidad == Decimal("1.00")
        assert config.huso_cierre_texto == "UTC-06:00"
        assert config.tipos["Publicidad"] == "publicidad"
        assert config.referencias["comision"].minimo == Decimal("0.10")

    def test_tipos_es_inmutable(self) -> None:
        config = cargar_config(soporte.CONFIG_EJEMPLO)
        with pytest.raises(TypeError):
            config.tipos["Nuevo"] = "venta"  # type: ignore[index]

    @pytest.mark.parametrize("cambios,fragmento", [
        ({"tasa_iva": "1.20"}, "tasa_iva"),
        ({"tasa_iva": 0.16}, "tasa_iva"),
        ({"huso_cierre": "GMT-6"}, "huso_cierre"),
        ({"moneda": ""}, "moneda"),
        ({"tipos": {"Pedido": "ingreso"}}, "categoría"),
        ({"tipos": {}}, "tipos"),
        ({"publicidad": {"fuente_autoritativa": "ads", "tolerancia": "1.00"}}, "fuente_autoritativa"),
        ({"publicidad": {"fuente_autoritativa": "consola", "tolerancia": "-1"}}, "tolerancia"),
        ({"retencion": {"tasa": "0", "banda": "0.01"}}, "retencion.tasa"),
        ({"retencion": {"tasa": "0.08", "banda": "-0.01"}}, "retencion.banda"),
        ({"retencion": {"tasa": "0.08"}}, "retencion.banda"),
        ({"referencias_tarifas": {"comision": {"min": "0.30", "max": "0.20"}}}, "min"),
        ({"referencias_tarifas": {"envio": {"min": "0.0", "max": "0.20"}}}, "envio"),
        ({"esquema": "otra/v9"}, "esquema"),
    ])
    def test_errores_de_config_son_explicitos(self, cambios: Dict[str, Any], fragmento: str) -> None:
        with pytest.raises(ErrorConfig, match=fragmento):
            config_desde_dict(soporte.config_dict(**cambios))

    def test_falta_seccion_obligatoria(self) -> None:
        datos = soporte.config_dict()
        del datos["retencion"]
        with pytest.raises(ErrorConfig, match="retencion"):
            config_desde_dict(datos)

    def test_referencias_son_opcionales(self) -> None:
        datos = soporte.config_dict()
        del datos["referencias_tarifas"]
        assert dict(config_desde_dict(datos).referencias) == {}

    def test_cambiar_fuente_devuelve_copia(self) -> None:
        original = cargar_config(soporte.CONFIG_EJEMPLO)
        otra = con_fuente_publicidad(original, "factura")
        assert otra.fuente_publicidad == "factura"
        assert original.fuente_publicidad == "consola"
        with pytest.raises(ErrorConfig):
            con_fuente_publicidad(original, "radio")

    def test_archivo_de_config_inexistente_o_invalido(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorConfig, match="no existe"):
            cargar_config(tmp_path / "falta.json")
        malo = tmp_path / "malo.json"
        malo.write_text("{no es json", encoding="utf-8")
        with pytest.raises(ErrorConfig, match="JSON"):
            cargar_config(malo)
        lista = tmp_path / "lista.json"
        lista.write_text("[]", encoding="utf-8")
        with pytest.raises(ErrorConfig, match="objeto"):
            cargar_config(lista)
