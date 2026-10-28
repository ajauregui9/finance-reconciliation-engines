"""Pruebas de lectura y validación de la config y de la exportación.

La config se lee en modo estricto: una llave desconocida o faltante es error.
Eso garantiza que ninguna llave de la config quede sin efecto.
"""

from __future__ import annotations

import json
import unittest
from datetime import date
from decimal import Decimal

from test_pl_audit_fixtures import (
    RUTA_CONFIG_EJEMPLO,
    con_cuenta,
    con_valor,
    config_base,
    exportacion_base,
    sin_llave,
)

from auditoria_pl import ErrorEntrada, leer_config, leer_exportacion
from auditoria_pl.validacion import leer_monto, leer_porcentaje


class TestFronteraDeMontos(unittest.TestCase):
    def test_texto_y_entero_se_llevan_a_centavos_sin_redondear(self) -> None:
        self.assertEqual(leer_monto("1234.5", "x"), Decimal("1234.50"))
        self.assertEqual(leer_monto(7, "x"), Decimal("7.00"))
        with self.assertRaises(ErrorEntrada):
            leer_monto("-0.005", "x")

    def test_float_pasa_por_repr_y_no_se_redondea(self) -> None:
        self.assertEqual(leer_monto(1234.56, "x"), Decimal("1234.56"))
        for ambiguo in (1234.565, 0.1 + 0.2):
            with self.subTest(valor=ambiguo):
                with self.assertRaises(ErrorEntrada):
                    leer_monto(ambiguo, "x")

    def test_rechaza_valores_que_no_son_montos(self) -> None:
        for malo in ("abc", "1,000.00", "", True, None, [1], float("nan"), float("inf"), "NaN", "Infinity"):
            with self.subTest(valor=malo):
                with self.assertRaises(ErrorEntrada) as ctx:
                    leer_monto(malo, "cuentas[0].actual")
                self.assertIn("cuentas[0].actual", str(ctx.exception))

    def test_monto_fuera_de_rango(self) -> None:
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_monto("9" * 40, "x")
        self.assertIn("fuera de rango", str(ctx.exception))

    def test_porcentaje_rechaza_negativos(self) -> None:
        self.assertEqual(leer_porcentaje("12.35", "p"), Decimal("12.35"))
        for malo in ("-1", "12.345"):
            with self.subTest(valor=malo):
                with self.assertRaises(ErrorEntrada):
                    leer_porcentaje(malo, "p")


class TestConfigEjemplo(unittest.TestCase):
    def test_config_de_ejemplo_se_lee_sin_errores(self) -> None:
        crudo = json.loads(RUTA_CONFIG_EJEMPLO.read_text(encoding="utf-8"))
        config = leer_config(crudo)
        self.assertEqual(config.publicidad.cuenta, "6120")

    def test_config_de_ejemplo_no_tiene_marcadores_de_estado(self) -> None:
        texto = RUTA_CONFIG_EJEMPLO.read_text(encoding="utf-8")
        self.assertNotIn('"estado"', texto)
        self.assertNotIn("CONFIRMADO", texto)


