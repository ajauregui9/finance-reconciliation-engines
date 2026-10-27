"""Fila por cargo del pipeline: une el universo con lo que decidió cada motor de cruce.

Una fila no recalcula nada: copia el resultado del cruce con CFDI y el resultado
final del cruce con libro, y deriva de ambos la situación del cargo. El monto es el
que leyeron los motores en su frontera de entrada (ya `Decimal`). Un cruce con CFDI
de tier `monto_sin_afinidad` no respalda al cargo: la fila queda `cfdi_por_revisar`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from . import universo as uv
from .cruce_cfdi_modelo import EVIDENCIAS_POR_REVISAR, ResultadoCargo, ResultadoCruce
from .cruce_cfdi_salida import texto_afinidad
from .cruce_libro_veredictos import Conciliacion
from .montos import texto_monto
from .pipeline_modelo import (
    SITUACION_CONCILIADO,
    SITUACION_EN_REVISION,
    SITUACION_FALTA_AMBOS,
    SITUACION_FALTA_CFDI,
    SITUACION_FALTA_REGISTRO,
    SITUACION_ININTERPRETABLE,
    SITUACION_NO_APLICA,
    SITUACIONES,
)
from .pipeline_revision import Observacion, observacion_a_dict, observaciones_de

ESTADO_OK = "ok"
TIPO_PAGO = "pago"

# El único CFDI candidato (o grupo) coincide solo por monto: ocupa su UUID, pero el
# cargo no cuenta como respaldado ni como falta_*; una persona confirma o descarta.
SITUACION_CFDI_POR_REVISAR = "cfdi_por_revisar"
SITUACIONES_FILA: Tuple[str, ...] = SITUACIONES + (SITUACION_CFDI_POR_REVISAR,)

_POR_EVIDENCIA = {
    (True, True): SITUACION_CONCILIADO,
    (False, True): SITUACION_FALTA_CFDI,
    (True, False): SITUACION_FALTA_REGISTRO,
    (False, False): SITUACION_FALTA_AMBOS,
}


@dataclass(frozen=True)
class LadoCfdi:
    uuids: Tuple[str, ...]
    tier: Optional[str]
    motivo: Optional[str]
    diferencia: Optional[Decimal]
    moneda_diferencia: Optional[str]
    deltas: Tuple[int, ...]
    afinidad: Optional[Fraction] = None

    @property
    def por_revisar(self) -> bool:
        return self.tier in EVIDENCIAS_POR_REVISAR


@dataclass(frozen=True)
class LadoLibro:
    """Resultado final (después de veredictos) más lo que el motor propuso por sí solo."""

    asiento_id: Optional[str]
    origen: str
    riesgo_cubeta: bool
    motivo: Optional[str]
    propuesta_asiento_id: Optional[str]
    conflicto: Optional[str]
    veredicto: Optional[str]


@dataclass(frozen=True)
class FilaCargo:
    cargo_id: str
    emisor: str
    fecha: Optional[date]
    descripcion: Optional[str]
    monto: Decimal
    moneda: str
    tipo_movimiento: Optional[str]
    estado: str
    motivo_fila: Optional[str]
    cfdi: LadoCfdi
    libro: LadoLibro
    provisional: bool
    revision: Tuple[Observacion, ...]

    @property
    def situacion(self) -> str:
        return situacion_de(self.estado, self.tipo_movimiento, bool(self.cfdi.uuids),
                            self.libro.asiento_id is not None, en_revision=bool(self.revision),
                            cfdi_por_revisar=self.cfdi.por_revisar)


def situacion_de(estado: str, tipo_movimiento: Optional[str], tiene_cfdi: bool, tiene_asiento: bool, *,
                 en_revision: bool = False, cfdi_por_revisar: bool = False) -> str:
    """La situación del cargo: la revisión de texto libre gana a todo; luego la fila ilegible, el pago a la
    tarjeta y el CFDI que solo coincide por monto; al final, la combinación de CFDI y asiento."""
    if en_revision:
        return SITUACION_EN_REVISION
    if estado != ESTADO_OK:
        return SITUACION_ININTERPRETABLE
    if tipo_movimiento == TIPO_PAGO:
        return SITUACION_NO_APLICA
    if cfdi_por_revisar:
        return SITUACION_CFDI_POR_REVISAR
    return _POR_EVIDENCIA[(tiene_cfdi, tiene_asiento)]


def _lado_cfdi(resultado: ResultadoCargo) -> LadoCfdi:
    return LadoCfdi(resultado.cfdis, resultado.evidencia, resultado.motivo, resultado.diferencia,
                    resultado.moneda_diferencia, resultado.deltas, resultado.afinidad)


def _lado_libro(conciliacion: Conciliacion, cargo_id: str) -> LadoLibro:
    final = conciliacion.final[cargo_id]
    veredicto = conciliacion.veredictos.get(cargo_id)
    return LadoLibro(final.asiento_id, final.origen, final.riesgo_cubeta, final.motivo,
                     conciliacion.propuesta[cargo_id].asiento_id, conciliacion.conflictos.get(cargo_id),
                     veredicto.veredicto if veredicto is not None else None)


def ensamblar_filas(cargos: Sequence[uv.Cargo], cruce_cfdi: ResultadoCruce, conciliacion: Conciliacion,
                    cola: Sequence[Observacion], provisional: bool) -> Tuple[FilaCargo, ...]:
    """Una fila por cargo, ordenadas por `cargo_id`; exige que la cobertura ya se haya verificado."""
    por_cfdi: Mapping[str, ResultadoCargo] = {r.cargo_id: r for r in cruce_cfdi.cargos}
    montos = {e.cargo.cargo_id: e.cargo.monto for e in conciliacion.evaluaciones}
    filas = []
    for cargo in sorted(cargos, key=lambda c: c.cargo_id):
        cfdi = _lado_cfdi(por_cfdi[cargo.cargo_id])
        filas.append(FilaCargo(
            cargo_id=cargo.cargo_id, emisor=cargo.emisor, fecha=cargo.fecha, descripcion=cargo.descripcion,
            monto=montos[cargo.cargo_id], moneda=cargo.moneda, tipo_movimiento=cargo.tipo_movimiento,
            estado=cargo.estado, motivo_fila=cargo.motivo, cfdi=cfdi,
            libro=_lado_libro(conciliacion, cargo.cargo_id), provisional=provisional,
            revision=observaciones_de(cola, cargo.cargo_id, cfdi.uuids)))
    return tuple(filas)


def _texto(valor: Optional[Decimal]) -> Optional[str]:
    return texto_monto(valor) if valor is not None else None


def fila_a_dict(fila: FilaCargo) -> Dict[str, Any]:
    """La fila como objeto JSON: fechas ISO e importes como texto con dos decimales."""
    cfdi, libro = fila.cfdi, fila.libro
    return {
        "cargo_id": fila.cargo_id, "emisor": fila.emisor,
        "fecha": fila.fecha.isoformat() if fila.fecha is not None else None,
        "descripcion": fila.descripcion, "monto": texto_monto(fila.monto), "moneda": fila.moneda,
        "tipo_movimiento": fila.tipo_movimiento, "estado": fila.estado, "motivo_fila": fila.motivo_fila,
        "situacion": fila.situacion, "provisional": fila.provisional,
        "cfdi": {"uuids": list(cfdi.uuids), "tier": cfdi.tier, "motivo_sin_cruce": cfdi.motivo,
                 "diferencia": _texto(cfdi.diferencia), "moneda_diferencia": cfdi.moneda_diferencia,
                 "delta_dias": list(cfdi.deltas), "afinidad_nombre": texto_afinidad(cfdi.afinidad)},
        "libro_mayor": {"asiento_id": libro.asiento_id, "origen": libro.origen,
                        "riesgo_cubeta": libro.riesgo_cubeta, "motivo_sin_cruce": libro.motivo,
                        "propuesta_asiento_id": libro.propuesta_asiento_id, "conflicto": libro.conflicto,
                        "veredicto": libro.veredicto},
        "revision": [observacion_a_dict(o) for o in fila.revision],
    }
