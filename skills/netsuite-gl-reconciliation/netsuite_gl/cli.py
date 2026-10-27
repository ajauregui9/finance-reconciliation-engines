"""CLI: corre las queries contra la base sintética, muestra el manifiesto y genera CSV de carga.

Códigos de salida: 0 éxito, 2 entrada o argumentos inválidos, 3 CSV rechazado.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable, Dict, Optional, Sequence, Tuple

from netsuite_gl.carga_csv import CargaRechazada, describir_errores, generar_csv
from netsuite_gl.carga_modelo import AsientoCarga, ErrorEntrada, asientos_desde_json
from netsuite_gl.carga_validacion import FORMATO_VENDOR_BILL, FORMATOS, leer_catalogo
from netsuite_gl.cfdis import ErrorInsumo
from netsuite_gl.compat import ErrorCompatibilidad, traducir
from netsuite_gl.config import CONFIG_DEFAULT
from netsuite_gl.consultas import ORDEN_CONSULTAS, ErrorConsulta, cargar_consulta, ejecutar_todas
from netsuite_gl.errores import ErrorPoblado
from netsuite_gl.poblado import BaseSintetica, construir_base
from netsuite_gl.propuestas import proponer_facturas_sin_registro
from netsuite_gl.salida import manifiesto_a_json, resultado_a_csv

SALIDA_OK = 0
SALIDA_ENTRADA_INVALIDA = 2
SALIDA_CSV_RECHAZADO = 3

CFDIS_DEFAULT = Path(__file__).resolve().parents[3] / "examples" / "synthetic" / "cfdis.jsonl"
NOMBRE_MANIFIESTO = "discrepancias_plantadas.json"

ERRORES_DE_ENTRADA = (ErrorInsumo, ErrorPoblado, ErrorConsulta, ErrorCompatibilidad, ErrorEntrada, OSError)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as salida:  # argparse ya imprimió el motivo; se respeta su código
        return salida.code if isinstance(salida.code, int) else SALIDA_ENTRADA_INVALIDA
    manejador: Callable[[argparse.Namespace], int] = args.manejador
    try:
        return manejador(args)
    except CargaRechazada as rechazo:
        print(str(rechazo), file=sys.stderr)
        for linea in describir_errores(rechazo.errores):
            print(f"  {linea}", file=sys.stderr)
        return SALIDA_CSV_RECHAZADO
    except ERRORES_DE_ENTRADA as exc:
        print(f"error: {exc}", file=sys.stderr)
        return SALIDA_ENTRADA_INVALIDA


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_netsuite_gl.py",
        description="Cuadre CFDI ↔ libro mayor con SuiteQL sobre un esquema SQLite sintético.",
    )
    subcomandos = parser.add_subparsers(dest="comando", required=True)

    consultar = _subcomando(subcomandos, "consultar", "Ejecuta las queries en orden fijo.", _consultar)
    consultar.add_argument("--consulta", action="append", choices=None, metavar="NOMBRE",
                           help=f"Query a ejecutar (repetible). Por omisión: {', '.join(ORDEN_CONSULTAS)}")
    consultar.add_argument("--salida", type=Path, help="Carpeta donde escribir un CSV por query y el manifiesto")

    discrepancias = _subcomando(subcomandos, "discrepancias", "Imprime el manifiesto de lo plantado.", _discrepancias)
    discrepancias.add_argument("--salida", type=Path, help="Archivo JSON de salida")

    traduccion = _subcomando(subcomandos, "traducir", "Imprime el SQL traducido para SQLite.", _traducir)
    traduccion.add_argument("nombre", help="Nombre de la query")

    carga = _subcomando(subcomandos, "generar-csv", "Valida asientos y escribe el CSV de carga.", _generar_csv)
    origen = carga.add_mutually_exclusive_group(required=True)
    origen.add_argument("--asientos", type=Path, help="JSON con {\"asientos\": [...]}")
    origen.add_argument("--desde-sin-registro", action="store_true",
                        help="Propone un vendor bill por cada factura de cfdi_sin_registro")
    carga.add_argument("--formato", choices=FORMATOS, help="Formato del CSV (obligatorio con --asientos)")
    carga.add_argument("--salida", type=Path, required=True, help="Archivo CSV de salida")
    return parser


def _subcomando(
    subcomandos: "argparse._SubParsersAction[argparse.ArgumentParser]",
    nombre: str,
    ayuda: str,
    manejador: Callable[[argparse.Namespace], int],
) -> argparse.ArgumentParser:
    sub = subcomandos.add_parser(nombre, help=ayuda, description=ayuda)
    sub.add_argument("--cfdis", type=Path, default=CFDIS_DEFAULT, help="Ruta de cfdis.jsonl (solo lectura)")
    sub.set_defaults(manejador=manejador)
    return sub


def _consultar(args: argparse.Namespace) -> int:
    nombres: Tuple[str, ...] = tuple(args.consulta) if args.consulta else ORDEN_CONSULTAS
    for nombre in nombres:
        cargar_consulta(nombre)  # valida antes de construir la base
    base = _base(args)
    resultados = ejecutar_todas(base.conexion, nombres)
    if args.salida is None:
        bloques = [f"# {r.nombre} ({len(r.filas)} filas)\n{resultado_a_csv(r)}" for r in resultados]
        sys.stdout.write("\n".join(bloques))
        return SALIDA_OK
    archivos: Dict[str, str] = {f"{r.nombre}.csv": resultado_a_csv(r) for r in resultados}
    archivos[NOMBRE_MANIFIESTO] = manifiesto_a_json(base.manifiesto)
    args.salida.mkdir(parents=True, exist_ok=True)
    for nombre_archivo, texto in sorted(archivos.items()):
        _escribir(args.salida / nombre_archivo, texto)
    for r in resultados:
        print(f"{r.nombre}: {len(r.filas)} filas -> {r.nombre}.csv")
    print(f"manifiesto -> {NOMBRE_MANIFIESTO}")
    return SALIDA_OK


def _discrepancias(args: argparse.Namespace) -> int:
    texto = manifiesto_a_json(_base(args).manifiesto)
    if args.salida is None:
        sys.stdout.write(texto)
    else:
        _escribir(args.salida, texto)
    return SALIDA_OK


def _traducir(args: argparse.Namespace) -> int:
    print(traducir(cargar_consulta(args.nombre).suiteql).strip())
    return SALIDA_OK


def _generar_csv(args: argparse.Namespace) -> int:
    base = _base(args)
    if args.desde_sin_registro:
        if args.formato not in (None, FORMATO_VENDOR_BILL):
            raise ErrorEntrada("--desde-sin-registro solo genera el formato vendor_bill")
        propuesta = proponer_facturas_sin_registro(base.conexion, CONFIG_DEFAULT)
        asientos: Tuple[AsientoCarga, ...] = propuesta.asientos
        formato = FORMATO_VENDOR_BILL
        avisos = [f"pendiente {p.uuid}: {p.motivo}" for p in propuesta.pendientes]
    else:
        if args.formato is None:
            raise ErrorEntrada("--formato es obligatorio con --asientos")
        asientos = asientos_desde_json(args.asientos.read_text(encoding="utf-8"))
        formato = args.formato
        avisos = []
    texto = generar_csv(asientos, leer_catalogo(base.conexion), formato)
    _escribir(args.salida, texto)
    print(f"{len(asientos)} asientos validados y escritos en {args.salida.name} (formato {formato})")
    for aviso in avisos:
        print(aviso)
    return SALIDA_OK


def _base(args: argparse.Namespace) -> BaseSintetica:
    return construir_base(args.cfdis)


def _escribir(ruta: Path, texto: str) -> None:
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        archivo.write(texto)
