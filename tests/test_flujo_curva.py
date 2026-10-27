"""Pruebas del calendario de 13 semanas y de la curva de cobranza."""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
MODULO = RAIZ / "skills" / "cashflow-forecasting"
if str(MODULO) not in sys.path:
    sys.path.insert(0, str(MODULO))

from flujo.calendario import SEMANAS_HORIZONTE, indice_semana, semanas_del_horizonte  # noqa: E402
from flujo.config import validar_curva  # noqa: E402
from flujo.curva import planear_cobro, repartir, tramo_para  # noqa: E402
from flujo.errores import ErrorConfig  # noqa: E402

CORTE = date(2026, 11, 2)
D = Decimal


def _curva_cruda() -> List[Dict[str, Any]]:
    return [
        {"tramo": "por_vencer", "dias_desde": None, "dias_hasta": 0, "pesos": ["0.60", "0.25", "0.10"]},
        {"tramo": "vencido_1_30", "dias_desde": 1, "dias_hasta": 30, "pesos": ["0.50", "0.30", "0.10"]},
        {"tramo": "vencido_31_60", "dias_desde": 31, "dias_hasta": 60, "pesos": ["0.30", "0.30", "0.20"]},
        {"tramo": "vencido_61_90", "dias_desde": 61, "dias_hasta": 90, "pesos": ["0.20", "0.20", "0.20"]},
        {"tramo": "vencido_mas_90", "dias_desde": 91, "dias_hasta": None, "pesos": ["0.10", "0.10"]},
    ]


# --- calendario -------------------------------------------------------------------------


def test_horizonte_tiene_exactamente_13_semanas_contiguas() -> None:
    semanas = semanas_del_horizonte(CORTE)
    assert SEMANAS_HORIZONTE == 13
    assert len(semanas) == 13
    assert [s.numero for s in semanas] == list(range(1, 14))
    assert semanas[0].inicio == CORTE
    assert semanas[-1].fin == CORTE + timedelta(days=90)
    for previa, siguiente in zip(semanas, semanas[1:]):
        assert siguiente.inicio == previa.fin + timedelta(days=1)
        assert (previa.fin - previa.inicio).days == 6


@pytest.mark.parametrize("dias, esperado", [(0, 1), (6, 1), (7, 2), (13, 2), (84, 13), (90, 13), (91, 14)])
def test_indice_semana_en_bordes(dias: int, esperado: int) -> None:
    assert indice_semana(CORTE + timedelta(days=dias), CORTE) == esperado


def test_indice_semana_rechaza_fecha_anterior_al_corte() -> None:
    with pytest.raises(ValueError, match="anterior al corte"):
        indice_semana(CORTE - timedelta(days=1), CORTE)


# --- selección de tramo -----------------------------------------------------------------


@pytest.mark.parametrize("antiguedad, tramo", [
    (-500, "por_vencer"), (0, "por_vencer"), (1, "vencido_1_30"), (30, "vencido_1_30"),
    (31, "vencido_31_60"), (60, "vencido_31_60"), (61, "vencido_61_90"), (90, "vencido_61_90"),
    (91, "vencido_mas_90"), (10_000, "vencido_mas_90"),
])
def test_tramo_segun_antiguedad_en_bordes(antiguedad: int, tramo: str) -> None:
    curva = validar_curva(_curva_cruda())
    assert tramo_para(curva, antiguedad).tramo == tramo


# --- reparto al centavo -----------------------------------------------------------------


def test_repartir_tercios_suma_exacta() -> None:
    piezas = repartir(D("100.00"), (D("0.3333"), D("0.3333"), D("0.3334")))
    assert piezas == (D("33.33"), D("33.33"), D("33.34"))
    assert sum(piezas) == D("100.00")


def test_repartir_un_centavo_no_crea_centavos() -> None:
    piezas = repartir(D("0.01"), (D("0.5"), D("0.5")))
    assert piezas == (D("0.01"), D("0.00"))


def test_repartir_con_pesos_menores_a_uno_deja_residuo() -> None:
    piezas = repartir(D("1000.00"), (D("0.50"), D("0.30")))
    assert piezas == (D("500.00"), D("300.00"))


def test_repartir_siempre_cuadra_con_el_residuo() -> None:
    generador = random.Random(11)
    pesos = (D("0.137"), D("0.2501"), D("0.0005"), D("0.333"))
    for _ in range(2000):
        saldo = D(generador.randint(1, 50_000_000)) / 100
        piezas = repartir(saldo, pesos)
        cobrable = (saldo * sum(pesos)).quantize(D("0.01"), rounding=ROUND_HALF_UP)
        assert all(p >= 0 for p in piezas)
        assert sum(piezas) == cobrable
        assert all(p == p.quantize(D("0.01")) for p in piezas)


