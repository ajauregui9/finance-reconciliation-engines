"""Pruebas de la afinidad de nombres del cruce cargo ↔ CFDI."""
from __future__ import annotations

import sys
from fractions import Fraction
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion.cruce_cfdi_nombres import afinidad, palabras_nombre  # noqa: E402


class TestPalabrasNombre:
    def test_quita_acentos_formas_societarias_y_numeros(self) -> None:
        assert palabras_nombre("Cafetería Luna Azul, S.A. de C.V. 0231") == ("CAFETERIA", "LUNA", "AZUL")

    def test_descarta_palabras_cortas_y_articulos(self) -> None:
        assert palabras_nombre("ES EL CRUCERO 0874 PUE") == ("CRUCERO", "PUE")

    def test_texto_vacio_o_solo_ruido(self) -> None:
        assert palabras_nombre("") == ()
        assert palabras_nombre("   12 34 ") == ()
        assert palabras_nombre("SA DE CV") == ()

    def test_caracteres_especiales_y_emoji(self) -> None:
        assert palabras_nombre("PANADERÍA 🍞 'TRIGO'; DROP TABLE--") == ("PANADERIA", "TRIGO", "DROP", "TABLE")

    def test_enie_se_normaliza(self) -> None:
        assert palabras_nombre("PIÑATAS DEL NIÑO") == ("PINATAS", "NINO")


class TestAfinidad:
    def test_nombres_iguales_valen_uno(self) -> None:
        assert afinidad("FARMACIA SALUD EJEMPLO", "FARMACIA SALUD EJEMPLO SA DE CV") == Fraction(1)

    def test_nombres_ajenos_valen_cero(self) -> None:
        assert afinidad("FARMACIA SALUD CDMX", "OPERADORA HOTEL MIRADOR DEL LAGO SA DE CV") == Fraction(0)

    def test_abreviatura_por_truncamiento(self) -> None:
        assert afinidad("SUMINISTROS OFI MTY", "SUMINISTROS DE OFICINA SA DE CV") == Fraction(1)

    def test_toma_la_mayor_de_las_dos_coberturas(self) -> None:
        # Cada lado tiene una palabra sin pareja (MTY y EJEMPLO): 2 de 3 en ambos sentidos.
        assert afinidad("SUMINISTROS OFI MTY", "SUMINISTROS DE OFICINA EJEMPLO SA DE CV") == Fraction(2, 3)
        # Un nombre corto contenido completo en uno largo vale 1.
        assert afinidad("HOTEL", "HOTEL PLAYA DEMO SA DE CV") == Fraction(1)

    def test_abreviatura_por_omision_de_letras(self) -> None:
        assert afinidad("HTL PLAZA CENTRAL", "HOTEL PLAZA CENTRAL DEMO SA DE CV") == Fraction(1)

    def test_prefijo_comun_de_cuatro_letras(self) -> None:
        assert afinidad("AERODEMO NAL", "AEROLINEA DEMO NACIONAL SA DE CV") == Fraction(1)

    def test_prefijo_de_tres_letras_no_basta_sin_orden(self) -> None:
        assert afinidad("CAMARA", "CAMINO REAL") == Fraction(0)

    def test_vacio_da_cero(self) -> None:
        assert afinidad("", "HOTEL") == Fraction(0)
        assert afinidad("HOTEL", "") == Fraction(0)

    def test_es_simetrica(self) -> None:
        a, b = "TAXI SEGURO EJEMPLO GDL", "VIGILANCIA Y SEGURIDAD EJEMPLO SA DE CV"
        assert afinidad(a, b) == afinidad(b, a)

    @pytest.mark.parametrize(
        "descriptor,razon",
        [
            ("GAS RUTA NORTE 5521 MTY", "GASOLINERA RUTA NORTE SA DE CV"),
            ("TAQ EL FOGONCITO GDL", "TAQUERIA EL FOGONCITO SA DE CV"),
            ("REST TERRAZA DEL VALLE MTY", "RESTAURANTE LA TERRAZA DEL VALLE S DE RL DE CV"),
        ],
    )
    def test_descriptores_de_tarjeta_contra_razon_social(self, descriptor: str, razon: str) -> None:
        assert afinidad(descriptor, razon) >= Fraction(1, 2)
