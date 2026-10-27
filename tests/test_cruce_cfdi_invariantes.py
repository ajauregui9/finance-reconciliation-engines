"""Pruebas de los invariantes (candados) del cruce cargo ↔ CFDI."""
from __future__ import annotations

import dataclasses
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

import pytest

SKILL = Path(__file__).resolve().parents[1] / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion.cruce_cfdi_config import ConfigCruce  # noqa: E402
from conciliacion.cruce_cfdi_invariantes import NOMBRES_INVARIANTES, verificar_invariantes  # noqa: E402
from conciliacion.cruce_cfdi_modelo import Cargo, Cfdi, ResultadoCruce  # noqa: E402
from conciliacion.cruce_cfdi_motor import cruzar  # noqa: E402

CONFIG = ConfigCruce()
DIA = date(2026, 7, 10)


def _cargo(cid: str, monto: str) -> Cargo:
    valor = Decimal(monto)
    return Cargo(cid, DIA, "CAFE LUNA AZUL", valor, "MXN", valor, "cargo", "ok")


def _cfdi(uuid: str, total: str, rfc: str = "RFC_COM_01", dia: int = 0) -> Cfdi:
    return Cfdi(uuid, DIA + timedelta(days=dia), "I", "recibido", rfc, "CAFETERIA LUNA AZUL",
                "RFC_EMPRESA_DEMO", "MXN", Decimal(total), Decimal(total))


CARGOS = (_cargo("ALFA-0001", "100.00"), _cargo("ALFA-0002", "250.00"), _cargo("ALFA-0003", "7.00"))
CFDIS = (_cfdi("U-1", "100.00"), _cfdi("U-2", "150.00"), _cfdi("U-3", "100.00"),
         _cfdi("U-4", "100.40"), _cfdi("U-5", "100.00", rfc="RFC_COM_02"), _cfdi("U-6", "100.00", dia=40))


def _base() -> ResultadoCruce:
    return cruzar(CARGOS, CFDIS, CONFIG)


def _cambiar(resultado: ResultadoCruce, cid: str, **campos: object) -> ResultadoCruce:
    nuevos = tuple(dataclasses.replace(r, **campos) if r.cargo_id == cid else r for r in resultado.cargos)
    return dataclasses.replace(resultado, cargos=nuevos)


def _estado(resultado: ResultadoCruce) -> Dict[str, bool]:
    return {i.nombre: i.cumple for i in verificar_invariantes(CARGOS, CFDIS, CONFIG, resultado)}


def _fallidos(resultado: ResultadoCruce) -> List[str]:
    return [nombre for nombre, ok in _estado(resultado).items() if not ok]


def test_resultado_del_motor_cumple_todo() -> None:
    base = _base()
    assert base.buscar("ALFA-0002").evidencia == "suma"
    invariantes = verificar_invariantes(CARGOS, CFDIS, CONFIG, base)
    assert tuple(i.nombre for i in invariantes) == NOMBRES_INVARIANTES
    assert all(i.cumple for i in invariantes)
    assert all(i.detalle == "sin observaciones" for i in invariantes)


def test_cobertura_detecta_cargo_faltante_y_repetido() -> None:
    base = _base()
    sin_uno = dataclasses.replace(base, cargos=base.cargos[1:])
    repetido = dataclasses.replace(base, cargos=base.cargos + base.cargos[:1])
    assert "cobertura" in _fallidos(sin_uno)
    assert "cobertura" in _fallidos(repetido)


def test_exclusividad_detecta_cfdi_compartido() -> None:
    base = _base()
    otro = base.buscar("ALFA-0001")
    copia = _cambiar(base, "ALFA-0003", cfdis=otro.cfdis, evidencia=otro.evidencia, motivo=None,
                     diferencia=otro.diferencia, moneda_diferencia="MXN", deltas=otro.deltas)
    fallidos = _fallidos(copia)
    assert "exclusividad" in fallidos
    assert "coherencia_tier" in fallidos


def test_cfdis_conocidos() -> None:
    falso = _cambiar(_base(), "ALFA-0001", cfdis=("U-999",))
    assert "cfdis_conocidos" in _fallidos(falso)


@pytest.mark.parametrize(
    "campos",
    [
        {"motivo": "sin_candidato"},
        {"evidencia": None},
        {"cfdis": ()},
    ],
)
def test_evidencia_o_motivo(campos: Dict[str, object]) -> None:
    assert "evidencia_o_motivo" in _fallidos(_cambiar(_base(), "ALFA-0001", **campos))


def test_evidencia_o_motivo_sin_ninguno() -> None:
    vacio = _cambiar(_base(), "ALFA-0003", motivo=None)
    assert "evidencia_o_motivo" in _fallidos(vacio)


@pytest.mark.parametrize(
    "cfdis,evidencia",
    [
        (("U-4",), "monto_exacto"),
        (("U-1",), "monto_tolerancia"),
        (("U-1",), "moneda_original"),
        (("U-6",), "monto_exacto"),
        (("U-3", "U-5"), "suma"),
        (("U-1",), "suma"),
        (("U-1",), "tier_inventado"),
    ],
)
def test_coherencia_tier(cfdis: Tuple[str, ...], evidencia: str) -> None:
    alterado = _cambiar(_base(), "ALFA-0001", cfdis=cfdis, evidencia=evidencia)
    assert "coherencia_tier" in _fallidos(alterado)


def test_maximalidad_uno_a_uno() -> None:
    base = _base()
    suelto = _cambiar(base, "ALFA-0001", cfdis=(), evidencia=None, motivo="sin_candidato",
                      diferencia=None, moneda_diferencia=None, deltas=(), afinidad=None)
    assert _fallidos(suelto) == ["maximalidad_uno_a_uno"]


def test_detalle_nombra_al_cargo() -> None:
    falso = _cambiar(_base(), "ALFA-0001", cfdis=("U-999",))
    detalle = {i.nombre: i.detalle for i in verificar_invariantes(CARGOS, CFDIS, CONFIG, falso)}
    assert "ALFA-0001" in detalle["cfdis_conocidos"]
