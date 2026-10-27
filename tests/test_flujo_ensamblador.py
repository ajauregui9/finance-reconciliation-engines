"""Pruebas del ensamblador: esquema de filas contrato, cuadre por fuente e invariantes.

Los resultados por fuente se arman a mano, sin archivos, para aislar al ensamblador.
"""
from __future__ import annotations

import dataclasses
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

import pytest

RAIZ = Path(__file__).resolve().parents[1]
MODULO = RAIZ / "skills" / "cashflow-forecasting"
if str(MODULO) not in sys.path:
    sys.path.insert(0, str(MODULO))

from flujo.avisos import avisos  # noqa: E402
from flujo.contrato import CONCEPTO_DE_FUENTE, CONCEPTOS_FLUJO, FUENTES, FilaContrato, ResultadoFuente  # noqa: E402
from flujo.ensamblador import Flujo, ensamblar, verificar_invariantes  # noqa: E402
from flujo.errores import ErrorInvariante  # noqa: E402

CORTE = date(2026, 11, 2)
D = Decimal
CERO = D("0.00")


def _semana(n: int) -> date:
    return CORTE + timedelta(days=7 * (n - 1))


def _fila(fuente: str, semana: int, monto: str, referencia: str = "REF-1", /, **cambios: Any) -> FilaContrato:
    """Fila válida de `fuente`; `cambios` sobrescribe campos (incluso fuente o semana) para romperla."""
    base = FilaContrato(
        fuente=fuente, concepto=CONCEPTO_DE_FUENTE[fuente], semana=semana, fecha=_semana(semana),
        referencia=referencia, contraparte="CONTRAPARTE", monto=D(monto),
    )
    return dataclasses.replace(base, **cambios)


def _resultado(fuente: str, filas: Sequence[FilaContrato], fuera: Decimal = CERO, no_cobrable: Decimal = CERO,
               total: Optional[Decimal] = None) -> ResultadoFuente:
    if total is None:
        total = sum((f.monto for f in filas), CERO) + fuera + no_cobrable
    return ResultadoFuente(
        fuente=fuente, archivo=f"{fuente}.csv", sha256="0" * 64, registros=len(filas),
        total_insumo=total,
        filas=tuple(filas), fuera_horizonte=fuera, no_cobrable=no_cobrable,
    )


def _resultados(**reemplazos: ResultadoFuente) -> Tuple[ResultadoFuente, ...]:
    base: Dict[str, ResultadoFuente] = {
        "saldos_bancarios": _resultado("saldos_bancarios", [
            _fila("saldos_bancarios", 1, "1000.00", "CTA-1"), _fila("saldos_bancarios", 1, "-200.00", "CTA-2"),
        ]),
        "cxc_antiguedad": _resultado("cxc_antiguedad", [
            _fila("cxc_antiguedad", 1, "500.00", "FV-1"), _fila("cxc_antiguedad", 2, "300.00", "FV-1"),
            _fila("cxc_antiguedad", 2, "50.00", "FV-2"),
        ], fuera=D("70.00"), no_cobrable=D("80.00")),
        "cxp_programadas": _resultado("cxp_programadas", [
            _fila("cxp_programadas", 1, "-400.00", "PRV-1/FP-1", fecha=_semana(1) + timedelta(days=6)),
        ], fuera=D("-90.00")),
        "nomina": _resultado("nomina", [_fila("nomina", 2, "-600.00", "Q1")]),
        "impuestos": _resultado("impuestos", [_fila("impuestos", 13, "-25.50", "ISR/2026-10")]),
    }
    base.update(reemplazos)
    return tuple(base[f] for f in FUENTES)


def _flujo() -> Flujo:
    return ensamblar(_resultados(), CORTE, "MXN")


# --- tabla semanal ----------------------------------------------------------------------


