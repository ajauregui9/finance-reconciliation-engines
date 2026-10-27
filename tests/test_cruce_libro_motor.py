"""Pruebas unitarias del motor cargo ↔ libro mayor con fixtures mínimos."""
from __future__ import annotations

import random
import sys
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Mapping, Optional, Sequence

import pytest

RAIZ_SKILL = Path(__file__).resolve().parents[1] / "skills" / "credit-card-reconciliation"
if str(RAIZ_SKILL) not in sys.path:
    sys.path.insert(0, str(RAIZ_SKILL))

from conciliacion import cruce_libro_motor as motor  # noqa: E402
from conciliacion.cruce_libro_modelo import (  # noqa: E402
    Cargo,
    ConfigCruceLibro,
    Cruce,
    LineaLibro,
    VentanaDias,
)

DIA = date(2026, 7, 10)
CUENTA_ALFA = "2105-001"
CUENTA_BETA = "2105-002"
CUBETA = "PRV-0999"
CERO = Decimal("0.00")


def _cargo(cid: str, monto: str, desc: str = "CAFE LUNA AZUL CDMX", *, dias: int = 0, emisor: str = "ALFA",
           tipo: Optional[str] = None, estado: str = "ok") -> Cargo:
    valor = Decimal(monto)
    tipo = tipo or ("cargo" if valor > 0 else "abono")
    fecha = None if estado != "ok" else DIA + timedelta(days=dias)
    return Cargo(cargo_id=cid, emisor=emisor, estado=estado, fecha=fecha, descripcion=desc, monto=valor,
                 tipo_movimiento=tipo)


def _linea(asiento: str, importe: str, nombre: str = "CAFETERIA LUNA AZUL", *, dias: int = 1,
           cuenta: str = CUENTA_ALFA, proveedor: str = "PRV-0001", lado: str = "haber", linea: int = 2) -> LineaLibro:
    valor = Decimal(importe)
    return LineaLibro(asiento_id=asiento, linea=linea, fecha=DIA + timedelta(days=dias), cuenta=cuenta,
                      proveedor_id=proveedor, proveedor_nombre=nombre,
                      debe=valor if lado == "debe" else CERO, haber=valor if lado == "haber" else CERO)


def _cruzar(cargos: Sequence[Cargo], lineas: Sequence[LineaLibro],
            config: Optional[ConfigCruceLibro] = None, **kwargs: frozenset) -> Mapping[str, Cruce]:
    evaluaciones = motor.evaluar_cargos(tuple(cargos), tuple(lineas), config or ConfigCruceLibro())
    return motor.asignar(evaluaciones, **kwargs)


# ------------------------------------------------------------- caso feliz
class TestCruceConProveedorPropio:
    def test_monto_exacto_y_nombre_parecido_cruzan(self) -> None:
        res = _cruzar([_cargo("A-1", "250.00")], [_linea("AS-1", "250.00")])["A-1"]
        assert res.asiento_id == "AS-1"
        assert res.motivo is None
        assert res.candidato is not None
        assert res.candidato.evidencia == "monto_y_nombre"
        assert res.riesgo_cubeta is False
        assert res.candidato.diferencia == Decimal("0.00")

    def test_diferencia_dentro_de_tolerancia_cruza_y_fuera_no(self) -> None:
        cargos = [_cargo("A-1", "250.00"), _cargo("A-2", "900.00")]
        lineas = [_linea("AS-1", "251.00"), _linea("AS-2", "901.01")]
        res = _cruzar(cargos, lineas)
        assert res["A-1"].asiento_id == "AS-1"
        assert res["A-1"].candidato is not None and res["A-1"].candidato.diferencia == Decimal("1.00")
        assert res["A-2"].asiento_id is None
        assert res["A-2"].motivo == "sin_candidato"

    def test_abono_cruza_con_el_debe_de_la_tarjeta(self) -> None:
        res = _cruzar([_cargo("A-1", "-80.00")], [_linea("AS-1", "80.00", lado="debe")])["A-1"]
        assert res.asiento_id == "AS-1"

    def test_lado_contrario_no_es_candidato(self) -> None:
        res = _cruzar([_cargo("A-1", "-80.00")], [_linea("AS-1", "80.00", lado="haber")])["A-1"]
        assert res.motivo == "sin_candidato"

    def test_reembolso_total_se_distingue_por_el_signo(self) -> None:
        cargos = [_cargo("A-1", "300.00"), _cargo("A-2", "-300.00", dias=3)]
        lineas = [_linea("AS-1", "300.00"), _linea("AS-2", "300.00", dias=4, lado="debe")]
        res = _cruzar(cargos, lineas)
        assert (res["A-1"].asiento_id, res["A-2"].asiento_id) == ("AS-1", "AS-2")


