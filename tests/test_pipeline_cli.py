"""CLI del pipeline de tarjetas: códigos de salida 0/2/3, universo parcial y limpieza de la salida."""
from __future__ import annotations

import contextlib
import csv
import io
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import pytest

from conciliacion import pipeline
from conciliacion import pipeline_etapas as etapas
from conciliacion.cruce_cfdi_invariantes import Invariante

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
SINTETICO = RAIZ / "examples" / "synthetic"
INSUMOS = ("resumen_estados_cuenta.json", "estado_cuenta_alfa.csv", "estado_cuenta_beta.csv",
           "cfdis.jsonl", "libro_mayor.csv", "veredictos_libro.csv")
PRINCIPALES = ("reporte.json", "cargos.jsonl")


def copiar_datos(destino: Path) -> Path:
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in INSUMOS:
        shutil.copyfile(SINTETICO / nombre, destino / nombre)
    return destino


def correr(argv: Sequence[str]) -> Tuple[int, str, str]:
    salida, errores = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
        codigo = pipeline.main(list(argv))
    return codigo, salida.getvalue(), errores.getvalue()


def argv(datos: Path, salida: Path, *extra: str) -> List[str]:
    return ["--datos", str(datos), "--salida", str(salida), *extra]


def leer_json(ruta: Path) -> Dict[str, Any]:
    return json.loads(ruta.read_text(encoding="utf-8"))


def leer_filas(ruta: Path) -> List[Dict[str, Any]]:
    return [json.loads(linea) for linea in ruta.read_text(encoding="utf-8").splitlines()]


def archivos(carpeta: Path) -> List[str]:
    if not carpeta.exists():
        return []
    return sorted(str(p.relative_to(carpeta)) for p in carpeta.rglob("*") if p.is_file())


def editar_resumen(carpeta: Path, emisor: str, **campos: object) -> None:
    ruta = carpeta / "resumen_estados_cuenta.json"
    datos = leer_json(ruta)
    estados = [{**e, **campos} if e["emisor"] == emisor else e for e in datos["estados_cuenta"]]
    ruta.write_text(json.dumps({**datos, "estados_cuenta": estados}), encoding="utf-8")


def reescribir_csv(ruta: Path, transformar: Any) -> None:
    with ruta.open(encoding="utf-8", newline="") as archivo:
        filas = list(csv.reader(archivo))
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        csv.writer(archivo, lineterminator="\n").writerows(transformar(filas))


@pytest.fixture(scope="module")
def corrida_completa(tmp_path_factory: pytest.TempPathFactory) -> Path:
    salida = tmp_path_factory.mktemp("completa")
    codigo, _, errores = correr(argv(SINTETICO, salida))
    assert codigo == 0, errores
    return salida


# ------------------------------------------------------------------ código 0
class TestCorridaCompleta:
    def test_escribe_reporte_filas_y_etapas(self, corrida_completa: Path) -> None:
        assert archivos(corrida_completa) == [
            "cargos.jsonl", "etapas/cruce_cfdi.json", "etapas/cruce_libro.json",
            "etapas/universo.control.json", "etapas/universo.jsonl", "reporte.json"]

    def test_reporte_no_provisional_y_candados_en_verde(self, corrida_completa: Path) -> None:
        reporte = leer_json(corrida_completa / "reporte.json")
        assert reporte["esquema"] == "pipeline_tarjetas/v1"
        assert reporte["provisional"] is False and reporte["motivos_provisional"] == []
        assert [c for c in reporte["candados"] if not c["cumple"]] == []
        etapas_vistas = [c["etapa"] for c in reporte["candados"]]
        orden = ["universo", "revision_texto_libre", "cruce_cfdi", "cruce_libro", "pipeline"]
        assert sorted(set(etapas_vistas), key=orden.index) == orden
        assert etapas_vistas == sorted(etapas_vistas, key=orden.index)

    def test_cada_fila_resume_cfdi_tier_libro_y_motivo(self, corrida_completa: Path) -> None:
        filas = leer_filas(corrida_completa / "cargos.jsonl")
        assert len(filas) == 199
        assert [f["cargo_id"] for f in filas] == sorted(f["cargo_id"] for f in filas)
        for fila in filas:
            assert set(fila) == {"cargo_id", "emisor", "fecha", "descripcion", "monto", "moneda",
                                 "tipo_movimiento", "estado", "motivo_fila", "situacion", "provisional",
                                 "cfdi", "libro_mayor", "revision"}
            assert set(fila["cfdi"]) == {"uuids", "tier", "motivo_sin_cruce", "diferencia",
                                         "moneda_diferencia", "delta_dias", "afinidad_nombre"}
            assert (fila["cfdi"]["afinidad_nombre"] is None) == (fila["cfdi"]["tier"] is None)
            assert set(fila["libro_mayor"]) == {"asiento_id", "origen", "riesgo_cubeta", "motivo_sin_cruce",
                                                "propuesta_asiento_id", "conflicto", "veredicto"}
            assert fila["provisional"] is False and isinstance(fila["revision"], list)
            assert isinstance(fila["monto"], str)
        en_revision = [f["cargo_id"] for f in filas if f["revision"]]
        assert en_revision == [f["cargo_id"] for f in filas if f["situacion"] == "en_revision"]
        assert len(en_revision) == 2

    def test_modulo_corre_desde_la_carpeta_de_la_skill(self, tmp_path: Path) -> None:
        proceso = subprocess.run(
            [sys.executable, "-m", "conciliacion.pipeline", "--datos", str(SINTETICO), "--salida", str(tmp_path)],
            cwd=SKILL, capture_output=True, text=True, check=False)
        assert proceso.returncode == 0, proceso.stderr
        assert "199 cargos" in proceso.stdout
        assert (tmp_path / "reporte.json").is_file()

    def test_acepta_las_configs_de_ejemplo(self, tmp_path: Path, corrida_completa: Path) -> None:
        config = SKILL / "config"
        codigo, _, errores = correr(argv(SINTETICO, tmp_path, "--config-cfdi", str(config / "cruce_cfdi.example.json"),
                                         "--config-libro", str(config / "cruce_libro.example.json")))
        assert codigo == 0, errores
        assert (tmp_path / "cargos.jsonl").read_bytes() == (corrida_completa / "cargos.jsonl").read_bytes()
        insumos = leer_json(tmp_path / "reporte.json")["insumos"]
        assert insumos["config_cfdi"]["archivo"] == "cruce_cfdi.example.json"
        assert insumos["config_libro"]["archivo"] == "cruce_libro.example.json"
        assert leer_json(corrida_completa / "reporte.json")["insumos"]["config_cfdi"] == {
            "archivo": None, "sha256": None}


