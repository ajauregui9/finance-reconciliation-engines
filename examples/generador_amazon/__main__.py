"""CLI del generador.

    python3 examples/generador_amazon                 # escribe en examples/synthetic_amazon/
    python3 examples/generador_amazon --salida /tmp/x --semilla 7

Códigos de salida: 0 archivos escritos, 2 parámetros inválidos, 3 autoverificación fallida.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from generador_amazon import ParametrosGenerador, escribir, generar  # noqa: E402
from generador_amazon.parametros import SEMILLA_POR_DEFECTO  # noqa: E402

SALIDA_POR_DEFECTO = Path(__file__).resolve().parent.parent / "synthetic_amazon"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="generador_amazon", description="Liquidaciones sintéticas de Amazon.")
    parser.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO)
    parser.add_argument("--semilla", type=int, default=SEMILLA_POR_DEFECTO)
    parser.add_argument("--pedidos-por-mes", type=int, default=ParametrosGenerador().pedidos_por_mes)
    args = parser.parse_args(argv)
    try:
        parametros = ParametrosGenerador(semilla=args.semilla, pedidos_por_mes=args.pedidos_por_mes)
    except ValueError as exc:
        print(f"Parámetros inválidos: {exc}", file=sys.stderr)
        return 2
    try:
        archivos = generar(parametros)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 3
    rutas = escribir(archivos, args.salida)
    print(json.dumps({"archivos": [r.name for r in rutas], "semilla": parametros.semilla}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
