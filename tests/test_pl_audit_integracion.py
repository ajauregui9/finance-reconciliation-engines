"""Pruebas de punta a punta del revisor de P&L: muestra, CLI, determinismo y docs."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from test_pl_audit_fixtures import (
    DIR_SCRIPTS,
    DIR_SKILL,
    PERIODO_MUESTRA,
    ROOT,
    RUTA_CONFIG_EJEMPLO,
    RUTA_MUESTRA,
)

import run_pl_audit  # noqa: E402
from auditoria_pl import a_json  # noqa: E402

if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
import sanitize_audit  # noqa: E402

SCRIPT = DIR_SCRIPTS / "run_pl_audit.py"
DOCS = (DIR_SKILL / "README.md", DIR_SKILL / "SKILL.md", DIR_SKILL / "ARCHITECTURE.md",
        DIR_SKILL / "specs" / "auditoria_pl.md")


def leer_json(ruta: Path) -> Dict[str, Any]:
    datos: Dict[str, Any] = json.loads(ruta.read_text(encoding="utf-8"))
    return datos


def correr_cli(*args: str) -> Tuple[int, str, str]:
    salida, errores = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
        codigo = run_pl_audit.main(list(args))
    return codigo, salida.getvalue(), errores.getvalue()


def args_muestra(*extra: str) -> List[str]:
    return ["--periodo", PERIODO_MUESTRA, "--config", str(RUTA_CONFIG_EJEMPLO), "--entrada", str(RUTA_MUESTRA), *extra]


class TestMuestraVersionada(unittest.TestCase):
    codigo: int
    reporte: Dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        codigo, salida, _ = correr_cli(*args_muestra())
        cls.codigo = codigo
        cls.reporte = json.loads(salida)

    def test_sin_bloqueos_y_codigo_cero(self) -> None:
        self.assertEqual(self.codigo, 0)
        self.assertEqual(self.reporte["bloqueos"], [])
        self.assertFalse(self.reporte["provisional"])
        self.assertEqual(self.reporte["madurez"]["dias_tras_cierre"], 6)

    def test_base_de_ingreso_aparta_polizas_manuales(self) -> None:
        base = self.reporte["base_ingreso"]
        self.assertEqual(
            (base["ingreso_rubro"], base["polizas_aisladas"], base["base"]),
            ("2470000.00", "-30000.00", "2500000.00"),
        )

    def test_bandas(self) -> None:
        estados = {b["metrica"]: (b["valor_pct"], b["estado"]) for b in self.reporte["bandas"]}
        self.assertEqual(
            estados,
            {
                "margen_bruto": ("50.00", "dentro"),
                "gasto_venta": ("22.80", "fuera_desfavorable"),
                "gasto_admin": ("14.38", "dentro"),
                "ebitda": ("12.82", "dentro"),
            },
        )

    def test_una_alerta_de_publicidad(self) -> None:
        alertas = self.reporte["publicidad"]["alertas"]
        self.assertEqual(
            [(a["marca"], a["publicidad_pct"], a["exceso_sobre_objetivo"]) for a in alertas],
            [("Marca Norte", "15.00", "84000.00")],
        )
        self.assertEqual(self.reporte["publicidad"]["total_marcas"], self.reporte["publicidad"]["total_cuenta"])

    def test_variaciones(self) -> None:
        variaciones = self.reporte["variaciones"]
        self.assertEqual(variaciones["piso_material"], "25000.00")
        self.assertEqual([m["cuenta"] for m in variaciones["materiales"]], ["6120", "6250"])
        self.assertEqual([m["cuenta"] for m in variaciones["menciones"]], ["5020", "6240"])
        self.assertEqual(
            variaciones["conteos"],
            {"bajo_monto": 5, "bajo_variacion_pct": 5, "materiales": 2, "menciones": 2, "omitidas_por_tope": 0},
        )

    def test_hechos_clave_de_la_muestra(self) -> None:
        # Cuatro hechos clave de la muestra versionada, verificados juntos.
        self.assertEqual(self.reporte["bloqueos"], [])
        self.assertEqual(self.reporte["base_ingreso"]["base"], "2500000.00")
        self.assertEqual(len(self.reporte["publicidad"]["alertas"]), 1)
        self.assertEqual(self.reporte["variaciones"]["materiales"][0]["cuenta"], "6120")


class TestCli(unittest.TestCase):
    def test_periodo_es_obligatorio(self) -> None:
        sin_periodo = ["--config", str(RUTA_CONFIG_EJEMPLO), "--entrada", str(RUTA_MUESTRA)]
        with self.assertRaises(SystemExit) as ctx, contextlib.redirect_stderr(io.StringIO()):
            run_pl_audit.main(sin_periodo)
        self.assertEqual(ctx.exception.code, 2)

    def test_periodo_que_no_coincide(self) -> None:
        codigo, salida, errores = correr_cli("--periodo", "2026-08", *args_muestra()[2:])
        self.assertEqual((codigo, salida), (2, ""))
        self.assertIn("2026-08", errores)

    def test_salida_a_archivo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            destino = Path(tmp) / "sub" / "reporte.json"
            codigo, salida, _ = correr_cli(*args_muestra("--salida", str(destino)))
            self.assertEqual(codigo, 0)
            self.assertEqual(json.loads(salida), {"bloqueos": 0, "materiales": 2, "salida": str(destino)})
            _, directo, _ = correr_cli(*args_muestra())
            self.assertEqual(destino.read_text(encoding="utf-8"), directo)

    def test_bloqueos_devuelven_tres(self) -> None:
        exportacion = leer_json(RUTA_MUESTRA)
        exportacion["fecha_extraccion"] = "2026-10-01"
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "inmaduro.json"
            ruta.write_text(json.dumps(exportacion), encoding="utf-8")
            codigo, salida, _ = correr_cli(
                "--periodo", PERIODO_MUESTRA, "--config", str(RUTA_CONFIG_EJEMPLO), "--entrada", str(ruta)
            )
        self.assertEqual(codigo, 3)
        reporte = json.loads(salida)
        self.assertTrue(reporte["provisional"])
        self.assertEqual([b["codigo"] for b in reporte["bloqueos"]], ["mes_inmaduro"])

    def test_entradas_invalidas_devuelven_dos(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            roto = Path(tmp) / "roto.json"
            roto.write_text("{no es json", encoding="utf-8")
            config_mala = Path(tmp) / "config.json"
            config = leer_json(RUTA_CONFIG_EJEMPLO)
            config["llave_sin_efecto"] = True
            config_mala.write_text(json.dumps(config), encoding="utf-8")
            repetida = Path(tmp) / "repetida.json"
            repetida.write_text(
                RUTA_MUESTRA.read_text(encoding="utf-8").replace(
                    '"periodo": "2026-09",', '"periodo": "2026-08", "periodo": "2026-09",'
                ),
                encoding="utf-8",
            )
            casos = {
                "llave repetida": ["--entrada", str(repetida), "--config", str(RUTA_CONFIG_EJEMPLO)],
                "json roto": ["--entrada", str(roto), "--config", str(RUTA_CONFIG_EJEMPLO)],
                "archivo ausente": [
                    "--entrada",
                    str(Path(tmp) / "no_existe.json"),
                    "--config",
                    str(RUTA_CONFIG_EJEMPLO),
                ],
                "config con llave desconocida": ["--entrada", str(RUTA_MUESTRA), "--config", str(config_mala)],
            }
            for nombre, args in casos.items():
                with self.subTest(caso=nombre):
                    codigo, salida, errores = correr_cli("--periodo", PERIODO_MUESTRA, *args)
                    self.assertEqual((codigo, salida), (2, ""))
                    self.assertTrue(errores.strip())

    def test_salida_que_no_se_puede_escribir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archivo = Path(tmp) / "archivo"
            archivo.write_text("x", encoding="utf-8")
            codigo, salida, errores = correr_cli(*args_muestra("--salida", str(archivo / "reporte.json")))
        self.assertEqual((codigo, salida), (2, ""))
        self.assertIn("Error al escribir", errores)

    def test_serializador_rechaza_tipos_desconocidos(self) -> None:
        with self.assertRaises(TypeError):
            a_json({"conjunto": {1, 2}})

    def test_script_como_proceso(self) -> None:
        resultado = subprocess.run(
            [sys.executable, str(SCRIPT), *args_muestra()], capture_output=True, text=True, check=False, cwd=str(ROOT)
        )
        self.assertEqual(resultado.returncode, 0, resultado.stderr)
        self.assertEqual(json.loads(resultado.stdout)["periodo"], PERIODO_MUESTRA)


class TestDeterminismo(unittest.TestCase):
    def test_dos_corridas_dan_el_mismo_sha256(self) -> None:
        huellas = set()
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(2):
                destino = Path(tmp) / f"r{i}.json"
                correr_cli(*args_muestra("--salida", str(destino)))
                huellas.add(hashlib.sha256(destino.read_bytes()).hexdigest())
        self.assertEqual(len(huellas), 1)

    def test_orden_de_la_entrada_no_cambia_el_reporte(self) -> None:
        exportacion = leer_json(RUTA_MUESTRA)
        invertida = copy.deepcopy(exportacion)
        for lista in ("cuentas", "marcas", "provisiones"):
            invertida[lista] = list(reversed(invertida[lista]))
        with tempfile.TemporaryDirectory() as tmp:
            ruta = Path(tmp) / "invertida.json"
            ruta.write_text(json.dumps(invertida), encoding="utf-8")
            _, normal, _ = correr_cli(*args_muestra())
            _, al_reves, _ = correr_cli(
                "--periodo", PERIODO_MUESTRA, "--config", str(RUTA_CONFIG_EJEMPLO), "--entrada", str(ruta)
            )
        self.assertEqual(normal, al_reves)

    def test_salida_canonica(self) -> None:
        _, salida, _ = correr_cli(*args_muestra())
        self.assertTrue(salida.endswith("}\n"))
        self.assertEqual(salida, json.dumps(json.loads(salida), indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _rutas_hoja(nodo: Any, prefijo: str = "") -> Set[str]:
    if not isinstance(nodo, dict):
        return {prefijo}
    rutas: Set[str] = set()
    for llave, valor in nodo.items():
        nombre = "<metric>" if prefijo == "bandas" else llave
        rutas |= _rutas_hoja(valor, f"{prefijo}.{nombre}" if prefijo else nombre)
    return rutas


def _seccion(texto: str, titulo: str) -> str:
    inicio = texto.index(titulo)
    fin = texto.find("\n## ", inicio + len(titulo))
    return texto[inicio : fin if fin != -1 else len(texto)]


class TestDocumentacionHonesta(unittest.TestCase):
    def test_docs_mencionan_solo_banderas_existentes(self) -> None:
        parser = run_pl_audit.construir_parser()
        existentes = {s for accion in parser._actions for s in accion.option_strings if s.startswith("--")}
        existentes.discard("--help")
        for ruta in DOCS:
            with self.subTest(doc=ruta.name):
                mencionadas = set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", ruta.read_text(encoding="utf-8")))
                self.assertLessEqual(mencionadas, existentes)
        readme = DOCS[0].read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", readme)), existentes)

    def test_readme_documenta_exactamente_las_llaves_de_la_config(self) -> None:
        config = leer_json(RUTA_CONFIG_EJEMPLO)
        seccion = _seccion(DOCS[0].read_text(encoding="utf-8"), "## Configuration")
        documentadas = set(re.findall(r"^\| `([a-z_<>.]+)` \|", seccion, flags=re.MULTILINE))
        self.assertEqual(documentadas, _rutas_hoja(config))

    def test_config_de_ejemplo_declara_las_cuatro_bandas(self) -> None:
        self.assertEqual(
            sorted(leer_json(RUTA_CONFIG_EJEMPLO)["bandas"]), ["ebitda", "gasto_admin", "gasto_venta", "margen_bruto"]
        )

    def test_estacionalidad_queda_como_limite_declarado(self) -> None:
        readme = DOCS[0].read_text(encoding="utf-8")
        self.assertIn("seasonal", _seccion(readme, "## Known limitations").lower())
        self.assertIn("Estacionalidad", _seccion(DOCS[3].read_text(encoding="utf-8"), "## 6. Límites declarados"))

    def test_codigo_sin_periodo_fijo(self) -> None:
        for ruta in sorted(DIR_SCRIPTS.rglob("*.py")):
            with self.subTest(archivo=ruta.name):
                self.assertIsNone(re.search(r"\b(?:19|20)\d{2}-\d{2}\b", ruta.read_text(encoding="utf-8")))

    def test_sanitizer_sin_hallazgos(self) -> None:
        reglas, _ = sanitize_audit.load_custom_rules(None)
        rutas = [p for p in sorted(DIR_SKILL.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
        rutas += [RUTA_MUESTRA, *sorted((ROOT / "tests").glob("test_pl_audit_*.py"))]
        alertas = [(r.name, a) for r in rutas for a in sanitize_audit.audit_file(str(r), reglas)]
        self.assertEqual(alertas, [])


if __name__ == "__main__":
    unittest.main()
