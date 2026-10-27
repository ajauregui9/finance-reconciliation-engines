#!/usr/bin/env python3
"""CLI del revisor del estado de resultados previo al cierre.

    python3 run_pl_audit.py --periodo AAAA-MM --config <config.json> --entrada <exportacion.json>
    python3 run_pl_audit.py --periodo AAAA-MM --config <config.json> --entrada <exportacion.json> \
        --salida <reporte.json>

Sin `--salida` el reporte se imprime en stdout; con `--salida` se escribe en el
archivo y stdout recibe un resumen de una línea. El periodo no tiene valor por
omisión y debe coincidir con el de la exportación.

Códigos de salida: 0 = reporte sin bloqueos; 2 = argumentos, config o
exportación inválidos, o salida que no se pudo escribir (no hay reporte);
3 = reporte con bloqueos (provisional).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

_AQUI = str(Path(__file__).resolve().parent)
if _AQUI not in sys.path:
    sys.path.insert(0, _AQUI)

from auditoria_pl import ErrorEntrada, ReporteAuditoria, auditar, leer_config, leer_exportacion, serializar  # noqa: E402

CODIGO_SIN_BLOQUEOS = 0
CODIGO_CON_BLOQUEOS = 3
CODIGO_ERROR = 2


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Revisión del estado de resultados antes de cerrar un mes.")
    parser.add_argument("--periodo", required=True, help="Periodo a revisar, AAAA-MM (obligatorio).")
    parser.add_argument("--config", required=True, type=Path, help="Config auditoria_pl_config/v1 (JSON).")
    parser.add_argument("--entrada", required=True, type=Path, help="Exportación exportacion_pl/v1 (JSON).")
    parser.add_argument("--salida", type=Path, help="Archivo donde escribir el reporte (opcional).")
    return parser


def _rechazar_llaves_repetidas(pares: List[Tuple[str, Any]]) -> Dict[str, Any]:
    """Un JSON con la misma llave dos veces es ambiguo: se rechaza en lugar de quedarse con la última."""
    objeto: Dict[str, Any] = {}
    for llave, valor in pares:
        if llave in objeto:
            raise ErrorEntrada(f"llave repetida en el JSON: {llave!r}")
        objeto[llave] = valor
    return objeto


def _leer_json(ruta: Path, que: str) -> Any:
    try:
        contenido = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ErrorEntrada(f"no se pudo leer {que} {ruta}: {exc}") from exc
    try:
        return json.loads(contenido, object_pairs_hook=_rechazar_llaves_repetidas)
    except json.JSONDecodeError as exc:
        raise ErrorEntrada(f"{que} {ruta} no es JSON válido (línea {exc.lineno}, columna {exc.colno})") from exc


def _resumen(reporte: ReporteAuditoria, destino: Path) -> str:
    datos = {"bloqueos": len(reporte.bloqueos), "materiales": reporte.variaciones.conteos.materiales}
    return json.dumps({**datos, "salida": str(destino)}, ensure_ascii=False, sort_keys=True)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        config = leer_config(_leer_json(args.config, "la config"))
        exportacion = leer_exportacion(_leer_json(args.entrada, "la exportación"))
        reporte = auditar(config, exportacion, args.periodo)
    except ErrorEntrada as exc:
        print(f"Error de entrada: {exc}", file=sys.stderr)
        return CODIGO_ERROR
    contenido = serializar(reporte)
    if args.salida is None:
        sys.stdout.write(contenido)
    else:
        destino: Path = args.salida
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(contenido.encode("utf-8"))
        except OSError as exc:
            print(f"Error al escribir {destino}: {exc}", file=sys.stderr)
            return CODIGO_ERROR
        print(_resumen(reporte, destino))
    return CODIGO_CON_BLOQUEOS if reporte.bloqueos else CODIGO_SIN_BLOQUEOS


if __name__ == "__main__":
    sys.exit(main())
