#!/usr/bin/env python3
"""Pruebas unitarias de la lectura de importes del universo de cargos.

Compatibles con `pytest` y con `python3 -m unittest`.
"""
from __future__ import annotations

import sys
import unittest
from decimal import Decimal
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
RUTA_SKILL = str(RAIZ / "skills" / "credit-card-reconciliation")
if RUTA_SKILL not in sys.path:
    sys.path.insert(0, RUTA_SKILL)

from conciliacion import montos  # noqa: E402


class LeerImporteConMilesTest(unittest.TestCase):
    """Formato de una columna firmada con separador de miles opcional."""

    def leer(self, texto: str):
        return montos.leer_importe(texto, con_signo=True, con_miles=True)

    def test_importe_agrupado_positivo(self) -> None:
        self.assertEqual(self.leer("2,847.11"), Decimal("2847.11"))

    def test_importe_agrupado_negativo(self) -> None:
        self.assertEqual(self.leer("-81,036.96"), Decimal("-81036.96"))

    def test_importe_sin_agrupar_se_acepta(self) -> None:
        self.assertEqual(self.leer("208.82"), Decimal("208.82"))
        self.assertEqual(self.leer("1234.56"), Decimal("1234.56"))

    def test_importe_grande(self) -> None:
        self.assertEqual(self.leer("999,999,999.99"), Decimal("999999999.99"))

    def test_espacios_externos_se_ignoran(self) -> None:
        self.assertEqual(self.leer("  12.30 "), Decimal("12.30"))

    def test_resultado_tiene_dos_decimales(self) -> None:
        valor = self.leer("5.00")
        self.assertIsNotNone(valor)
        self.assertEqual(str(valor), "5.00")

    def test_agrupacion_mal_formada_se_rechaza(self) -> None:
        for texto in ("1,23.45", "12,3456.00", ",123.00", "1,,234.00", "1,234,5.00"):
            with self.subTest(texto=texto):
                self.assertIsNone(self.leer(texto))

    def test_decimales_distintos_de_dos_se_rechazan(self) -> None:
        for texto in ("12.3", "12", "12.345", "12."):
            with self.subTest(texto=texto):
                self.assertIsNone(self.leer(texto))

    def test_texto_vacio_o_basura_se_rechaza(self) -> None:
        for texto in ("", "   ", "abc", "12.3a", "$12.30", "1 234.00", "--5.00", "+5.00"):
            with self.subTest(texto=texto):
                self.assertIsNone(self.leer(texto))

    def test_digitos_no_ascii_se_rechazan(self) -> None:
        # `\d` de Python acepta dígitos de otros alfabetos; el formato no.
        for texto in ("١٢.٣٤", "１２.３４", "12.3٤"):
            with self.subTest(texto=texto):
                self.assertIsNone(self.leer(texto))


class LeerImporteSinSignoTest(unittest.TestCase):
    """Formato de columnas sin signo y sin separador de miles."""

    def leer(self, texto: str):
        return montos.leer_importe(texto, con_signo=False, con_miles=False)

    def test_importe_simple(self) -> None:
        self.assertEqual(self.leer("1588.65"), Decimal("1588.65"))

    def test_signo_se_rechaza(self) -> None:
        self.assertIsNone(self.leer("-5.00"))

    def test_separador_de_miles_se_rechaza(self) -> None:
        self.assertIsNone(self.leer("1,000.00"))

    def test_cero_es_un_importe_valido(self) -> None:
        self.assertEqual(self.leer("0.00"), Decimal("0.00"))


class LeerTipoCambioTest(unittest.TestCase):
    def test_cuatro_decimales(self) -> None:
        self.assertEqual(montos.leer_tipo_cambio("17.7145"), Decimal("17.7145"))

    def test_menos_decimales_se_completan(self) -> None:
        valor = montos.leer_tipo_cambio("19.36")
        self.assertEqual(valor, Decimal("19.36"))
        self.assertIsNotNone(valor)
        self.assertEqual(montos.texto_tipo_cambio(valor), "19.3600")  # type: ignore[arg-type]

    def test_entero_se_acepta(self) -> None:
        self.assertEqual(montos.leer_tipo_cambio("18"), Decimal("18"))

    def test_mas_de_cuatro_decimales_se_rechaza(self) -> None:
        self.assertIsNone(montos.leer_tipo_cambio("17.71455"))

    def test_cero_negativo_o_vacio_se_rechaza(self) -> None:
        for texto in ("0", "0.0000", "-1.5", "", "abc", "1,8.00", "١٨.٢"):
            with self.subTest(texto=texto):
                self.assertIsNone(montos.leer_tipo_cambio(texto))


class LeerMontoResumenTest(unittest.TestCase):
    """El resumen es dato externo: solo texto con dos decimales."""

    def test_texto_valido(self) -> None:
        self.assertEqual(montos.leer_monto_resumen("-1234.56", "campo"), Decimal("-1234.56"))
        self.assertEqual(montos.leer_monto_resumen("0.00", "campo"), Decimal("0.00"))

    def test_numero_json_se_rechaza(self) -> None:
        for valor in (1234.56, 12, True, None, ["1.00"]):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError) as ctx:
                    montos.leer_monto_resumen(valor, "total_neto")
                self.assertIn("total_neto", str(ctx.exception))

    def test_formato_invalido_se_rechaza(self) -> None:
        for valor in ("12.3", "1,234.56", "", " 1.00", "1.00 ", "+1.00"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    montos.leer_monto_resumen(valor, "total_neto")


class FormatoSalidaTest(unittest.TestCase):
    def test_texto_monto(self) -> None:
        self.assertEqual(montos.texto_monto(Decimal("5")), "5.00")
        self.assertEqual(montos.texto_monto(Decimal("-0.5")), "-0.50")
        self.assertEqual(montos.texto_monto(Decimal("1234567.891")), "1234567.89")

    def test_texto_monto_redondea_mitad_hacia_arriba(self) -> None:
        self.assertEqual(montos.texto_monto(Decimal("0.005")), "0.01")
        self.assertEqual(montos.texto_monto(Decimal("-0.005")), "-0.01")

    def test_texto_tipo_cambio(self) -> None:
        self.assertEqual(montos.texto_tipo_cambio(Decimal("18")), "18.0000")
        self.assertEqual(montos.texto_tipo_cambio(Decimal("17.7145")), "17.7145")


if __name__ == "__main__":
    unittest.main()
