"""Integración del pipeline de tarjetas sobre examples/synthetic: determinismo y oráculo.

El pipeline corre dos veces como proceso independiente y cada archivo de la salida
debe dar el mismo SHA-256. Después, las filas por cargo se comparan contra
`oraculo.json`: tasa de acierto por tier (y por motivo) del lado CFDI y por
desenlace del lado libro mayor, aceptando cualquier biyección dentro de un grupo
de empate.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Set, Tuple

import pytest

from conciliacion import cruce_cfdi, cruce_libro
from conciliacion import universo as uv
from conciliacion.pipeline import OpcionesPipeline, correr_pipeline

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
SINTETICO = RAIZ / "examples" / "synthetic"
TIERS = ("monto_exacto", "moneda_original", "monto_tolerancia", "suma", "monto_sin_afinidad")

Tasa = Dict[str, Tuple[int, int]]


def sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def huellas(carpeta: Path) -> Dict[str, str]:
    return {str(p.relative_to(carpeta)): sha256(p) for p in sorted(carpeta.rglob("*")) if p.is_file()}


def correr_cli(salida: Path) -> None:
    proceso = subprocess.run(
        [sys.executable, "-m", "conciliacion.pipeline", "--datos", str(SINTETICO), "--salida", str(salida)],
        cwd=SKILL, capture_output=True, text=True, check=False)
    assert proceso.returncode == 0, proceso.stderr


@pytest.fixture(scope="module")
def dos_corridas(tmp_path_factory: pytest.TempPathFactory) -> Tuple[Path, Path]:
    primera, segunda = tmp_path_factory.mktemp("primera"), tmp_path_factory.mktemp("segunda")
    correr_cli(primera)
    correr_cli(segunda)
    return primera, segunda


@pytest.fixture(scope="module")
def oraculo() -> Dict[str, Any]:
    return json.loads((SINTETICO / "oraculo.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def filas(dos_corridas: Tuple[Path, Path]) -> Dict[str, Dict[str, Any]]:
    texto = (dos_corridas[0] / "cargos.jsonl").read_text(encoding="utf-8")
    return {f["cargo_id"]: f for f in map(json.loads, texto.splitlines())}


# --------------------------------------------------------------- determinismo
class TestDeterminismo:
    def test_dos_corridas_dan_el_mismo_sha256_en_cada_archivo(self, dos_corridas: Tuple[Path, Path]) -> None:
        primera, segunda = (huellas(c) for c in dos_corridas)
        assert set(primera) == {"reporte.json", "cargos.jsonl", "etapas/universo.jsonl",
                                "etapas/universo.control.json", "etapas/cruce_cfdi.json", "etapas/cruce_libro.json"}
        assert primera == segunda

    def test_la_api_produce_los_mismos_bytes_que_la_cli(self, dos_corridas: Tuple[Path, Path]) -> None:
        corrida = correr_pipeline(OpcionesPipeline(datos=SINTETICO))
        assert corrida.codigo == 0
        en_memoria = {ruta: hashlib.sha256(texto.encode("utf-8")).hexdigest() for ruta, texto in corrida.artefactos}
        assert en_memoria == huellas(dos_corridas[0])

    def test_formato_utf8_lf_y_llaves_ordenadas(self, dos_corridas: Tuple[Path, Path]) -> None:
        carpeta = dos_corridas[0]
        crudo = (carpeta / "reporte.json").read_bytes()
        assert not crudo.startswith(b"\xef\xbb\xbf") and b"\r" not in crudo and crudo.endswith(b"}\n")
        reporte = json.loads(crudo)
        assert crudo.decode("utf-8") == json.dumps(reporte, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
        for linea in (carpeta / "cargos.jsonl").read_text(encoding="utf-8").splitlines():
            assert linea == json.dumps(json.loads(linea), ensure_ascii=False, sort_keys=True)

    def test_el_reporte_registra_el_sha256_de_cada_artefacto(self, dos_corridas: Tuple[Path, Path]) -> None:
        carpeta = dos_corridas[0]
        esperados = {k: v for k, v in huellas(carpeta).items() if k != "reporte.json"}
        assert json.loads((carpeta / "reporte.json").read_text(encoding="utf-8"))["artefactos"] == esperados

    def test_sin_rutas_absolutas_en_la_salida(self, dos_corridas: Tuple[Path, Path]) -> None:
        for ruta in dos_corridas[0].rglob("*"):
            if ruta.is_file():
                assert str(RAIZ) not in ruta.read_text(encoding="utf-8"), ruta.name


# ----------------------------------------------------------- cadena de etapas
class TestCadenaDeEtapas:
    def test_universo_desde_crudos_es_el_esperado(self, dos_corridas: Tuple[Path, Path]) -> None:
        obtenido = (dos_corridas[0] / "etapas" / "universo.jsonl").read_bytes()
        assert obtenido == (SINTETICO / "universo_cargos_esperado.jsonl").read_bytes()

    def test_los_cruces_leyeron_el_universo_escrito(self, dos_corridas: Tuple[Path, Path]) -> None:
        carpeta = dos_corridas[0]
        huella = sha256(carpeta / "etapas" / "universo.jsonl")
        cfdi = json.loads((carpeta / "etapas" / "cruce_cfdi.json").read_text(encoding="utf-8"))
        libro = json.loads((carpeta / "etapas" / "cruce_libro.json").read_text(encoding="utf-8"))
        assert cfdi["insumos"]["universo"] == {"registros": 199, "sha256": huella}
        assert libro["insumos"]["universo"] == {"cargos": 199, "sha256": huella}
        assert cfdi["insumos"]["cfdis"]["sha256"] == sha256(SINTETICO / "cfdis.jsonl")
        assert libro["insumos"]["libro"]["sha256"] == sha256(SINTETICO / "libro_mayor.csv")
        assert libro["insumos"]["veredictos"]["sha256"] == sha256(SINTETICO / "veredictos_libro.csv")

    def test_cada_etapa_es_lo_que_escribe_la_cli_de_su_motor(self, dos_corridas: Tuple[Path, Path],
                                                             tmp_path: Path) -> None:
        etapas = dos_corridas[0] / "etapas"
        universo_cli, cfdi_cli, libro_cli = tmp_path / "u.jsonl", tmp_path / "cfdi.json", tmp_path / "libro.json"
        with contextlib.redirect_stdout(io.StringIO()):
            assert uv.main([str(SINTETICO), "--salida", str(universo_cli)]) == 0
            assert cruce_cfdi.main(["--universo", str(etapas / "universo.jsonl"), "--cfdis",
                                    str(SINTETICO / "cfdis.jsonl"), "--salida", str(cfdi_cli)]) == 0
            assert cruce_libro.main(["--universo", str(etapas / "universo.jsonl"), "--libro",
                                     str(SINTETICO / "libro_mayor.csv"), "--veredictos",
                                     str(SINTETICO / "veredictos_libro.csv"), "--salida", str(libro_cli)]) == 0
        assert universo_cli.read_bytes() == (etapas / "universo.jsonl").read_bytes()
        assert (tmp_path / "u.control.json").read_bytes() == (etapas / "universo.control.json").read_bytes()
        assert cfdi_cli.read_bytes() == (etapas / "cruce_cfdi.json").read_bytes()
        assert libro_cli.read_bytes() == (etapas / "cruce_libro.json").read_bytes()

    def test_el_reporte_registra_el_sha256_de_cada_insumo(self, dos_corridas: Tuple[Path, Path]) -> None:
        insumos = json.loads((dos_corridas[0] / "reporte.json").read_text(encoding="utf-8"))["insumos"]
        assert insumos["resumen_estados_cuenta"] == {
            "archivo": "resumen_estados_cuenta.json", "sha256": sha256(SINTETICO / "resumen_estados_cuenta.json")}
        assert insumos["estados_cuenta"] == {
            emisor: {"archivo": archivo, "sha256": sha256(SINTETICO / archivo)}
            for emisor, archivo in (("ALFA", "estado_cuenta_alfa.csv"), ("BETA", "estado_cuenta_beta.csv"))}
        assert (insumos["cfdis"]["registros"], insumos["libro_mayor"]["lineas"]) == (254, 550)
        assert insumos["veredictos"] == {"archivo": "veredictos_libro.csv", "filas": 12, "aplicados": 12,
                                         "en_espera": 0, "sha256": sha256(SINTETICO / "veredictos_libro.csv")}

    def test_totales_por_emisor_cuadran_con_el_estado_de_cuenta(self, dos_corridas: Tuple[Path, Path],
                                                                filas: Dict[str, Dict[str, Any]]) -> None:
        resumen_estados = json.loads((SINTETICO / "resumen_estados_cuenta.json").read_text(encoding="utf-8"))
        reporte = json.loads((dos_corridas[0] / "reporte.json").read_text(encoding="utf-8"))
        for estado in resumen_estados["estados_cuenta"]:
            emisor = estado["emisor"]
            suma = sum((Decimal(f["monto"]) for f in filas.values() if f["emisor"] == emisor), Decimal("0.00"))
            assert str(suma) == estado["total_neto"]
            assert reporte["resumen"]["por_emisor"][emisor]["monto"] == estado["total_neto"]
            assert reporte["resumen"]["por_emisor"][emisor]["total_neto_estado"] == estado["total_neto"]


# --------------------------------------------------------------------- oráculo
def _tasa_cfdi(filas: Mapping[str, Mapping[str, Any]], oraculo: Mapping[str, Any]) -> Tuple[Tasa, List[str]]:
    """Aciertos por tier (o motivo) esperado; en un grupo de empate basta un CFDI del grupo y una biyección."""
    grupos = {g["grupo"]: set(g["cfdis"]) for g in oraculo["grupos_empate"]}
    conteo: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    errores: List[str] = []
    usados: Dict[str, List[str]] = defaultdict(list)
    for esperado in oraculo["cargos"]:
        cid, cfdi, grupo = esperado["cargo_id"], esperado["cfdi"], esperado["grupo_empate"]
        obtenido = filas[cid]["cfdi"]
        clave = cfdi["evidencia"] or f"sin_cruce:{cfdi['motivo_sin_cruce']}"
        uuids = obtenido["uuids"]
        if grupo is None:
            cfdis_ok = sorted(uuids) == sorted(cfdi["esperados"])
        else:
            cfdis_ok = len(uuids) == 1 and uuids[0] in grupos[grupo]
            usados[grupo].extend(uuids)
        acierto = (cfdis_ok and obtenido["tier"] == cfdi["evidencia"]
                   and obtenido["motivo_sin_cruce"] == cfdi["motivo_sin_cruce"]
                   and not set(uuids) & set(cfdi["prohibidos"]))
        conteo[clave][1] += 1
        conteo[clave][0] += int(acierto)
        if not acierto:
            errores.append(f"{cid}: {obtenido} != {cfdi}")
    errores.extend(f"{g}: no biyectivo {sorted(u)}" for g, u in sorted(usados.items())
                   if sorted(u) != sorted(grupos[g]))
    return {k: (v[0], v[1]) for k, v in conteo.items()}, errores


def _desenlace_libro(libro: Mapping[str, Any]) -> str:
    if libro["veredicto"] is not None:
        return f"veredicto:{libro['conflicto'] or 'sin_conflicto'}"
    if libro["esperado"] is None:
        return f"sin_registro:{libro['motivo_sin_cruce']}"
    return "registrado_cubeta" if libro["riesgo_cubeta"] else "registrado"


def _tasa_libro(filas: Mapping[str, Mapping[str, Any]], oraculo: Mapping[str, Any]) -> Tuple[Tasa, List[str]]:
    """Aciertos por desenlace esperado: asiento, riesgo de cubeta y motivo; con veredicto, conflicto y final."""
    grupos = {c: set(g["asientos"]) for g in oraculo["grupos_empate"] for c in g["cargos"]}
    conteo: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    errores: List[str] = []
    for esperado in oraculo["cargos"]:
        cid, libro = esperado["cargo_id"], esperado["libro_mayor"]
        obtenido = filas[cid]["libro_mayor"]
        permitidos: Set[str] = grupos.get(cid, set()) | ({libro["esperado"]} if libro["esperado"] else set())
        propuesta_ok = (obtenido["propuesta_asiento_id"] in permitidos if permitidos
                        else obtenido["propuesta_asiento_id"] is None)
        propuesta_ok = propuesta_ok and obtenido["propuesta_asiento_id"] not in libro["prohibidos"]
        if libro["veredicto"] is not None:
            acierto = (propuesta_ok and obtenido["conflicto"] == libro["conflicto"]
                       and obtenido["origen"] == "veredicto_humano"
                       and obtenido["asiento_id"] == libro["veredicto"]["asiento_id"])
        else:
            acierto = (propuesta_ok and obtenido["asiento_id"] == obtenido["propuesta_asiento_id"]
                       and obtenido["riesgo_cubeta"] == libro["riesgo_cubeta"]
                       and obtenido["motivo_sin_cruce"] == libro["motivo_sin_cruce"]
                       and obtenido["conflicto"] is None)
        clave = _desenlace_libro(libro)
        conteo[clave][1] += 1
        conteo[clave][0] += int(acierto)
        if not acierto:
            errores.append(f"{cid}: {obtenido} != {libro}")
    return {k: (v[0], v[1]) for k, v in conteo.items()}, errores


class TestOraculo:
    def test_cubre_todos_los_cargos_del_oraculo(self, filas: Dict[str, Dict[str, Any]],
                                                oraculo: Dict[str, Any]) -> None:
        assert sorted(filas) == sorted(c["cargo_id"] for c in oraculo["cargos"])

    def test_tasa_de_acierto_por_tier_de_cfdi(self, filas: Dict[str, Dict[str, Any]],
                                             oraculo: Dict[str, Any]) -> None:
        tasa, errores = _tasa_cfdi(filas, oraculo)
        assert set(TIERS) <= set(tasa), tasa
        assert errores == []
        assert {k: ok == total for k, (ok, total) in tasa.items()} == {k: True for k in tasa}, tasa

    def test_tasa_de_acierto_por_desenlace_del_libro(self, filas: Dict[str, Dict[str, Any]],
                                                    oraculo: Dict[str, Any]) -> None:
        tasa, errores = _tasa_libro(filas, oraculo)
        assert {"registrado", "registrado_cubeta", "sin_registro:sin_candidato",
                "veredicto:asiento_distinto"} <= set(tasa), tasa
        assert errores == []
        assert {k: ok == total for k, (ok, total) in tasa.items()} == {k: True for k in tasa}, tasa

    def test_situacion_es_consistente_con_ambos_lados(self, filas: Dict[str, Dict[str, Any]]) -> None:
        for fila in filas.values():
            tiene_cfdi, tiene_asiento = bool(fila["cfdi"]["uuids"]), fila["libro_mayor"]["asiento_id"] is not None
            if fila["revision"]:
                esperada = "en_revision"
            elif fila["estado"] != "ok":
                esperada = "fila_ininterpretable"
            elif fila["tipo_movimiento"] == "pago":
                esperada = "no_aplica"
            elif fila["cfdi"]["tier"] == "monto_sin_afinidad":
                esperada = "cfdi_por_revisar"
            else:
                esperada = {(True, True): "conciliado", (False, True): "falta_cfdi",
                            (True, False): "falta_registro", (False, False): "falta_cfdi_y_registro"}[
                    (tiene_cfdi, tiene_asiento)]
            assert fila["situacion"] == esperada, fila["cargo_id"]

    def test_la_cola_de_revision_es_la_que_sembro_el_generador(self, dos_corridas: Tuple[Path, Path],
                                                              filas: Dict[str, Dict[str, Any]],
                                                              oraculo: Dict[str, Any]) -> None:
        esperado = oraculo["revision_texto_libre"]
        cola = json.loads((dos_corridas[0] / "reporte.json").read_text(encoding="utf-8"))["revision_humana"]["cola"]
        assert sorted({(o["origen"], o["registro_id"], o["campo"]) for o in cola}) == sorted(
            (m["origen"], m["registro_id"], m["campo"]) for m in esperado["marcados"])
        for marcado in esperado["marcados"]:
            assert marcado["familia"] in {o["familia"] for o in cola if o["registro_id"] == marcado["registro_id"]}
        assert sorted(k for k, f in filas.items() if f["situacion"] == "en_revision") == esperado["cargos_en_revision"]

    def test_los_cfdis_sin_afinidad_quedan_por_revisar_y_en_el_reporte(
            self, dos_corridas: Tuple[Path, Path], filas: Dict[str, Dict[str, Any]], oraculo: Dict[str, Any]) -> None:
        esperados = sorted(c["cargo_id"] for c in oraculo["cargos"] if c["cfdi"]["evidencia"] == "monto_sin_afinidad")
        reporte = json.loads((dos_corridas[0] / "reporte.json").read_text(encoding="utf-8"))
        publicados = reporte["cfdi_por_revisar"]
        assert [p["cargo_id"] for p in publicados] == esperados and len(esperados) == 3
        assert {(p["situacion"], p["tier"], p["afinidad_nombre"]) for p in publicados} == {
            ("cfdi_por_revisar", "monto_sin_afinidad", "0.00")}
        assert [p["uuids"] for p in publicados] == [filas[c]["cfdi"]["uuids"] for c in esperados]
        assert reporte["resumen"]["por_situacion"]["cfdi_por_revisar"]["cargos"] == 3
        assert reporte["etapas"]["cruce_cfdi"]["resumen"]["por_revisar"] == 3
        assert not any(filas[c]["situacion"] in {"conciliado", "falta_registro"} for c in esperados)

    def test_el_resumen_publicado_cuadra_con_las_filas(self, dos_corridas: Tuple[Path, Path],
                                                       filas: Dict[str, Dict[str, Any]]) -> None:
        resumen = json.loads((dos_corridas[0] / "reporte.json").read_text(encoding="utf-8"))["resumen"]
        total = sum((Decimal(f["monto"]) for f in filas.values()), Decimal("0.00"))
        assert resumen["total"] == {"cargos": len(filas), "monto": str(total)}
        for tier in TIERS:
            del_tier = [f for f in filas.values() if f["cfdi"]["tier"] == tier]
            assert resumen["cfdi"]["por_tier"][tier] == {
                "cargos": len(del_tier), "monto": str(sum((Decimal(f["monto"]) for f in del_tier), Decimal("0.00")))}
        assert sum(b["cargos"] for b in resumen["por_situacion"].values()) == len(filas)
