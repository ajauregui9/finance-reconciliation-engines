"""Pruebas de los lectores: liquidación, consola de publicidad, facturas y venta del ERP."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import pytest

import test_amazon_soporte as soporte
from cierre_amazon.config import cargar_config
from cierre_amazon.errores import ErrorInsumo
from cierre_amazon.insumos import cargar_insumos
from cierre_amazon.lector_fuentes import (
    facturas_desde_dict,
    leer_consola_texto,
    venta_erp_desde_dict,
)
from cierre_amazon.lector_liquidacion import leer_liquidacion, leer_liquidacion_texto
from cierre_amazon.modelo import ArchivoLiquidacion


def _leer(texto: str, nombre: str = "liquidacion_2026-04.csv") -> ArchivoLiquidacion:
    return leer_liquidacion_texto(texto, nombre=nombre, moneda="MXN")


class TestLiquidacion:
    def test_lee_preambulo_y_filas(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.venta("2026-04-10 10:00:00", "P-1", "1,500.00", comision="-150.00",
                          retencion="-120.00"),
            soporte.cargo("2026-04-11 09:00:00", "Almacenaje", "-300.00"),
        ])
        archivo = _leer(texto)
        assert archivo.periodo == "2026-04"
        assert archivo.huso_texto == "UTC-07:00"
        assert archivo.nombre == "liquidacion_2026-04.csv"
        assert len(archivo.filas) == 2
        primera = archivo.filas[0]
        assert primera.numero == 1
        assert primera.montos.venta_productos == Decimal("1500.00")
        assert primera.montos.comision == Decimal("-150.00")
        assert primera.total == Decimal("1230.00")
        assert primera.instante_pedido is not None
        segunda = archivo.filas[1]
        assert segunda.instante_pedido is None
        assert segunda.pedido == ""
        assert segunda.cantidad == 0

    def test_tolera_bom_y_claves_extra(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00",
                                        [soporte.cargo("2026-04-11 09:00:00", "Almacenaje", "-1.00")],
                                        preambulo_extra=[["Cuenta", "VENDEDOR-DEMO"]])
        assert len(_leer("﻿" + texto).filas) == 1

    def test_falta_el_huso(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", []).replace("Huso horario,UTC-07:00\n", "")
        with pytest.raises(ErrorInsumo, match="Huso horario"):
            _leer(texto)

    def test_huso_con_horario_de_verano_se_rechaza(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "America/Los_Angeles", [])
        with pytest.raises(ErrorInsumo, match="desfase fijo"):
            _leer(texto)

    def test_clave_repetida(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [],
                                        preambulo_extra=[["Periodo", "2026-05"]])
        with pytest.raises(ErrorInsumo, match="repetida"):
            _leer(texto)

    def test_moneda_distinta(self) -> None:
        with pytest.raises(ErrorInsumo, match="Moneda"):
            _leer(soporte.csv_liquidacion("2026-04", "UTC-07:00", [], moneda="USD"))

    def test_encabezado_distinto(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [],
                                        encabezado=soporte.ENCABEZADO.replace("Total", "Neto"))
        with pytest.raises(ErrorInsumo, match="encabezado"):
            _leer(texto)

    def test_sin_fila_vacia_tras_preambulo(self) -> None:
        texto = "Periodo,2026-04\nHuso horario,UTC-07:00\nMoneda,MXN\n"
        with pytest.raises(ErrorInsumo, match="encabezado"):
            _leer(texto)

    def test_monto_invalido_nombra_fila_y_columna(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.venta("2026-04-10 10:00:00", "P-1", "100.00"),
            soporte.fila("2026-04-10 11:00:00", venta_productos="cien", total="0"),
        ])
        with pytest.raises(ErrorInsumo, match=r"fila 2.*Venta de productos"):
            _leer(texto)

    def test_total_que_no_cuadra(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.fila("2026-04-10 11:00:00", venta_productos="100.00", total="99.99"),
        ])
        with pytest.raises(ErrorInsumo, match="no cuadra"):
            _leer(texto)

    def test_fecha_fuera_del_periodo_local(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.venta("2026-05-01 00:10:00", "P-1", "100.00"),
        ])
        with pytest.raises(ErrorInsumo, match="fuera del periodo"):
            _leer(texto)

    def test_pedido_posterior_a_la_liquidacion(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.venta("2026-04-10 10:00:00", "P-1", "100.00", fecha_pedido="2026-04-11 10:00:00"),
        ])
        with pytest.raises(ErrorInsumo, match="posterior"):
            _leer(texto)

    def test_fecha_invalida(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.venta("2026-04-31 10:00:00", "P-1", "100.00", fecha_pedido=""),
        ])
        with pytest.raises(ErrorInsumo, match="Fecha y hora"):
            _leer(texto)

    def test_cantidad_no_entera(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.fila("2026-04-10 10:00:00", cantidad="1.5", venta_productos="1.00"),
        ])
        with pytest.raises(ErrorInsumo, match="Cantidad"):
            _leer(texto)

    def test_columnas_de_mas(self) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [
            soporte.venta("2026-04-10 10:00:00", "P-1", "100.00"),
        ]) + "a,b\n"
        with pytest.raises(ErrorInsumo, match="columnas"):
            _leer(texto)

    def test_lee_desde_archivo(self, tmp_path: Path) -> None:
        ruta = tmp_path / "liquidacion_2026-04.csv"
        ruta.write_text(soporte.csv_liquidacion("2026-04", "UTC-07:00", []), encoding="utf-8")
        assert leer_liquidacion(ruta, "MXN").filas == ()
        with pytest.raises(ErrorInsumo, match="no se pudo leer"):
            leer_liquidacion(tmp_path / "falta.csv", "MXN")


class TestFuentes:
    def test_consola(self) -> None:
        gastos = leer_consola_texto("Fecha,Campaña,Gasto\n2026-04-01,NOR | Búsqueda,\"1,000.50\"\n",
                                    "publicidad_consola.csv")
        assert gastos[0].fecha == date(2026, 4, 1)
        assert gastos[0].gasto == Decimal("1000.50")

    @pytest.mark.parametrize("texto,fragmento", [
        ("Fecha,Campana,Gasto\n", "encabezado"),
        ("Fecha,Campaña,Gasto\n2026-04-31,X,1.00\n", "Fecha"),
        ("Fecha,Campaña,Gasto\n2026-04-01,X,uno\n", "Gasto"),
        ("Fecha,Campaña,Gasto\n2026-04-01,X\n", "columnas"),
        ("", "vacío"),
    ])
    def test_consola_invalida(self, texto: str, fragmento: str) -> None:
        with pytest.raises(ErrorInsumo, match=fragmento):
            leer_consola_texto(texto, "publicidad_consola.csv")

    def test_facturas(self) -> None:
        facturas = facturas_desde_dict({"esquema": "facturas_publicidad/v1", "facturas": [
            {"mes": "2026-04", "folio": "F-1", "subtotal": "100.00", "iva": "16.00", "total": "116.00"},
        ]}, "facturas_publicidad.json")
        assert facturas[0].subtotal == Decimal("100.00")

    @pytest.mark.parametrize("documento,fragmento", [
        ({"esquema": "x", "facturas": []}, "esquema"),
        ({"esquema": "facturas_publicidad/v1", "facturas": {}}, "lista"),
        ({"esquema": "facturas_publicidad/v1", "facturas": [{"mes": "2026-04"}]}, "folio"),
        ({"esquema": "facturas_publicidad/v1", "facturas": [
            {"mes": "2026-04", "folio": "A", "subtotal": "1", "iva": "0", "total": "1"},
            {"mes": "2026-04", "folio": "B", "subtotal": "1", "iva": "0", "total": "1"}]}, "repetido"),
        ({"esquema": "facturas_publicidad/v1", "facturas": [
            {"mes": "abril", "folio": "A", "subtotal": "1", "iva": "0", "total": "1"}]}, "mes"),
    ])
    def test_facturas_invalidas(self, documento: Dict[str, Any], fragmento: str) -> None:
        with pytest.raises(ErrorInsumo, match=fragmento):
            facturas_desde_dict(documento, "facturas_publicidad.json")

    def test_venta_erp(self) -> None:
        venta = venta_erp_desde_dict({"esquema": "venta_erp/v1",
                                      "venta_neta_por_mes_de_pedido": {"2026-04": "1,000.00"}}, "venta_erp.json")
        assert venta["2026-04"] == Decimal("1000.00")
        with pytest.raises(TypeError):
            venta["2026-05"] = Decimal("1")  # type: ignore[index]

    @pytest.mark.parametrize("documento,fragmento", [
        ({"esquema": "venta_erp/v1"}, "venta_neta_por_mes_de_pedido"),
        ({"esquema": "venta_erp/v1", "venta_neta_por_mes_de_pedido": {"2026-4": "1"}}, "mes"),
        ({"esquema": "venta_erp/v1", "venta_neta_por_mes_de_pedido": {"2026-04": "x"}}, "monto"),
        ([], "objeto"),
    ])
    def test_venta_erp_invalida(self, documento: object, fragmento: str) -> None:
        with pytest.raises(ErrorInsumo, match=fragmento):
            venta_erp_desde_dict(documento, "venta_erp.json")


class TestCargarInsumos:
    def test_descubre_archivos_y_fuentes_opcionales(self, tmp_path: Path) -> None:
        config = cargar_config(soporte.CONFIG_EJEMPLO)
        directorio = soporte.escribir_insumos(tmp_path, {
            "2026-05": soporte.csv_liquidacion("2026-05", "UTC-07:00", []),
            "2026-04": soporte.csv_liquidacion("2026-04", "UTC-07:00", []),
        })
        insumos = cargar_insumos(directorio, config)
        assert [a.periodo for a in insumos.archivos] == ["2026-04", "2026-05"]
        assert insumos.consola is None
        assert insumos.facturas is None
        assert insumos.venta_erp is None

    def test_sin_liquidaciones(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="liquidacion_"):
            cargar_insumos(tmp_path, cargar_config(soporte.CONFIG_EJEMPLO))

    def test_directorio_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="no existe"):
            cargar_insumos(tmp_path / "nada", cargar_config(soporte.CONFIG_EJEMPLO))

    def test_periodo_repetido(self, tmp_path: Path) -> None:
        texto = soporte.csv_liquidacion("2026-04", "UTC-07:00", [])
        soporte.escribir_insumos(tmp_path, {"2026-04": texto})
        (tmp_path / "liquidacion_2026-04_copia.csv").write_text(texto, encoding="utf-8")
        with pytest.raises(ErrorInsumo, match="mismo Periodo"):
            cargar_insumos(tmp_path, cargar_config(soporte.CONFIG_EJEMPLO))

    def test_json_invalido(self, tmp_path: Path) -> None:
        soporte.escribir_insumos(tmp_path, {"2026-04": soporte.csv_liquidacion("2026-04", "UTC-07:00", [])})
        (tmp_path / "venta_erp.json").write_text("{", encoding="utf-8")
        with pytest.raises(ErrorInsumo, match="JSON"):
            cargar_insumos(tmp_path, cargar_config(soporte.CONFIG_EJEMPLO))

    def test_lee_todas_las_fuentes(self, tmp_path: Path) -> None:
        soporte.escribir_insumos(
            tmp_path, {"2026-04": soporte.csv_liquidacion("2026-04", "UTC-07:00", [])},
            consola="Fecha,Campaña,Gasto\n2026-04-01,X,10.00\n",
            facturas=[{"mes": "2026-04", "folio": "F", "subtotal": "10.00", "iva": "1.60", "total": "11.60"}],
            venta_erp={"2026-04": "0.00"},
        )
        insumos = cargar_insumos(tmp_path, cargar_config(soporte.CONFIG_EJEMPLO))
        assert insumos.consola is not None and len(insumos.consola) == 1
        assert insumos.facturas is not None and insumos.facturas[0].folio == "F"
        assert insumos.venta_erp is not None and json.dumps(sorted(insumos.venta_erp)) == '["2026-04"]'