class TestConfigEstricta(unittest.TestCase):
    def assertRechaza(self, crudo: object, fragmento: str) -> None:
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_config(crudo)
        self.assertIn(fragmento, str(ctx.exception))

    def test_config_base_produce_decimales(self) -> None:
        config = leer_config(config_base())
        banda = config.bandas["margen_bruto"]
        self.assertEqual(
            (banda.minimo_pct, banda.maximo_pct, banda.favorable), (Decimal("40.00"), Decimal("60.00"), "alto")
        )
        self.assertEqual(config.materialidad.piso_monto, Decimal("20000.00"))
        self.assertEqual(config.materialidad.tope_materiales, 10)
        self.assertEqual(config.madurez.dias_minimos_tras_cierre, 3)

    def test_raiz_que_no_es_objeto(self) -> None:
        self.assertRechaza([1, 2], "objeto")

    def test_llave_desconocida_en_raiz(self) -> None:
        self.assertRechaza(con_valor(config_base(), "usar_clase_exacta", True), "usar_clase_exacta")

    def test_llave_desconocida_anidada(self) -> None:
        self.assertRechaza(con_valor(config_base(), "materialidad.monto_extra", "1"), "materialidad.monto_extra")

    def test_llave_faltante(self) -> None:
        self.assertRechaza(sin_llave(config_base(), "madurez.cuentas_nomina"), "madurez.cuentas_nomina")

    def test_esquema_distinto(self) -> None:
        self.assertRechaza(con_valor(config_base(), "esquema", "auditoria_pl_config/v0"), "esquema")

    def test_prefijos_traslapados_entre_rubros(self) -> None:
        self.assertRechaza(con_valor(config_base(), "rubros.gasto_venta", ["6"]), "traslapa")

    def test_prefijo_repetido(self) -> None:
        self.assertRechaza(con_valor(config_base(), "rubros.costo", ["5", "5"]), "repetid")

    def test_rubro_ingreso_vacio(self) -> None:
        self.assertRechaza(con_valor(config_base(), "rubros.ingreso", []), "rubros.ingreso")

    def test_rubro_desconocido(self) -> None:
        self.assertRechaza(con_valor(config_base(), "rubros.otros", ["8"]), "rubros.otros")

    def test_cuenta_sin_polizas_fuera_del_rubro_ingreso(self) -> None:
        self.assertRechaza(con_valor(config_base(), "cuentas_sin_polizas_manuales", ["5010"]), "5010")

    def test_lista_con_elemento_no_texto(self) -> None:
        self.assertRechaza(
            con_valor(config_base(), "madurez.cuentas_nomina", ["6130", 6210]), "madurez.cuentas_nomina[1]"
        )

    def test_lista_con_cuenta_repetida(self) -> None:
        self.assertRechaza(con_valor(config_base(), "madurez.provisiones_obligatorias", ["2150", "2150"]), "repetid")

    def test_dias_minimos_invalidos(self) -> None:
        for malo in (-1, True, "3", 3.5):
            with self.subTest(valor=malo):
                self.assertRechaza(con_valor(config_base(), "madurez.dias_minimos_tras_cierre", malo), "dias_minimos")

    def test_metrica_de_banda_desconocida(self) -> None:
        banda = {"minimo_pct": "1", "maximo_pct": "2", "favorable": "alto"}
        self.assertRechaza(con_valor(config_base(), "bandas.utilidad_neta", banda), "bandas.utilidad_neta")

    def test_banda_con_minimo_mayor_que_maximo(self) -> None:
        self.assertRechaza(con_valor(config_base(), "bandas.ebitda.minimo_pct", "31"), "bandas.ebitda")

    def test_banda_con_lado_favorable_invalido(self) -> None:
        self.assertRechaza(con_valor(config_base(), "bandas.ebitda.favorable", "arriba"), "favorable")

    def test_bandas_parciales_son_validas(self) -> None:
        crudo = sin_llave(sin_llave(config_base(), "bandas.ebitda"), "bandas.gasto_admin")
        self.assertEqual(sorted(leer_config(crudo).bandas), ["gasto_venta", "margen_bruto"])

    def test_objetivo_de_publicidad_mayor_que_alerta(self) -> None:
        self.assertRechaza(con_valor(config_base(), "publicidad.objetivo_pct", "13"), "objetivo_pct")

    def test_cuenta_de_publicidad_vacia(self) -> None:
        self.assertRechaza(con_valor(config_base(), "publicidad.cuenta", " "), "publicidad.cuenta")

    def test_piso_de_mencion_mayor_que_piso_material(self) -> None:
        self.assertRechaza(con_valor(config_base(), "materialidad.piso_mencion", "20000.01"), "piso_mencion")

    def test_piso_de_mencion_cero(self) -> None:
        self.assertRechaza(con_valor(config_base(), "materialidad.piso_mencion", "0"), "piso_mencion")

    def test_tope_de_materiales_invalido(self) -> None:
        for malo in (0, True, "10"):
            with self.subTest(valor=malo):
                self.assertRechaza(con_valor(config_base(), "materialidad.tope_materiales", malo), "tope_materiales")


