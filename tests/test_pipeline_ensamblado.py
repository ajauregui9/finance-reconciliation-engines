"""Ensamblado por cargo del pipeline: situación, resumen e invariantes recalculados sobre las filas."""
from __future__ import annotations

import copy
import dataclasses
import json
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, Optional, Tuple

import pytest

from conciliacion import pipeline_filas
from conciliacion.pipeline_filas import SITUACIONES_FILA, FilaCargo, LadoCfdi, LadoLibro, fila_a_dict, situacion_de
from conciliacion.pipeline_invariantes import invariantes_de_filas, resumir, verificar_cobertura
from conciliacion.pipeline_modelo import SITUACIONES
from conciliacion.pipeline_reporte import a_json, a_jsonl, cfdi_por_revisar
from conciliacion.pipeline_revision import Observacion

SIN_CFDI = LadoCfdi((), None, "sin_candidato", None, None, ())
SIN_ASIENTO = LadoLibro(None, "motor", False, "sin_candidato", None, None, None)


def lado_cfdi(*uuids: str, tier: str = "monto_exacto", afinidad: Optional[Fraction] = Fraction(1)) -> LadoCfdi:
    return LadoCfdi(tuple(uuids), tier, None, Decimal("0.00"), "MXN", tuple(0 for _ in uuids), afinidad)


def lado_libro(asiento: str, cubeta: bool = False) -> LadoLibro:
    return LadoLibro(asiento, "motor", cubeta, None, asiento, None, None)


def fila(cargo_id: str, monto: str, cfdi: LadoCfdi = SIN_CFDI, libro: LadoLibro = SIN_ASIENTO, *,
         estado: str = "ok", tipo: Optional[str] = "cargo") -> FilaCargo:
    return FilaCargo(
        cargo_id=cargo_id, emisor=cargo_id.split("-")[0], fecha=date(2026, 7, 1), descripcion="COMERCIO",
        monto=Decimal(monto), moneda="MXN", tipo_movimiento=tipo, estado=estado,
        motivo_fila=None if estado == "ok" else "fecha_invalida", cfdi=cfdi, libro=libro,
        provisional=False, revision=())


def base() -> Tuple[FilaCargo, ...]:
    return (
        fila("ALFA-0001", "100.00", lado_cfdi("U-1"), lado_libro("AS-1")),
        fila("ALFA-0002", "-40.00", lado_cfdi("U-2", "U-3", tier="suma")),
        fila("ALFA-0003", "-500.00", LadoCfdi((), None, "no_aplica", None, None, ()),
             LadoLibro(None, "motor", False, "no_aplica", None, None, None), tipo="pago"),
        fila("BETA-0001", "25.50", libro=lado_libro("AS-2", cubeta=True)),
    )


CONTROL = {"ALFA": Decimal("-440.00"), "BETA": Decimal("25.50")}


