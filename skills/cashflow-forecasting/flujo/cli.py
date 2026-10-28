"""Punto de entrada: `python3 -m flujo --config <json> --corte AAAA-MM-DD --salida <dir>`.

Lee la config y los cinco insumos, ensambla el flujo y solo entonces escribe las
tres salidas. Los códigos de salida están en `errores.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from frontera import ErrorFrontera, leer_fecha

from .avisos import avisos
from .config import cargar_config
from .dinero import texto_monto
from .ensamblador import Flujo, ensamblar
from .errores import CODIGO_ESCRITURA, CODIGO_EXITO, ErrorFlujo
from .fuentes import leer_fuentes
from .salida_json import contenido_json, contenido_jsonl
from .salida_xlsx import libro_xlsx

ARCHIVO_JSON = "flujo_13_semanas.json"
ARCHIVO_JSONL = "filas_contrato.jsonl"
ARCHIVO_XLSX = "flujo_13_semanas.xlsx"
CODIFICACION_SALIDA = "utf-8"


def fecha_corte(texto: str) -> date:
    """Tipo de argparse para `--corte`: exige AAAA-MM-DD y una fecha real."""
    try:
        return leer_fecha(texto)
    except ErrorFrontera as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python3 -m flujo", description="Flujo de efectivo de 13 semanas.")
    parser.add_argument("--config", type=Path, required=True, help="Config JSON (flujo_config/v1).")
    parser.add_argument("--corte", type=fecha_corte, required=True, help="Fecha de corte AAAA-MM-DD.")
    parser.add_argument("--salida", type=Path, required=True, help="Directorio donde se escriben las salidas.")
    return parser.parse_args(argv)


def preparar(ruta_config: Path, corte: date) -> Tuple[Flujo, Dict[str, bytes]]:
    """Corre todo el cálculo en memoria; lanza `ErrorFlujo` si algo no cuadra."""
    config = cargar_config(ruta_config)
    flujo = ensamblar(leer_fuentes(config, corte), corte, config.moneda)
    contenidos = {
        ARCHIVO_JSON: contenido_json(flujo).encode(CODIFICACION_SALIDA),
        ARCHIVO_JSONL: contenido_jsonl(flujo).encode(CODIFICACION_SALIDA),
        ARCHIVO_XLSX: libro_xlsx(flujo),
    }
    return flujo, contenidos


def escribir(salida: Path, contenidos: Dict[str, bytes]) -> List[Path]:
    salida.mkdir(parents=True, exist_ok=True)
    rutas = [salida / nombre for nombre in sorted(contenidos)]
    for ruta in rutas:
        ruta.write_bytes(contenidos[ruta.name])
    return rutas


def _resumen(flujo: Flujo, rutas: Sequence[Path]) -> str:
    resumen = {
        "corte": flujo.corte.isoformat(),
        "moneda": flujo.moneda,
        "semanas": len(flujo.semanas),
        "saldo_inicial": texto_monto(flujo.semanas[0].saldo_inicial),
        "saldo_final": texto_monto(flujo.semanas[-1].saldo_final),
        "avisos": {a.clave: a.registros for a in avisos(flujo)},
        "archivos": [r.name for r in rutas],
    }
    return json.dumps(resumen, ensure_ascii=False, sort_keys=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    try:
        flujo, contenidos = preparar(args.config, args.corte)
    except ErrorFlujo as exc:
        sys.stderr.write(f"{type(exc).__name__}: {exc}\n")
        return exc.codigo_salida
    try:
        rutas = escribir(args.salida, contenidos)
    except OSError as exc:
        sys.stderr.write(f"no se pudo escribir en {args.salida}: {exc}\n")
        return CODIGO_ESCRITURA
    sys.stdout.write(_resumen(flujo, rutas) + "\n")
    return CODIGO_EXITO