# ------------------------------------------------------------ sin candidato
class TestSinCandidato:
    def test_cuenta_de_otro_emisor_no_es_candidata(self) -> None:
        res = _cruzar([_cargo("A-1", "250.00")], [_linea("AS-1", "250.00", cuenta=CUENTA_BETA)])["A-1"]
        assert res.motivo == "sin_candidato"

    def test_nomina_o_banco_con_el_mismo_importe_no_es_candidato(self) -> None:
        lineas = [_linea("AS-9", "250.00", "EMPLEADO SINTETICO 01", cuenta="1102-001", proveedor="EMP-01")]
        assert _cruzar([_cargo("A-1", "250.00")], lineas)["A-1"].motivo == "sin_candidato"

    def test_ventana_de_busqueda_es_inclusiva_en_ambos_extremos(self) -> None:
        cargos = [_cargo(f"A-{n}", monto) for n, monto in enumerate(("100.00", "200.00", "300.00", "400.00"))]
        lineas = [_linea("AS-0", "100.00", dias=-30), _linea("AS-1", "200.00", dias=30),
                  _linea("AS-2", "300.00", dias=-31), _linea("AS-3", "400.00", dias=31)]
        res = _cruzar(cargos, lineas)
        assert [res[f"A-{n}"].asiento_id for n in range(4)] == ["AS-0", "AS-1", None, None]
        assert res["A-3"].motivo == "sin_candidato"

    def test_libro_vacio_deja_todo_sin_candidato(self) -> None:
        assert _cruzar([_cargo("A-1", "250.00")], [])["A-1"].motivo == "sin_candidato"

    def test_importe_cero_nunca_es_candidato(self) -> None:
        res = _cruzar([_cargo("A-1", "0.00", tipo="abono")], [_linea("AS-1", "0.00", lado="debe")])["A-1"]
        assert res.motivo == "sin_candidato"


# -------------------------------------------------------- no se buscan
class TestCargosQueNoSeBuscan:
    def test_pago_de_tarjeta_no_aplica(self) -> None:
        cargo = _cargo("A-1", "-5000.00", "PAGO RECIBIDO GRACIAS", tipo="pago")
        res = _cruzar([cargo], [_linea("AS-1", "5000.00", lado="debe")])["A-1"]
        assert (res.asiento_id, res.motivo) == (None, "no_aplica")

    def test_fila_ininterpretable_va_antes_que_cualquier_otra_regla(self) -> None:
        cargo = _cargo("A-1", "250.00", estado="ininterpretable", tipo="pago")
        res = _cruzar([cargo], [_linea("AS-1", "250.00")])["A-1"]
        assert (res.asiento_id, res.motivo) == (None, "fila_ininterpretable")


