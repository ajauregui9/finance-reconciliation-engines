"""CLI del demo: `python3 skills/llm-extraction-qc/run_llm_extraction.py --salida <dir> [opciones]`.

Códigos de salida: 0 = reporte escrito; 2 = argumento, config, insumo o entorno inválido
(incluye falta de `ANTHROPIC_API_KEY` o del SDK en modo vivo y errores de la API);
3 = tope de documentos o de tokens excedido (no se escribe reporte). Contrato en
`specs/extraccion_llm.md`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Mapping, Optional, Sequence, Tuple

from conciliacion.pipeline_guardia import cargar_inspector
from conciliacion.pipeline_modelo import InsumoPipeline

from .config import Config, Precios, cargar_config, con_ajustes
from .costo import usd_estimado
from .documentos import (
    Documento,
    Verdad,
    cargar_documentos,
    cargar_verdad,
    huella_archivo,
    huella_documentos,
    verificar_alineacion,
)
from .errores import InsumoInvalido, TopeExcedido
from .evaluacion import evaluar
from .grabadas import ExtractorGrabado, cargar_grabadas, huella_grabadas
from .pipeline import Extractor, Inspector, ejecutar
from .pool import Pool, cargar_pool
from .reporte import armar_reporte, texto_json, texto_markdown
from .respuesta import ClienteSdk
from .rutas import ARCHIVO_VERDAD, CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO, DIR_DOCUMENTOS, DIR_GRABADAS, DIR_POOL
from .vivo import ExtractorVivo, crear_cliente_sdk, exigir_api_key

ARCHIVO_JSON = "evaluacion.json"
ARCHIVO_MD = "evaluacion.md"
MODO_GRABADO = "grabado"
MODO_VIVO = "vivo"
CODIGO_EXITO = 0
CODIGO_INVALIDO = 2
CODIGO_TOPE = 3

FabricaCliente = Callable[[], ClienteSdk]
CargadorGuardia = Callable[[], Inspector]


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run_llm_extraction.py",
                                     description="Extracción de CFDI con un LLM validada por código determinista.")
    parser.add_argument("--salida", type=Path, required=True, help="Carpeta existente para evaluacion.json/.md.")
    parser.add_argument("--modo", choices=(MODO_GRABADO, MODO_VIVO), default=MODO_GRABADO,
                        help="grabado (por omisión, sin red ni llave) o vivo (requiere ANTHROPIC_API_KEY).")
    parser.add_argument("--grabadas", type=Path, default=DATOS_POR_DEFECTO / DIR_GRABADAS,
                        help="Respuestas grabadas para el modo grabado.")
    parser.add_argument("--grabar", type=Path, default=None, help="Solo en modo vivo: carpeta donde grabar respuestas.")
    parser.add_argument("--documentos", type=Path, default=DATOS_POR_DEFECTO / DIR_DOCUMENTOS)
    parser.add_argument("--pool", type=Path, default=DATOS_POR_DEFECTO / DIR_POOL, help="XML de CFDIs conocidos.")
    parser.add_argument("--verdad", type=Path, default=DATOS_POR_DEFECTO / ARCHIVO_VERDAD)
    parser.add_argument("--config", type=Path, default=CONFIG_POR_DEFECTO)
    parser.add_argument("--modelo", default=None, help="Sustituye el modelo de la config.")
    parser.add_argument("--max-documentos", type=int, default=None, help="Sustituye limites.max_documentos.")
    parser.add_argument("--max-tokens", type=int, default=None, help="Sustituye limites.max_tokens.")
    args = parser.parse_args(argv)
    if args.grabar is not None and args.modo != MODO_VIVO:
        parser.error("--grabar solo se usa con --modo vivo")
    return args


def _carpeta(ruta: Path, que: str) -> None:
    if not ruta.is_dir():
        raise InsumoInvalido(f"la carpeta {que} {ruta} no existe")


def _guardia(cargar: CargadorGuardia) -> Inspector:
    try:
        return cargar()
    except InsumoPipeline as exc:
        raise InsumoInvalido(str(exc)) from None


def _insumos(args: argparse.Namespace, documentos: Sequence[Documento], verdades: Sequence[Verdad], pool: Pool,
             grabadas: Optional[int]) -> Dict[str, Any]:
    return {
        "documentos": {"registros": len(documentos), "sha256": huella_documentos(documentos)},
        "pool": {"registros": len(pool.cfdis), "sha256": pool.sha256},
        "verdad": {"registros": len(verdades), "sha256": huella_archivo(args.verdad)},
        "grabadas": None if grabadas is None else {"registros": grabadas, "sha256": huella_grabadas(args.grabadas)},
    }


def _extractor(args: argparse.Namespace, fabrica: FabricaCliente) -> Tuple[Extractor, Optional[Mapping[str, Any]]]:
    if args.modo == MODO_VIVO:
        return ExtractorVivo(fabrica(), args.grabar), None
    grabadas = cargar_grabadas(args.grabadas)
    return ExtractorGrabado(grabadas), grabadas


def _config(args: argparse.Namespace) -> Config:
    return con_ajustes(cargar_config(args.config), modelo=args.modelo, max_documentos=args.max_documentos,
                       max_tokens=args.max_tokens)


def _correr(args: argparse.Namespace, config: Config, entorno: Mapping[str, str], fabrica: FabricaCliente,
            cargar_guardia: CargadorGuardia) -> int:
    _carpeta(args.salida, "de salida")
    if args.modo == MODO_VIVO:
        exigir_api_key(entorno)
        if args.grabar is not None:
            _carpeta(args.grabar, "de grabado")
    documentos = cargar_documentos(args.documentos)
    verdades = cargar_verdad(args.verdad)
    verificar_alineacion(documentos, verdades)
    pool = cargar_pool(args.pool, config.rfc_empresa)
    inspector = _guardia(cargar_guardia)
    extractor, grabadas = _extractor(args, fabrica)
    corrida = ejecutar(documentos, pool, extractor, inspector, config)
    evaluacion = evaluar(corrida, {v.documento_id: v for v in verdades})
    enviados = {r.documento_id for r in corrida.resultados if r.enviado}
    sin_usar = sorted(set(grabadas or ()) - enviados)
    insumos = _insumos(args, documentos, verdades, pool, None if grabadas is None else len(grabadas))
    reporte = armar_reporte(modo=args.modo, config=config, corrida=corrida, evaluacion=evaluacion, insumos=insumos,
                            grabadas_sin_usar=sin_usar)
    (args.salida / ARCHIVO_JSON).write_bytes(texto_json(reporte).encode("utf-8"))
    (args.salida / ARCHIVO_MD).write_bytes(texto_markdown(reporte).encode("utf-8"))
    resumen = {"modo": args.modo, "archivos": [ARCHIVO_JSON, ARCHIVO_MD],
               "decisiones": {d: reporte["decisiones"][d] for d in ("concordante", "revision_humana")},
               "tokens_totales": corrida.consumo.tokens_totales,
               "usd_estimado": str(usd_estimado(corrida.consumo, config.precios))}
    sys.stdout.write(json.dumps(resumen, ensure_ascii=False, sort_keys=True) + "\n")
    return CODIGO_EXITO


def _mensaje_tope(error: TopeExcedido, precios: Precios) -> str:
    lineas = [f"Corrida detenida por el tope de costo: {error}. No se escribió reporte."]
    if error.consumo is not None:
        lineas.append(f"Consumo hasta aquí: {error.consumo.tokens_totales} tokens en "
                      f"{len(error.consumo.por_documento)} respuestas; USD estimado "
                      f"{usd_estimado(error.consumo, precios)}.")
    return "\n".join(lineas) + "\n"


def _invalido(error: InsumoInvalido) -> int:
    sys.stderr.write(f"Corrida inválida: {error}\n")
    return CODIGO_INVALIDO


def main(argv: Optional[Sequence[str]] = None, entorno: Optional[Mapping[str, str]] = None,
         fabrica_cliente: Optional[FabricaCliente] = None,
         cargar_guardia: CargadorGuardia = cargar_inspector) -> int:
    args = _argumentos(argv)
    entorno_efectivo = os.environ if entorno is None else entorno
    fabrica = crear_cliente_sdk if fabrica_cliente is None else fabrica_cliente
    try:
        config = _config(args)
    except InsumoInvalido as exc:
        return _invalido(exc)
    try:
        return _correr(args, config, entorno_efectivo, fabrica, cargar_guardia)
    except TopeExcedido as exc:
        sys.stderr.write(_mensaje_tope(exc, config.precios))
        return CODIGO_TOPE
    except InsumoInvalido as exc:
        return _invalido(exc)
