"""Prueba de aceptación: el cruce cargo ↔ CFDI reproduce el oráculo sintético."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion.cruce_cfdi_config import ConfigCruce  # noqa: E402
from conciliacion.cruce_cfdi_insumos import leer_cargos, leer_cfdis  # noqa: E402
from conciliacion.cruce_cfdi_invariantes import verificar_invariantes  # noqa: E402
from conciliacion.cruce_cfdi_modelo import ResultadoCruce  # noqa: E402
from conciliacion.cruce_cfdi_motor import cruzar  # noqa: E402
from conciliacion.cruce_cfdi_salida import armar_salida, serializar  # noqa: E402

SINTETICOS = RAIZ / "examples" / "synthetic"
GENERADOR = RAIZ / "examples" / "generate.py"


def config_desde_oraculo(parametros: Mapping[str, Any]) -> ConfigCruce:
    """La config que el oráculo supone; el resto queda en los valores de ejemplo."""
    return ConfigCruce(
        rfc_empresa=parametros["empresa"]["rfc"],
        rfcs_genericos=tuple(parametros["rfcs_genericos"]),
        ventana_min=parametros["ventana_dias"]["min"],
        ventana_max=parametros["ventana_dias"]["max"],
        tolerancia_uno_a_uno=Decimal(parametros["tolerancia_monto"]),
        tolerancia_moneda_original=Decimal(parametros["tolerancia_monto"]),
        tolerancia_suma=Decimal(parametros["tolerancia_monto"]),
    )


def correr(carpeta: Path, banda: Optional[str] = None) -> Dict[str, Any]:
    oraculo = json.loads((carpeta / "oraculo.json").read_text(encoding="utf-8"))
    cargos = leer_cargos(carpeta / "universo_cargos_esperado.jsonl")
    cfdis = leer_cfdis(carpeta / "cfdis.jsonl")
    config = config_desde_oraculo(oraculo["parametros"])
    if banda is not None:
        config = dataclasses.replace(config, banda_fuera_de_tolerancia=Decimal(banda))
    return {"oraculo": oraculo, "cargos": cargos, "cfdis": cfdis, "config": config,
            "resultado": cruzar(cargos, cfdis, config)}


def diferencias(resultado: ResultadoCruce, oraculo: Mapping[str, Any]) -> List[str]:
    """Compara CFDIs, evidencia y motivo por cargo; dentro de un grupo de empate basta una biyección."""
    grupos = {g["grupo"]: g for g in oraculo["grupos_empate"]}
    salida: List[str] = []
    usados_por_grupo: Dict[str, List[str]] = {}
    for esperado in oraculo["cargos"]:
        cid, cfdi = esperado["cargo_id"], esperado["cfdi"]
        obtenido = resultado.buscar(cid)
        if (obtenido.evidencia, obtenido.motivo) != (cfdi["evidencia"], cfdi["motivo_sin_cruce"]):
            salida.append(f"{cid}: {obtenido.evidencia}/{obtenido.motivo} != "
                          f"{cfdi['evidencia']}/{cfdi['motivo_sin_cruce']}")
        prohibidos = set(obtenido.cfdis) & set(cfdi["prohibidos"])
        if prohibidos:
            salida.append(f"{cid}: asigna prohibidos {sorted(prohibidos)}")
        grupo = esperado["grupo_empate"]
        if grupo is None:
            if sorted(obtenido.cfdis) != sorted(cfdi["esperados"]):
                salida.append(f"{cid}: {list(obtenido.cfdis)} != {sorted(cfdi['esperados'])}")
            continue
        if len(obtenido.cfdis) != 1 or obtenido.cfdis[0] not in grupos[grupo]["cfdis"]:
            salida.append(f"{cid}: {list(obtenido.cfdis)} fuera del grupo {grupo}")
        usados_por_grupo.setdefault(grupo, []).extend(obtenido.cfdis)
    for grupo, usados in sorted(usados_por_grupo.items()):
        if sorted(usados) != sorted(grupos[grupo]["cfdis"]):
            salida.append(f"{grupo}: asignación no biyectiva {sorted(usados)}")
    return salida


@pytest.fixture(scope="module")
def corrida() -> Dict[str, Any]:
    return correr(SINTETICOS)


def test_reproduce_el_oraculo(corrida: Dict[str, Any]) -> None:
    assert diferencias(corrida["resultado"], corrida["oraculo"]) == []


def _casos() -> List[str]:
    oraculo = json.loads((SINTETICOS / "oraculo.json").read_text(encoding="utf-8"))
    return sorted(oraculo["resumen"]["casos"])


@pytest.mark.parametrize("caso", _casos())
def test_cada_caso_del_catalogo(corrida: Dict[str, Any], caso: str) -> None:
    oraculo = corrida["oraculo"]
    del_caso: Set[str] = {c["cargo_id"] for c in oraculo["cargos"] if caso in c["casos"]}
    assert del_caso, caso
    filtrado = dict(oraculo, cargos=[c for c in oraculo["cargos"] if c["cargo_id"] in del_caso])
    grupos_del_caso = {c["grupo_empate"] for c in filtrado["cargos"]} - {None}
    filtrado["grupos_empate"] = [g for g in oraculo["grupos_empate"] if g["grupo"] in grupos_del_caso]
    assert diferencias(corrida["resultado"], filtrado) == []


def test_cubre_todos_los_tiers_y_motivos(corrida: Dict[str, Any]) -> None:
    resultado: ResultadoCruce = corrida["resultado"]
    evidencias = {r.evidencia for r in resultado.cargos} - {None}
    motivos = {r.motivo for r in resultado.cargos} - {None}
    assert evidencias == {"monto_exacto", "monto_tolerancia", "moneda_original", "suma"}
    assert motivos == {"sin_candidato", "fuera_de_ventana", "fuera_de_tolerancia", "solo_rfc_generico",
                       "fila_ininterpretable", "no_aplica"}


def test_invariantes_se_cumplen(corrida: Dict[str, Any]) -> None:
    invariantes = verificar_invariantes(corrida["cargos"], corrida["cfdis"], corrida["config"],
                                        corrida["resultado"])
    assert [i.nombre for i in invariantes if not i.cumple] == []


def test_dos_corridas_dan_el_mismo_sha256(corrida: Dict[str, Any]) -> None:
    def huella(cargos: Any, cfdis: Any) -> str:
        resultado = cruzar(cargos, cfdis, corrida["config"])
        invariantes = verificar_invariantes(cargos, cfdis, corrida["config"], resultado)
        documento = armar_salida(corrida["config"], resultado, invariantes, {"universo": {}, "cfdis": {}},
                                 cfdis_en_pool=len(cfdis))
        return hashlib.sha256(serializar(documento)).hexdigest()

    primera = huella(corrida["cargos"], corrida["cfdis"])
    assert primera == huella(corrida["cargos"], corrida["cfdis"])
    assert primera == huella(tuple(reversed(corrida["cargos"])), tuple(reversed(corrida["cfdis"])))


@pytest.mark.parametrize(
    "argumentos,banda",
    [
        (["--semilla", "7", "--ventana-min", "-3", "--ventana-max", "10", "--tolerancia", "0.50"], None),
        (["--semilla", "11"], None),
        # Con tolerancia 2.00 los casi-cruces plantados quedan a 4.50-6.50: la banda de
        # diagnóstico es un parámetro y se amplía en la config, como lo haría un usuario.
        (["--semilla", "2026", "--ventana-min", "-7", "--ventana-max", "20", "--tolerancia", "2.00"], "7.00"),
    ],
)
def test_reproduce_oraculos_regenerados(tmp_path: Path, argumentos: List[str], banda: Optional[str]) -> None:
    proceso = subprocess.run(
        [sys.executable, str(GENERADOR), "--salida", str(tmp_path), *argumentos],
        capture_output=True, text=True, check=False,
    )
    assert proceso.returncode == 0, proceso.stderr
    nueva = correr(tmp_path, banda)
    assert diferencias(nueva["resultado"], nueva["oraculo"]) == []


def test_banda_por_defecto_no_alcanza_casi_cruces_lejanos(tmp_path: Path) -> None:
    argumentos = ["--semilla", "2026", "--ventana-min", "-7", "--ventana-max", "20", "--tolerancia", "2.00"]
    subprocess.run([sys.executable, str(GENERADOR), "--salida", str(tmp_path), *argumentos],
                   capture_output=True, check=True)
    nueva = correr(tmp_path)
    errores = diferencias(nueva["resultado"], nueva["oraculo"])
    assert errores and all("sin_candidato != None/fuera_de_tolerancia" in e for e in errores)
