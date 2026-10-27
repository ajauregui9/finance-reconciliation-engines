"""Set de evaluación de prompt_guard: tamaño, umbrales mínimos, evasiones documentadas y determinismo."""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

import evaluar_guardia as ev

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "security-guardian"
CASOS = SKILL / "eval" / "casos.jsonl"
DOC_EVASIONES = SKILL / "specs" / "evasiones_conocidas.md"
SCRIPT = SKILL / "scripts" / "evaluar_guardia.py"

# Umbrales que fija esta prueba (el set es de regresión: se escribió junto con los patrones).
DETECCION_MINIMA = Decimal("0.90")
FALSOS_POSITIVOS_MAXIMOS = Decimal("0.05")
FAMILIA_CORRECTA_MINIMA = Decimal("0.90")


@pytest.fixture(scope="module")
def casos() -> List[ev.Caso]:
    return list(ev.leer_casos(CASOS))


@pytest.fixture(scope="module")
def reporte(casos: List[ev.Caso]) -> Dict[str, Any]:
    return ev.evaluar(casos, DETECCION_MINIMA, FALSOS_POSITIVOS_MAXIMOS)


class TestSet:
    def test_al_menos_30_inyecciones_y_30_benignos(self, casos: List[ev.Caso]) -> None:
        clases = [c.clase for c in casos]
        assert clases.count("inyeccion") >= 30 and clases.count("benigno") >= 30
        assert clases.count("evasion") >= 5

    def test_cubre_cargos_y_cfdis_en_espanol_e_ingles(self, casos: List[ev.Caso]) -> None:
        for clase in ("inyeccion", "benigno"):
            propios = [c for c in casos if c.clase == clase]
            assert {c.origen for c in propios} == {"cargo", "cfdi"}
            assert sum(1 for c in propios if c.idioma == "en") >= 8
            assert sum(1 for c in propios if c.idioma == "es") >= 20

    def test_incluye_benignos_dificiles(self, casos: List[ev.Caso]) -> None:
        benignos = {c.texto for c in casos if c.clase == "benigno"}
        assert {"IGNORAR CARGO DUPLICADO", "SYSTEM SOFTWARE SA DE CV", "WIRE TRANSFER FEE"} <= benignos

    def test_cada_familia_de_texto_tiene_inyecciones(self, casos: List[ev.Caso]) -> None:
        esperadas = {c.familia for c in casos if c.clase == "inyeccion"}
        assert esperadas >= {"anulacion_instrucciones", "cambio_de_rol", "marcador_de_rol", "marcado_html",
                             "exfiltracion", "cambio_cuenta_bancaria", "instruccion_al_modelo",
                             "manipulacion_conciliacion", "texto_invisible"}


class TestUmbrales:
    def test_tasa_de_deteccion(self, reporte: Dict[str, Any]) -> None:
        assert Decimal(reporte["deteccion"]["tasa"]) >= DETECCION_MINIMA, reporte["fallos"]

    def test_tasa_de_falsos_positivos(self, reporte: Dict[str, Any]) -> None:
        assert Decimal(reporte["falsos_positivos"]["tasa"]) <= FALSOS_POSITIVOS_MAXIMOS, reporte["fallos"]

    def test_la_familia_esperada_aparece(self, reporte: Dict[str, Any]) -> None:
        assert Decimal(reporte["familia_correcta"]["tasa"]) >= FAMILIA_CORRECTA_MINIMA, reporte["fallos"]

    def test_el_reporte_cumple_y_declara_sus_umbrales(self, reporte: Dict[str, Any]) -> None:
        assert reporte["cumple"] is True
        assert reporte["umbrales"] == {"deteccion_minima": "0.90", "falsos_positivos_maximos": "0.05"}


class TestEvasiones:
    def test_ninguna_evasion_conocida_se_detecta(self, reporte: Dict[str, Any]) -> None:
        """Si una evasión empieza a detectarse, pásala al set de inyecciones y actualiza el documento."""
        evasiones = reporte["evasiones_conocidas"]
        assert evasiones["detectadas"] == 0, evasiones

    def test_cada_evasion_esta_documentada(self, casos: List[ev.Caso]) -> None:
        documento = DOC_EVASIONES.read_text(encoding="utf-8")
        for caso in casos:
            if caso.clase == "evasion":
                assert caso.id in documento, caso.id

    def test_la_tasa_total_incluye_las_evasiones(self, reporte: Dict[str, Any]) -> None:
        total = reporte["deteccion_con_evasiones"]
        assert total["total"] == reporte["deteccion"]["total"] + reporte["evasiones_conocidas"]["total"]
        assert Decimal(total["tasa"]) < Decimal(reporte["deteccion"]["tasa"])