def test_ensamblar_arma_13_semanas_encadenadas() -> None:
    flujo = _flujo()
    assert len(flujo.semanas) == 13
    assert flujo.semanas[0].saldo_inicial == D("800.00")
    s1, s2 = flujo.semanas[0], flujo.semanas[1]
    assert dict(s1.montos) == {
        "cobranza_clientes": D("500.00"), "pago_proveedores": D("-400.00"), "pago_nomina": CERO, "pago_impuestos": CERO,
    }
    assert (s1.entradas, s1.salidas) == (D("500.00"), D("-400.00"))
    assert (s1.flujo_neto, s1.saldo_final) == (D("100.00"), D("900.00"))
    assert (s2.saldo_inicial, s2.flujo_neto, s2.saldo_final) == (D("900.00"), D("-250.00"), D("650.00"))
    for previa, siguiente in zip(flujo.semanas, flujo.semanas[1:]):
        assert siguiente.saldo_inicial == previa.saldo_final
    assert flujo.semanas[-1].saldo_final == D("624.50")
    assert all(tuple(c for c, _ in s.montos) == CONCEPTOS_FLUJO for s in flujo.semanas)


def test_ensamblar_conserva_fuentes_y_filas_ordenadas() -> None:
    flujo = _flujo()
    assert tuple(r.fuente for r in flujo.fuentes) == FUENTES
    claves = [(f.semana, f.concepto, f.fuente, f.referencia) for f in flujo.filas]
    assert claves == sorted(claves)
    assert len(flujo.filas) == 8


def test_semanas_sin_filas_quedan_en_cero_y_arrastran_saldo() -> None:
    flujo = _flujo()
    semana_7 = flujo.semanas[6]
    assert all(m == CERO for _, m in semana_7.montos)
    assert semana_7.saldo_inicial == semana_7.saldo_final == flujo.semanas[5].saldo_final


# --- presencia de fuentes ---------------------------------------------------------------


def test_falta_una_fuente_es_error() -> None:
    incompletos = tuple(r for r in _resultados() if r.fuente != "nomina")
    with pytest.raises(ErrorInvariante, match="faltan fuentes.*nomina"):
        ensamblar(incompletos, CORTE, "MXN")


def test_fuente_repetida_es_error() -> None:
    resultados = _resultados()
    with pytest.raises(ErrorInvariante, match="repetida"):
        ensamblar(resultados + (resultados[-1],), CORTE, "MXN")


def test_fuente_desconocida_es_error() -> None:
    extra = dataclasses.replace(_resultados()[-1], fuente="ventas_futuras", filas=())
    with pytest.raises(ErrorInvariante, match="desconocida"):
        ensamblar(_resultados() + (extra,), CORTE, "MXN")


# --- esquema de filas contrato ----------------------------------------------------------


@pytest.mark.parametrize("cambios, mensaje", [
    ({"concepto": "pago_nomina"}, "concepto"),
    ({"semana": 0}, "semana"),
    ({"semana": 14}, "semana"),
    ({"semana": True}, "semana"),
    ({"fecha": _semana(1) + timedelta(days=7)}, "fuera de la semana"),
    ({"fecha": "2026-11-02"}, "fecha"),
    ({"monto": D("10.001")}, "dos decimales"),
    ({"monto": 10.5}, "Decimal"),
    ({"monto": D("NaN")}, "Decimal"),
    ({"monto": D("-10.00")}, "positivo"),
    ({"monto": CERO}, "positivo"),
    ({"referencia": " "}, "referencia"),
    ({"contraparte": ""}, "contraparte"),
    ({"fuente": "nomina"}, "no corresponde"),
])
def test_fila_de_cobranza_con_esquema_invalido_es_error(cambios: Dict[str, Any], mensaje: str) -> None:
    mala = _fila("cxc_antiguedad", 1, "10.00", "FV-9", **cambios)
    resultado = _resultado("cxc_antiguedad", [mala], total=D("10.00"))
    with pytest.raises(ErrorInvariante, match=mensaje):
        ensamblar(_resultados(cxc_antiguedad=resultado), CORTE, "MXN")


def test_pago_con_signo_positivo_es_error() -> None:
    resultado = _resultado("impuestos", [_fila("impuestos", 3, "25.00")])
    with pytest.raises(ErrorInvariante, match="negativo"):
        ensamblar(_resultados(impuestos=resultado), CORTE, "MXN")


