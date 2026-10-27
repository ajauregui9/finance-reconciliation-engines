"""CLI del generador: `PYTHONPATH=examples python3 -m generador_flujo [--parametros] [--salida] [--semilla]`.

Códigos de salida: 0 = archivos escritos; 2 = parámetros inválidos (no se escribe nada).
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .escritura import escribir_salida
from .fabricas import generar
from .parametros import ErrorParametros, cargar_parametros

PARAMETROS_POR_DEFECTO = Path(__file__).resolve().parent / "parametros.json"
SALIDA_POR_DEFECTO = Path(__file__).resolve().parents[1] / "synthetic_flujo"
CODIGO_EXITO = 0
CODIGO_PARAMETROS = 2


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m generador_flujo",
                                     description="Generador sintético de insumos de flujo de efectivo.")
    parser.add_argument("--parametros", type=Path, default=PARAMETROS_POR_DEFECTO,
                        help="JSON parametros_generador_flujo/v1 (por omisión, el de ejemplo).")
    parser.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO,
                        help="Directorio de salida (por omisión examples/synthetic_flujo).")
    parser.add_argument("--semilla", type=int, default=None, help="Sustituye la semilla de los parámetros.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    try:
        parametros = cargar_parametros(args.parametros)
    except ErrorParametros as exc:
        sys.stderr.write(f"Parámetros inválidos: {exc}\n")
        return CODIGO_PARAMETROS
    if args.semilla is not None:
        parametros = dataclasses.replace(parametros, semilla=args.semilla)
    datos = generar(parametros)
    rutas = escribir_salida(datos, args.salida)
    resumen = {
        "archivos": [r.name for r in rutas],
        "semilla": parametros.semilla,
        "registros": {"saldos_bancarios": len(datos.saldos), "cxc_antiguedad": len(datos.cxc),
                      "cxp_programadas": len(datos.cxp), "nomina": len(datos.nomina),
                      "impuestos": len(datos.impuestos)},
    }
    sys.stdout.write(json.dumps(resumen, ensure_ascii=False, sort_keys=True) + "\n")
    return CODIGO_EXITO


if __name__ == "__main__":
    sys.exit(main())
