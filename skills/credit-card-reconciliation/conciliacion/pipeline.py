"""Pipeline de tarjetas de punta a punta: estado de cuenta crudo → reporte de conciliación.

Uso, con cwd en `skills/credit-card-reconciliation`:

    python3 -m conciliacion.pipeline --datos <carpeta> --salida <carpeta>
        [--config-cfdi <json>] [--config-libro <json>] [--sin-estado EMISOR ...] [--sin-veredictos]
        [--sin-guardia]

Etapas: universo → revisión de texto libre (prompt_guard: cuarentena con revisión
humana) → cruce con CFDI → cruce con libro mayor → ensamblado por cargo. Códigos de
salida: 0 reporte escrito (puede ser provisional y puede traer cargos en revisión), 2
insumo o argumento inválido (no se escribe nada), 3 un candado bloquea (solo se
escribe `bloqueo.json`). Reglas en `specs/pipeline.md`.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path
from typing import NoReturn, Optional, Sequence, TextIO, Tuple

from . import universo as uv
from .cruce_cfdi_salida import serializar as serializar_cfdi
from .cruce_libro_salida import a_json as serializar_libro
from .pipeline_etapas import (
    EtapaCfdi,
    EtapaLibro,
    Insumos,
    OpcionesPipeline,
    adaptar_universo,
    candados_universo,
    correr_cruce_cfdi,
    correr_cruce_libro,
    leer_insumos,
    motivos_provisional,
    sha256_texto,
    totales_de_control,
)
from .pipeline_filas import FilaCargo, ensamblar_filas
from .pipeline_invariantes import invariantes_de_filas, resumir, verificar_cobertura
from .pipeline_modelo import (
    ARTEFACTO_BLOQUEO,
    ARTEFACTO_CARGOS,
    ARTEFACTO_CFDI,
    ARTEFACTO_CONTROL,
    ARTEFACTO_LIBRO,
    ARTEFACTO_REPORTE,
    ARTEFACTO_UNIVERSO,
    ARTEFACTOS,
    ETAPA_CFDI,
    ETAPA_LIBRO,
    ETAPA_PIPELINE,
    ETAPA_REVISION,
    ETAPA_UNIVERSO,
    SALIDA_BLOQUEO,
    SALIDA_INSUMO,
    SALIDA_OK,
    Candado,
    Corrida,
    InsumoPipeline,
    MotivoProvisional,
)
from .pipeline_reporte import a_json, a_jsonl, armar_bloqueo, armar_reporte, cargos_en_revision
from .pipeline_revision import NOMBRE_IDENTIDAD, RevisorIdentidad, Revision, revisar_texto_libre, textos_de_cargos

__all__ = ["Corrida", "InsumoPipeline", "OpcionesPipeline", "correr_pipeline", "escribir_artefactos",
           "limpiar_artefactos", "main"]

PREFIJO = "pipeline"


class _Bloqueo(Exception):
    """Un candado no se cumple: la corrida termina con código 3 y el detalle de lo evaluado."""

    def __init__(self, etapa: str, candados: Tuple[Candado, ...]) -> None:
        super().__init__(etapa)
        self.etapa = etapa
        self.candados = candados


def _exigir(etapa: str, evaluados: Tuple[Candado, ...]) -> None:
    if not all(c.cumple for c in evaluados if c.etapa == etapa):
        raise _Bloqueo(etapa, evaluados)


def _avisos_bloqueo(bloqueo: _Bloqueo) -> Tuple[str, ...]:
    return tuple(f"{c.etapa}: candado {c.nombre} no se cumple: {c.detalle}"
                 for c in bloqueo.candados if not c.cumple)


def _aviso_revision(revision: Revision, filas: Sequence[FilaCargo]) -> Tuple[str, ...]:
    if revision.revisor == NOMBRE_IDENTIDAD:
        return (f"{PREFIJO}: AVISO: revisión de texto libre desactivada; ningún texto pasó por prompt_guard",)
    if not revision.cola:
        return ()
    textos = len({o.llave for o in revision.cola})
    return (f"{PREFIJO}: REVISIÓN HUMANA: {textos} textos marcados; {len(cargos_en_revision(filas))} cargos en "
            "revisión (su cruce no se acepta en automático); detalle en revision_humana de reporte.json",)


def _avisos_ok(filas: Sequence[FilaCargo], motivos: Sequence[MotivoProvisional], candados: int,
               revision: Revision) -> Tuple[str, ...]:
    # Un CFDI que solo coincide por monto (`monto_sin_afinidad`) ocupa su UUID pero no respalda al cargo.
    respaldados = sum(1 for f in filas if f.cfdi.uuids and not f.cfdi.por_revisar)
    por_revisar = sum(1 for f in filas if f.cfdi.uuids and f.cfdi.por_revisar)
    con_asiento = sum(1 for f in filas if f.libro.asiento_id is not None)
    avisos = [f"{PREFIJO}: {len(filas)} cargos; {respaldados} respaldados por CFDI; {por_revisar} con CFDI por "
              f"revisar; {con_asiento} con asiento en el libro mayor; {candados} candados en verde"]
    avisos.extend(f"{PREFIJO}: PROVISIONAL: {m.etapa}/{m.motivo}: {m.detalle}" for m in motivos)
    avisos.extend(_aviso_revision(revision, filas))
    return tuple(avisos)


def _cruces(insumos: Insumos, evaluados: Tuple[Candado, ...]
            ) -> Tuple[str, EtapaCfdi, EtapaLibro, Tuple[Candado, ...]]:
    """Pasos 6 a 8: adaptación del universo y los dos cruces, cada uno con sus candados."""
    adaptado = adaptar_universo(insumos.universo)
    cfdi = correr_cruce_cfdi(adaptado, insumos)
    evaluados = evaluados + cfdi.candados
    _exigir(ETAPA_CFDI, evaluados)
    libro = correr_cruce_libro(adaptado, insumos)
    evaluados = evaluados + libro.candados
    _exigir(ETAPA_LIBRO, evaluados)
    return adaptado.texto, cfdi, libro, evaluados


def _correr(opciones: OpcionesPipeline, insumos: Insumos, motivos: Tuple[MotivoProvisional, ...]) -> Corrida:
    universo = insumos.universo
    evaluados = candados_universo(universo)
    _exigir(ETAPA_UNIVERSO, evaluados)
    revision = revisar_texto_libre(opciones.revisor, tuple(sorted(
        textos_de_cargos(universo.cargos) + insumos.textos_cfdi, key=lambda t: t.llave)))
    evaluados = evaluados + (revision.candado,)
    _exigir(ETAPA_REVISION, evaluados)
    texto_universo, cfdi, libro, evaluados = _cruces(insumos, evaluados)
    evaluados = evaluados + (verificar_cobertura([c.cargo_id for c in universo.cargos],
                                                 [r.cargo_id for r in cfdi.resultado.cargos],
                                                 list(libro.conciliacion.final)),)
    _exigir(ETAPA_PIPELINE, evaluados)
    filas = ensamblar_filas(universo.cargos, cfdi.resultado, libro.conciliacion, revision.cola, bool(motivos))
    control = totales_de_control(universo)
    resumen = resumir(filas, control)
    evaluados = evaluados + invariantes_de_filas(filas, resumen, control, revision.cola)
    _exigir(ETAPA_PIPELINE, evaluados)
    escritos = (
        (ARTEFACTO_CARGOS, a_jsonl(filas)),
        (ARTEFACTO_UNIVERSO, texto_universo),
        (ARTEFACTO_CONTROL, uv.serializar_control(universo)),
        (ARTEFACTO_CFDI, serializar_cfdi(cfdi.documento).decode("utf-8")),
        (ARTEFACTO_LIBRO, serializar_libro(libro.documento)),
    )
    reporte = armar_reporte(insumos=insumos, motivos=motivos, revision=revision, cfdi=cfdi, libro=libro,
                            candados=evaluados, resumen=resumen, filas=filas,
                            artefactos={ruta: sha256_texto(texto) for ruta, texto in escritos})
    artefactos = tuple(sorted(escritos + ((ARTEFACTO_REPORTE, a_json(reporte)),)))
    return Corrida(SALIDA_OK, artefactos, _avisos_ok(filas, motivos, len(evaluados), revision))


def correr_pipeline(opciones: OpcionesPipeline) -> Corrida:
    """Lee, cruza y ensambla; no escribe nada. Lanza `InsumoPipeline` ante un insumo inválido."""
    insumos = leer_insumos(opciones)
    motivos = motivos_provisional(opciones, insumos)
    try:
        return _correr(opciones, insumos, motivos)
    except _Bloqueo as bloqueo:
        documento = armar_bloqueo(bloqueo.etapa, bloqueo.candados, motivos, insumos)
        return Corrida(SALIDA_BLOQUEO, ((ARTEFACTO_BLOQUEO, a_json(documento)),), _avisos_bloqueo(bloqueo))


# --- escritura ------------------------------------------------------------------


def limpiar_artefactos(carpeta: Path) -> None:
    """Borra solo los artefactos que el pipeline escribe, para no dejar un reporte viejo que parezca vigente."""
    for ruta in ARTEFACTOS:
        (carpeta / ruta).unlink(missing_ok=True)
    for subcarpeta in sorted({(carpeta / r).parent for r in ARTEFACTOS} - {carpeta}):
        if subcarpeta.is_dir() and not any(subcarpeta.iterdir()):
            subcarpeta.rmdir()


def escribir_artefactos(carpeta: Path, corrida: Corrida) -> None:
    for ruta, texto in corrida.artefactos:
        destino = carpeta / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(texto.encode("utf-8"))


# --- CLI ------------------------------------------------------------------------


class _ErrorArgumentos(Exception):
    pass


class _Analizador(argparse.ArgumentParser):
    """argparse que devuelve el error a `main` (código 2) en vez de terminar el proceso."""

    def error(self, message: str) -> NoReturn:
        raise _ErrorArgumentos(message)


def _analizador() -> _Analizador:
    analizador = _Analizador(prog="python3 -m conciliacion.pipeline",
                             description="Conciliación de tarjetas de punta a punta: universo, CFDI y libro mayor.")
    analizador.add_argument("--datos", type=Path, required=True,
                            help="carpeta con el resumen de estados de cuenta, los CSV, cfdis.jsonl, "
                                 "libro_mayor.csv y veredictos_libro.csv")
    analizador.add_argument("--salida", type=Path, required=True, help="carpeta de salida (se crea si no existe)")
    analizador.add_argument("--config-cfdi", type=Path, default=None, help="config del cruce con CFDI")
    analizador.add_argument("--config-libro", type=Path, default=None, help="config del cruce con libro mayor")
    analizador.add_argument("--sin-estado", action="append", default=[], metavar="EMISOR",
                            help="declara ausente el estado de cuenta de EMISOR (repetible); reporte provisional")
    analizador.add_argument("--sin-veredictos", action="store_true",
                            help="declara que el periodo no trae veredictos humanos; reporte provisional")
    analizador.add_argument("--sin-guardia", action="store_true",
                            help="desactiva la revisión de texto libre con prompt_guard (no recomendado)")
    return analizador


def _validar_salida(datos: Path, salida: Path) -> None:
    if salida.exists() and not salida.is_dir():
        raise InsumoPipeline(f"{PREFIJO}: --salida no es una carpeta: {salida}")
    if salida.resolve() == datos.resolve():
        raise InsumoPipeline(f"{PREFIJO}: --salida no puede ser la carpeta de datos")


def _imprimir(lineas: Sequence[str], destino: TextIO) -> None:
    for linea in lineas:
        print(linea, file=destino)


def main(argv: Optional[Sequence[str]] = None) -> int:
    analizador = _analizador()
    try:
        args = analizador.parse_args(argv)
    except _ErrorArgumentos as error:
        _imprimir([analizador.format_usage().rstrip(), f"{PREFIJO}: argumentos inválidos: {error}"], sys.stderr)
        return SALIDA_INSUMO
    opciones = OpcionesPipeline(datos=args.datos, config_cfdi=args.config_cfdi, config_libro=args.config_libro,
                                estados_omitidos=tuple(args.sin_estado), sin_veredictos=args.sin_veredictos)
    if args.sin_guardia:
        opciones = replace(opciones, revisor=RevisorIdentidad())
    salida: Path = args.salida
    try:
        _validar_salida(opciones.datos, salida)
        limpiar_artefactos(salida)
        corrida = correr_pipeline(opciones)
        escribir_artefactos(salida, corrida)
    except InsumoPipeline as error:
        _imprimir([str(error)], sys.stderr)
        return SALIDA_INSUMO
    except OSError as error:
        _imprimir([f"{PREFIJO}: no se pudo escribir en {salida}: {error.strerror or error}"], sys.stderr)
        return SALIDA_INSUMO
    if corrida.codigo == SALIDA_OK:
        _imprimir(list(corrida.avisos) + [f"{PREFIJO}: salida en {salida}"], sys.stdout)
    else:
        _imprimir(list(corrida.avisos) + [f"{PREFIJO}: bloqueado; detalle en {salida / ARTEFACTO_BLOQUEO}"],
                  sys.stderr)
    return corrida.codigo


if __name__ == "__main__":
    sys.exit(main())