def test_saldo_inicial_fuera_de_la_semana_1_es_error() -> None:
    resultado = _resultado("saldos_bancarios", [_fila("saldos_bancarios", 2, "100.00")])
    with pytest.raises(ErrorInvariante, match="semana 1"):
        ensamblar(_resultados(saldos_bancarios=resultado), CORTE, "MXN")


def test_saldo_inicial_con_fecha_distinta_al_corte_es_error() -> None:
    fila = _fila("saldos_bancarios", 1, "100.00", fecha=CORTE + timedelta(days=1))
    with pytest.raises(ErrorInvariante, match="fecha de corte"):
        ensamblar(_resultados(saldos_bancarios=_resultado("saldos_bancarios", [fila])), CORTE, "MXN")


def test_saldo_inicial_en_cero_o_negativo_es_valido() -> None:
    filas = [_fila("saldos_bancarios", 1, "-50.00"), _fila("saldos_bancarios", 1, "0.00", "CTA-0")]
    resultado = _resultado("saldos_bancarios", filas)
    flujo = ensamblar(_resultados(saldos_bancarios=resultado), CORTE, "MXN")
    assert flujo.semanas[0].saldo_inicial == D("-50.00")


# --- marcas: saldo acreedor de CxC y egreso vencido ------------------------------------


def test_saldo_acreedor_resta_de_la_cobranza_de_la_semana_1() -> None:
    acreedora = _fila("cxc_antiguedad", 1, "-120.00", "NC-1", marca="saldo_acreedor")
    base = {r.fuente: r for r in _resultados()}["cxc_antiguedad"]
    cxc = _resultado("cxc_antiguedad", list(base.filas) + [acreedora], fuera=D("70.00"), no_cobrable=D("80.00"))
    flujo = ensamblar(_resultados(cxc_antiguedad=cxc), CORTE, "MXN")
    assert dict(flujo.semanas[0].montos)["cobranza_clientes"] == D("380.00")
    assert flujo.semanas[-1].saldo_final == D("504.50")


def test_egreso_vencido_marcado_es_valido_en_la_semana_1() -> None:
    vencida = _fila("cxp_programadas", 1, "-30.00", "PRV-1/FP-0", marca="vencido")
    flujo = ensamblar(_resultados(cxp_programadas=_resultado("cxp_programadas", [vencida])), CORTE, "MXN")
    assert dict(flujo.semanas[0].montos)["pago_proveedores"] == D("-30.00")


@pytest.mark.parametrize("fuente, semana, monto, cambios, mensaje", [
    ("cxc_antiguedad", 1, "-10.00", {}, "positivo"),
    ("cxc_antiguedad", 1, "10.00", {"marca": "saldo_acreedor"}, "negativo"),
    ("cxc_antiguedad", 2, "-10.00", {"marca": "saldo_acreedor"}, "semana 1"),
    ("cxc_antiguedad", 1, "-10.00", {"marca": "saldo_acreedor", "fecha": CORTE + timedelta(days=3)}, "corte"),
    ("cxc_antiguedad", 1, "10.00", {"marca": "vencido"}, "no aplica"),
    ("nomina", 1, "-10.00", {"marca": "saldo_acreedor"}, "no aplica"),
    ("nomina", 3, "-10.00", {"marca": "vencido"}, "semana 1"),
    ("saldos_bancarios", 1, "10.00", {"marca": "vencido"}, "no aplica"),
    ("impuestos", 1, "-10.00", {"marca": "atrasado"}, "marca desconocida"),
    ("impuestos", 1, "-10.00", {"marca": ""}, "marca desconocida"),
])
def test_marca_invalida_es_error(fuente: str, semana: int, monto: str, cambios: Dict[str, Any],
                                 mensaje: str) -> None:
    mala = _fila(fuente, semana, monto, "REF-9", **cambios)
    with pytest.raises(ErrorInvariante, match=mensaje):
        ensamblar(_resultados(**{fuente: _resultado(fuente, [mala])}), CORTE, "MXN")