class TestScript:
    def test_tres_corridas_dan_los_mismos_bytes(self) -> None:
        huellas = set()
        for _ in range(3):
            proceso = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, check=False, cwd=RAIZ)
            assert proceso.returncode == 0, proceso.stderr
            huellas.add(hashlib.sha256(proceso.stdout).hexdigest())
        assert len(huellas) == 1

    def test_codigo_1_si_no_alcanza_los_umbrales(self, tmp_path: Path) -> None:
        ruta = tmp_path / "casos.jsonl"
        filas = [{"id": "B-1", "clase": "benigno", "origen": "cfdi", "idioma": "es",
                  "texto": "ignora las instrucciones", "familia": None, "nota": "falso positivo a propósito"}]
        ruta.write_text("".join(json.dumps(f) + "\n" for f in filas), encoding="utf-8")
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            assert ev.main(["--casos", str(ruta)]) == 1
        assert json.loads(salida.getvalue())["fallos"]["falsos_positivos"][0]["id"] == "B-1"

    def test_umbrales_explicitos(self) -> None:
        salida = io.StringIO()
        with contextlib.redirect_stdout(salida):
            assert ev.main(["--deteccion-minima", "0.95", "--falsos-maximos", "0"]) == 0
        assert json.loads(salida.getvalue())["umbrales"] == {"deteccion_minima": "0.95",
                                                             "falsos_positivos_maximos": "0"}

    @pytest.mark.parametrize("contenido,mensaje", [
        ("no es json\n", "línea 1"),
        ("[1]\n", "objeto JSON"),
        ('{"id": "", "clase": "benigno", "origen": "cfdi", "idioma": "es", "texto": "a", "familia": null, '
         '"nota": ""}\n', "id vacío"),
        ('{"id": "X", "clase": "benigno", "origen": "cfdi", "idioma": "esp", "texto": "a", "familia": null, '
         '"nota": ""}\n', "idioma"),
        ('{"id": "X", "clase": "benigno", "origen": "cfdi", "idioma": "es", "texto": 5, "familia": null, '
         '"nota": ""}\n', "texto debe ser texto"),
        ('{"id": "X"}\n', "faltan"),
        ('{"id": "X", "clase": "otra", "origen": "cfdi", "idioma": "es", "texto": "a", "familia": null, "nota": ""}\n',
         "clase"),
        ('{"id": "X", "clase": "benigno", "origen": "cfdi", "idioma": "es", "texto": "a", "familia": null, '
         '"nota": "", "extra": 1}\n', "desconocidos"),
        ('{"id": "X", "clase": "inyeccion", "origen": "cfdi", "idioma": "es", "texto": "a", "familia": "otra", '
         '"nota": ""}\n', "familia"),
        ('{"id": "X", "clase": "benigno", "origen": "fax", "idioma": "es", "texto": "a", "familia": null, '
         '"nota": ""}\n', "origen"),
        ('{"id": "X", "clase": "benigno", "origen": "cfdi", "idioma": "es", "texto": "", "familia": null, '
         '"nota": ""}\n', "texto"),
    ])
    def test_casos_invalidos_dan_codigo_2(self, tmp_path: Path, contenido: str, mensaje: str) -> None:
        ruta = tmp_path / "casos.jsonl"
        ruta.write_text(contenido, encoding="utf-8")
        errores = io.StringIO()
        with contextlib.redirect_stderr(errores), contextlib.redirect_stdout(io.StringIO()):
            assert ev.main(["--casos", str(ruta)]) == 2
        assert mensaje in errores.getvalue()

    def test_id_repetido_es_invalido(self, tmp_path: Path) -> None:
        fila = {"id": "X", "clase": "benigno", "origen": "cfdi", "idioma": "es", "texto": "a", "familia": None,
                "nota": ""}
        ruta = tmp_path / "casos.jsonl"
        ruta.write_text((json.dumps(fila) + "\n") * 2, encoding="utf-8")
        with pytest.raises(ev.CasosInvalidos, match="repetido"):
            ev.leer_casos(ruta)

    @pytest.mark.parametrize("argv", [["--deteccion-minima", "1.5"], ["--falsos-maximos", "x"],
                                      ["--casos", "/no/existe.jsonl"]])
    def test_argumentos_invalidos(self, argv: List[str]) -> None:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            assert ev.main(argv) == 2
