"""Permite `python3 -m netsuite_gl` con el repo instalado (`pip install -e .`)."""
from __future__ import annotations

import sys

from netsuite_gl.cli import main

sys.exit(main())
