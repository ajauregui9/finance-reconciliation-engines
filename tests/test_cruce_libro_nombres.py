"""Pruebas de la similitud de nombres del cruce con libro mayor."""
from __future__ import annotations

import sys
import time
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

RAIZ_SKILL = Path(__file__).resolve().parents[1] / "skills" / "credit-card-reconciliation"
if str(RAIZ_SKILL) not in sys.path:
    sys.path.insert(0, str(RAIZ_SKILL))

from conciliacion import nombres  # noqa: E402
from conciliacion.nombres import ComparadorNombres, ReglasNombres  # noqa: E402

REGLAS = ReglasNombres()


def _comparador(stop_izq: frozenset = frozenset(), stop_der: frozenset = frozenset()) -> ComparadorNombres:
    return ComparadorNombres(stop_izq=stop_izq, stop_der=stop_der, reglas=REGLAS)


# ------------------------------------------------------------------ tokens
class TestTokenizar:
    def test_quita_acentos_puntuacion_digitos_y_letras_sueltas(self) -> None:
        assert nombres.tokenizar("Café  Luna-Azul 0231 y") == ("CAFE", "LUNA", "AZUL")

    def test_texto_vacio_o_solo_simbolos_no_da_tokens(self) -> None:
        assert nombres.tokenizar("") == ()
        assert nombres.tokenizar(" *** 123 ") == ()

    def test_unicode_y_emojis_se_vuelven_separadores(self) -> None:
        assert nombres.tokenizar("CAFÉ☕LUNA ñandú") == ("CAFE", "LUNA", "NANDU")

    def test_caracteres_de_sql_no_rompen_nada(self) -> None:
        assert nombres.tokenizar("O'BRIEN; DROP TABLE--") == ("BRIEN", "DROP", "TABLE")

    def test_tokens_alfanumericos_se_conservan(self) -> None:
        assert nombres.tokenizar("TIENDA 24H") == ("TIENDA", "24H")


# --------------------------------------------------------------- stopwords
class TestStopwordsPorLado:
    def test_token_en_suficientes_nombres_distintos_es_stopword(self) -> None:
        reglas = ReglasNombres(min_nombres_stopword=2, stopwords_fijas=frozenset())
        lado = ["CAFE LUNA CDMX", "TAXI SOL CDMX", "PAN TRIGO"]
        assert nombres.stopwords_de_lado(lado, reglas) == frozenset({"CDMX"})

    def test_un_nombre_repetido_cuenta_una_sola_vez(self) -> None:
        reglas = ReglasNombres(min_nombres_stopword=2, stopwords_fijas=frozenset())
        lado = ["CAFE LUNA CDMX"] * 10 + ["PAN TRIGO"]
        assert nombres.stopwords_de_lado(lado, reglas) == frozenset()

    def test_las_stopwords_fijas_siempre_cuentan(self) -> None:
        reglas = ReglasNombres(min_nombres_stopword=99, stopwords_fijas=frozenset({"SA", "CV"}))
        assert nombres.stopwords_de_lado(["CAFE SA DE CV"], reglas) == frozenset({"SA", "CV"})

    def test_vocabulario_vacio_solo_trae_las_fijas(self) -> None:
        assert nombres.stopwords_de_lado([], REGLAS) == REGLAS.stopwords_fijas

    def test_stopword_de_un_lado_solo_se_quita_de_ese_lado(self) -> None:
        # CDMX es stopword solo a la izquierda: a la derecha sigue contando y no se explica.
        por_lado = _comparador(stop_izq=frozenset({"CDMX"}))
        en_ambos = _comparador(stop_izq=frozenset({"CDMX"}), stop_der=frozenset({"CDMX"}))
        assert por_lado.similitud("LUNA CDMX", "LUNA CDMX") == Fraction(2, 3)
        assert en_ambos.similitud("LUNA CDMX", "LUNA CDMX") == Fraction(1)

    def test_desde_vocabularios_calcula_cada_lado_por_separado(self) -> None:
        reglas = ReglasNombres(min_nombres_stopword=2, stopwords_fijas=frozenset())
        comp = ComparadorNombres.desde_vocabularios(
            ["CAFE LUNA CDMX", "TAXI SOL CDMX"], ["CAFETERIA LUNA DEMO", "TAXIS SOL DEMO"], reglas)
        assert comp.stop_izq == frozenset({"CDMX"})
        assert comp.stop_der == frozenset({"DEMO"})

    def test_diez_mil_nombres_se_procesan_rapido(self) -> None:
        lado = [f"COMERCIO {n:05d} SUCURSAL{n % 7}" for n in range(10_000)]
        inicio = time.perf_counter()
        stop = nombres.stopwords_de_lado(lado, ReglasNombres(min_nombres_stopword=50))
        assert time.perf_counter() - inicio < 5
        assert "COMERCIO" in stop