# --- plan de cobro por factura ----------------------------------------------------------


def test_factura_vencida_se_ancla_en_la_semana_1() -> None:
    curva = validar_curva(_curva_cruda())
    plan = planear_cobro(D("1000.00"), CORTE - timedelta(days=45), CORTE, curva)
    assert plan.tramo == "vencido_31_60"
    assert plan.piezas == ((1, D("300.00")), (2, D("300.00")), (3, D("200.00")))
    assert plan.fuera_horizonte == D("0.00")
    assert plan.no_cobrable == D("200.00")


def test_factura_por_vencer_se_ancla_en_su_semana_de_vencimiento() -> None:
    curva = validar_curva(_curva_cruda())
    plan = planear_cobro(D("1000.00"), CORTE + timedelta(days=30), CORTE, curva)
    assert plan.tramo == "por_vencer"
    assert plan.piezas == ((5, D("600.00")), (6, D("250.00")), (7, D("100.00")))
    assert plan.no_cobrable == D("50.00")


def test_factura_que_vence_el_dia_de_corte_cobra_en_semana_1() -> None:
    curva = validar_curva(_curva_cruda())
    plan = planear_cobro(D("200.00"), CORTE, CORTE, curva)
    assert plan.piezas[0] == (1, D("120.00"))


def test_piezas_despues_de_la_semana_13_van_a_fuera_de_horizonte() -> None:
    curva = validar_curva(_curva_cruda())
    plan = planear_cobro(D("1000.00"), CORTE + timedelta(days=88), CORTE, curva)
    assert plan.piezas == ((13, D("600.00")),)
    assert plan.fuera_horizonte == D("350.00")
    assert plan.no_cobrable == D("50.00")


def test_factura_que_vence_despues_del_horizonte_queda_toda_fuera() -> None:
    curva = validar_curva(_curva_cruda())
    plan = planear_cobro(D("1000.00"), CORTE + timedelta(days=91), CORTE, curva)
    assert plan.piezas == ()
    assert plan.fuera_horizonte == D("950.00")
    assert plan.no_cobrable == D("50.00")


def test_plan_omite_piezas_en_cero_pero_cuadra() -> None:
    curva = validar_curva([
        {"tramo": "todo", "dias_desde": None, "dias_hasta": None, "pesos": ["0.5", "0", "0.5"]},
    ])
    plan = planear_cobro(D("10.00"), CORTE - timedelta(days=3), CORTE, curva)
    assert plan.piezas == ((1, D("5.00")), (3, D("5.00")))
    assert sum(m for _, m in plan.piezas) + plan.fuera_horizonte + plan.no_cobrable == D("10.00")


# --- validación de la curva -------------------------------------------------------------


def _con(indice: int, **cambios: Any) -> List[Dict[str, Any]]:
    curva = _curva_cruda()
    curva[indice] = {**curva[indice], **cambios}
    return curva


@pytest.mark.parametrize("curva, mensaje", [
    ([], "al menos un tramo"),
    ("no es lista", "lista"),
    (_con(1, dias_desde=2), "hueco o traslape"),
    (_con(2, dias_desde=30), "hueco o traslape"),
    (_con(0, dias_desde=-10), "primer tramo"),
    (_con(4, dias_hasta=400), "último tramo"),
    (_con(1, pesos=["-0.10", "0.20"]), "entre 0 y 1"),
    (_con(1, pesos=["1.50"]), "entre 0 y 1"),
    (_con(1, pesos=["0.60", "0.50"]), "suman más de 1"),
    (_con(1, pesos=[]), "al menos un peso"),
    (_con(1, pesos=[0.5]), "float"),
    (_con(1, pesos=["medio"]), "decimal"),
    (_con(1, pesos=[True]), "decimal"),
    (_con(2, tramo="vencido_1_30"), "repetido"),
    (_con(1, tramo=""), "tramo"),
    (_con(1, extra=1), "desconocidas"),
    ([{"tramo": "x", "dias_desde": None, "pesos": ["1"]}], "faltan"),
    (_con(1, dias_desde=True), "entero"),
    (_con(1, dias_hasta="30"), "entero"),
    (_con(1, dias_hasta=0), "dias_desde mayor"),
    (["no es objeto"], "objeto"),
])
def test_curva_invalida_es_error_de_config(curva: Any, mensaje: str) -> None:
    with pytest.raises(ErrorConfig, match=mensaje):
        validar_curva(curva)


def test_curva_acepta_decimal_y_entero_como_peso() -> None:
    curva = validar_curva([
        {"tramo": "unico", "dias_desde": None, "dias_hasta": None, "pesos": [D("0.25"), 0, "0.75"]},
    ])
    assert curva.tramos[0].pesos == (D("0.25"), D("0"), D("0.75"))
