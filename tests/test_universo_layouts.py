#!/usr/bin/env python3
"""Pruebas unitarias de detección de layout e interpretación de filas.

Compatibles con `pytest` y con `python3 -m unittest`.
"""
from __future__ import annotations

import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Tuple

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SKILL = str(RAIZ / "skills" / "credit-card-reconciliation")
if RUTA_SKILL not in sys.path:
    sys.path.insert(0, RUTA_SKILL)

from conciliacion import layouts  # noqa: E402

ENCABEZADO_ALFA = (
    "Fecha de operación", "Fecha de aplicación", "Descripción", "Titular", "Tarjeta",
    "Moneda origen", "Importe origen", "Tipo de cambio", "Importe MXN",
)
ENCABEZADO_BETA = (
    "Transaction Date", "Post Date", "Description", "Card Member", "Account Ending",
    "Foreign Spend Amount", "Foreign Currency", "Exchange Rate", "Charges", "Credits",
)


def fila_alfa(**cambios: str) -> Tuple[str, ...]:
    base = {
        "operacion": "08/07/2026", "aplicacion": "09/07/2026",
        "descripcion": "CAFE  DE  PRUEBA        CDMX", "titular": "ANA DEMO",
        "tarjeta": "****1001", "moneda": "MXN", "origen": "1,250.40", "tc": "",
        "mxn": "1,250.40",
    }
    base.update(cambios)
    return (base["operacion"], base["aplicacion"], base["descripcion"], base["titular"],
            base["tarjeta"], base["moneda"], base["origen"], base["tc"], base["mxn"])


def fila_beta(**cambios: str) -> Tuple[str, ...]:
    base = {
        "operacion": "07/08/2026", "aplicacion": "07/09/2026",
        "descripcion": "TIENDA DE PRUEBA GDL", "titular": "CARLA DEMO", "tarjeta": "2001",
        "extranjero": "", "divisa": "", "tc": "", "cargo": "540.10", "abono": "",
    }
    base.update(cambios)
    return (base["operacion"], base["aplicacion"], base["descripcion"], base["titular"],
            base["tarjeta"], base["extranjero"], base["divisa"], base["tc"], base["cargo"],
            base["abono"])


ALFA = layouts.LAYOUTS["ALFA_V1"]
BETA = layouts.LAYOUTS["BETA_V1"]


class CatalogoTest(unittest.TestCase):
    def test_catalogo_tiene_los_dos_layouts(self) -> None:
        self.assertEqual(sorted(layouts.LAYOUTS), ["ALFA_V1", "BETA_V1"])
        self.assertEqual(ALFA.encabezado, ENCABEZADO_ALFA)
        self.assertEqual(BETA.encabezado, ENCABEZADO_BETA)

    def test_encabezados_unicos(self) -> None:
        encabezados = [lay.encabezado for lay in layouts.LAYOUTS.values()]
        self.assertEqual(len(encabezados), len(set(encabezados)))

    def test_catalogo_rechaza_encabezado_repetido(self) -> None:
        copia = layouts.Layout(
            nombre="OTRO_V1", encabezado=ALFA.encabezado, moneda="MXN",
            marca_pago="X", interpretar=ALFA.interpretar)
        with self.assertRaises(ValueError):
            layouts.armar_catalogo((ALFA, copia))

    def test_catalogo_rechaza_nombre_repetido(self) -> None:
        with self.assertRaises(ValueError):
            layouts.armar_catalogo((ALFA, ALFA))

    def test_catalogo_es_inmutable(self) -> None:
        with self.assertRaises(TypeError):
            layouts.LAYOUTS["NUEVO"] = ALFA  # type: ignore[index]


class DetectarLayoutTest(unittest.TestCase):
    def test_detecta_alfa(self) -> None:
        self.assertIs(layouts.detectar_layout(list(ENCABEZADO_ALFA), "a.csv"), ALFA)

    def test_detecta_beta(self) -> None:
        self.assertIs(layouts.detectar_layout(ENCABEZADO_BETA, "b.csv"), BETA)

    def test_encabezado_desconocido_no_se_adivina(self) -> None:
        variantes = {
            "espacio_extra": (ENCABEZADO_ALFA[0] + " ",) + ENCABEZADO_ALFA[1:],
            "orden_distinto": (ENCABEZADO_BETA[1], ENCABEZADO_BETA[0]) + ENCABEZADO_BETA[2:],
            "columna_extra": ENCABEZADO_ALFA + ("Referencia",),
            "columna_faltante": ENCABEZADO_BETA[:-1],
            "minusculas": tuple(c.lower() for c in ENCABEZADO_BETA),
            "sin_acentos": tuple(c.replace("ó", "o") for c in ENCABEZADO_ALFA),
            "vacio": (),
            "libro_mayor": ("asiento_id", "linea", "fecha"),
        }
        for nombre, encabezado in variantes.items():
            with self.subTest(variante=nombre):
                with self.assertRaises(layouts.EncabezadoDesconocido) as ctx:
                    layouts.detectar_layout(encabezado, "estado_x.csv")
                mensaje = str(ctx.exception)
                self.assertIn("estado_x.csv", mensaje)
                self.assertIn("encabezado", mensaje.lower())

    def test_encabezado_desconocido_es_error_de_insumo(self) -> None:
        self.assertTrue(issubclass(layouts.EncabezadoDesconocido, layouts.ErrorInsumo))


