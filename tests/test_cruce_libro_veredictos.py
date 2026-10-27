"""Pruebas del veredicto humano y sus conflictos con la propuesta del motor."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional, Sequence

import pytest

RAIZ_SKILL = Path(__file__).resolve().parents[1] / "skills" / "credit-card-reconciliation"
if str(RAIZ_SKILL) not in sys.path:
    sys.path.insert(0, str(RAIZ_SKILL))

from conciliacion import cruce_libro_veredictos as ver  # noqa: E402
from conciliacion.cruce_libro_modelo import (  # noqa: E402
    Cargo,
    ConfigCruceLibro,
    Cruce,
    LineaLibro,
    Veredicto,
)

DIA = date(2026, 7, 10)
CERO = Decimal("0.00")


def _cargo(cid: str, monto: str, desc: str = "CAFE LUNA AZUL CDMX", dias: int = 0) -> Cargo:
    return Cargo(cid, "ALFA", "ok", DIA + timedelta(days=dias), desc, Decimal(monto), "cargo")


def _linea(asiento: str, importe: str, nombre: str = "CAFETERIA LUNA AZUL", dias: int = 1,
           proveedor: str = "PRV-0001") -> LineaLibro:
    return LineaLibro(asiento, 2, DIA + timedelta(days=dias), "2105-001", proveedor, nombre, CERO, Decimal(importe))


def _v(cid: str, asiento: Optional[str] = None, nota: str = "") -> Veredicto:
    return Veredicto(cid, "registrado" if asiento else "no_registrado", asiento, nota)


def _conciliar(cargos: Sequence[Cargo], lineas: Sequence[LineaLibro],
               veredictos: Sequence[Veredicto] = ()) -> ver.Conciliacion:
    return ver.conciliar(tuple(cargos), tuple(lineas), tuple(veredictos), ConfigCruceLibro())


# ------------------------------------------------------- tabla de conflictos
class TestTipoDeConflicto:
    def _propuesta(self, asiento: Optional[str]) -> Cruce:
        conc = _conciliar([_cargo("A-1", "250.00")], [_linea(asiento, "250.00")] if asiento else [])
        return conc.propuesta["A-1"]

    @pytest.mark.parametrize("veredicto, propuesta, esperado", [
        (("AS-1",), "AS-1", None),
        (("AS-2",), "AS-1", "asiento_distinto"),
        (("AS-2",), None, "motor_sin_cruce"),
        ((None,), "AS-1", "motor_con_cruce"),
        ((None,), None, None),
    ])
    def test_cada_combinacion_de_la_spec(self, veredicto: tuple, propuesta: Optional[str],
                                         esperado: Optional[str]) -> None:
        assert ver.tipo_conflicto(_v("A-1", veredicto[0]), self._propuesta(propuesta)) == esperado


# ------------------------------------------------------- resultado final
class TestResultadoFinal:
    def test_sin_veredictos_el_final_es_la_propuesta(self) -> None:
        conc = _conciliar([_cargo("A-1", "250.00"), _cargo("A-2", "99.00")], [_linea("AS-1", "250.00")])
        assert conc.conflictos == {}
        for cid in ("A-1", "A-2"):
            final, propuesta = conc.final[cid], conc.propuesta[cid]
            assert (final.asiento_id, final.motivo, final.origen) == (propuesta.asiento_id, propuesta.motivo, "motor")
            assert final.reasignado is False

    def test_veredicto_registrado_nunca_se_sobrescribe(self) -> None:
        lineas = [_linea("AS-1", "250.00"), _linea("AS-7", "123.45", "OTRO PROVEEDOR", dias=20, proveedor="P")]
        conc = _conciliar([_cargo("A-1", "250.00")], lineas, [_v("A-1", "AS-7", "capturado a mano")])
        assert conc.propuesta["A-1"].asiento_id == "AS-1"
        assert conc.conflictos == {"A-1": "asiento_distinto"}
        final = conc.final["A-1"]
        assert (final.asiento_id, final.origen, final.motivo) == ("AS-7", "veredicto_humano", None)
        assert conc.veredictos["A-1"].nota == "capturado a mano"

    def test_veredicto_no_registrado_queda_sin_cruce_aunque_el_motor_lo_vea(self) -> None:
        conc = _conciliar([_cargo("A-1", "250.00")], [_linea("AS-1", "250.00")], [_v("A-1")])
        assert conc.conflictos == {"A-1": "motor_con_cruce"}
        final = conc.final["A-1"]
        assert (final.asiento_id, final.origen, final.motivo) == (None, "veredicto_humano", "veredicto_no_registrado")

    def test_confirmar_un_cruce_contra_la_cubeta_no_quita_el_riesgo(self) -> None:
        cubeta = _linea("AS-1", "250.00", "GASTOS VARIOS TARJETA", proveedor="PRV-0999")
        conc = _conciliar([_cargo("A-1", "250.00")], [cubeta], [_v("A-1", "AS-1")])
        assert conc.conflictos == {}
        assert conc.final["A-1"].riesgo_cubeta is True
        assert conc.propuesta["A-1"].riesgo_cubeta is True

    def test_veredicto_que_toma_el_asiento_de_otro_cargo_lo_reasigna_y_se_marca(self) -> None:
        # Dos cargos iguales a 4 días; la persona cruza A-1 con el asiento que el motor dio a A-2.
        cargos = [_cargo("A-1", "250.00"), _cargo("A-2", "250.00", dias=4)]
        lineas = [_linea("AS-1", "250.00", dias=0), _linea("AS-2", "250.00", dias=4)]
        conc = _conciliar(cargos, lineas, [_v("A-1", "AS-2")])
        assert conc.propuesta["A-2"].asiento_id == "AS-2"
        assert conc.conflictos == {"A-1": "asiento_distinto"}
        final = conc.final["A-2"]
        assert (final.asiento_id, final.origen, final.reasignado) == ("AS-1", "motor", True)

    def test_si_no_queda_otro_candidato_el_desplazado_queda_ocupado(self) -> None:
        cargos = [_cargo("A-1", "250.00"), _cargo("A-2", "250.00", dias=1)]
        conc = _conciliar(cargos, [_linea("AS-1", "250.00")], [_v("A-1", "AS-1")])
        assert conc.propuesta["A-2"].asiento_id == "AS-1"
        assert conc.conflictos == {"A-1": "motor_sin_cruce"}
        final = conc.final["A-2"]
        assert (final.asiento_id, final.motivo, final.reasignado) == (None, "candidato_ocupado", True)

    def test_no_registrado_libera_el_asiento_para_otro_cargo(self) -> None:
        cargos = [_cargo("A-1", "250.00", dias=1), _cargo("A-2", "250.00")]
        conc = _conciliar(cargos, [_linea("AS-1", "250.00")], [_v("A-1")])
        assert conc.propuesta["A-2"].motivo == "candidato_ocupado"
        assert conc.final["A-2"].asiento_id == "AS-1"
        assert conc.final["A-2"].reasignado is True

    def test_dos_veredictos_sobre_el_mismo_asiento_se_conservan_ambos(self) -> None:
        cargos = [_cargo("A-1", "250.00"), _cargo("A-2", "300.00")]
        conc = _conciliar(cargos, [_linea("AS-1", "250.00")], [_v("A-1", "AS-1"), _v("A-2", "AS-1")])
        assert conc.final["A-1"].asiento_id == conc.final["A-2"].asiento_id == "AS-1"
        assert conc.conflictos == {"A-2": "motor_sin_cruce"}

    def test_conciliacion_es_inmutable(self) -> None:
        conc = _conciliar([_cargo("A-1", "250.00")], [_linea("AS-1", "250.00")])
        with pytest.raises(TypeError):
            conc.final["A-1"] = conc.final["A-1"]  # type: ignore[index]
