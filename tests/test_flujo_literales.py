"""Guarda estática: ningún monto ni conteo hardcodeado en el paquete del flujo y su generador.

Revisa con `tokenize` el paquete `flujo` y el generador `generador_flujo`:
  - Un literal numérico distinto de 0 y 1 solo puede aparecer en la definición de una
    constante de módulo con nombre en MAYÚSCULAS (un solo lugar, con nombre).
  - Ningún string con forma de monto (`123.45`) aparece fuera de esas constantes.
Los montos y conteos de ejemplo viven en la config y en los parámetros JSON.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path
from typing import List, Tuple

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CARPETAS = (RAIZ / "skills" / "cashflow-forecasting" / "flujo", RAIZ / "examples" / "generador_flujo")
PERMITIDOS = {"0", "1"}
CONSTANTE = re.compile(r"^[A-Z][A-Z0-9_]*(?:\s*:\s*[^=]+)?\s*=")
FORMA_MONTO = re.compile(r"^-?\d+\.\d+$")


def _modulos() -> List[Path]:
    return sorted(p for carpeta in CARPETAS for p in carpeta.rglob("*.py"))


def _literales_sospechosos(ruta: Path) -> List[Tuple[int, str]]:
    sospechosos: List[Tuple[int, str]] = []
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    tokens = tokenize.generate_tokens(io.StringIO(ruta.read_text(encoding="utf-8")).readline)
    for token in tokens:
        if token.type not in (tokenize.NUMBER, tokenize.STRING):
            continue
        es_constante = bool(CONSTANTE.match(lineas[token.start[0] - 1]))
        if token.type == tokenize.NUMBER and token.string not in PERMITIDOS and not es_constante:
            sospechosos.append((token.start[0], token.string))
        if token.type == tokenize.STRING and not es_constante:
            contenido = token.string.strip("\"'")
            if FORMA_MONTO.match(contenido):
                sospechosos.append((token.start[0], token.string))
    return sospechosos


def test_hay_modulos_que_revisar() -> None:
    nombres = {p.name for p in _modulos()}
    assert {"ensamblador.py", "curva.py", "cli.py", "parametros.py"} <= nombres


@pytest.mark.parametrize("ruta", _modulos(), ids=lambda p: p.relative_to(RAIZ).as_posix())
def test_sin_montos_ni_conteos_hardcodeados(ruta: Path) -> None:
    assert _literales_sospechosos(ruta) == []