# ----------------------------------------------------------- nombre
class TestDescartePorNombre:
    def test_candidato_de_otro_comercio_se_descarta_por_nombre(self) -> None:
        lineas = [_linea("AS-1", "250.00", "PARQUIMETROS MUNICIPALES DEMO", proveedor="PRV-0104")]
        res = _cruzar([_cargo("A-1", "250.00", "TIENDITA LA ESQUINA GDL")], lineas)["A-1"]
        assert (res.asiento_id, res.motivo) == (None, "descartado_por_nombre")

    def test_mismo_monto_y_fecha_de_comercios_distintos_decide_el_nombre(self) -> None:
        cargos = [_cargo("A-1", "250.00", "FARMACIA SALUD EJEMPLO CDMX"),
                  _cargo("A-2", "250.00", "HOTEL MIRADOR DEL LAGO MICH")]
        lineas = [_linea("AS-1", "250.00", "HOTEL MIRADOR DEL LAGO", proveedor="PRV-0010"),
                  _linea("AS-2", "250.00", "FARMACIA SALUD EJEMPLO", proveedor="PRV-0023")]
        res = _cruzar(cargos, lineas)
        assert (res["A-1"].asiento_id, res["A-2"].asiento_id) == ("AS-2", "AS-1")

    def test_el_umbral_es_configurable(self) -> None:
        exigente = replace(ConfigCruceLibro(), umbral_similitud=Decimal("1.00"))
        res = _cruzar([_cargo("A-1", "250.00", "CAFE LUNA AZUL CDMX")], [_linea("AS-1", "250.00")], exigente)
        assert res["A-1"].motivo == "descartado_por_nombre"


# ----------------------------------------------------------- cubeta
class TestProveedorCubeta:
    def _cubeta(self, asiento: str, importe: str, dias: int) -> LineaLibro:
        return _linea(asiento, importe, "GASTOS VARIOS TARJETA", dias=dias, proveedor=CUBETA)

    def test_cubeta_con_monto_y_fecha_cruza_con_riesgo(self) -> None:
        res = _cruzar([_cargo("A-1", "250.00")], [self._cubeta("AS-1", "250.00", 2)])["A-1"]
        assert res.asiento_id == "AS-1"
        assert res.riesgo_cubeta is True
        assert res.candidato is not None and res.candidato.evidencia == "monto_y_fecha_cubeta"
        assert res.candidato.similitud is None

    def test_cubeta_lejana_no_basta(self) -> None:
        for dias in (-25, 6, 22):
            res = _cruzar([_cargo("A-1", "250.00")], [self._cubeta("AS-1", "250.00", dias)])["A-1"]
            assert (res.asiento_id, res.motivo) == (None, "cubeta_evidencia_insuficiente"), dias

    def test_ventana_de_cubeta_es_inclusiva(self) -> None:
        cargos = [_cargo("A-1", "100.00"), _cargo("A-2", "200.00")]
        res = _cruzar(cargos, [self._cubeta("AS-1", "100.00", 0), self._cubeta("AS-2", "200.00", 5)])
        assert (res["A-1"].asiento_id, res["A-2"].asiento_id) == ("AS-1", "AS-2")

    def test_proveedor_propio_gana_sobre_la_cubeta(self) -> None:
        lineas = [self._cubeta("AS-1", "250.00", 0), _linea("AS-2", "250.00", dias=3)]
        res = _cruzar([_cargo("A-1", "250.00")], lineas)["A-1"]
        assert (res.asiento_id, res.riesgo_cubeta) == ("AS-2", False)

    def test_nombre_descartado_tiene_precedencia_sobre_cubeta_lejana(self) -> None:
        lineas = [self._cubeta("AS-1", "250.00", 20), _linea("AS-2", "250.00", "JUGOS EL OASIS", proveedor="P")]
        res = _cruzar([_cargo("A-1", "250.00")], lineas)["A-1"]
        assert res.motivo == "descartado_por_nombre"


