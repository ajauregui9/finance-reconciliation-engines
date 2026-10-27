"""Cruce cargo ↔ libro mayor: fachada y línea de comandos.

    cd skills/credit-card-reconciliation
    python3 -m conciliacion.cruce_libro --universo <jsonl> --libro <csv> \\
        --veredictos <csv> --salida <json> [--config <json>]

Códigos de salida: 0 = salida escrita y candados en verde; 2 = argumentos, config o
insumos inválidos (no se escribe nada); 3 = algún candado falló (la salida se escribe
igual, con el detalle). Reglas completas en `specs/cruce_libro.md`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence

from . import cruce_libro_insumos as insumos
from .cruce_libro_config import cargar_config
from .cruce_libro_insumos import ErrorInsumo
from .cruce_libro_modelo import ConfigCruceLibro, Cargo
from .cruce_libro_salida import a_json, candados_fallidos, construir_reporte
from .cruce_libro_veredictos import conciliar

SALIDA_OK = 0
SALIDA_INSUMO_INVALIDO = 2
SALIDA_CANDADO = 3


def _validar_emisores(cargos: Sequence[Cargo], config: ConfigCruceLibro) -> None:
    faltantes = sorted({c.emisor for c in cargos} - set(config.cuenta_por_emisor))
    if faltantes:
        raise ErrorInsumo(f"config: emisores del universo sin cuenta de tarjeta: {', '.join(faltantes)}.")


def ejecutar(universo: Path, libro: Path, veredictos: Optional[Path],
             config: ConfigCruceLibro) -> Dict[str, object]:
    """Lee y valida los insumos, corre el cruce y devuelve el documento de salida."""
    cargos = insumos.leer_universo(universo)
    lineas = insumos.leer_libro(libro, config.moneda_libro)
    _validar_emisores(cargos, config)
    lista = insumos.leer_veredictos(veredictos, frozenset(c.cargo_id for c in cargos),
                                    frozenset(x.asiento_id for x in lineas))
    conciliacion = conciliar(cargos, lineas, lista, config)
    huellas: Dict[str, object] = {
        "universo": {"cargos": len(cargos), "sha256": insumos.huella(universo)},
        "libro": {"lineas": len(lineas), "asientos": len({x.asiento_id for x in lineas}),
                  "sha256": insumos.huella(libro)},
        "veredictos": {"filas": len(lista), "sha256": insumos.huella(veredictos) if veredictos else None},
    }
    return construir_reporte(conciliacion, cargos, lineas, config, huellas)


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cruce cargo ↔ libro mayor.")
    parser.add_argument("--universo", type=Path, required=True, help="Universo de cargos (JSONL).")
    parser.add_argument("--libro", type=Path, required=True, help="Libro mayor (CSV).")
    parser.add_argument("--veredictos", type=Path, default=None, help="Veredictos humanos (CSV, opcional).")
    parser.add_argument("--salida", type=Path, required=True, help="Archivo JSON de salida.")
    parser.add_argument("--config", type=Path, default=None, help="Config JSON (por omisión, la de ejemplo).")
    return parser.parse_args(argv)


def _escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(texto.encode("utf-8"))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    try:
        reporte = ejecutar(args.universo, args.libro, args.veredictos, cargar_config(args.config))
    except ErrorInsumo as exc:
        print(f"Insumo inválido: {exc}", file=sys.stderr)
        return SALIDA_INSUMO_INVALIDO
    try:
        _escribir(args.salida, a_json(reporte))
    except OSError as exc:
        print(f"No se pudo escribir la salida {args.salida.name}: {exc.strerror}", file=sys.stderr)
        return SALIDA_INSUMO_INVALIDO
    fallidos = candados_fallidos(reporte)
    resumen = reporte["resumen"]
    assert isinstance(resumen, dict)
    print(json.dumps({"cargos": resumen["cargos"], "con_cruce_final": resumen["final"]["con_cruce"],
                      "conflictos": sum(resumen["veredictos"]["conflictos"].values()),
                      "candados_ok": not fallidos, "salida": args.salida.name}, sort_keys=True))
    if fallidos:
        print(f"Candados fallidos: {', '.join(fallidos)} (detalle en la salida).", file=sys.stderr)
        return SALIDA_CANDADO
    return SALIDA_OK


if __name__ == "__main__":
    sys.exit(main())