# ----------------------------------------------------------------- créditos
class TestCreditoEntreTokens:
    @pytest.mark.parametrize("a, b, esperado", [
        ("LUNA", "LUNA", 4),            # iguales
        ("TAQ", "TAQUERIA", 3),         # truncamiento
        ("TAQUERIA", "TAQ", 3),         # truncamiento, sin importar el lado
        ("HTL", "HOTEL", 3),            # abreviatura
        ("NAL", "NACIONAL", 3),         # abreviatura
        ("SW", "SOFTWARE", 2),          # abreviatura de dos letras
        ("AUTOS", "AUTOLAVADO", 4),     # raíz común
        ("XTL", "HOTEL", 0),            # abreviatura con otra inicial
        ("HOTL", "HOTEL", 0),           # cuatro letras: ni prefijo ni abreviatura ni raíz
        ("PLAZA", "CENTRAL", 0),        # sin relación
    ])
    def test_reglas_de_enlace(self, a: str, b: str, esperado: int) -> None:
        assert nombres.credito_tokens(a, b, REGLAS) == esperado

    def test_los_largos_minimos_son_configurables(self) -> None:
        estricto = ReglasNombres(largo_min_prefijo=5, largo_max_abreviatura=1, largo_min_raiz=9)
        assert nombres.credito_tokens("TAQ", "TAQUERIA", estricto) == 0
        assert nombres.credito_tokens("AUTOS", "AUTOLAVADO", estricto) == 0


# --------------------------------------------------------------- similitud
class TestSimilitud:
    def test_nombres_iguales_valen_uno(self) -> None:
        assert _comparador().similitud("CAFE LUNA AZUL", "CAFE LUNA AZUL") == 1

    def test_sin_ningun_enlace_vale_cero(self) -> None:
        assert _comparador().similitud("PLAZA NORTE", "FARMACIA SALUD") == 0

    def test_nombre_vacio_vale_cero(self) -> None:
        assert _comparador().similitud("", "CAFE LUNA") == 0
        assert _comparador().similitud("CAFE", "   ") == 0

    def test_descriptor_truncado_contra_razon_comercial(self) -> None:
        # TAQ(3+3) + FOGONCITO(9+9) sobre (3+9) + (8+9) caracteres.
        assert _comparador().similitud("TAQ FOGONCITO", "TAQUERIA FOGONCITO") == Fraction(24, 29)

    def test_palabra_pegada_se_enlaza_con_dos_tokens_del_otro_lado(self) -> None:
        comp = _comparador(stop_der=frozenset({"DEMO"}))
        assert comp.similitud("DEMOCLOUD TOOLS", "DEMO CLOUD TOOLS") == 1

    def test_pieza_corta_no_forma_palabra_pegada(self) -> None:
        # "AB" + "CLOUD" no cuenta: la primera pieza mide menos que largo_min_pieza.
        assert _comparador().similitud("ABCLOUD", "AB CLOUD") < Fraction(1, 2)

    def test_palabra_pegada_tambien_funciona_del_lado_derecho(self) -> None:
        assert _comparador().similitud("TEST DATA", "TESTDATA") == 1

    def test_si_todo_el_nombre_es_stopword_se_usa_completo(self) -> None:
        comp = _comparador(stop_izq=frozenset({"HOTEL", "PLAYA"}))
        assert comp.similitud("HOTEL PLAYA", "HOTEL PLAYA") == 1

    def test_un_token_no_se_usa_dos_veces(self) -> None:
        # Un solo LUNA a la derecha no explica dos LUNA a la izquierda.
        assert _comparador().similitud("LUNA LUNA", "LUNA") == Fraction(8, 12)

    def test_con_las_mismas_stopwords_es_simetrica(self) -> None:
        comp = _comparador(stop_izq=frozenset({"DEMO"}), stop_der=frozenset({"DEMO"}))
        pares = [("ES EL CRUCERO", "ESTACION SERVICIO CRUCERO"), ("AERODEMO NAL", "AEROLINEA DEMO NACIONAL"),
                 ("GAS RUTA NORTE", "AUTOBUSES RUTA")]
        for a, b in pares:
            assert comp.similitud(a, b) == comp.similitud(b, a)

    def test_siempre_queda_entre_cero_y_uno(self) -> None:
        comp = _comparador()
        textos = ["A B C", "DEMOCLOUD", "DEMO CLOUD", "TAQ", "TAQUERIA EL FOGONCITO", "HTL PLAZA", "X"]
        for a in textos:
            for b in textos:
                assert 0 <= comp.similitud(a, b) <= 1

    def test_comparador_es_inmutable(self) -> None:
        comp = _comparador()
        with pytest.raises(AttributeError):
            comp.stop_izq = frozenset({"X"})  # type: ignore[misc]


# ---------------------------------------------------------------- decimales
class TestDecimalCuatro:
    @pytest.mark.parametrize("valor, texto", [
        (Fraction(1, 8), "0.1250"),
        (Fraction(2, 3), "0.6667"),
        (Fraction(1, 20000), "0.0001"),   # 0.00005 redondea hacia arriba
        (Fraction(0), "0.0000"),
        (Fraction(1), "1.0000"),
    ])
    def test_redondeo_half_up_a_cuatro_decimales(self, valor: Fraction, texto: str) -> None:
        resultado = nombres.a_decimal4(valor)
        assert isinstance(resultado, Decimal)
        assert str(resultado) == texto

    def test_valor_negativo_es_un_error(self) -> None:
        with pytest.raises(ValueError, match="negativa"):
            nombres.a_decimal4(Fraction(-1, 2))