@pytest.mark.parametrize("en_cero", [-1, 3, True, "1"])
def test_registros_en_cero_fuera_de_rango_es_error(en_cero: Any) -> None:
    original = {r.fuente: r for r in _resultados()}["cxc_antiguedad"]
    malo = dataclasses.replace(original, registros=2, registros_en_cero=en_cero)
    with pytest.raises(ErrorInvariante, match="registros_en_cero"):
        ensamblar(_resultados(cxc_antiguedad=malo), CORTE, "MXN")


def test_registros_en_cero_en_una_fuente_que_no_los_admite_es_error() -> None:
    original = {r.fuente: r for r in _resultados()}["nomina"]
    malo = dataclasses.replace(original, registros=2, registros_en_cero=1)
    with pytest.raises(ErrorInvariante, match="nomina.*no admite registros_en_cero"):
        ensamblar(_resultados(nomina=malo), CORTE, "MXN")


def test_registros_en_cero_dentro_de_rango_es_valido() -> None:
    original = {r.fuente: r for r in _resultados()}["cxc_antiguedad"]
    flujo = ensamblar(_resultados(cxc_antiguedad=dataclasses.replace(original, registros_en_cero=2)), CORTE, "MXN")
    assert flujo.registros_en_cero == 2


def test_avisos_cuentan_vencidos_acreedores_y_registros_en_cero() -> None:
    base = {r.fuente: r for r in _resultados()}
    cxc = dataclasses.replace(
        _resultado("cxc_antiguedad", list(base["cxc_antiguedad"].filas) + [
            _fila("cxc_antiguedad", 1, "-120.00", "NC-1", marca="saldo_acreedor"),
        ], fuera=D("70.00"), no_cobrable=D("80.00")),
        registros=6, registros_en_cero=2,
    )
    cxp = _resultado("cxp_programadas", [
        _fila("cxp_programadas", 1, "-30.00", "PRV-1/FP-0", marca="vencido"),
        _fila("cxp_programadas", 4, "-5.00", "PRV-1/FP-1"),
    ])
    nomina = _resultado("nomina", [_fila("nomina", 1, "-15.25", "Q0", marca="vencido")])
    flujo = ensamblar(_resultados(cxc_antiguedad=cxc, cxp_programadas=cxp, nomina=nomina), CORTE, "MXN")
    resumen = [(a.clave, a.registros, a.monto) for a in avisos(flujo)]
    assert resumen == [
        ("cxc_saldo_acreedor", 1, D("-120.00")),
        ("cxc_saldo_cero", 2, CERO),
        ("egresos_vencidos", 2, D("-45.25")),
    ]
    assert all(a.descripcion for a in avisos(flujo))


def test_avisos_en_cero_cuando_no_hay_casos_especiales() -> None:
    assert [(a.clave, a.registros, a.monto) for a in avisos(_flujo())] == [
        ("cxc_saldo_acreedor", 0, CERO), ("cxc_saldo_cero", 0, CERO), ("egresos_vencidos", 0, CERO),
    ]


def test_filas_contrato_repetidas_son_error() -> None:
    fila = _fila("nomina", 2, "-600.00", "Q1")
    with pytest.raises(ErrorInvariante, match="fila contrato repetida"):
        ensamblar(_resultados(nomina=_resultado("nomina", [fila, fila])), CORTE, "MXN")


def test_resultado_que_no_es_resultado_fuente_es_error() -> None:
    with pytest.raises(ErrorInvariante, match="ResultadoFuente"):
        ensamblar(_resultados()[:-1] + ("impuestos",), CORTE, "MXN")  # type: ignore[operator]


# --- cuadre por fuente al centavo -------------------------------------------------------


@pytest.mark.parametrize("fuente", FUENTES)
def test_descuadre_de_un_centavo_en_cualquier_fuente_es_error(fuente: str) -> None:
    original = {r.fuente: r for r in _resultados()}[fuente]
    descuadrado = dataclasses.replace(original, total_insumo=original.total_insumo + D("0.01"))
    with pytest.raises(ErrorInvariante, match=rf"{fuente}.*no cuadra.*0\.01"):
        ensamblar(_resultados(**{fuente: descuadrado}), CORTE, "MXN")


