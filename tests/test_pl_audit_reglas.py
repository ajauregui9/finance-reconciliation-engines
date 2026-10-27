"""Pruebas de las reglas del revisor de P&L sobre el reporte JSON.

Cada prueba parte de la corrida base (sin bloqueos, todo dentro de banda, sin
variaciones), cambia una sola cosa y verifica su efecto en el reporte. Así cada
llave de la config tiene al menos una prueba que demuestra que cambia el
resultado.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from test_pl_audit_fixtures import (
    PERIODO_BASE,
    con_cuenta,
    con_valor,
    config_base,
    exportacion_base,
    sin_cuenta,
    sin_llave,
)

from auditoria_pl import ErrorEntrada, auditar_crudo


def correr(config: Dict[str, Any], exportacion: Dict[str, Any], periodo: str = PERIODO_BASE) -> Dict[str, Any]:
    return auditar_crudo(config, exportacion, periodo)


def codigos(reporte: Dict[str, Any]) -> List[str]:
    return [b["codigo"] for b in reporte["bloqueos"]]


def banda(reporte: Dict[str, Any], metrica: str) -> Dict[str, Any]:
    return next(b for b in reporte["bandas"] if b["metrica"] == metrica)


class TestCorridaBase(unittest.TestCase):
    def test_base_sin_bloqueos_y_todo_dentro(self) -> None:
        reporte = correr(config_base(), exportacion_base())
        self.assertEqual(reporte["bloqueos"], [])
        self.assertFalse(reporte["provisional"])
        self.assertEqual(reporte["periodo"], "2026-03")
        self.assertEqual({b["estado"] for b in reporte["bandas"]}, {"dentro"})
        self.assertEqual(reporte["publicidad"]["alertas"], [])
        conteos = reporte["variaciones"]["conteos"]
        self.assertEqual(conteos["bajo_monto"], 5)
        self.assertEqual(reporte["variaciones"]["materiales"], [])


class TestPeriodo(unittest.TestCase):
    def test_periodo_distinto_al_de_la_exportacion(self) -> None:
        with self.assertRaises(ErrorEntrada) as ctx:
            correr(config_base(), exportacion_base(), "2026-04")
        self.assertIn("2026-04", str(ctx.exception))

    def test_periodo_mal_formado(self) -> None:
        with self.assertRaises(ErrorEntrada):
            correr(config_base(), exportacion_base(), "marzo")


class TestMadurez(unittest.TestCase):
    def test_extraccion_justo_en_el_minimo_no_bloquea(self) -> None:
        reporte = correr(config_base(), con_valor(exportacion_base(), "fecha_extraccion", "2026-04-03"))
        self.assertEqual(reporte["madurez"]["dias_tras_cierre"], 3)
        self.assertNotIn("mes_inmaduro", codigos(reporte))

    def test_extraccion_un_dia_antes_del_minimo_bloquea(self) -> None:
        reporte = correr(config_base(), con_valor(exportacion_base(), "fecha_extraccion", "2026-04-02"))
        self.assertEqual(codigos(reporte), ["mes_inmaduro"])
        self.assertTrue(reporte["provisional"])
        self.assertEqual(reporte["bloqueos"][0]["referencia"], "2026-03")

    def test_dias_minimos_cambia_el_resultado(self) -> None:
        exportacion = con_valor(exportacion_base(), "fecha_extraccion", "2026-03-31")
        self.assertIn("mes_inmaduro", codigos(correr(config_base(), exportacion)))
        config = con_valor(config_base(), "madurez.dias_minimos_tras_cierre", 0)
        self.assertNotIn("mes_inmaduro", codigos(correr(config, exportacion)))

    def test_extraccion_antes_del_fin_de_mes_da_dias_negativos(self) -> None:
        reporte = correr(config_base(), con_valor(exportacion_base(), "fecha_extraccion", "2026-03-30"))
        self.assertEqual(reporte["madurez"]["dias_tras_cierre"], -1)
        self.assertIn("mes_inmaduro", codigos(reporte))

    def test_fin_de_periodo_respeta_febrero_y_diciembre(self) -> None:
        casos = (("2028-02", "2028-02-29"), ("2026-02", "2026-02-28"), ("2026-12", "2026-12-31"))
        for periodo, fin in casos:
            with self.subTest(periodo=periodo):
                exportacion = con_valor(exportacion_base(), "periodo", periodo)
                exportacion = con_valor(exportacion, "fecha_extraccion", "2029-01-31")
                self.assertEqual(correr(config_base(), exportacion, periodo)["madurez"]["fin_periodo"], fin)

    def test_nomina_en_cero_bloquea(self) -> None:
        reporte = correr(config_base(), con_cuenta(exportacion_base(), "6210", actual="0.00"))
        self.assertEqual(
            [(b["codigo"], b["referencia"]) for b in reporte["bloqueos"]], [("nomina_sin_registrar", "6210")]
        )

    def test_nomina_ausente_bloquea(self) -> None:
        reporte = correr(config_base(), sin_cuenta(exportacion_base(), "6130"))
        self.assertEqual(
            [(b["codigo"], b["referencia"]) for b in reporte["bloqueos"]], [("nomina_sin_registrar", "6130")]
        )

    def test_sin_cuentas_de_nomina_no_se_verifica(self) -> None:
        config = con_valor(config_base(), "madurez.cuentas_nomina", [])
        reporte = correr(config, con_cuenta(exportacion_base(), "6210", actual="0.00"))
        self.assertEqual(reporte["bloqueos"], [])

    def test_provision_ausente_o_en_cero_bloquea(self) -> None:
        for provisiones in ([], [{"cuenta": "2150", "creado": "0"}], [{"cuenta": "2150", "creado": "-5"}]):
            with self.subTest(provisiones=provisiones):
                reporte = correr(config_base(), con_valor(exportacion_base(), "provisiones", provisiones))
                self.assertEqual(
                    [(b["codigo"], b["referencia"]) for b in reporte["bloqueos"]], [("provision_sin_crear", "2150")]
                )

    def test_provisiones_no_exigidas_se_listan(self) -> None:
        provisiones = [{"cuenta": "2150", "creado": "1"}, {"cuenta": "2199", "creado": "1"}]
        reporte = correr(config_base(), con_valor(exportacion_base(), "provisiones", provisiones))
        self.assertEqual(reporte["madurez"]["provisiones_no_exigidas"], ["2199"])
        self.assertEqual(reporte["bloqueos"], [])

    def test_sin_provisiones_obligatorias_no_se_verifica(self) -> None:
        config = con_valor(config_base(), "madurez.provisiones_obligatorias", [])
        reporte = correr(config, con_valor(exportacion_base(), "provisiones", []))
        self.assertEqual(reporte["bloqueos"], [])

    def test_bloqueos_ordenados_por_codigo_y_referencia(self) -> None:
        exportacion = con_valor(exportacion_base(), "fecha_extraccion", "2026-04-01")
        exportacion = con_cuenta(sin_cuenta(exportacion, "6130"), "6210", actual="0")
        exportacion = con_valor(exportacion, "provisiones", [])
        pares = [(b["codigo"], b["referencia"]) for b in correr(config_base(), exportacion)["bloqueos"]]
        self.assertEqual(
            pares,
            [
                ("mes_inmaduro", "2026-03"),
                ("nomina_sin_registrar", "6130"),
                ("nomina_sin_registrar", "6210"),
                ("provision_sin_crear", "2150"),
            ],
        )


class TestRubrosYBase(unittest.TestCase):
    def test_cuenta_sin_rubro_bloquea_y_no_se_descarta(self) -> None:
        exportacion = con_cuenta(exportacion_base(), "9010", anterior="0", actual="3000")
        reporte = correr(config_base(), exportacion)
        self.assertEqual([(b["codigo"], b["referencia"]) for b in reporte["bloqueos"]], [("cuenta_sin_rubro", "9010")])
        self.assertEqual(reporte["rubros"]["sin_rubro"], "3000.00")
        self.assertEqual(reporte["variaciones"]["menciones"][0]["cuenta"], "9010")
        self.assertIsNone(reporte["variaciones"]["menciones"][0]["rubro"])

    def test_bajo_ebitda_no_cambia_el_ebitda(self) -> None:
        exportacion = con_cuenta(exportacion_base(), "7010", anterior="40000", actual="40000")
        reporte = correr(config_base(), exportacion)
        self.assertEqual(reporte["rubros"]["bajo_ebitda"], "40000.00")
        self.assertEqual(reporte["metricas"]["ebitda"], {"monto": "180000.00", "pct": "18.00"})

    def test_totales_por_rubro(self) -> None:
        rubros = correr(config_base(), exportacion_base())["rubros"]
        self.assertEqual(
            rubros,
            {
                "ingreso": "1000000.00",
                "costo": "500000.00",
                "gasto_venta": "170000.00",
                "gasto_admin": "150000.00",
                "bajo_ebitda": "0.00",
                "sin_rubro": "0.00",
            },
        )

    def test_polizas_manuales_se_apartan_de_la_base(self) -> None:
        exportacion = con_cuenta(exportacion_base(), "4010", actual="950000", polizas_manuales_actual="-50000")
        reporte = correr(config_base(), exportacion)
        base = reporte["base_ingreso"]
        self.assertEqual(base["ingreso_rubro"], "950000.00")
        self.assertEqual(base["polizas_aisladas"], "-50000.00")
        self.assertEqual(base["base"], "1000000.00")
        self.assertEqual(base["aislado_por_cuenta"], [{"cuenta": "4010", "monto": "-50000.00"}])
        self.assertEqual(reporte["metricas"]["margen_bruto"]["pct"], "50.00")

    def test_sin_cuentas_configuradas_la_base_incluye_polizas(self) -> None:
        config = con_valor(config_base(), "cuentas_sin_polizas_manuales", [])
        exportacion = con_cuenta(exportacion_base(), "4010", actual="950000", polizas_manuales_actual="-50000")
        reporte = correr(config, exportacion)
        self.assertEqual(reporte["base_ingreso"]["base"], "950000.00")
        self.assertEqual(reporte["base_ingreso"]["aislado_por_cuenta"], [])
        self.assertEqual(reporte["metricas"]["margen_bruto"]["pct"], "47.37")

    def test_polizas_de_cuentas_no_configuradas_no_se_apartan(self) -> None:
        exportacion = con_cuenta(exportacion_base(), "4020", anterior="0", actual="100", polizas_manuales_actual="100")
        self.assertEqual(correr(config_base(), exportacion)["base_ingreso"]["base"], "1000100.00")

    def test_cuenta_configurada_ausente_aparta_cero(self) -> None:
        config = con_valor(config_base(), "cuentas_sin_polizas_manuales", ["4010", "4090"])
        aislado = correr(config, exportacion_base())["base_ingreso"]["aislado_por_cuenta"]
        self.assertEqual(aislado, [{"cuenta": "4010", "monto": "0.00"}, {"cuenta": "4090", "monto": "0.00"}])

    def test_base_no_positiva_se_rechaza(self) -> None:
        exportacion = con_cuenta(exportacion_base(), "4010", actual="0")
        with self.assertRaises(ErrorEntrada) as ctx:
            correr(config_base(), exportacion)
        self.assertIn("base", str(ctx.exception))


class TestBandas(unittest.TestCase):
    def test_extremos_del_corredor_estan_dentro(self) -> None:
        reporte = correr(config_base(), con_cuenta(exportacion_base(), "6130", actual="150000"))
        fila = banda(reporte, "gasto_venta")
        self.assertEqual((fila["valor_pct"], fila["estado"], fila["desvio_pct"]), ("20.00", "dentro", "0.00"))

    def test_gasto_sobre_el_maximo_es_desfavorable(self) -> None:
        reporte = correr(config_base(), con_cuenta(exportacion_base(), "6130", actual="180000"))
        fila = banda(reporte, "gasto_venta")
        self.assertEqual(
            (fila["valor_pct"], fila["estado"], fila["desvio_pct"]), ("23.00", "fuera_desfavorable", "3.00")
        )

    def test_gasto_bajo_el_minimo_es_favorable(self) -> None:
        reporte = correr(config_base(), con_cuenta(exportacion_base(), "6210", actual="50000"))
        fila = banda(reporte, "gasto_admin")
        self.assertEqual((fila["valor_pct"], fila["estado"], fila["desvio_pct"]), ("5.00", "fuera_favorable", "5.00"))

    def test_margen_alto_favorable_y_bajo_desfavorable(self) -> None:
        alto = correr(config_base(), con_cuenta(exportacion_base(), "5010", actual="300000"))
        self.assertEqual(banda(alto, "margen_bruto")["estado"], "fuera_favorable")
        bajo = correr(config_base(), con_cuenta(exportacion_base(), "5010", actual="700000"))
        self.assertEqual(banda(bajo, "margen_bruto")["estado"], "fuera_desfavorable")
        self.assertEqual(banda(bajo, "ebitda")["estado"], "fuera_desfavorable")
        self.assertEqual(banda(bajo, "ebitda")["valor_pct"], "-2.00")

    def test_valores_del_corredor_salen_en_el_reporte(self) -> None:
        fila = banda(correr(config_base(), exportacion_base()), "ebitda")
        self.assertEqual(
            fila,
            {
                "metrica": "ebitda",
                "monto": "180000.00",
                "valor_pct": "18.00",
                "minimo_pct": "10.00",
                "maximo_pct": "30.00",
                "favorable": "alto",
                "estado": "dentro",
                "desvio_pct": "0.00",
            },
        )

    def test_metrica_sin_banda_se_reporta_pero_no_se_evalua(self) -> None:
        reporte = correr(sin_llave(config_base(), "bandas.gasto_admin"), exportacion_base())
        self.assertIn("gasto_admin", reporte["metricas"])
        self.assertEqual([b["metrica"] for b in reporte["bandas"]], ["margen_bruto", "gasto_venta", "ebitda"])

    def test_porcentaje_redondea_mitad_hacia_arriba(self) -> None:
        exportacion = con_cuenta(exportacion_base(), "4010", actual="200000")
        exportacion = con_cuenta(exportacion, "5010", actual="100000")
        exportacion = con_cuenta(exportacion, "6120", actual="0")
        exportacion = con_cuenta(exportacion, "6210", actual="24690")
        exportacion = con_valor(exportacion, "marcas", [])
        metricas = correr(config_base(), exportacion)["metricas"]
        self.assertEqual(metricas["gasto_admin"]["pct"], "12.35")  # 12.345 exacto
        self.assertEqual(metricas["gasto_venta"]["pct"], "60.00")


class TestPublicidad(unittest.TestCase):
    def _con_publicidad(self, venta: str, publicidad: str) -> Dict[str, Any]:
        exportacion = con_cuenta(exportacion_base(), "6120", actual=publicidad)
        return con_valor(exportacion, "marcas", [{"marca": "Marca Uno", "venta": venta, "publicidad": publicidad}])

    def test_publicidad_igual_al_umbral_no_alerta(self) -> None:
        reporte = correr(config_base(), self._con_publicidad("1000000", "120000"))
        self.assertEqual(reporte["publicidad"]["alertas"], [])

    def test_publicidad_sobre_el_umbral_alerta_con_exceso(self) -> None:
        reporte = correr(config_base(), self._con_publicidad("1000000", "120100"))
        self.assertEqual(
            reporte["publicidad"]["alertas"],
            [
                {
                    "marca": "Marca Uno",
                    "motivo": "sobre_umbral",
                    "venta": "1000000.00",
                    "publicidad": "120100.00",
                    "publicidad_pct": "12.01",
                    "exceso_sobre_objetivo": "40100.00",
                }
            ],
        )

    def test_umbral_y_objetivo_vienen_de_la_config(self) -> None:
        config = con_valor(config_base(), "publicidad.alerta_pct", "4")
        config = con_valor(config, "publicidad.objetivo_pct", "2")
        alertas = correr(config, exportacion_base())["publicidad"]["alertas"]
        self.assertEqual([(a["marca"], a["exceso_sobre_objetivo"]) for a in alertas], [("Marca Uno", "30000.00")])

    def test_publicidad_sin_venta_alerta_sin_porcentaje(self) -> None:
        marcas = [
            {"marca": "Marca Uno", "venta": "1000000", "publicidad": "45000"},
            {"marca": "Marca Dos", "venta": "0", "publicidad": "5000"},
            {"marca": "Marca Tres", "venta": "0", "publicidad": "0"},
        ]
        reporte = correr(config_base(), con_valor(exportacion_base(), "marcas", marcas))
        self.assertEqual(
            reporte["publicidad"]["alertas"],
            [
                {
                    "marca": "Marca Dos",
                    "motivo": "publicidad_sin_venta",
                    "venta": "0.00",
                    "publicidad": "5000.00",
                    "publicidad_pct": None,
                    "exceso_sobre_objetivo": "5000.00",
                }
            ],
        )

    def test_alertas_ordenadas_por_marca(self) -> None:
        marcas = [
            {"marca": "Zeta", "venta": "100000", "publicidad": "25000"},
            {"marca": "Alfa", "venta": "100000", "publicidad": "25000"},
        ]
        exportacion = con_valor(con_cuenta(exportacion_base(), "6120", actual="50000"), "marcas", marcas)
        alertas = correr(config_base(), exportacion)["publicidad"]["alertas"]
        self.assertEqual([a["marca"] for a in alertas], ["Alfa", "Zeta"])

    def test_suma_por_marca_que_no_cuadra_bloquea(self) -> None:
        reporte = correr(config_base(), con_cuenta(exportacion_base(), "6120", actual="50000.01"))
        self.assertEqual(
            [(b["codigo"], b["referencia"]) for b in reporte["bloqueos"]], [("publicidad_sin_cuadre", "6120")]
        )
        self.assertIn("-0.01", reporte["bloqueos"][0]["detalle"])
        self.assertEqual(reporte["publicidad"]["total_cuenta"], "50000.01")
        self.assertEqual(reporte["publicidad"]["total_marcas"], "50000.00")

    def test_cuenta_de_publicidad_ausente_sin_gasto_por_marca_cuadra(self) -> None:
        exportacion = con_valor(sin_cuenta(exportacion_base(), "6120"), "marcas", [])
        reporte = correr(config_base(), exportacion)
        self.assertEqual(reporte["bloqueos"], [])
        self.assertEqual(reporte["publicidad"]["total_cuenta"], "0.00")

    def test_cuenta_de_publicidad_viene_de_la_config(self) -> None:
        config = con_valor(config_base(), "publicidad.cuenta", "6130")
        reporte = correr(config, exportacion_base())
        self.assertEqual(
            [(b["codigo"], b["referencia"]) for b in reporte["bloqueos"]], [("publicidad_sin_cuadre", "6130")]
        )


class TestVariaciones(unittest.TestCase):
    def _variar(self, *cambios: Any) -> Dict[str, Any]:
        """Agrega cuentas de gasto administrativo con (cuenta, anterior, actual)."""
        exportacion = exportacion_base()
        for cuenta, anterior, actual in cambios:
            exportacion = con_cuenta(exportacion, cuenta, anterior=anterior, actual=actual)
        return exportacion

    def test_piso_material_toma_el_mayor_de_los_dos_pisos(self) -> None:
        reporte = correr(config_base(), exportacion_base())
        self.assertEqual(reporte["variaciones"]["piso_material"], "20000.00")
        config = con_valor(config_base(), "materialidad.piso_pct_ingreso", "5")
        self.assertEqual(correr(config, exportacion_base())["variaciones"]["piso_material"], "50000.00")

    def test_clases_en_sus_fronteras(self) -> None:
        exportacion = self._variar(
            ("6231", "5000", "6999.99"),  # delta bajo el piso de mención
            ("6232", "10000", "12000"),  # mención justo en ambos mínimos (2000 y 20%)
            ("6233", "100000", "120000"),  # material justo en el piso (20000 y 20%)
            ("6234", "200000", "230000"),  # monto material, variación de 15%
            ("6235", "100000", "80000"),  # material negativa
        )
        variaciones = correr(config_base(), exportacion)["variaciones"]
        self.assertEqual([m["cuenta"] for m in variaciones["materiales"]], ["6233", "6235"])
        self.assertEqual([m["cuenta"] for m in variaciones["menciones"]], ["6232"])
        self.assertEqual(variaciones["conteos"]["bajo_variacion_pct"], 1)
        self.assertEqual(variaciones["conteos"]["bajo_monto"], 6)

    def test_piso_de_mencion_viene_de_la_config(self) -> None:
        exportacion = self._variar(("6231", "5000", "6500"))
        config = con_valor(config_base(), "materialidad.piso_mencion", "1000")
        self.assertEqual([m["cuenta"] for m in correr(config, exportacion)["variaciones"]["menciones"]], ["6231"])

    def test_variacion_minima_viene_de_la_config(self) -> None:
        exportacion = self._variar(("6234", "200000", "230000"))
        config = con_valor(config_base(), "materialidad.variacion_pct_minima", "10")
        self.assertEqual([m["cuenta"] for m in correr(config, exportacion)["variaciones"]["materiales"]], ["6234"])

    def test_fila_material_completa(self) -> None:
        exportacion = self._variar(("6235", "100000", "80000"))
        fila = correr(config_base(), exportacion)["variaciones"]["materiales"][0]
        self.assertEqual(
            fila,
            {
                "cuenta": "6235",
                "nombre": "Cuenta 6235",
                "rubro": "gasto_admin",
                "anterior": "100000.00",
                "actual": "80000.00",
                "delta": "-20000.00",
                "variacion_pct": "20.00",
                "cuenta_nueva": False,
            },
        )

    def test_cuenta_nueva_no_tiene_porcentaje_y_pasa_el_filtro(self) -> None:
        fila = correr(config_base(), self._variar(("6250", "0", "25000")))["variaciones"]["materiales"][0]
        self.assertEqual((fila["cuenta"], fila["variacion_pct"], fila["cuenta_nueva"]), ("6250", None, True))

    def test_cuenta_que_desaparece_es_cien_por_ciento(self) -> None:
        fila = correr(config_base(), self._variar(("6250", "25000", "0")))["variaciones"]["materiales"][0]
        self.assertEqual((fila["delta"], fila["variacion_pct"]), ("-25000.00", "100.00"))

    def test_tope_lista_las_mayores_y_cuenta_las_omitidas(self) -> None:
        exportacion = self._variar(("6241", "0", "30000"), ("6242", "0", "-50000"), ("6243", "0", "30000"))
        config = con_valor(config_base(), "materialidad.tope_materiales", 2)
        variaciones = correr(config, exportacion)["variaciones"]
        self.assertEqual([m["cuenta"] for m in variaciones["materiales"]], ["6242", "6241"])
        self.assertEqual(variaciones["conteos"]["materiales"], 3)
        self.assertEqual(variaciones["conteos"]["omitidas_por_tope"], 1)

    def test_conteos_suman_el_numero_de_cuentas(self) -> None:
        exportacion = self._variar(
            ("6231", "10000", "10500"), ("6232", "10000", "13000"), ("6233", "0", "90000"), ("6234", "100000", "105000")
        )
        conteos = correr(config_base(), exportacion)["variaciones"]["conteos"]
        total = conteos["bajo_monto"] + conteos["bajo_variacion_pct"] + conteos["menciones"] + conteos["materiales"]
        self.assertEqual(total, 9)
        self.assertEqual(conteos["menciones"], 1)


if __name__ == "__main__":
    unittest.main()
