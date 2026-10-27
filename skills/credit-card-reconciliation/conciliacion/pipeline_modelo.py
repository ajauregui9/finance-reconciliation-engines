"""Vocabulario compartido del pipeline de tarjetas: etapas, artefactos, códigos y tipos inmutables.

Las reglas están en `specs/pipeline.md`. Este módulo no importa ningún motor.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

ESQUEMA_REPORTE = "pipeline_tarjetas/v1"
ESQUEMA_BLOQUEO = "pipeline_tarjetas_bloqueo/v1"

SALIDA_OK = 0
SALIDA_INSUMO = 2
SALIDA_BLOQUEO = 3

# Etapas en el orden en que corren; los candados se publican en este orden.
ETAPA_UNIVERSO = "universo"
ETAPA_REVISION = "revision_texto_libre"
ETAPA_CFDI = "cruce_cfdi"
ETAPA_LIBRO = "cruce_libro"
ETAPA_PIPELINE = "pipeline"
ETAPAS: Tuple[str, ...] = (ETAPA_UNIVERSO, ETAPA_REVISION, ETAPA_CFDI, ETAPA_LIBRO, ETAPA_PIPELINE)

# Insumos con nombre fijo dentro de la carpeta de datos (el universo los toma de su resumen).
ARCHIVO_CFDIS = "cfdis.jsonl"
ARCHIVO_LIBRO = "libro_mayor.csv"
ARCHIVO_VEREDICTOS = "veredictos_libro.csv"

# Artefactos, como rutas relativas a la carpeta de salida.
ARTEFACTO_REPORTE = "reporte.json"
ARTEFACTO_CARGOS = "cargos.jsonl"
ARTEFACTO_BLOQUEO = "bloqueo.json"
ARTEFACTO_UNIVERSO = "etapas/universo.jsonl"
ARTEFACTO_CONTROL = "etapas/universo.control.json"
ARTEFACTO_CFDI = "etapas/cruce_cfdi.json"
ARTEFACTO_LIBRO = "etapas/cruce_libro.json"
ARTEFACTOS: Tuple[str, ...] = (ARTEFACTO_REPORTE, ARTEFACTO_CARGOS, ARTEFACTO_BLOQUEO, ARTEFACTO_UNIVERSO,
                               ARTEFACTO_CONTROL, ARTEFACTO_CFDI, ARTEFACTO_LIBRO)

# Situación de un cargo después de ambos cruces (gana la primera que aplica). Un cargo
# con observaciones de la revisión de texto libre queda en revisión humana: su cruce
# se publica, pero no se acepta en automático.
SITUACION_EN_REVISION = "en_revision"
SITUACION_ININTERPRETABLE = "fila_ininterpretable"
SITUACION_NO_APLICA = "no_aplica"
SITUACION_CONCILIADO = "conciliado"
SITUACION_FALTA_CFDI = "falta_cfdi"
SITUACION_FALTA_REGISTRO = "falta_registro"
SITUACION_FALTA_AMBOS = "falta_cfdi_y_registro"
SITUACIONES: Tuple[str, ...] = (SITUACION_EN_REVISION, SITUACION_ININTERPRETABLE, SITUACION_NO_APLICA,
                                SITUACION_CONCILIADO, SITUACION_FALTA_CFDI, SITUACION_FALTA_REGISTRO,
                                SITUACION_FALTA_AMBOS)

# Motivos de un periodo provisional.
MOTIVO_ESTADO_OMITIDO = "estado_omitido"
MOTIVO_VEREDICTOS_OMITIDOS = "veredictos_omitidos"
MOTIVO_VEREDICTOS_EN_ESPERA = "veredictos_en_espera"

SEPARADOR_CARGO_ID = "-"


class InsumoPipeline(Exception):
    """Argumento, config o insumo inválido; el mensaje empieza con la etapa (código de salida 2)."""


@dataclass(frozen=True)
class Candado:
    """Una verificación de integridad de cualquier etapa, con forma común para el reporte."""

    etapa: str
    nombre: str
    cumple: bool
    detalle: str


@dataclass(frozen=True)
class MotivoProvisional:
    etapa: str
    motivo: str
    detalle: str


@dataclass(frozen=True)
class Corrida:
    """Resultado de `correr_pipeline`: código (0 o 3), artefactos (ruta relativa, texto) y avisos."""

    codigo: int
    artefactos: Tuple[Tuple[str, str], ...]
    avisos: Tuple[str, ...]