class TestExportacion(unittest.TestCase):
    def assertRechaza(self, crudo: object, fragmento: str) -> None:
        with self.assertRaises(ErrorEntrada) as ctx:
            leer_exportacion(crudo)
        self.assertIn(fragmento, str(ctx.exception))

    def test_exportacion_base(self) -> None:
        exportacion = leer_exportacion(exportacion_base())
        self.assertEqual(exportacion.periodo, "2026-03")
        self.assertEqual(exportacion.fecha_extraccion, date(2026, 4, 5))
        primera = exportacion.cuentas[0]
        self.assertEqual((primera.cuenta, primera.actual), ("4010", Decimal("1000000.00")))
        self.assertEqual(primera.polizas_manuales_actual, Decimal("0.00"))

    def test_polizas_manuales_opcionales(self) -> None:
        crudo = con_cuenta(exportacion_base(), "4010", polizas_manuales_actual="-25000")
        self.assertEqual(leer_exportacion(crudo).cuentas[0].polizas_manuales_actual, Decimal("-25000.00"))

    def test_raiz_que_no_es_objeto(self) -> None:
        self.assertRechaza("texto", "objeto")

    def test_esquema_distinto(self) -> None:
        self.assertRechaza(con_valor(exportacion_base(), "esquema", "otro"), "esquema")

    def test_periodo_invalido(self) -> None:
        for malo in ("2026-13", "2026-3", "26-03", "2026-00", 202603):
            with self.subTest(valor=malo):
                self.assertRechaza(con_valor(exportacion_base(), "periodo", malo), "periodo")

    def test_fecha_de_extraccion_invalida(self) -> None:
        for malo in ("2026-02-30", "05/04/2026", None):
            with self.subTest(valor=malo):
                self.assertRechaza(con_valor(exportacion_base(), "fecha_extraccion", malo), "fecha_extraccion")

    def test_sin_cuentas(self) -> None:
        self.assertRechaza(con_valor(exportacion_base(), "cuentas", []), "cuentas")

    def test_cuenta_repetida(self) -> None:
        crudo = exportacion_base()
        crudo["cuentas"].append(dict(crudo["cuentas"][0]))
        self.assertRechaza(crudo, "4010")

    def test_cuenta_vacia(self) -> None:
        crudo = exportacion_base()
        crudo["cuentas"][1]["cuenta"] = ""
        self.assertRechaza(crudo, "cuentas[1].cuenta")

    def test_codigo_con_espacios_al_borde(self) -> None:
        crudo = exportacion_base()
        crudo["marcas"][0]["marca"] = "Marca Uno "
        self.assertRechaza(crudo, "espacios")

    def test_polizas_manuales_en_null_no_se_leen_como_cero(self) -> None:
        crudo = con_cuenta(exportacion_base(), "4010", polizas_manuales_actual=None)
        self.assertRechaza(crudo, "cuentas[0].polizas_manuales_actual")

    def test_monto_invalido_indica_ruta(self) -> None:
        crudo = con_cuenta(exportacion_base(), "5010", actual="mil")
        self.assertRechaza(crudo, "cuentas[1].actual")

    def test_llave_desconocida_en_fila(self) -> None:
        crudo = con_cuenta(exportacion_base(), "5010", nota_del_analista="x")
        self.assertRechaza(crudo, "nota_del_analista")

    def test_llave_faltante_en_fila(self) -> None:
        crudo = exportacion_base()
        del crudo["cuentas"][2]["anterior"]
        self.assertRechaza(crudo, "cuentas[2].anterior")

    def test_marca_repetida(self) -> None:
        crudo = exportacion_base()
        crudo["marcas"].append(dict(crudo["marcas"][0]))
        self.assertRechaza(crudo, "Marca Uno")

    def test_provision_repetida(self) -> None:
        crudo = exportacion_base()
        crudo["provisiones"].append(dict(crudo["provisiones"][0]))
        self.assertRechaza(crudo, "2150")

    def test_lista_que_no_es_lista(self) -> None:
        self.assertRechaza(con_valor(exportacion_base(), "marcas", {"a": 1}), "marcas")

    def test_fila_que_no_es_objeto(self) -> None:
        self.assertRechaza(con_valor(exportacion_base(), "provisiones", ["2150"]), "provisiones[0]")


if __name__ == "__main__":
    unittest.main()