class LeerFechaTest(unittest.TestCase):
    def test_dia_mes_anio(self) -> None:
        self.assertEqual(layouts.leer_fecha("01/07/2026", "DMA"), date(2026, 7, 1))

    def test_mes_dia_anio(self) -> None:
        self.assertEqual(layouts.leer_fecha("01/07/2026", "MDA"), date(2026, 1, 7))

    def test_fecha_imposible(self) -> None:
        self.assertIsNone(layouts.leer_fecha("30/02/2026", "DMA"))
        self.assertIsNone(layouts.leer_fecha("04/31/2026", "MDA"))
        self.assertIsNone(layouts.leer_fecha("00/07/2026", "DMA"))
        self.assertIsNone(layouts.leer_fecha("13/13/2026", "DMA"))

    def test_formato_distinto_se_rechaza(self) -> None:
        for texto in ("1/7/2026", "2026-07-01", "01-07-2026", "01/07/26", "", "  ", "٠١/٠٧/٢٠٢٦"):
            with self.subTest(texto=texto):
                self.assertIsNone(layouts.leer_fecha(texto, "DMA"))

    def test_espacios_externos_se_ignoran(self) -> None:
        self.assertEqual(layouts.leer_fecha(" 28/07/2026 ", "DMA"), date(2026, 7, 28))

    def test_orden_desconocido_es_error_de_programa(self) -> None:
        with self.assertRaises(ValueError):
            layouts.leer_fecha("01/07/2026", "AMD")


class ClasificarMovimientoTest(unittest.TestCase):
    def test_reglas(self) -> None:
        casos = [
            (Decimal("10.00"), "CAFE", "cargo"),
            (Decimal("10.00"), "PAGO RECIBIDO GRACIAS", "cargo"),
            (Decimal("-10.00"), "PAGO RECIBIDO GRACIAS", "pago"),
            (Decimal("-10.00"), "pago recibido gracias", "pago"),
            (Decimal("-10.00"), "DEVOLUCION PAGO RECIBIDO", "abono"),
            (Decimal("-10.00"), "CAFE", "abono"),
            (Decimal("0.00"), "CAFE", None),
            (None, "CAFE", None),
            (Decimal("-10.00"), None, "abono"),
        ]
        for monto, descripcion, esperado in casos:
            with self.subTest(monto=monto, descripcion=descripcion):
                self.assertEqual(
                    layouts.clasificar_movimiento(monto, descripcion, "PAGO RECIBIDO"), esperado)