def fallidos(filas: Tuple[FilaCargo, ...], control: Dict[str, Decimal] = CONTROL,
             resumen: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
    publicado = resumir(filas, control) if resumen is None else resumen
    return {c.nombre: c.detalle for c in invariantes_de_filas(filas, publicado, control) if not c.cumple}


# ------------------------------------------------------------------ situación
@pytest.mark.parametrize("estado,tipo,tiene_cfdi,tiene_asiento,esperada", [
    ("ininterpretable", "cargo", True, True, "fila_ininterpretable"),
    ("ok", "pago", False, True, "no_aplica"),
    ("ok", "cargo", True, True, "conciliado"),
    ("ok", "abono", False, True, "falta_cfdi"),
    ("ok", "cargo", True, False, "falta_registro"),
    ("ok", "cargo", False, False, "falta_cfdi_y_registro"),
])
def test_situacion(estado: str, tipo: str, tiene_cfdi: bool, tiene_asiento: bool, esperada: str) -> None:
    assert situacion_de(estado, tipo, tiene_cfdi, tiene_asiento) == esperada
    assert esperada in SITUACIONES


@pytest.mark.parametrize("tiene_asiento", [True, False])
def test_un_cfdi_sin_afinidad_queda_por_revisar_con_o_sin_asiento(tiene_asiento: bool) -> None:
    assert situacion_de("ok", "cargo", True, tiene_asiento, cfdi_por_revisar=True) == "cfdi_por_revisar"
    assert situacion_de("ok", "cargo", True, tiene_asiento, en_revision=True, cfdi_por_revisar=True) == "en_revision"
    assert set(SITUACIONES_FILA) == set(SITUACIONES) | {"cfdi_por_revisar"}


def test_la_fila_con_tier_sin_afinidad_nunca_queda_conciliada() -> None:
    sin_afinidad = fila("ALFA-0001", "100.00", lado_cfdi("U-9", tier="monto_sin_afinidad", afinidad=Fraction(0)),
                        lado_libro("AS-1"))
    assert sin_afinidad.situacion == "cfdi_por_revisar"
    objeto = fila_a_dict(sin_afinidad)
    assert (objeto["cfdi"]["tier"], objeto["cfdi"]["afinidad_nombre"]) == ("monto_sin_afinidad", "0.00")


@pytest.mark.parametrize("estado,tipo,tiene_cfdi,tiene_asiento", [
    ("ininterpretable", "cargo", True, True),
    ("ok", "pago", False, False),
    ("ok", "cargo", True, True),
    ("ok", "cargo", False, False),
])
def test_un_registro_marcado_queda_en_revision_sea_cual_sea_su_evidencia(
        estado: str, tipo: str, tiene_cfdi: bool, tiene_asiento: bool) -> None:
    assert situacion_de(estado, tipo, tiene_cfdi, tiene_asiento, en_revision=True) == "en_revision"
    assert SITUACIONES[0] == "en_revision"


def test_la_fila_deriva_su_situacion_de_ambos_lados() -> None:
    assert [f.situacion for f in base()] == ["conciliado", "falta_registro", "no_aplica", "falta_cfdi"]


def test_fila_como_objeto_json() -> None:
    observacion = Observacion("cargo", "ALFA-0001", "descripcion", "anulacion_instrucciones", "IGNORA LO ANTERIOR")
    objeto = fila_a_dict(dataclasses.replace(base()[0], revision=(observacion,), provisional=True))
    assert objeto == {
        "cargo_id": "ALFA-0001", "emisor": "ALFA", "fecha": "2026-07-01", "descripcion": "COMERCIO",
        "monto": "100.00", "moneda": "MXN", "tipo_movimiento": "cargo", "estado": "ok", "motivo_fila": None,
        "situacion": "en_revision", "provisional": True,
        "cfdi": {"uuids": ["U-1"], "tier": "monto_exacto", "motivo_sin_cruce": None, "diferencia": "0.00",
                 "moneda_diferencia": "MXN", "delta_dias": [0], "afinidad_nombre": "1.00"},
        "libro_mayor": {"asiento_id": "AS-1", "origen": "motor", "riesgo_cubeta": False, "motivo_sin_cruce": None,
                        "propuesta_asiento_id": "AS-1", "conflicto": None, "veredicto": None},
        "revision": [{"origen": "cargo", "registro_id": "ALFA-0001", "campo": "descripcion",
                      "familia": "anulacion_instrucciones", "fragmento": "IGNORA LO ANTERIOR"}],
    }


# -------------------------------------------------------------------- resumen
class TestResumen:
    def test_totales_y_particiones(self) -> None:
        resumen = resumir(base(), CONTROL)
        assert resumen["total"] == {"cargos": 4, "monto": "-414.50"}
        assert resumen["por_emisor"] == {
            "ALFA": {"cargos": 3, "monto": "-440.00", "total_neto_estado": "-440.00"},
            "BETA": {"cargos": 1, "monto": "25.50", "total_neto_estado": "25.50"}}
        assert list(resumen["por_situacion"]) == sorted(SITUACIONES_FILA)
        assert resumen["por_situacion"]["falta_cfdi_y_registro"] == {"cargos": 0, "monto": "0.00"}
        assert resumen["por_situacion"]["cfdi_por_revisar"] == {"cargos": 0, "monto": "0.00"}
        assert resumen["cfdi"]["por_tier"]["suma"] == {"cargos": 1, "monto": "-40.00"}
        assert resumen["cfdi"]["por_tier"]["monto_sin_afinidad"] == {"cargos": 0, "monto": "0.00"}
        assert resumen["cfdi"]["por_motivo"]["no_aplica"] == {"cargos": 1, "monto": "-500.00"}
        assert resumen["cfdi"]["uuids_asignados"] == 3
        libro = resumen["libro_mayor"]
        assert (libro["con_asiento"], libro["sin_asiento"]) == (
            {"cargos": 2, "monto": "125.50"}, {"cargos": 2, "monto": "-540.00"})
        assert (libro["riesgo_cubeta"], libro["por_origen"]) == (1, {"motor": 4, "veredicto_humano": 0})
        assert libro["conflictos"] == {"asiento_distinto": 0, "motor_con_cruce": 0, "motor_sin_cruce": 0}

    def test_el_resumen_no_lleva_numeros_con_decimales(self) -> None:
        def rechazar(texto: str) -> None:
            raise AssertionError(f"número con decimales en el resumen: {texto}")

        json.loads(a_json(resumir(base(), CONTROL)), parse_float=rechazar)


# ---------------------------------------------------------------- invariantes
class TestInvariantes:
    def test_todo_en_verde(self) -> None:
        nombres = [c.nombre for c in invariantes_de_filas(base(), resumir(base(), CONTROL), CONTROL)]
        assert nombres == ["exclusividad_uuid", "exclusividad_asiento", "tier_o_motivo_cfdi",
                           "asiento_o_motivo_libro", "totales_control", "totales_resumen", "cuarentena",
                           "cola_completa", "candidato_por_revisar"]
        assert fallidos(base()) == {}

    def test_un_candidato_por_revisar_en_verde(self) -> None:
        filas = base()[:3] + (dataclasses.replace(
            base()[3], cfdi=lado_cfdi("U-9", tier="monto_sin_afinidad", afinidad=Fraction(1, 4))),)
        assert fallidos(filas, resumen=resumir(filas, CONTROL)) == {}

    def test_un_candidato_por_revisar_sin_afinidad_publicada(self) -> None:
        filas = base()[:3] + (dataclasses.replace(
            base()[3], cfdi=lado_cfdi("U-9", tier="monto_sin_afinidad", afinidad=None)),)
        detalle = fallidos(filas)
        assert set(detalle) == {"candidato_por_revisar"} and "BETA-0001" in detalle["candidato_por_revisar"]

    def test_un_candidato_por_revisar_que_cuenta_como_conciliado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        filas = base()[:3] + (dataclasses.replace(
            base()[3], cfdi=lado_cfdi("U-9", tier="monto_sin_afinidad", afinidad=Fraction(0))),)
        monkeypatch.setattr(pipeline_filas, "situacion_de", lambda *args, **kwargs: "conciliado")
        assert "candidato_por_revisar" in fallidos(filas)

    def test_uuid_en_dos_cargos(self) -> None:
        filas = base()[:1] + (dataclasses.replace(base()[1], cfdi=lado_cfdi("U-1", "U-3", tier="suma")),) + base()[2:]
        assert set(fallidos(filas)) == {"exclusividad_uuid"}
        assert "U-1" in fallidos(filas)["exclusividad_uuid"]

    def test_asiento_en_dos_cargos(self) -> None:
        filas = base()[:3] + (dataclasses.replace(base()[3], libro=lado_libro("AS-1")),)
        assert set(fallidos(filas)) == {"exclusividad_asiento"}

    @pytest.mark.parametrize("cfdi", [
        LadoCfdi((), "monto_exacto", None, None, None, ()),
        LadoCfdi(("U-9",), "monto_exacto", "sin_candidato", None, None, (0,)),
        LadoCfdi((), None, None, None, None, ()),
        LadoCfdi(("U-9",), None, "sin_candidato", None, None, (0,)),
    ])
    def test_tier_o_motivo(self, cfdi: LadoCfdi) -> None:
        filas = base()[:3] + (dataclasses.replace(base()[3], cfdi=cfdi),)
        assert "tier_o_motivo_cfdi" in fallidos(filas)

    @pytest.mark.parametrize("libro", [
        LadoLibro("AS-9", "motor", False, "sin_candidato", None, None, None),
        LadoLibro(None, "motor", False, None, None, None, None),
    ])
    def test_asiento_o_motivo(self, libro: LadoLibro) -> None:
        filas = base()[:3] + (dataclasses.replace(base()[3], libro=libro),)
        assert "asiento_o_motivo_libro" in fallidos(filas)

    def test_totales_que_no_cuadran_con_el_estado_de_cuenta(self) -> None:
        detalle = fallidos(base(), {"ALFA": Decimal("-440.01"), "BETA": Decimal("25.50")})
        assert set(detalle) == {"totales_control"} and "ALFA" in detalle["totales_control"]

    def test_un_estado_sin_filas_o_filas_sin_estado(self) -> None:
        assert "totales_control" in fallidos(base(), {"ALFA": Decimal("-440.00")})
        assert "totales_control" in fallidos(base(), {**CONTROL, "GAMMA": Decimal("10.00")})
        # Un estado leído sin movimientos y con neto cero cuadra: no es una falla.
        assert fallidos(base(), {**CONTROL, "GAMMA": Decimal("0.00")}) == {}

    @pytest.mark.parametrize("ruta,valor", [
        (("total", "monto"), "-414.49"),
        (("por_situacion", "conciliado", "cargos"), 2),
        (("cfdi", "por_tier", "monto_exacto", "monto"), "100.01"),
        (("cfdi", "por_motivo", "sin_candidato", "cargos"), 5),
        (("libro_mayor", "sin_asiento", "monto"), "0.00"),
        (("libro_mayor", "por_motivo", "no_aplica", "cargos"), 0),
        (("por_emisor", "BETA", "monto"), "25.51"),
    ])
    def test_un_resumen_publicado_que_no_suma(self, ruta: Tuple[str, ...], valor: object) -> None:
        resumen = copy.deepcopy(resumir(base(), CONTROL))
        destino = resumen
        for llave in ruta[:-1]:
            destino = destino[llave]
        destino[ruta[-1]] = valor
        assert set(fallidos(base(), resumen=resumen)) == {"totales_resumen"}


class TestCobertura:
    def test_mismos_cargos_en_todas_las_etapas(self) -> None:
        candado = verificar_cobertura(("A-1", "A-2"), ("A-2", "A-1"), ("A-1", "A-2"))
        assert (candado.etapa, candado.nombre, candado.cumple) == ("pipeline", "cobertura", True)

    @pytest.mark.parametrize("cfdi,libro,pista", [
        (("A-1",), ("A-1", "A-2"), "cruce_cfdi"),
        (("A-1", "A-2"), ("A-1", "A-2", "A-3"), "cruce_libro"),
        (("A-1", "A-2", "A-2"), ("A-1", "A-2"), "A-2"),
    ])
    def test_falta_sobra_o_se_repite_un_cargo(self, cfdi: Tuple[str, ...], libro: Tuple[str, ...],
                                              pista: str) -> None:
        candado = verificar_cobertura(("A-1", "A-2"), cfdi, libro)
        assert not candado.cumple and pista in candado.detalle


# ------------------------------------------------- candidatos por revisar
def test_el_reporte_lista_los_cfdis_por_revisar_con_su_afinidad() -> None:
    observacion = Observacion("cargo", "BETA-0001", "descripcion", "anulacion_instrucciones", "X")
    sin_afinidad = lado_cfdi("U-9", tier="monto_sin_afinidad", afinidad=Fraction(1, 3))
    filas = (base()[0], dataclasses.replace(base()[3], cfdi=sin_afinidad),
             dataclasses.replace(fila("ALFA-0009", "7.00"), cfdi=sin_afinidad, revision=(observacion,)))
    assert cfdi_por_revisar(filas) == [
        {"cargo_id": "ALFA-0009", "uuids": ["U-9"], "tier": "monto_sin_afinidad", "afinidad_nombre": "0.33",
         "diferencia": "0.00", "moneda_diferencia": "MXN", "situacion": "en_revision"},
        {"cargo_id": "BETA-0001", "uuids": ["U-9"], "tier": "monto_sin_afinidad", "afinidad_nombre": "0.33",
         "diferencia": "0.00", "moneda_diferencia": "MXN", "situacion": "cfdi_por_revisar"},
    ]
    assert cfdi_por_revisar(base()) == []


# ------------------------------------------------------------ serialización
def test_jsonl_ordenado_por_cargo_y_con_llaves_ordenadas() -> None:
    texto = a_jsonl(tuple(reversed(base())))
    lineas = texto.splitlines()
    assert texto.endswith("\n") and "\r" not in texto
    assert [json.loads(x)["cargo_id"] for x in lineas] == ["ALFA-0001", "ALFA-0002", "ALFA-0003", "BETA-0001"]
    assert all(x == json.dumps(json.loads(x), ensure_ascii=False, sort_keys=True) for x in lineas)


def test_json_determinista() -> None:
    assert a_json({"b": "ñ", "a": [1]}) == '{\n  "a": [\n    1\n  ],\n  "b": "ñ"\n}\n'
