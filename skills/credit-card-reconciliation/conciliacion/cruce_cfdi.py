"""CLI del cruce cargo ↔ CFDI.

Uso (desde skills/credit-card-reconciliation):
    python3 -m conciliacion.cruce_cfdi --universo <jsonl> --cfdis <jsonl> --salida <json> [--config <json>]
    python3 -m conciliacion.cruce_cfdi --universo <jsonl> --cfdis-xml <dir> --salida <json> [--config <json>]

Códigos de salida: 0 salida escrita; 2 insumo, config o dependencia inválidos;
3 invariante violado (la salida no se escribe). Ver specs/cruce_cfdi.md.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from .cruce_cfdi_config import ConfigCruce, cargar_config
from .cruce_cfdi_insumos import leer_cargos, leer_cfdis
from .cruce_cfdi_invariantes import verificar_invariantes
from .cruce_cfdi_modelo import Cargo, Cfdi, InsumoInvalido
from .cruce_cfdi_motor import cruzar
from .cruce_cfdi_salida import armar_salida, serializar
from .cruce_cfdi_xml import DependenciaFaltante, cargar_cfdis_xml, huella_directorio

SALIDA_OK = 0
SALIDA_INSUMO_INVALIDO = 2
SALIDA_INVARIANTE = 3


@dataclass(frozen=True)
class _Insumos:
    config: ConfigCruce
    cargos: Tuple[Cargo, ...]
    cfdis: Tuple[Cfdi, ...]
    huellas: Dict[str, Dict[str, Any]]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cruce_cfdi", description="Cruce determinista cargo ↔ CFDI.")
    parser.add_argument("--universo", type=Path, required=True, help="universo de cargos normalizado (JSONL)")
    origen = parser.add_mutually_exclusive_group(required=True)
    origen.add_argument("--cfdis", type=Path, help="pool de CFDIs (JSONL)")
    origen.add_argument("--cfdis-xml", type=Path, help="directorio con CFDI en XML (requiere defusedxml)")
    parser.add_argument("--salida", type=Path, required=True, help="archivo JSON de salida")
    parser.add_argument("--config", type=Path, help="config JSON (por defecto, los valores de ejemplo)")
    return parser


def _sha256(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _leer(args: argparse.Namespace) -> _Insumos:
    config = cargar_config(args.config) if args.config else ConfigCruce()
    if not args.salida.parent.is_dir():
        raise InsumoInvalido(f"la carpeta de salida no existe: {args.salida.parent}")
    cargos = leer_cargos(args.universo)
    if args.cfdis is not None:
        cfdis = leer_cfdis(args.cfdis)
        huella_cfdis = _sha256(args.cfdis)
    else:
        cfdis = cargar_cfdis_xml(args.cfdis_xml, config.rfc_empresa)
        huella_cfdis = huella_directorio(args.cfdis_xml)
    huellas = {
        "universo": {"registros": len(cargos), "sha256": _sha256(args.universo)},
        "cfdis": {"registros": len(cfdis), "sha256": huella_cfdis},
    }
    return _Insumos(config, cargos, cfdis, huellas)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        insumos = _leer(args)
    except InsumoInvalido as exc:
        print(f"cruce_cfdi: insumo inválido: {exc}", file=sys.stderr)
        return SALIDA_INSUMO_INVALIDO
    except DependenciaFaltante as exc:
        print(f"cruce_cfdi: dependencia faltante: {exc}", file=sys.stderr)
        return SALIDA_INSUMO_INVALIDO
    resultado = cruzar(insumos.cargos, insumos.cfdis, insumos.config)
    invariantes = verificar_invariantes(insumos.cargos, insumos.cfdis, insumos.config, resultado)
    violados = [i for i in invariantes if not i.cumple]
    if violados:
        for invariante in violados:
            print(f"cruce_cfdi: invariante violado {invariante.nombre}: {invariante.detalle}", file=sys.stderr)
        return SALIDA_INVARIANTE
    documento = armar_salida(insumos.config, resultado, invariantes, insumos.huellas, len(insumos.cfdis))
    try:
        args.salida.write_bytes(serializar(documento))
    except OSError as exc:
        print(f"cruce_cfdi: no se puede escribir {args.salida}: {exc}", file=sys.stderr)
        return SALIDA_INSUMO_INVALIDO
    resumen = documento["resumen"]
    print(f"cruce_cfdi: {resumen['cargos']} cargos, {resumen['con_cruce']} con cruce, "
          f"{resumen['sin_cruce']} sin cruce; invariantes cumplidos; salida en {args.salida}")
    return SALIDA_OK


if __name__ == "__main__":
    sys.exit(main())
