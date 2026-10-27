"""Controles que no dependen del texto y cómo se describen.

- Ningún módulo parsea XML sin defusedxml, sin lector alternativo ni uso directo de lxml.
- defusedxml es dependencia obligatoria: si falta, esta prueba falla (no se salta).
- La documentación del guard dice "cuarentena + revisión humana".
"""
from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path
from typing import Iterator, List, Tuple

RAIZ = Path(__file__).resolve().parents[1]
CODIGO = ("skills", "examples", "tools")
PROHIBIDOS = ("xml", "lxml", "html5lib", "bs4")
GUARDIA = RAIZ / "skills" / "security-guardian"
ESPEC_PIPELINE = RAIZ / "skills" / "credit-card-reconciliation" / "specs" / "pipeline.md"
FRASES_PROHIBIDAS = re.compile(r"frontera\s+dura|hard[\s-]+boundar(?:y|ies)", re.IGNORECASE)


def modulos_python() -> Iterator[Path]:
    for carpeta in CODIGO:
        yield from sorted((RAIZ / carpeta).rglob("*.py"))


def importaciones(ruta: Path) -> List[Tuple[int, str]]:
    """(línea, módulo) de cada import y de cada `importlib.import_module("<literal>")`."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    vistas: List[Tuple[int, str]] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            vistas.extend((nodo.lineno, alias.name) for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            vistas.append((nodo.lineno, nodo.module))
        elif (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute)
              and nodo.func.attr == "import_module" and nodo.args
              and isinstance(nodo.args[0], ast.Constant) and isinstance(nodo.args[0].value, str)):
            vistas.append((nodo.lineno, nodo.args[0].value))
    return vistas


class TestXml:
    def test_ningun_modulo_importa_un_parser_xml_inseguro(self) -> None:
        hallados = [f"{ruta.relative_to(RAIZ)}:{linea}: {modulo}"
                    for ruta in modulos_python() for linea, modulo in importaciones(ruta)
                    if modulo.split(".")[0] in PROHIBIDOS]
        assert hallados == []

    def test_el_lector_de_cfdi_en_xml_usa_defusedxml_y_falla_cerrado(self) -> None:
        lector = RAIZ / "skills" / "credit-card-reconciliation" / "conciliacion" / "cruce_cfdi_xml.py"
        modulos = {m for _, m in importaciones(lector)}
        assert {"defusedxml", "defusedxml.ElementTree"} <= modulos
        texto = lector.read_text(encoding="utf-8")
        assert "DependenciaFaltante" in texto and "except ImportError" in texto

    def test_solo_el_lector_de_cfdi_toca_xml(self) -> None:
        usan = sorted(str(r.relative_to(RAIZ)) for r in modulos_python()
                      if any(m.startswith("defusedxml") for _, m in importaciones(r)))
        assert usan == ["skills/credit-card-reconciliation/conciliacion/cruce_cfdi_xml.py"]

    def test_defusedxml_es_dependencia_obligatoria_e_instalada(self) -> None:
        assert re.search(r"^defusedxml>=", (RAIZ / "requirements.txt").read_text(encoding="utf-8"), re.MULTILINE)
        proyecto = (RAIZ / "pyproject.toml").read_text(encoding="utf-8")
        dependencias = proyecto.split("dependencies = [", 1)[1].split("]", 1)[0]
        assert '"defusedxml>=' in dependencias
        modulo = importlib.import_module("defusedxml.ElementTree")
        assert hasattr(modulo, "fromstring")


class TestRedaccion:
    def documentos(self) -> List[Path]:
        return sorted(p for p in GUARDIA.rglob("*") if p.is_file() and p.suffix in (".md", ".py")) + [ESPEC_PIPELINE]

    def test_nunca_se_presenta_como_frontera(self) -> None:
        hallados = [str(p.relative_to(RAIZ)) for p in self.documentos()
                    if FRASES_PROHIBIDAS.search(p.read_text(encoding="utf-8"))]
        assert hallados == []

    def test_readme_y_skill_dicen_cuarentena_con_revision_humana(self) -> None:
        for nombre in ("README.md", "SKILL.md"):
            texto = (GUARDIA / nombre).read_text(encoding="utf-8").lower()
            assert "quarantine" in texto and "human review" in texto, nombre
