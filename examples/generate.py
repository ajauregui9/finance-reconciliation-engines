#!/usr/bin/env python3
"""Genera los insumos sintéticos de conciliación de tarjetas.

    python3 examples/generate.py                      # escribe en examples/synthetic/
    python3 examples/generate.py --salida /tmp/x --semilla 7 --ventana-min -3 --ventana-max 10

Códigos de salida: 0 = archivos escritos; 2 = parámetros inválidos;
3 = no se logró un conjunto que pase la autoverificación.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

from frontera import leer_importe  # noqa: E402
from generador_sintetico import ConfigGenerador, escribir_salida, generar  # noqa: E402
from generador_sintetico.config import SEMILLA_POR_DEFECTO  # noqa: E402

SALIDA_POR_DEFECTO = Path(__file__).resolve().parent / "synthetic"
CODIGO_PARAMETROS = 2
CODIGO_AUTOVERIFICACION = 3


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generador sintético determinista.")
    parser.add_argument("--salida", type=Path, default=SALIDA_POR_DEFECTO,
                        help="Directorio de salida (por omisión examples/synthetic).")
    parser.add_argument("--semilla", type=int, default=SEMILLA_POR_DEFECTO)
    parser.add_argument("--ventana-min", type=int, default=-3, help="Días antes del cargo (<= 0).")
    parser.add_argument("--ventana-max", type=int, default=10, help="Días después del cargo (>= 0).")
    parser.add_argument("--tolerancia", default="1.00", help="Tolerancia de monto en pesos (Decimal).")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    try:
        config = ConfigGenerador(semilla=args.semilla, ventana_min=args.ventana_min,
                                 ventana_max=args.ventana_max, tolerancia_monto=leer_importe(args.tolerancia))
    except (ValueError, TypeError) as exc:
        print(f"Parámetros inválidos: {exc}", file=sys.stderr)
        return CODIGO_PARAMETROS
    try:
        datos = generar(config)
    except RuntimeError as exc:
        print(f"Autoverificación fallida: {exc}", file=sys.stderr)
        return CODIGO_AUTOVERIFICACION
    rutas = escribir_salida(datos, args.salida)
    resumen = {"cargos": len(datos.cargos), "cfdis": len(datos.cfdis), "asientos": len(datos.asientos),
               "archivos": [r.name for r in rutas], "intento": datos.intento}
    print(json.dumps(resumen, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
