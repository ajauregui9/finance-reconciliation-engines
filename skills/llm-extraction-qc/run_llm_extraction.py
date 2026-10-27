#!/usr/bin/env python3
"""Punto de entrada: `python3 skills/llm-extraction-qc/run_llm_extraction.py --salida <dir>`.

Agrega a `sys.path` la carpeta de este skill (paquete `extraccion_llm`) y la del skill de
conciliación de tarjetas (paquete `conciliacion`, que trae el lector XML del motor de cruce y
el cargador de prompt_guard). No instala nada.
"""
from __future__ import annotations

import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
_CARPETAS = [str(_AQUI), str(_AQUI.parent / "credit-card-reconciliation")]
sys.path[:0] = [c for c in _CARPETAS if c not in sys.path]

from extraccion_llm.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
