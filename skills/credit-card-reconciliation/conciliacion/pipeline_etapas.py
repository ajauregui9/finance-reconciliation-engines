"""Etapas del pipeline: lectura de insumos y una envoltura delgada por motor.

Cada motor conserva su propia frontera de entrada y sus propios candados; aquí solo
se le entregan sus insumos, se traducen sus errores a `InsumoPipeline` con el nombre
de la etapa y se llevan sus candados a la forma común `Candado`. Los dos cruces leen
el mismo texto del universo, el que se escribe en `etapas/universo.jsonl`.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterator, List, Mapping, Optional, Sequence, Tuple, cast

from . import universo as uv
from .cruce_cfdi_config import ConfigCruce
from .cruce_cfdi_config import cargar_config as cargar_config_cfdi
from .cruce_cfdi_insumos import cargo_desde_dict, leer_cfdis, leer_jsonl, verificar_unicos
from .cruce_cfdi_invariantes import verificar_invariantes
from .cruce_cfdi_modelo import Cargo as CargoCfdi
from .cruce_cfdi_modelo import Cfdi, InsumoInvalido, ResultadoCruce
from .cruce_cfdi_motor import cruzar
from .cruce_cfdi_salida import armar_salida
from .cruce_libro_config import cargar_config as cargar_config_libro
from .cruce_libro_insumos import ErrorInsumo as ErrorInsumoLibro
from .cruce_libro_insumos import leer_libro, leer_texto, leer_veredictos, universo_desde_texto
from .cruce_libro_modelo import Cargo as CargoLibro
from .cruce_libro_modelo import ConfigCruceLibro, LineaLibro, Veredicto
from .cruce_libro_salida import construir_reporte
from .cruce_libro_veredictos import Conciliacion, conciliar
from .pipeline_modelo import (
    ARCHIVO_CFDIS,
    ARCHIVO_LIBRO,
    ARCHIVO_VEREDICTOS,
    ETAPA_CFDI,
    ETAPA_LIBRO,
    ETAPA_UNIVERSO,
    ETAPAS,
    MOTIVO_ESTADO_OMITIDO,
    MOTIVO_VEREDICTOS_EN_ESPERA,
    MOTIVO_VEREDICTOS_OMITIDOS,
    SEPARADOR_CARGO_ID,
    Candado,
    InsumoPipeline,
    MotivoProvisional,
)
from .pipeline_guardia import RevisorGuardia
from .pipeline_revision import Revisor, TextoLibre, textos_de_cfdis

NOMBRE_UNIVERSO = "universo.jsonl"
COMPROBACION_NETO = "total_neto"
_ERRORES_DE_MOTOR = (uv.ErrorInsumo, InsumoInvalido, ErrorInsumoLibro, csv.Error)


@dataclass(frozen=True)
class OpcionesPipeline:
    datos: Path
    config_cfdi: Optional[Path] = None
    config_libro: Optional[Path] = None
    estados_omitidos: Tuple[str, ...] = ()
    sin_veredictos: bool = False
    revisor: Revisor = RevisorGuardia()


@dataclass(frozen=True)
class Insumos:
    universo: uv.Universo
    config_cfdi: ConfigCruce
    config_libro: ConfigCruceLibro
    cfdis: Tuple[Cfdi, ...]
    textos_cfdi: Tuple[TextoLibre, ...]
    lineas: Tuple[LineaLibro, ...]
    veredictos: Tuple[Veredicto, ...]
    en_espera: Tuple[Veredicto, ...]
    huellas: Mapping[str, Any]


@dataclass(frozen=True)
class UniversoAdaptado:
    texto: str
    sha256: str
    cargos_cfdi: Tuple[CargoCfdi, ...]
    cargos_libro: Tuple[CargoLibro, ...]


@dataclass(frozen=True)
class EtapaCfdi:
    resultado: ResultadoCruce
    candados: Tuple[Candado, ...]
    documento: Mapping[str, Any]


@dataclass(frozen=True)
class EtapaLibro:
    conciliacion: Conciliacion
    candados: Tuple[Candado, ...]
    documento: Mapping[str, object]


@contextmanager
def _en_etapa(etapa: str) -> Iterator[None]:
    """Traduce el error de insumo de un motor a `InsumoPipeline`, con la etapa al frente."""
    try:
        yield
    except _ERRORES_DE_MOTOR as error:
        raise InsumoPipeline(f"{etapa}: {error}") from error


def _sha256(ruta: Path, etapa: str) -> str:
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except OSError as error:
        raise InsumoPipeline(f"{etapa}: no se pudo leer {ruta.name}: {error.strerror}") from error


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def emisor_de_cargo(cargo_id: str) -> str:
    """El emisor de un `cargo_id` con forma `<EMISOR>-<fila>` (el emisor no lleva guiones)."""
    return cargo_id.split(SEPARADOR_CARGO_ID, 1)[0]


# --- lectura de insumos ---------------------------------------------------------


def _huella_config(ruta: Optional[Path], etapa: str) -> Dict[str, Optional[str]]:
    if ruta is None:
        return {"archivo": None, "sha256": None}
    return {"archivo": ruta.name, "sha256": _sha256(ruta, etapa)}


def _cuentas_completas(universo: uv.Universo, config: ConfigCruceLibro) -> None:
    faltantes = sorted({c.emisor for c in universo.cargos} - set(config.cuenta_por_emisor))
    if faltantes:
        raise InsumoPipeline(f"{ETAPA_LIBRO}: config: emisores del universo sin cuenta de tarjeta: "
                             f"{', '.join(faltantes)}")


def _ids_de_estados_omitidos(ruta: Path, omitidos: FrozenSet[str]) -> FrozenSet[str]:
    """Los `cargo_id` del archivo de veredictos que pertenecen a un estado declarado ausente."""
    if not omitidos:
        return frozenset()
    filas = csv.DictReader(io.StringIO(leer_texto(ruta), newline=""))
    ids = ((fila.get("cargo_id") or "").strip() for fila in filas)
    return frozenset(i for i in ids if emisor_de_cargo(i) in omitidos)


def _veredictos(opciones: OpcionesPipeline, universo: uv.Universo,
                lineas: Sequence[LineaLibro]) -> Tuple[Tuple[Veredicto, ...], Tuple[Veredicto, ...]]:
    """(aplicables, en espera): un veredicto de un cargo de un estado omitido queda en espera."""
    if opciones.sin_veredictos:
        return (), ()
    ruta = opciones.datos / ARCHIVO_VEREDICTOS
    if not ruta.is_file():
        raise InsumoPipeline(f"{ETAPA_LIBRO}: falta {ARCHIVO_VEREDICTOS} en la carpeta de datos; si el periodo "
                             f"no trae veredictos humanos, declararlo con --sin-veredictos")
    del_universo = frozenset(c.cargo_id for c in universo.cargos)
    permitidos = del_universo | _ids_de_estados_omitidos(ruta, frozenset(universo.estados_omitidos))
    todos = leer_veredictos(ruta, permitidos, frozenset(x.asiento_id for x in lineas))
    return (tuple(v for v in todos if v.cargo_id in del_universo),
            tuple(v for v in todos if v.cargo_id not in del_universo))


def _huellas(opciones: OpcionesPipeline, universo: uv.Universo, cfdis: Sequence[Cfdi],
             lineas: Sequence[LineaLibro], veredictos: Tuple[Tuple[Veredicto, ...], Tuple[Veredicto, ...]]
             ) -> Dict[str, Any]:
    datos = opciones.datos
    aplicables, en_espera = veredictos
    huella_veredictos = None if opciones.sin_veredictos else {
        "archivo": ARCHIVO_VEREDICTOS, "filas": len(aplicables) + len(en_espera), "aplicados": len(aplicables),
        "en_espera": len(en_espera), "sha256": _sha256(datos / ARCHIVO_VEREDICTOS, ETAPA_LIBRO)}
    return {
        "resumen_estados_cuenta": {"archivo": uv.NOMBRE_RESUMEN,
                                   "sha256": _sha256(datos / uv.NOMBRE_RESUMEN, ETAPA_UNIVERSO)},
        "estados_cuenta": {c.emisor: {"archivo": c.archivo, "sha256": _sha256(datos / c.archivo, ETAPA_UNIVERSO)}
                           for c in universo.controles},
        "cfdis": {"archivo": ARCHIVO_CFDIS, "registros": len(cfdis),
                  "sha256": _sha256(datos / ARCHIVO_CFDIS, ETAPA_CFDI)},
        "libro_mayor": {"archivo": ARCHIVO_LIBRO, "lineas": len(lineas),
                        "asientos": len({x.asiento_id for x in lineas}),
                        "sha256": _sha256(datos / ARCHIVO_LIBRO, ETAPA_LIBRO)},
        "veredictos": huella_veredictos,
        "config_cfdi": _huella_config(opciones.config_cfdi, ETAPA_CFDI),
        "config_libro": _huella_config(opciones.config_libro, ETAPA_LIBRO),
    }


def leer_insumos(opciones: OpcionesPipeline) -> Insumos:
    """Paso 3 de la spec: lee y valida todo antes de evaluar cualquier candado."""
    datos = opciones.datos
    with _en_etapa(ETAPA_CFDI):
        config_cfdi = cargar_config_cfdi(opciones.config_cfdi) if opciones.config_cfdi else ConfigCruce()
    with _en_etapa(ETAPA_LIBRO):
        config_libro = cargar_config_libro(opciones.config_libro)
    with _en_etapa(ETAPA_UNIVERSO):
        universo = uv.construir_universo(datos, opciones.estados_omitidos)
    with _en_etapa(ETAPA_CFDI):
        cfdis = leer_cfdis(datos / ARCHIVO_CFDIS)
        textos_cfdi = textos_de_cfdis(leer_jsonl(datos / ARCHIVO_CFDIS))
    with _en_etapa(ETAPA_LIBRO):
        lineas = leer_libro(datos / ARCHIVO_LIBRO, config_libro.moneda_libro)
        _cuentas_completas(universo, config_libro)
        veredictos = _veredictos(opciones, universo, lineas)
    return Insumos(universo, config_cfdi, config_libro, cfdis, textos_cfdi, lineas, veredictos[0], veredictos[1],
                   _huellas(opciones, universo, cfdis, lineas, veredictos))


def motivos_provisional(opciones: OpcionesPipeline, insumos: Insumos) -> Tuple[MotivoProvisional, ...]:
    """Por qué el periodo es provisional; vacío si no falta ningún insumo."""
    motivos: List[MotivoProvisional] = [
        MotivoProvisional(ETAPA_UNIVERSO, MOTIVO_ESTADO_OMITIDO, f"{emisor}: estado de cuenta declarado ausente")
        for emisor in insumos.universo.estados_omitidos]
    if opciones.sin_veredictos:
        motivos.append(MotivoProvisional(ETAPA_LIBRO, MOTIVO_VEREDICTOS_OMITIDOS,
                                         f"{ARCHIVO_VEREDICTOS} declarado ausente; el resultado final es la "
                                         "propuesta del motor"))
    if insumos.en_espera:
        ids = ", ".join(v.cargo_id for v in insumos.en_espera)
        motivos.append(MotivoProvisional(ETAPA_LIBRO, MOTIVO_VEREDICTOS_EN_ESPERA,
                                         f"{len(insumos.en_espera)} veredictos de estados omitidos: {ids}"))
    return tuple(sorted(motivos, key=lambda m: (ETAPAS.index(m.etapa), m.motivo, m.detalle)))


# --- universo -------------------------------------------------------------------


def candados_universo(universo: uv.Universo) -> Tuple[Candado, ...]:
    """Cada comprobación de totales de control como `<EMISOR>.<comprobación>`."""
    return tuple(Candado(ETAPA_UNIVERSO, f"{control.emisor}.{c.nombre}", c.cuadra,
                         f"esperado {c.esperado}, calculado {c.calculado}")
                 for control in universo.controles for c in control.comprobaciones)


def totales_de_control(universo: uv.Universo) -> Dict[str, Decimal]:
    """El `total_neto` que publica el resumen de cada estado leído."""
    return {control.emisor: Decimal(c.esperado) for control in universo.controles
            for c in control.comprobaciones if c.nombre == COMPROBACION_NETO}


def _cargos_para_cfdi(texto: str) -> Tuple[CargoCfdi, ...]:
    filas: List[Tuple[int, CargoCfdi]] = []
    for numero, linea in enumerate(texto.splitlines(), 1):
        registro = json.loads(linea)
        try:
            filas.append((numero, cargo_desde_dict(registro)))
        except InsumoInvalido as error:
            raise InsumoInvalido(f"{NOMBRE_UNIVERSO}, línea {numero} ({registro.get('cargo_id')}): {error}") from error
    verificar_unicos(((c.cargo_id, f"línea {n}") for n, c in filas), f"{NOMBRE_UNIVERSO}: cargo_id")
    return tuple(c for _, c in filas)


def adaptar_universo(universo: uv.Universo) -> UniversoAdaptado:
    """Paso 6: el universo certificado como texto JSONL, leído por la frontera de cada cruce."""
    texto = uv.serializar_universo(universo)
    with _en_etapa(ETAPA_CFDI):
        cargos_cfdi = _cargos_para_cfdi(texto)
    with _en_etapa(ETAPA_LIBRO):
        cargos_libro = universo_desde_texto(texto, NOMBRE_UNIVERSO)
    return UniversoAdaptado(texto, sha256_texto(texto), cargos_cfdi, cargos_libro)


# --- cruces ---------------------------------------------------------------------


def correr_cruce_cfdi(adaptado: UniversoAdaptado, insumos: Insumos) -> EtapaCfdi:
    config, cargos, cfdis = insumos.config_cfdi, adaptado.cargos_cfdi, insumos.cfdis
    resultado = cruzar(cargos, cfdis, config)
    invariantes = verificar_invariantes(cargos, cfdis, config, resultado)
    huellas = {"universo": {"registros": len(cargos), "sha256": adaptado.sha256},
               "cfdis": {"registros": len(cfdis), "sha256": insumos.huellas["cfdis"]["sha256"]}}
    documento = armar_salida(config, resultado, invariantes, huellas, len(cfdis))
    candados = tuple(Candado(ETAPA_CFDI, i.nombre, i.cumple, i.detalle) for i in invariantes)
    return EtapaCfdi(resultado, candados, documento)


def _candados_libro(documento: Mapping[str, object]) -> Tuple[Candado, ...]:
    tabla = cast(Mapping[str, Mapping[str, object]], documento["candados"])
    return tuple(Candado(ETAPA_LIBRO, nombre, bool(tabla[nombre]["ok"]),
                         json.dumps(tabla[nombre]["detalle"], ensure_ascii=False, sort_keys=True))
                 for nombre in sorted(tabla))


def correr_cruce_libro(adaptado: UniversoAdaptado, insumos: Insumos) -> EtapaLibro:
    config, cargos, lineas = insumos.config_libro, adaptado.cargos_libro, insumos.lineas
    conciliacion = conciliar(cargos, lineas, insumos.veredictos, config)
    huella_veredictos = insumos.huellas["veredictos"]
    huellas: Dict[str, object] = {
        "universo": {"cargos": len(cargos), "sha256": adaptado.sha256},
        "libro": {"lineas": len(lineas), "asientos": len({x.asiento_id for x in lineas}),
                  "sha256": insumos.huellas["libro_mayor"]["sha256"]},
        "veredictos": {"filas": len(insumos.veredictos),
                       "sha256": huella_veredictos["sha256"] if huella_veredictos else None},
    }
    documento = construir_reporte(conciliacion, cargos, lineas, config, huellas)
    return EtapaLibro(conciliacion, _candados_libro(documento), documento)
