#!/usr/bin/env python3
"""Punto de entrada de la CLI del skill: `python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py`.

Python agrega la carpeta de este script a `sys.path`, así que el paquete `netsuite_gl` se
importa sin instalar nada.
"""
from __future__ import annotations

import sys

from netsuite_gl.cli import main

if __name__ == "__main__":
    sys.exit(main())