# ---------------------------------------------------- exclusividad y orden
class TestAsignacionExclusiva:
    def test_un_asiento_respalda_a_un_solo_cargo(self) -> None:
        cargos = [_cargo("A-1", "250.00"), _cargo("A-2", "250.00", dias=1)]
        res = _cruzar(cargos, [_linea("AS-1", "250.00", dias=1)])
        # A-2 está a 0 días del asiento y A-1 a 1: gana la fecha más cercana.
        assert res["A-2"].asiento_id == "AS-1"
        assert (res["A-1"].asiento_id, res["A-1"].motivo) == (None, "candidato_ocupado")

    def test_grupo_de_cargos_identicos_queda_uno_a_uno(self) -> None:
        cargos = [_cargo(f"A-{n}", "250.00") for n in (3, 1, 2)]
        lineas = [_linea(f"AS-{n}", "250.00") for n in (2, 3, 1)]
        res = _cruzar(cargos, lineas)
        assert {c: res[c].asiento_id for c in ("A-1", "A-2", "A-3")} == {
            "A-1": "AS-1", "A-2": "AS-2", "A-3": "AS-3"}

    def test_mismo_monto_en_fechas_distintas_gana_la_fecha_mas_cercana(self) -> None:
        cargos = [_cargo("A-2", "250.00", dias=4), _cargo("A-1", "250.00")]
        lineas = [_linea("AS-9", "250.00", dias=0), _linea("AS-5", "250.00", dias=4)]
        res = _cruzar(cargos, lineas)
        assert (res["A-1"].asiento_id, res["A-2"].asiento_id) == ("AS-9", "AS-5")

    def test_monto_exacto_gana_sobre_monto_con_tolerancia(self) -> None:
        lineas = [_linea("AS-1", "250.50", dias=0), _linea("AS-2", "250.00", dias=3)]
        assert _cruzar([_cargo("A-1", "250.00")], lineas)["A-1"].asiento_id == "AS-2"

    def test_resultado_no_depende_del_orden_de_los_insumos(self) -> None:
        cargos = [_cargo(f"A-{n}", "250.00", dias=n % 3) for n in range(8)]
        lineas = [_linea(f"AS-{n}", "250.00", dias=n % 4) for n in range(6)]
        base = {c: r.asiento_id for c, r in _cruzar(cargos, lineas).items()}
        azar = random.Random(7)
        for _ in range(5):
            otro = {c: r.asiento_id for c, r in
                    _cruzar(azar.sample(cargos, len(cargos)), azar.sample(lineas, len(lineas))).items()}
            assert otro == base

    def test_asientos_reservados_dejan_el_candidato_ocupado(self) -> None:
        res = _cruzar([_cargo("A-1", "250.00")], [_linea("AS-1", "250.00")], reservados=frozenset({"AS-1"}))
        assert (res["A-1"].asiento_id, res["A-1"].motivo) == (None, "candidato_ocupado")

    def test_cargos_excluidos_no_aparecen_ni_compiten(self) -> None:
        cargos = [_cargo("A-1", "250.00"), _cargo("A-2", "250.00", dias=2)]
        res = _cruzar(cargos, [_linea("AS-1", "250.00")], excluidos=frozenset({"A-1"}))
        assert set(res) == {"A-2"}
        assert res["A-2"].asiento_id == "AS-1"


# ----------------------------------------------------------- evaluación
class TestEvaluacion:
    def test_candidatos_quedan_ordenados_y_contados(self) -> None:
        lineas = [_linea("AS-1", "250.00", "JUGOS EL OASIS", proveedor="P"), _linea("AS-2", "250.40", dias=2),
                  _linea("AS-3", "250.00", "GASTOS VARIOS TARJETA", dias=12, proveedor=CUBETA),
                  _linea("AS-4", "250.00", dias=3)]
        (ev,) = motor.evaluar_cargos((_cargo("A-1", "250.00"),), tuple(lineas), ConfigCruceLibro())
        assert [c.linea.asiento_id for c in ev.candidatos] == ["AS-4", "AS-2", "AS-1", "AS-3"]
        assert [c.evaluacion for c in ev.candidatos] == [
            "elegible", "elegible", "nombre_insuficiente", "cubeta_fuera_de_fecha"]
        assert ev.conteos() == {"total": 4, "elegibles": 2, "descartados_por_nombre": 1, "cubeta_fuera_de_fecha": 1}

    def test_emisor_sin_cuenta_configurada_es_un_error_claro(self) -> None:
        with pytest.raises(ValueError, match="GAMMA"):
            motor.evaluar_cargos((_cargo("G-1", "10.00", emisor="GAMMA"),), (), ConfigCruceLibro())

    def test_ventana_invalida_se_rechaza(self) -> None:
        with pytest.raises(ValueError):
            VentanaDias(minimo=3, maximo=-3)