class InterpretarAlfaTest(unittest.TestCase):
    def test_fila_mxn(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa())
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.fecha, date(2026, 7, 8))
        self.assertEqual(lectura.fecha_aplicacion, date(2026, 7, 9))
        self.assertEqual(lectura.descripcion, "CAFE DE PRUEBA CDMX")
        self.assertEqual(lectura.titular, "ANA DEMO")
        self.assertEqual(lectura.tarjeta_ultimos4, "1001")
        self.assertEqual(lectura.monto, Decimal("1250.40"))
        self.assertEqual(lectura.monto_original, Decimal("1250.40"))
        self.assertEqual(lectura.moneda_original, "MXN")
        self.assertIsNone(lectura.tipo_cambio)

    def test_fila_usd(self) -> None:
        lectura = layouts.interpretar_fila(
            ALFA, fila_alfa(moneda="USD", origen="19.00", tc="17.5000", mxn="332.50"))
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.moneda_original, "USD")
        self.assertEqual(lectura.monto_original, Decimal("19.00"))
        self.assertEqual(lectura.tipo_cambio, Decimal("17.5000"))
        self.assertEqual(lectura.monto, Decimal("332.50"))

    def test_devolucion_usd_negativa(self) -> None:
        lectura = layouts.interpretar_fila(
            ALFA, fila_alfa(moneda="USD", origen="-19.00", tc="17.5000", mxn="-332.50"))
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.monto_original, Decimal("-19.00"))

    def test_fecha_invalida_conserva_los_demas_campos(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(operacion="30/02/2026"))
        self.assertEqual(lectura.problemas, ("fecha_invalida",))
        self.assertIsNone(lectura.fecha)
        self.assertEqual(lectura.fecha_aplicacion, date(2026, 7, 9))
        self.assertEqual(lectura.monto, Decimal("1250.40"))

    def test_fecha_en_orden_de_beta_no_se_acepta_si_es_imposible(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(operacion="07/28/2026"))
        self.assertEqual(lectura.problemas, ("fecha_invalida",))

    def test_mxn_con_tipo_de_cambio_es_contradictorio(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(tc="17.0000"))
        self.assertEqual(lectura.problemas, ("moneda_original_invalida",))
        self.assertIsNone(lectura.moneda_original)
        self.assertIsNone(lectura.monto_original)
        self.assertIsNone(lectura.tipo_cambio)
        self.assertEqual(lectura.monto, Decimal("1250.40"))

    def test_mxn_con_importe_origen_distinto(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(origen="1,250.41"))
        self.assertEqual(lectura.problemas, ("moneda_original_invalida",))

    def test_extranjera_incompleta_o_contradictoria(self) -> None:
        variantes = {
            "sin_tipo_cambio": fila_alfa(moneda="USD", origen="19.00", tc="", mxn="332.50"),
            "signo_opuesto": fila_alfa(moneda="USD", origen="-19.00", tc="17.5000", mxn="332.50"),
            "origen_cero": fila_alfa(moneda="USD", origen="0.00", tc="17.5000", mxn="332.50"),
            "origen_ilegible": fila_alfa(moneda="USD", origen="x", tc="17.5000", mxn="332.50"),
            "codigo_raro": fila_alfa(moneda="usd", origen="19.00", tc="17.5000", mxn="332.50"),
            "codigo_vacio": fila_alfa(moneda="", origen="19.00", tc="17.5000", mxn="332.50"),
            "tc_excesivo": fila_alfa(moneda="USD", origen="19.00", tc="17.50001", mxn="332.50"),
        }
        for nombre, celdas in variantes.items():
            with self.subTest(variante=nombre):
                lectura = layouts.interpretar_fila(ALFA, celdas)
                self.assertEqual(lectura.problemas, ("moneda_original_invalida",))
                self.assertEqual(lectura.monto, Decimal("332.50"))

    def test_monto_ilegible(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(mxn="1.250,40"))
        self.assertIn("monto_invalido", lectura.problemas)
        self.assertIsNone(lectura.monto)

    def test_monto_cero(self) -> None:
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(origen="0.00", mxn="0.00"))
        self.assertEqual(lectura.problemas, ("monto_cero",))
        self.assertEqual(lectura.monto, Decimal("0.00"))

    def test_tarjeta_titular_y_descripcion(self) -> None:
        lectura = layouts.interpretar_fila(
            ALFA, fila_alfa(tarjeta="1001", titular="  ", descripcion=" \t "))
        self.assertEqual(
            lectura.problemas, ("descripcion_vacia", "titular_vacio", "tarjeta_invalida"))
        self.assertIsNone(lectura.tarjeta_ultimos4)
        self.assertIsNone(lectura.titular)
        self.assertIsNone(lectura.descripcion)

    def test_varios_motivos_en_orden_canonico(self) -> None:
        lectura = layouts.interpretar_fila(
            ALFA, fila_alfa(operacion="x", aplicacion="31/06/2026", tarjeta="****10", mxn="?"))
        self.assertEqual(
            lectura.problemas,
            ("fecha_invalida", "fecha_aplicacion_invalida", "tarjeta_invalida", "monto_invalido"))

    def test_caracteres_especiales_se_conservan(self) -> None:
        texto = "CAFÉ «ÑANDÚ» 'O''R; DROP--  ☃  MTY"
        lectura = layouts.interpretar_fila(ALFA, fila_alfa(descripcion=texto))
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.descripcion, "CAFÉ «ÑANDÚ» 'O''R; DROP-- ☃ MTY")