def test_partidas_de_conciliacion_deben_ser_decimal_con_centavos() -> None:
    original = {r.fuente: r for r in _resultados()}["cxc_antiguedad"]
    malo = dataclasses.replace(original, fuera_horizonte=D("70.001"), total_insumo=original.total_insumo + D("0.001"))
    with pytest.raises(ErrorInvariante, match="dos decimales"):
        ensamblar(_resultados(cxc_antiguedad=malo), CORTE, "MXN")


# --- invariantes de la tabla ------------------------------------------------------------


def _reemplazar_semana(flujo: Flujo, indice: int, **cambios: Any) -> Flujo:
    semanas = list(flujo.semanas)
    semanas[indice] = dataclasses.replace(semanas[indice], **cambios)
    return dataclasses.replace(flujo, semanas=tuple(semanas))


def test_invariantes_pasan_en_un_flujo_bien_armado() -> None:
    verificar_invariantes(_flujo())


def test_invariante_detecta_menos_de_13_semanas() -> None:
    flujo = _flujo()
    with pytest.raises(ErrorInvariante, match="13 semanas"):
        verificar_invariantes(dataclasses.replace(flujo, semanas=flujo.semanas[:12]))


def test_invariante_detecta_numeracion_o_fechas_rotas() -> None:
    with pytest.raises(ErrorInvariante, match="numeración o fechas"):
        verificar_invariantes(_reemplazar_semana(_flujo(), 4, numero=7))
    with pytest.raises(ErrorInvariante, match="numeración o fechas"):
        verificar_invariantes(_reemplazar_semana(_flujo(), 4, inicio=_semana(5) + timedelta(days=1)))


def test_invariante_detecta_saldo_inicial_distinto_a_los_saldos_bancarios() -> None:
    flujo = _flujo()
    s1 = flujo.semanas[0]
    roto = _reemplazar_semana(flujo, 0, saldo_inicial=s1.saldo_inicial + 1, saldo_final=s1.saldo_final + 1)
    with pytest.raises(ErrorInvariante, match="saldos bancarios"):
        verificar_invariantes(roto)


def test_invariante_detecta_saldo_final_mal_calculado() -> None:
    flujo = _flujo()
    roto = _reemplazar_semana(flujo, 12, saldo_final=flujo.semanas[12].saldo_final + D("0.01"))
    with pytest.raises(ErrorInvariante, match="semana 13.*saldo final"):
        verificar_invariantes(roto)


def test_invariante_detecta_cadena_de_saldos_rota() -> None:
    flujo = _flujo()
    s5 = flujo.semanas[4]
    roto = _reemplazar_semana(flujo, 4, saldo_inicial=s5.saldo_inicial + 5, saldo_final=s5.saldo_final + 5)
    with pytest.raises(ErrorInvariante, match="semana 5.*semana 4"):
        verificar_invariantes(roto)


def test_invariante_detecta_concepto_que_no_suma_sus_filas() -> None:
    flujo = _flujo()
    s3 = flujo.semanas[2]
    montos = tuple((c, m + D("1.00") if c == "pago_nomina" else m) for c, m in s3.montos)
    roto = _reemplazar_semana(flujo, 2, montos=montos, saldo_final=s3.saldo_final + D("1.00"))
    roto = dataclasses.replace(roto, semanas=roto.semanas[:3] + tuple(
        dataclasses.replace(s, saldo_inicial=s.saldo_inicial + D("1.00"), saldo_final=s.saldo_final + D("1.00"))
        for s in roto.semanas[3:]
    ))
    with pytest.raises(ErrorInvariante, match="pago_nomina"):
        verificar_invariantes(roto)


def test_invariante_detecta_conceptos_fuera_de_orden() -> None:
    flujo = _flujo()
    roto = _reemplazar_semana(flujo, 0, montos=tuple(reversed(flujo.semanas[0].montos)))
    with pytest.raises(ErrorInvariante, match="conceptos"):
        verificar_invariantes(roto)
