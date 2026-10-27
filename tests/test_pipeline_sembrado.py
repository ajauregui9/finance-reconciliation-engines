"""Inyecciones que el generador sintético siembra para el demo de la cola de revisión humana."""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
for _ruta in (RAIZ / "examples", RAIZ / "skills" / "security-guardian"):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

import generador_sintetico as gs  # noqa: E402
from generador_sintetico.inyecciones import PLANTILLAS, plantar_inyecciones, verificar_inyecciones  # noqa: E402
from guardia import inspeccionar  # noqa: E402


@pytest.fixture(scope="module")
def datos() -> gs.Datos:
    return gs.generar(gs.ConfigGenerador())


def test_siembra_una_por_plantilla_dos_con_cargo_y_una_suelta(datos: gs.Datos) -> None:
    assert sorted(s.plantilla for s in datos.inyecciones) == sorted(p.nombre for p in PLANTILLAS)
    assert sum(1 for s in datos.inyecciones if s.cargo_id is not None) == 2
    assert [s.uuid for s in datos.inyecciones] == sorted(s.uuid for s in datos.inyecciones)


def test_cada_texto_sembrado_lo_marca_el_guard_con_su_familia(datos: gs.Datos) -> None:
    conceptos = {c.uuid: c.concepto for c in datos.cfdis}
    for sembrada in datos.inyecciones:
        assert sembrada.familia in {h.familia for h in inspeccionar(conceptos[sembrada.uuid])}


def test_ningun_otro_texto_del_sintetico_se_marca(datos: gs.Datos) -> None:
    sembrados = {s.uuid for s in datos.inyecciones}
    marcados = [c.uuid for c in datos.cfdis if c.uuid not in sembrados and inspeccionar(c.concepto)]
    assert marcados == []


def test_los_cargos_con_inyeccion_esperan_ese_cfdi(datos: gs.Datos) -> None:
    esperados = {e.clave_cargo: e.cfdi.esperados for e in datos.expectativas}
    for sembrada in datos.inyecciones:
        if sembrada.cargo_id is not None:
            assert esperados[sembrada.cargo_id] == (sembrada.uuid,)
    assert verificar_inyecciones(datos) == []


def test_determinista_y_valida_con_otra_semilla() -> None:
    otra = gs.generar(gs.ConfigGenerador(semilla=7))
    assert otra.inyecciones == gs.generar(gs.ConfigGenerador(semilla=7)).inyecciones
    assert len(otra.inyecciones) == len(PLANTILLAS) and gs.verificar(otra) == ()


def test_la_autoverificacion_detecta_una_siembra_rota(datos: gs.Datos) -> None:
    sembrada = next(s for s in datos.inyecciones if s.cargo_id is not None)
    cfdis = tuple(dataclasses.replace(c, concepto="SIN INYECCION") if c.uuid == sembrada.uuid else c
                  for c in datos.cfdis)
    otro_cargo = next(e.clave_cargo for e in datos.expectativas if e.clave_cargo != sembrada.cargo_id)
    rotas = (dataclasses.replace(sembrada, cargo_id=otro_cargo),
             dataclasses.replace(sembrada, uuid="SINT0000-0000-0000-0000-000000000000"))
    errores = verificar_inyecciones(dataclasses.replace(datos, cfdis=cfdis, inyecciones=rotas))
    assert any("no trae la plantilla" in e for e in errores)
    assert any(f"el cargo {otro_cargo} no espera" in e for e in errores)
    assert any("CFDI inexistente" in e for e in errores)


def test_sin_cfdis_limpios_no_se_puede_sembrar(datos: gs.Datos) -> None:
    with pytest.raises(RuntimeError, match="suficientes"):
        plantar_inyecciones(datos.config, 0, (), datos.cfdis, ())