class InterpretarBetaTest(unittest.TestCase):
    def test_cargo_mxn(self) -> None:
        lectura = layouts.interpretar_fila(BETA, fila_beta())
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.fecha, date(2026, 7, 8))
        self.assertEqual(lectura.fecha_aplicacion, date(2026, 7, 9))
        self.assertEqual(lectura.tarjeta_ultimos4, "2001")
        self.assertEqual(lectura.monto, Decimal("540.10"))
        self.assertEqual(lectura.monto_original, Decimal("540.10"))
        self.assertEqual(lectura.moneda_original, "MXN")
        self.assertIsNone(lectura.tipo_cambio)

    def test_credito_es_negativo(self) -> None:
        lectura = layouts.interpretar_fila(BETA, fila_beta(cargo="", abono="324.23"))
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.monto, Decimal("-324.23"))
        self.assertEqual(lectura.monto_original, Decimal("-324.23"))

    def test_cargo_usd(self) -> None:
        lectura = layouts.interpretar_fila(
            BETA, fila_beta(extranjero="98.73", divisa="USD", tc="18.2765", cargo="1804.44"))
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.monto_original, Decimal("98.73"))
        self.assertEqual(lectura.moneda_original, "USD")
        self.assertEqual(lectura.tipo_cambio, Decimal("18.2765"))

    def test_credito_usd_toma_el_signo_del_credito(self) -> None:
        lectura = layouts.interpretar_fila(
            BETA, fila_beta(extranjero="10.00", divisa="USD", tc="18.0000", cargo="",
                            abono="180.00"))
        self.assertEqual(lectura.problemas, ())
        self.assertEqual(lectura.monto_original, Decimal("-10.00"))

    def test_ambas_columnas_o_ninguna(self) -> None:
        for cargo, abono in (("10.00", "10.00"), ("", ""), ("  ", "")):
            with self.subTest(cargo=cargo, abono=abono):
                lectura = layouts.interpretar_fila(BETA, fila_beta(cargo=cargo, abono=abono))
                self.assertEqual(lectura.problemas, ("monto_ambiguo",))
                self.assertIsNone(lectura.monto)
                self.assertIsNone(lectura.monto_original)

    def test_importe_con_signo_o_miles(self) -> None:
        for cargo in ("-10.00", "1,000.00", "10"):
            with self.subTest(cargo=cargo):
                lectura = layouts.interpretar_fila(BETA, fila_beta(cargo=cargo))
                self.assertEqual(lectura.problemas, ("monto_invalido",))
                self.assertIsNone(lectura.monto)

    def test_monto_cero(self) -> None:
        lectura = layouts.interpretar_fila(BETA, fila_beta(cargo="0.00"))
        self.assertEqual(lectura.problemas, ("monto_cero",))

    def test_extranjera_parcial_o_contradictoria(self) -> None:
        variantes = {
            "solo_importe": fila_beta(extranjero="10.00"),
            "sin_tipo_cambio": fila_beta(extranjero="10.00", divisa="USD"),
            "divisa_de_facturacion": fila_beta(extranjero="10.00", divisa="MXN", tc="1.0000"),
            "importe_con_signo": fila_beta(extranjero="-10.00", divisa="USD", tc="18.0000"),
            "importe_cero": fila_beta(extranjero="0.00", divisa="USD", tc="18.0000"),
            "tc_cero": fila_beta(extranjero="10.00", divisa="USD", tc="0.0000"),
        }
        for nombre, celdas in variantes.items():
            with self.subTest(variante=nombre):
                lectura = layouts.interpretar_fila(BETA, celdas)
                self.assertEqual(lectura.problemas, ("moneda_original_invalida",))
                self.assertIsNone(lectura.moneda_original)
                self.assertEqual(lectura.monto, Decimal("540.10"))

    def test_extranjera_sin_monto_conocido_no_inventa_signo(self) -> None:
        lectura = layouts.interpretar_fila(
            BETA, fila_beta(extranjero="10.00", divisa="USD", tc="18.0000", cargo="x"))
        self.assertEqual(lectura.problemas, ("monto_invalido",))
        self.assertIsNone(lectura.monto_original)
        self.assertEqual(lectura.moneda_original, "USD")
        self.assertEqual(lectura.tipo_cambio, Decimal("18.0000"))

    def test_fecha_imposible_de_beta(self) -> None:
        lectura = layouts.interpretar_fila(BETA, fila_beta(operacion="04/31/2026"))
        self.assertEqual(lectura.problemas, ("fecha_invalida",))
        self.assertIsNone(lectura.fecha)

    def test_tarjeta_enmascarada_no_es_de_beta(self) -> None:
        lectura = layouts.interpretar_fila(BETA, fila_beta(tarjeta="****2001"))
        self.assertEqual(lectura.problemas, ("tarjeta_invalida",))


class FilasIncompletasTest(unittest.TestCase):
    def test_fila_vacia(self) -> None:
        for celdas in ((), ("",) * 9, (" ",) * 9):
            with self.subTest(celdas=celdas):
                lectura = layouts.interpretar_fila(ALFA, celdas)
                self.assertEqual(lectura.problemas, ("fila_vacia",))
                self.assertIsNone(lectura.monto)
                self.assertIsNone(lectura.descripcion)

    def test_columnas_de_menos_o_de_mas(self) -> None:
        for celdas in (fila_alfa()[:-1], fila_alfa() + ("extra",)):
            with self.subTest(n=len(celdas)):
                lectura = layouts.interpretar_fila(ALFA, celdas)
                self.assertEqual(lectura.problemas, ("columnas_incompletas",))
                self.assertIsNone(lectura.fecha)
                self.assertIsNone(lectura.monto)
                self.assertIsNone(lectura.moneda_original)


if __name__ == "__main__":
    unittest.main()
