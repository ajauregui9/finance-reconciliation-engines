"""Punto de entrada de `python3 -m flujo`; toda la lógica vive en `flujo.cli`."""
from .cli import main as correr_cli

raise SystemExit(correr_cli())
