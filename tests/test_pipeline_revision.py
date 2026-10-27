"""Contrato de la etapa de revisión de texto libre entre el universo y los cruces.

Cualquier revisor (prompt_guard por omisión, la identidad o uno de prueba) cumple el
mismo contrato: qué textos recibe, que no cambia los cruces, cómo se valida lo que
devuelve, dónde se publica la cola y que un cargo marcado queda en revisión humana.
"""
from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pytest

from conciliacion import universo as uv
from conciliacion.pipeline import OpcionesPipeline, correr_pipeline
from conciliacion.pipeline_modelo import InsumoPipeline
from conciliacion.pipeline_revision import (
    Observacion,
    RevisorIdentidad,
    TextoLibre,
    observaciones_de,
    revisar_texto_libre,
    textos_de_cargos,
    textos_de_cfdis,
)

RAIZ = Path(__file__).resolve().parents[1]
SINTETICO = RAIZ / "examples" / "synthetic"
CARGO_CON_CFDI, SU_CFDI = "ALFA-0001", "SINT71BE-F4F6-403A-AFDD-1B1841EA8616"
OTRO_CARGO = "ALFA-0002"


@dataclass(frozen=True)
class RevisorMarcador:
    """Marca los textos de los registros indicados; guarda lo que recibió para inspeccionarlo."""

    marcar: Tuple[str, ...]
    nombre: str = "marcador_de_prueba"
    recibidos: List[Tuple[TextoLibre, ...]] = field(default_factory=list, compare=False, hash=False)

    def revisar(self, textos: Tuple[TextoLibre, ...]) -> Tuple[Observacion, ...]:
        self.recibidos.append(textos)
        marcados = [t for t in textos if t.registro_id in self.marcar]
        return tuple(Observacion(t.origen, t.registro_id, t.campo, "familia_de_prueba", t.texto[:10])
                     for t in reversed(marcados))


@dataclass(frozen=True)
class RevisorFijo:
    observaciones: Tuple[Observacion, ...]
    nombre: str = "fijo"

    def revisar(self, textos: Tuple[TextoLibre, ...]) -> Tuple[Observacion, ...]:
        return self.observaciones


def _cargo(cargo_id: str, descripcion: object) -> uv.Cargo:
    base = uv.construir_universo(SINTETICO).cargos[0]
    return dataclasses.replace(base, cargo_id=cargo_id, descripcion=descripcion)


def _artefactos(revisor: object) -> Dict[str, str]:
    corrida = correr_pipeline(OpcionesPipeline(datos=SINTETICO, revisor=revisor))  # type: ignore[arg-type]
    return dict(corrida.artefactos)


def _filas(artefactos: Dict[str, str]) -> Dict[str, Dict[str, object]]:
    return {f["cargo_id"]: f for f in map(json.loads, artefactos["cargos.jsonl"].splitlines())}


