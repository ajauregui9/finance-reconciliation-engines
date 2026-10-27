"""Permite `python3 -m netsuite_gl` con la carpeta del skill en PYTHONPATH."""
from __future__ import annotations

import sys

from netsuite_gl.cli import main

sys.exit(main())
