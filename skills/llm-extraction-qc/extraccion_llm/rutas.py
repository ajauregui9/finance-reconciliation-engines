"""Rutas por omisión: los insumos sintéticos del repo y la config de ejemplo del skill."""
from __future__ import annotations

from pathlib import Path

RAIZ_SKILL = Path(__file__).resolve().parents[1]
RAIZ_REPO = RAIZ_SKILL.parents[1]
DATOS_POR_DEFECTO = RAIZ_REPO / "examples" / "synthetic_llm"
CONFIG_POR_DEFECTO = RAIZ_SKILL / "config" / "extraccion_llm.example.json"

DIR_DOCUMENTOS = "documentos"
DIR_POOL = "cfdis_conocidos"
DIR_GRABADAS = "respuestas_grabadas"
ARCHIVO_VERDAD = "verdad.jsonl"
