"""Tipos inmutables del cruce cargo ↔ CFDI: cargos, CFDIs, resultados y errores."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import FrozenSet, Optional, Tuple

MONEDA_LOCAL = "MXN"

# Tiers en el orden en que se publican en el resumen. Los cuatro primeros respaldan
# al cargo; `monto_sin_afinidad` es un cruce que solo coincide por monto: ocupa sus
# CFDIs (exclusividad) pero queda pendiente de revisión humana, nunca respaldado.
MONTO_EXACTO = "monto_exacto"
MONEDA_ORIGINAL = "moneda_original"
MONTO_TOLERANCIA = "monto_tolerancia"
SUMA = "suma"
MONTO_SIN_AFINIDAD = "monto_sin_afinidad"
EVIDENCIAS: Tuple[str, ...] = (MONTO_EXACTO, MONEDA_ORIGINAL, MONTO_TOLERANCIA, SUMA, MONTO_SIN_AFINIDAD)
EVIDENCIAS_INDIVIDUALES: FrozenSet[str] = frozenset({MONTO_EXACTO, MONEDA_ORIGINAL, MONTO_TOLERANCIA})
EVIDENCIAS_POR_REVISAR: FrozenSet[str] = frozenset({MONTO_SIN_AFINIDAD})

# Motivos de no-cruce, en el orden en que se evalúan.
FILA_ININTERPRETABLE = "fila_ininterpretable"
NO_APLICA = "no_aplica"
SOLO_RFC_GENERICO = "solo_rfc_generico"
FUERA_DE_VENTANA = "fuera_de_ventana"
FUERA_DE_TOLERANCIA = "fuera_de_tolerancia"
SIN_CANDIDATO = "sin_candidato"
MOTIVOS: Tuple[str, ...] = (
    FILA_ININTERPRETABLE, NO_APLICA, SOLO_RFC_GENERICO, FUERA_DE_VENTANA, FUERA_DE_TOLERANCIA, SIN_CANDIDATO,
)

TIPOS_MOVIMIENTO: FrozenSet[str] = frozenset({"cargo", "abono", "pago"})
ESTADO_OK = "ok"
ESTADOS: FrozenSet[str] = frozenset({ESTADO_OK, "ininterpretable"})
TIPOS_COMPROBANTE: FrozenSet[str] = frozenset({"I", "E", "N", "P", "T"})
TIPOS_CON_EVIDENCIA: FrozenSet[str] = frozenset({"I", "E"})
RECIBIDO = "recibido"
DIRECCIONES: FrozenSet[str] = frozenset({RECIBIDO, "emitido"})


class InsumoInvalido(ValueError):
    """Un insumo (universo, CFDIs o config) no cumple el formato documentado."""


class ConfigInvalida(InsumoInvalido):
    """La config tiene llaves desconocidas o valores fuera de rango."""


@dataclass(frozen=True)
class Cargo:
    cargo_id: str
    fecha: Optional[date]
    descripcion: str
    monto: Decimal
    moneda_original: str
    monto_original: Decimal
    tipo_movimiento: str
    estado: str

    @property
    def cruzable(self) -> bool:
        """Solo un cargo interpretable que no es pago a la tarjeta entra a las fases de asignación."""
        return self.estado == ESTADO_OK and self.fecha is not None and self.tipo_movimiento != "pago"


@dataclass(frozen=True)
class Cfdi:
    uuid: str
    fecha_emision: date
    tipo_comprobante: str
    direccion: str
    rfc_emisor: str
    nombre_emisor: str
    rfc_receptor: str
    moneda: str
    total: Decimal
    total_mxn: Decimal
    uuid_relacionado: Optional[str] = None

    @property
    def signo(self) -> int:
        return -1 if self.tipo_comprobante == "E" else 1

    @property
    def valor_mxn(self) -> Decimal:
        return self.total_mxn * self.signo

    @property
    def valor_original(self) -> Decimal:
        return self.total * self.signo


@dataclass(frozen=True)
class Descarte:
    """Un CFDI que estuvo cerca de respaldar al cargo y por qué no lo hizo."""

    uuid: str
    motivo: str


@dataclass(frozen=True)
class ResultadoCargo:
    cargo_id: str
    cfdis: Tuple[str, ...]
    evidencia: Optional[str]
    motivo: Optional[str]
    diferencia: Optional[Decimal]
    moneda_diferencia: Optional[str]
    deltas: Tuple[int, ...]
    afinidad: Optional[Fraction]
    descartados: Tuple[Descarte, ...]
    advertencias: Tuple[str, ...]


@dataclass(frozen=True)
class ResultadoCruce:
    cargos: Tuple[ResultadoCargo, ...]

    def buscar(self, cargo_id: str) -> ResultadoCargo:
        for resultado in self.cargos:
            if resultado.cargo_id == cargo_id:
                return resultado
        raise KeyError(cargo_id)

    def cfdis_asignados(self) -> FrozenSet[str]:
        return frozenset(u for r in self.cargos for u in r.cfdis)
