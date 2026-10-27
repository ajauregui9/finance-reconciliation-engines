"""CLI del generador: `PYTHONPATH=examples python3 -m generador_llm [--salida DIR] [--semilla N]`.

Códigos de salida: 0 = archivos escritos; 2 = parámetros inválidos (no se escribe nada).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .catalogo import SEMILLA_POR_DEFECTO
from .escritura import DIR_POOL, escribir_salida
from .fabricas import generar
from .respuestas import error_plantado

SALIDA_POR_DEFECTO = Path(__file__).resolve().parents[1] / "synthetic_llm"
CODIGO_EXITO = 0
CODIGO_PARAMETROS = 2


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m generador_llm",
                                     description="Generador sintético para el demo de extracción con LLM.")
    parser.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO,
                        help="Directorio de salida (por omisión examples/synthetic_llm).")
    parser.add_argument("--semilla", type=int, default=SEMILLA_POR_DEFECTO)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    try:
        datos = generar(args.semilla)
    except ValueError as exc:
        sys.stderr.write(f"Parámetros inválidos: {exc}\n")
        return CODIGO_PARAMETROS
    rutas = escribir_salida(datos, args.salida)
    resumen = {
        "semilla": datos.semilla,
        "documentos": len(datos.documentos),
        "pool": sum(1 for r in rutas if r.parent.name == DIR_POOL),
        "inyecciones": sum(1 for d in datos.documentos if d.caso.inyeccion is not None),
        "errores_plantados": sum(1 for d in datos.documentos if error_plantado(d) is not None),
    }
    sys.stdout.write(json.dumps(resumen, ensure_ascii=False, sort_keys=True) + "\n")
    return CODIGO_EXITO


if __name__ == "__main__":
    sys.exit(main())
