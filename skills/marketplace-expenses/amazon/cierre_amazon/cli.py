"""Línea de comandos del cierre (spec, sección 11).

    python3 -m cierre_amazon --datos examples/synthetic_amazon --salida cierre.json --xlsx cierre.xlsx

Códigos de salida: 0 cierre completo (puede haber alertas), 1 candado o verificación del
xlsx en falla, 2 insumo, config o argumento inválido.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from .cierre import ResultadoCorrida, cerrar
from .config import cargar_config, con_fuente_publicidad
from .dinero import texto_monto
from .errores import ErrorCierre
from .huso import validar_mes
from .insumos import cargar_insumos
from .salida_json import a_json, seleccionar_meses
from .salida_xlsx import escribir_xlsx, verificar_xlsx

CONFIG_POR_DEFECTO = Path(__file__).resolve().parent.parent / "config" / "cierre.example.json"
SALIDA_OK, SALIDA_CANDADO, SALIDA_INVALIDA = 0, 1, 2


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="cierre_amazon", description="Cierre mensual de Amazon por devengo.")
    parser.add_argument("--datos", type=Path, required=True, help="Directorio con liquidacion_AAAA-MM.csv y fuentes.")
    parser.add_argument("--config", type=Path, default=CONFIG_POR_DEFECTO,
                        help="Config JSON (por omisión, la de ejemplo).")
    parser.add_argument("--salida", type=Path, help="Archivo JSON de salida; sin él, el JSON va a la salida estándar.")
    parser.add_argument("--xlsx", type=Path, help="Libro xlsx opcional; se relee y se verifica después de escribirlo.")
    parser.add_argument("--mes", action="append", default=[], help="Mes AAAA-MM a reportar (repetible).")
    parser.add_argument("--fuente-publicidad", help="Reemplaza publicidad.fuente_autoritativa de la config.")
    return parser.parse_args(argv)


def _resumen(resultado: ResultadoCorrida, meses: Sequence[str]) -> List[str]:
    lineas = []
    for cierre in seleccionar_meses(resultado, meses):
        estado = "candados ok" if cierre.ok else "CANDADO EN FALLA"
        lineas.append(f"{cierre.mes}: gasto devengado {texto_monto(cierre.gasto.total)}, "
                      f"{len(cierre.alertas)} alertas, {estado}")
    lineas += [f"{a.mes}: {a.codigo}" for a in resultado.alertas]
    return lineas


def _correr(args: argparse.Namespace) -> int:
    meses = [validar_mes(m) for m in args.mes]
    config = cargar_config(args.config)
    if args.fuente_publicidad:
        config = con_fuente_publicidad(config, args.fuente_publicidad)
    resultado = cerrar(cargar_insumos(args.datos, config), config)
    texto = a_json(resultado, meses)
    if args.salida is None:
        sys.stdout.write(texto)
    else:
        args.salida.write_text(texto, encoding="utf-8")
    codigo = SALIDA_OK if resultado.ok else SALIDA_CANDADO
    if args.xlsx is not None:
        escribir_xlsx(resultado, args.xlsx, meses)
        diferencias = verificar_xlsx(args.xlsx, resultado, meses)
        for diferencia in diferencias:
            print(f"xlsx: {diferencia}", file=sys.stderr)
        if diferencias:
            codigo = SALIDA_CANDADO
    for linea in _resumen(resultado, meses):
        print(linea, file=sys.stderr)
    return codigo


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    try:
        return _correr(args)
    except (ErrorCierre, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return SALIDA_INVALIDA