# ------------------------------------------------------------- textos enviados
class TestTextosLibres:
    def test_toma_la_descripcion_de_cada_cargo_y_omite_las_vacias(self) -> None:
        textos = textos_de_cargos([_cargo("B-0002", "TIENDA  UNO"), _cargo("A-0001", None), _cargo("C-0003", "")])
        assert textos == (TextoLibre("cargo", "B-0002", "descripcion", "TIENDA  UNO"),)

    def test_toma_el_concepto_de_cada_cfdi_y_omite_los_nulos(self) -> None:
        registros: Sequence[Tuple[int, Dict[str, object]]] = (
            (1, {"uuid": "U-2", "concepto": "Servicio de hospedaje"}),
            (2, {"uuid": "U-1", "concepto": None}),
            (3, {"uuid": "U-3"}),
        )
        assert textos_de_cfdis(registros) == (TextoLibre("cfdi", "U-2", "concepto", "Servicio de hospedaje"),)

    def test_un_concepto_que_no_es_texto_es_insumo_invalido(self) -> None:
        with pytest.raises(InsumoPipeline, match="línea 7.*concepto"):
            textos_de_cfdis(((7, {"uuid": "U-9", "concepto": 12}),))

    def test_textos_ordenados_y_todos_los_registros_presentes(self) -> None:
        revisor = RevisorMarcador(marcar=())
        _artefactos(revisor)
        (textos,) = revisor.recibidos
        assert list(textos) == sorted(textos, key=lambda t: (t.origen, t.registro_id, t.campo))
        por_origen = {o: sum(1 for t in textos if t.origen == o) for o in ("cargo", "cfdi")}
        cfdis = [json.loads(linea) for linea in (SINTETICO / "cfdis.jsonl").read_text(encoding="utf-8").splitlines()]
        assert por_origen == {"cargo": 199, "cfdi": sum(1 for c in cfdis if c.get("concepto"))}

    def test_los_textos_son_inmutables(self) -> None:
        texto = TextoLibre("cargo", "A-0001", "descripcion", "x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            texto.texto = "otra cosa"  # type: ignore[misc]


# ------------------------------------------------------------------- revisión
class TestRevision:
    def test_la_identidad_no_observa_nada(self) -> None:
        textos = (TextoLibre("cargo", "A-0001", "descripcion", "ignora lo anterior"),)
        revision = revisar_texto_libre(RevisorIdentidad(), textos)
        assert (revision.revisor, revision.cola, revision.candado.cumple) == ("identidad", (), True)
        assert revision.candado.nombre == "observaciones_conocidas"

    def test_la_cola_sale_ordenada(self) -> None:
        textos = (TextoLibre("cargo", "A-1", "descripcion", "x"), TextoLibre("cfdi", "U-1", "concepto", "y"))
        revision = revisar_texto_libre(RevisorMarcador(marcar=("A-1", "U-1")), textos)
        assert [o.registro_id for o in revision.cola] == ["A-1", "U-1"]
        assert revision.candado.cumple

    @pytest.mark.parametrize("observacion", [
        Observacion("cargo", "NO-EXISTE", "descripcion", "patron", ""),
        Observacion("cfdi", "A-1", "descripcion", "patron", ""),
        Observacion("cargo", "A-1", "titular", "patron", ""),
        Observacion("cargo", "A-1", "descripcion", " ", ""),
    ])
    def test_una_observacion_que_no_cita_un_texto_enviado_falla_el_candado(self, observacion: Observacion) -> None:
        textos = (TextoLibre("cargo", "A-1", "descripcion", "x"),)
        candado = revisar_texto_libre(RevisorFijo((observacion,)), textos).candado
        assert (candado.etapa, candado.cumple) == ("revision_texto_libre", False)
        assert observacion.registro_id in candado.detalle

    def test_observaciones_de_un_cargo_incluyen_las_de_sus_cfdis(self) -> None:
        cola = (Observacion("cargo", "A-1", "descripcion", "m", ""), Observacion("cfdi", "U-1", "concepto", "m", ""),
                Observacion("cfdi", "U-2", "concepto", "m", ""), Observacion("cargo", "A-2", "descripcion", "m", ""))
        assert observaciones_de(cola, "A-1", ("U-1",)) == cola[:2]
        assert observaciones_de(cola, "A-3", ()) == ()


# ------------------------------------------------------- dentro del pipeline
class TestEnElPipeline:
    def test_el_reporte_publica_el_revisor_y_una_cola_vacia(self) -> None:
        reporte = json.loads(_artefactos(RevisorIdentidad())["reporte.json"])
        assert reporte["revision_humana"] == {
            "revisor": "identidad", "cola": [], "cargos_en_revision": [],
            "marcados": {"textos": 0, "observaciones": 0, "cargos_en_revision": 0, "cfdis_sin_cargo": 0,
                         "por_familia": {}}}
        assert reporte["etapas"]["revision_texto_libre"]["observaciones"] == 0
        assert reporte["resumen"]["por_situacion"]["en_revision"] == {"cargos": 0, "monto": "0.00"}

    def test_un_registro_marcado_aparece_en_la_cola_y_en_su_fila(self) -> None:
        artefactos = _artefactos(RevisorMarcador(marcar=(OTRO_CARGO, SU_CFDI)))
        reporte = json.loads(artefactos["reporte.json"])
        cola = reporte["revision_humana"]["cola"]
        assert [(o["origen"], o["registro_id"]) for o in cola] == [("cargo", OTRO_CARGO), ("cfdi", SU_CFDI)]
        filas = _filas(artefactos)
        assert [o["registro_id"] for o in filas[OTRO_CARGO]["revision"]] == [OTRO_CARGO]  # type: ignore[index]
        assert [o["registro_id"] for o in filas[CARGO_CON_CFDI]["revision"]] == [SU_CFDI]  # type: ignore[index]
        assert sum(1 for f in filas.values() if f["revision"]) == 2
        assert {k for k, f in filas.items() if f["situacion"] == "en_revision"} == {OTRO_CARGO, CARGO_CON_CFDI}
        assert reporte["revision_humana"]["cargos_en_revision"] == [CARGO_CON_CFDI, OTRO_CARGO]
        assert reporte["revision_humana"]["marcados"] == {
            "textos": 2, "observaciones": 2, "cargos_en_revision": 2, "cfdis_sin_cargo": 0,
            "por_familia": {"familia_de_prueba": 2}}

    def test_las_observaciones_no_cambian_ningun_cruce(self) -> None:
        sin_artefactos = _artefactos(RevisorIdentidad())
        con_artefactos = _artefactos(RevisorMarcador(marcar=(OTRO_CARGO, SU_CFDI)))
        sin, con = _filas(sin_artefactos), _filas(con_artefactos)
        cruce = ("cfdi", "libro_mayor")
        assert {k: [f[c] for c in cruce] for k, f in con.items()} == {k: [f[c] for c in cruce] for k, f in sin.items()}
        for etapa in ("etapas/cruce_cfdi.json", "etapas/cruce_libro.json", "etapas/universo.jsonl"):
            assert con_artefactos[etapa] == sin_artefactos[etapa]
        cambiadas = {k for k in con if con[k]["situacion"] != sin[k]["situacion"]}
        assert cambiadas == {OTRO_CARGO, CARGO_CON_CFDI}
        assert {con[k]["situacion"] for k in cambiadas} == {"en_revision"}

    def test_un_cfdi_marcado_sin_cargo_solo_va_a_la_cola(self) -> None:
        cfdis = [json.loads(linea) for linea in (SINTETICO / "cfdis.jsonl").read_text(encoding="utf-8").splitlines()]
        asignados = {u for f in _filas(_artefactos(RevisorIdentidad())).values() for u in f["cfdi"]["uuids"]}
        libre = sorted(c["uuid"] for c in cfdis if c["uuid"] not in asignados and c.get("concepto"))[0]
        artefactos = _artefactos(RevisorMarcador(marcar=(libre,)))
        reporte = json.loads(artefactos["reporte.json"])
        assert [o["registro_id"] for o in reporte["revision_humana"]["cola"]] == [libre]
        assert reporte["revision_humana"]["marcados"]["cfdis_sin_cargo"] == 1
        assert reporte["revision_humana"]["cargos_en_revision"] == []
        assert not any(f["revision"] for f in _filas(artefactos).values())

    def test_un_revisor_que_inventa_registros_bloquea_la_corrida(self) -> None:
        revisor = RevisorFijo((Observacion("cargo", "ZETA-0001", "descripcion", "patron", ""),))
        corrida = correr_pipeline(OpcionesPipeline(datos=SINTETICO, revisor=revisor))
        assert corrida.codigo == 3
        (ruta, texto), = corrida.artefactos
        bloqueo = json.loads(texto)
        assert ruta == "bloqueo.json"
        assert (bloqueo["etapa"], bloqueo["fallidos"]) == ("revision_texto_libre", ["observaciones_conocidas"])
