"""Contrato de la frontera compartida de importes (`frontera.importes`)."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import pytest

from frontera import ErrorFrontera, FormaImporte, leer_entero, leer_importe

D = Decimal
TEXTO = FormaImporte()
CON_MILES = FormaImporte(miles=True)
CON_NUMEROS = FormaImporte(numeros=True)
EXACTA = FormaImporte(decimales=2, exactos=True)
SIN_TOPE = FormaImporte(decimales=None)


# ------------------------------------------------------------------ textos válidos
@pytest.mark.parametrize("texto, esperado", [
    ("100", "100.00"),
    ("100.5", "100.50"),
    ("-1234.56", "-1234.56"),
    ("0.00", "0.00"),
    ("  12.30\t", "12.30"),
])
def test_texto_valido_se_cuantiza_sin_redondear(texto: str, esperado: str) -> None:
    resultado = leer_importe(texto, TEXTO)
    assert resultado == D(esperado)
    assert str(resultado) == esperado


@pytest.mark.parametrize("texto, esperado", [("1,234.56", "1234.56"), ("12,345,678.90", "12345678.90"),
                                              ("999.99", "999.99"), ("-1,000.00", "-1000.00")])
def test_miles_bien_colocados(texto: str, esperado: str) -> None:
    assert leer_importe(texto, CON_MILES) == D(esperado)


def test_sin_tope_conserva_todos_los_decimales() -> None:
    assert str(leer_importe("0.123456789", SIN_TOPE)) == "0.123456789"


def test_exactos_exige_dos_decimales() -> None:
    assert leer_importe("12.34", EXACTA) == D("12.34")
    for texto in ("12.3", "12"):
        with pytest.raises(ErrorFrontera, match="exactamente 2 decimales"):
            leer_importe(texto, EXACTA)


# --------------------------------------------------------- casos que hoy fallan
@pytest.mark.parametrize("texto", ["١٠٠.٥٠", "１００.５０", "100.5٠", "٢"])
def test_digitos_no_ascii(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="no ASCII"):
        leer_importe(texto, TEXTO)


@pytest.mark.parametrize("texto", ["100.005", "-0.001", "1.000"])
def test_mas_decimales_de_los_permitidos_no_se_redondea(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="a lo más 2 decimales"):
        leer_importe(texto, TEXTO)


@pytest.mark.parametrize("texto", ["1,00.00", "1,2345.00", ",100.00", "1,,000.00", "1,000,0.00", "1000,00"])
def test_coma_de_miles_mal_puesta(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="comas de miles mal colocadas"):
        leer_importe(texto, CON_MILES)


def test_sin_miles_la_coma_se_rechaza() -> None:
    with pytest.raises(ErrorFrontera, match="no admite separador de miles"):
        leer_importe("1,000.00", TEXTO)


@pytest.mark.parametrize("texto", ["1 000.00", "- 5.00", "100 .00"])
def test_espacios_internos(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="espacios"):
        leer_importe(texto, TEXTO)


def test_espacios_al_borde_sin_recorte() -> None:
    with pytest.raises(ErrorFrontera, match="espacios"):
        leer_importe(" 1.00", FormaImporte(recortar=False))


def test_espacio_unicode_al_borde_no_se_recorta() -> None:
    with pytest.raises(ErrorFrontera):
        leer_importe(" 1.00", TEXTO)


@pytest.mark.parametrize("texto", ["", "   ", "abc", "1e3", "NaN", "Infinity", "1_000", ".5", "5.", "--5", "0x10"])
def test_forma_invalida(texto: str) -> None:
    with pytest.raises(ErrorFrontera):
        leer_importe(texto, TEXTO)


def test_signos_segun_la_forma() -> None:
    with pytest.raises(ErrorFrontera, match="signo"):
        leer_importe("-1.00", FormaImporte(negativo=False))
    with pytest.raises(ErrorFrontera, match="signo"):
        leer_importe("+1.00", TEXTO)
    assert leer_importe("+1.00", FormaImporte(positivo_explicito=True)) == D("1.00")


def test_fuera_de_rango_es_error_claro() -> None:
    with pytest.raises(ErrorFrontera, match="rango"):
        leer_importe("9" * 40, TEXTO)


# ------------------------------------------------------------------- números JSON
def test_texto_solo_rechaza_numeros() -> None:
    for valor in (100, 100.5, D("1.00")):
        with pytest.raises(ErrorFrontera, match="se espera texto"):
            leer_importe(valor, TEXTO)


@pytest.mark.parametrize("valor", [True, False, None, [1], {"a": 1}])
def test_tipos_que_no_son_importe(valor: object) -> None:
    with pytest.raises(ErrorFrontera):
        leer_importe(valor, CON_NUMEROS)


@pytest.mark.parametrize("valor, esperado", [
    (7, "7.00"), (-3, "-3.00"), (100.5, "100.50"), (0.1, "0.10"), (1e16, "10000000000000000.00"),
    (D("2.5"), "2.50"), (D("2.500"), "2.50"),
])
def test_numeros_admitidos_por_conversion_explicita(valor: object, esperado: str) -> None:
    assert str(leer_importe(valor, CON_NUMEROS)) == esperado


def test_float_ambiguo_se_rechaza() -> None:
    with pytest.raises(ErrorFrontera, match="decimales significativos"):
        leer_importe(0.1 + 0.2, CON_NUMEROS)


def test_float_con_mas_de_15_digitos_es_ambiguo() -> None:
    with pytest.raises(ErrorFrontera, match="15 dígitos"):
        leer_importe(1234567890123456.0, CON_NUMEROS)


def test_float_con_tres_decimales_se_rechaza() -> None:
    with pytest.raises(ErrorFrontera, match="a lo más 2 decimales"):
        leer_importe(100.005, CON_NUMEROS)


@pytest.mark.parametrize("valor", [float("nan"), float("inf"), D("NaN"), D("-Infinity")])
def test_numeros_no_finitos(valor: object) -> None:
    with pytest.raises(ErrorFrontera, match="finito"):
        leer_importe(valor, CON_NUMEROS)


def test_decimal_con_mas_decimales_significativos() -> None:
    with pytest.raises(ErrorFrontera, match="a lo más 2 decimales"):
        leer_importe(D("1.005"), CON_NUMEROS)
    largo = D("1." + "0" * 29 + "1")
    with pytest.raises(ErrorFrontera, match="a lo más 2 decimales"):
        leer_importe(largo, CON_NUMEROS)


def test_numero_negativo_segun_la_forma() -> None:
    with pytest.raises(ErrorFrontera, match="negativo"):
        leer_importe(-1, FormaImporte(numeros=True, negativo=False))


def test_float_sin_tope_conserva_el_repr() -> None:
    assert leer_importe(1e-06, FormaImporte(decimales=None, numeros=True)) == D("0.000001")


def test_float_con_tope_de_seis_decimales() -> None:
    forma = FormaImporte(decimales=6, numeros=True)
    assert str(leer_importe(0.083333, forma)) == "0.083333"
    with pytest.raises(ErrorFrontera):
        leer_importe(1 / 3, forma)


# ------------------------------------------------------------------- forma inválida
@pytest.mark.parametrize("argumentos", [{"decimales": -1}, {"decimales": None, "exactos": True}])
def test_forma_mal_construida(argumentos: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValueError):
        FormaImporte(**argumentos)


def test_error_es_value_error() -> None:
    assert issubclass(ErrorFrontera, ValueError)


# -------------------------------------------------------------------------- enteros
@pytest.mark.parametrize("texto, negativo, esperado", [("12", False, 12), (" 7 ", False, 7), ("-3", True, -3),
                                                       ("0", False, 0)])
def test_entero_valido(texto: str, negativo: bool, esperado: int) -> None:
    assert leer_entero(texto, negativo=negativo) == esperado


@pytest.mark.parametrize("valor", ["١٢", "+5", "-5", "1_000", "1.0", "1,000", "", "1 2", 12, None, True])
def test_entero_invalido(valor: Optional[object]) -> None:
    with pytest.raises(ErrorFrontera):
        leer_entero(valor)


def test_forma_sin_decimales_acepta_enteros_y_lo_dice_en_el_error() -> None:
    forma = FormaImporte(decimales=0)
    assert str(leer_importe("12", forma)) == "12"
    with pytest.raises(ErrorFrontera, match=r"como -1234$"):
        leer_importe("12x", forma)
    with pytest.raises(ErrorFrontera, match="a lo más 0 decimales"):
        leer_importe("12.5", forma)