# ------------------------------------------------------------------ código 2
class TestInsumoInvalido:
    def test_falta_el_pool_de_cfdis(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        (datos / "cfdis.jsonl").unlink()
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert codigo == 2
        assert errores.startswith("cruce_cfdi:") and "cfdis.jsonl" in errores
        assert archivos(tmp_path / "salida") == []

    def test_falta_el_libro_mayor(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        (datos / "libro_mayor.csv").unlink()
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert (codigo, errores.split(":")[0]) == (2, "cruce_libro")

    def test_faltan_veredictos_sin_declararlo(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        (datos / "veredictos_libro.csv").unlink()
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert codigo == 2
        assert "veredictos_libro.csv" in errores and "--sin-veredictos" in errores

    def test_estado_de_cuenta_faltante_sin_declarar(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        (datos / "estado_cuenta_beta.csv").unlink()
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert (codigo, errores.split(":")[0]) == (2, "universo")

    def test_declarar_ausente_un_emisor_desconocido(self, tmp_path: Path) -> None:
        codigo, _, errores = correr(argv(SINTETICO, tmp_path, "--sin-estado", "GAMMA"))
        assert (codigo, errores.split(":")[0]) == (2, "universo")

    def test_argumento_desconocido(self, tmp_path: Path) -> None:
        codigo, _, errores = correr(argv(SINTETICO, tmp_path, "--modo-magico"))
        assert codigo == 2 and "argumentos" in errores

    def test_falta_la_carpeta_de_datos(self, tmp_path: Path) -> None:
        codigo, _, _ = correr(["--salida", str(tmp_path)])
        assert codigo == 2

    def test_la_salida_no_puede_ser_la_carpeta_de_datos(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        codigo, _, errores = correr(argv(datos, datos))
        assert (codigo, errores.split(":")[0]) == (2, "pipeline")
        assert sorted(p.name for p in datos.iterdir()) == sorted(INSUMOS)

    def test_la_salida_no_puede_ser_un_archivo(self, tmp_path: Path) -> None:
        archivo = tmp_path / "ocupado.txt"
        archivo.write_text("x", encoding="utf-8")
        codigo, _, _ = correr(argv(SINTETICO, archivo))
        assert codigo == 2 and archivo.read_text(encoding="utf-8") == "x"

    def test_no_se_puede_escribir_la_salida(self, tmp_path: Path) -> None:
        # `etapas` ocupado por un archivo: ni se pueden borrar ni escribir los artefactos de esa carpeta.
        (tmp_path / "etapas").write_text("ocupado", encoding="utf-8")
        codigo, _, errores = correr(argv(SINTETICO, tmp_path))
        assert codigo == 2 and errores.startswith("pipeline: no se pudo escribir")
        assert not (tmp_path / "reporte.json").exists()

    def test_config_de_cfdi_invalida(self, tmp_path: Path) -> None:
        config = tmp_path / "cfdi.json"
        config.write_text(json.dumps({"esquema": "cruce_cfdi_config/v1", "llave_rara": 1}), encoding="utf-8")
        codigo, _, errores = correr(argv(SINTETICO, tmp_path / "salida", "--config-cfdi", str(config)))
        assert (codigo, errores.split(":")[0]) == (2, "cruce_cfdi")

    def test_config_de_libro_invalida(self, tmp_path: Path) -> None:
        config = tmp_path / "libro.json"
        config.write_text(json.dumps({"esquema": "cruce_libro_config/v1", "tolerancia_monto": 1.5}),
                          encoding="utf-8")
        codigo, _, errores = correr(argv(SINTETICO, tmp_path / "salida", "--config-libro", str(config)))
        assert (codigo, errores.split(":")[0]) == (2, "cruce_libro")

    def test_veredicto_de_un_cargo_inexistente_en_un_estado_leido(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        reescribir_csv(datos / "veredictos_libro.csv",
                       lambda filas: filas + [["ALFA-0999", "no_registrado", "", "x"]])
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert codigo == 2 and "ALFA-0999" in errores

    def test_un_motor_que_rechaza_el_universo_certificado_es_insumo_invalido(self, tmp_path: Path) -> None:
        # Una fila con importe cero cuadra en los totales del universo, pero no tiene tipo de
        # movimiento y la frontera del cruce con CFDI la rechaza: el pipeline lo reporta, no lo esconde.
        datos = copiar_datos(tmp_path / "datos")
        reescribir_csv(datos / "estado_cuenta_alfa.csv", lambda filas: filas + [
            ["15/07/2026", "15/07/2026", "COMERCIO EN CERO", "ANA DEMO", "****1001", "MXN", "0.00", "", "0.00"]])
        resumen = leer_json(datos / "resumen_estados_cuenta.json")
        alfa = next(e for e in resumen["estados_cuenta"] if e["emisor"] == "ALFA")
        editar_resumen(datos, "ALFA", num_movimientos=alfa["num_movimientos"] + 1)
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert (codigo, errores.split(":")[0]) == (2, "cruce_cfdi")
        assert "ALFA-0095" in errores or "tipo_movimiento" in errores
        assert archivos(tmp_path / "salida") == []


# ------------------------------------------------------------------ código 3
class TestCandadoBloquea:
    def test_totales_de_control_del_universo(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        editar_resumen(datos, "ALFA", total_neto="1.00")
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert codigo == 3 and errores.startswith("universo:")
        assert archivos(tmp_path / "salida") == ["bloqueo.json"]
        bloqueo = leer_json(tmp_path / "salida" / "bloqueo.json")
        assert bloqueo["esquema"] == "pipeline_tarjetas_bloqueo/v1"
        assert bloqueo["etapa"] == "universo"
        assert bloqueo["fallidos"] == ["ALFA.total_neto"]
        assert {c["etapa"] for c in bloqueo["candados"]} == {"universo"}

    def test_partida_doble_del_libro(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")

        def descuadrar(filas: List[List[str]]) -> List[List[str]]:
            encabezado, primera, resto = filas[0], filas[1], filas[2:]
            columna = encabezado.index("debe") if Decimal(primera[encabezado.index("debe")]) > 0 \
                else encabezado.index("haber")
            nueva = list(primera)
            nueva[columna] = str(Decimal(primera[columna]) + Decimal("1.00"))
            return [encabezado, nueva, *resto]

        reescribir_csv(datos / "libro_mayor.csv", descuadrar)
        codigo, _, errores = correr(argv(datos, tmp_path / "salida"))
        assert codigo == 3 and errores.startswith("cruce_libro:")
        bloqueo = leer_json(tmp_path / "salida" / "bloqueo.json")
        assert (bloqueo["etapa"], bloqueo["fallidos"]) == ("cruce_libro", ["partida_doble"])

    def test_dos_veredictos_citan_el_mismo_asiento(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        reescribir_csv(datos / "veredictos_libro.csv",
                       lambda filas: filas[:1] + [["ALFA-0001", "registrado", "AS-0081", "x"]] + filas[1:])
        codigo, _, _ = correr(argv(datos, tmp_path / "salida"))
        assert codigo == 3
        bloqueo = leer_json(tmp_path / "salida" / "bloqueo.json")
        assert (bloqueo["etapa"], bloqueo["fallidos"]) == ("cruce_libro", ["exclusividad"])

    def test_invariante_del_cruce_con_cfdi(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        def falla(*_: object) -> Tuple[Invariante, ...]:
            return (Invariante("exclusividad", False, "1 casos: X asignado a A, B"),)

        monkeypatch.setattr(etapas, "verificar_invariantes", falla)
        codigo, _, errores = correr(argv(SINTETICO, tmp_path))
        assert codigo == 3 and errores.startswith("cruce_cfdi:")
        bloqueo = leer_json(tmp_path / "bloqueo.json")
        assert (bloqueo["etapa"], bloqueo["fallidos"]) == ("cruce_cfdi", ["exclusividad"])

    def test_un_bloqueo_borra_el_reporte_de_una_corrida_anterior(self, tmp_path: Path) -> None:
        salida = tmp_path / "salida"
        assert correr(argv(SINTETICO, salida))[0] == 0
        (salida / "notas_propias.txt").write_text("no es del pipeline", encoding="utf-8")
        datos = copiar_datos(tmp_path / "datos")
        editar_resumen(datos, "BETA", saldo_al_corte="0.00")
        assert correr(argv(datos, salida))[0] == 3
        assert archivos(salida) == ["bloqueo.json", "notas_propias.txt"]
        assert correr(argv(SINTETICO, salida))[0] == 0
        assert "bloqueo.json" not in archivos(salida) and "notas_propias.txt" in archivos(salida)

    def test_un_insumo_invalido_tambien_borra_la_corrida_anterior(self, tmp_path: Path) -> None:
        salida = tmp_path / "salida"
        assert correr(argv(SINTETICO, salida))[0] == 0
        datos = copiar_datos(tmp_path / "datos")
        (datos / "cfdis.jsonl").unlink()
        assert correr(argv(datos, salida))[0] == 2
        assert archivos(salida) == []


# ------------------------------------------------------------ universo parcial
class TestUniversoParcial:
    def test_estado_omitido_marca_el_reporte_provisional(self, tmp_path: Path) -> None:
        codigo, salida, errores = correr(argv(SINTETICO, tmp_path, "--sin-estado", "BETA"))
        assert codigo == 0, errores
        assert "PROVISIONAL" in salida
        reporte = leer_json(tmp_path / "reporte.json")
        assert reporte["provisional"] is True
        motivos = [(m["etapa"], m["motivo"]) for m in reporte["motivos_provisional"]]
        assert motivos == [("universo", "estado_omitido"), ("cruce_libro", "veredictos_en_espera")]
        assert "BETA" in reporte["motivos_provisional"][0]["detalle"]
        assert [c for c in reporte["candados"] if not c["cumple"]] == []
        assert reporte["etapas"]["universo"]["estados_omitidos"] == ["BETA"]
        assert leer_json(tmp_path / "etapas" / "universo.control.json")["provisional"] is True

    def test_las_filas_de_un_reporte_provisional_lo_dicen(self, tmp_path: Path) -> None:
        assert correr(argv(SINTETICO, tmp_path, "--sin-estado", "BETA"))[0] == 0
        filas = leer_filas(tmp_path / "cargos.jsonl")
        assert filas and {f["emisor"] for f in filas} == {"ALFA"}
        assert all(f["provisional"] is True for f in filas)

    def test_veredictos_de_estados_omitidos_quedan_en_espera(self, tmp_path: Path) -> None:
        assert correr(argv(SINTETICO, tmp_path, "--sin-estado", "BETA"))[0] == 0
        reporte = leer_json(tmp_path / "reporte.json")
        with (SINTETICO / "veredictos_libro.csv").open(encoding="utf-8", newline="") as archivo:
            todos = list(csv.DictReader(archivo))
        de_beta = [{"cargo_id": v["cargo_id"], "veredicto": v["veredicto"], "asiento_id": v["asiento_id"] or None}
                   for v in todos if v["cargo_id"].startswith("BETA-")]
        assert de_beta and reporte["veredictos_en_espera"] == de_beta
        aplicados = {f["cargo_id"] for f in leer_filas(tmp_path / "cargos.jsonl")
                     if f["libro_mayor"]["veredicto"] is not None}
        assert aplicados == {v["cargo_id"] for v in todos if v["cargo_id"].startswith("ALFA-")}
        assert reporte["insumos"]["veredictos"]["en_espera"] == len(de_beta)

    def test_sin_veredictos_declarado(self, tmp_path: Path) -> None:
        datos = copiar_datos(tmp_path / "datos")
        (datos / "veredictos_libro.csv").unlink()
        codigo, _, errores = correr(argv(datos, tmp_path / "salida", "--sin-veredictos"))
        assert codigo == 0, errores
        reporte = leer_json(tmp_path / "salida" / "reporte.json")
        assert reporte["provisional"] is True
        assert [m["motivo"] for m in reporte["motivos_provisional"]] == ["veredictos_omitidos"]
        assert reporte["insumos"]["veredictos"] is None
        filas = leer_filas(tmp_path / "salida" / "cargos.jsonl")
        assert {f["libro_mayor"]["origen"] for f in filas} == {"motor"}
