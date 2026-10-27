"""Documento de salida del cruce cargo ↔ CFDI y su serialización determinista."""
from __future__ import annotations

import json
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any, Dict, Mapping, Optional, Sequence

from .cruce_cfdi_config import ConfigCruce, config_a_dict
from .cruce_cfdi_invariantes import Invariante
from .cruce_cfdi_modelo import EVIDENCIAS, EVIDENCIAS_POR_REVISAR, MOTIVOS, ResultadoCargo, ResultadoCruce

ESQUEMA_SALIDA = "cruce_cfdi/v1"
CENTESIMO = Decimal("0.01")


def _texto_decimal(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else str(valor.quantize(CENTESIMO, rounding=ROUND_HALF_UP))


def texto_afinidad(valor: Optional[Fraction]) -> Optional[str]:
    """Una afinidad (o None) como texto con dos decimales, `ROUND_HALF_UP`."""
    if valor is None:
        return None
    return _texto_decimal(Decimal(valor.numerator) / Decimal(valor.denominator))


def _cargo(r: ResultadoCargo) -> Dict[str, Any]:
    return {
        "cargo_id": r.cargo_id,
        "cfdis": list(r.cfdis),
        "evidencia": r.evidencia,
        "motivo_sin_cruce": r.motivo,
        "diferencia": _texto_decimal(r.diferencia),
        "moneda_diferencia": r.moneda_diferencia,
        "delta_dias": list(r.deltas),
        "afinidad_nombre": texto_afinidad(r.afinidad),
        "cfdis_descartados": [{"uuid": d.uuid, "motivo": d.motivo} for d in r.descartados],
        "advertencias": list(r.advertencias),
    }


def _resumen(resultado: ResultadoCruce, cfdis_en_pool: int) -> Dict[str, Any]:
    evidencias = Counter(r.evidencia for r in resultado.cargos if r.evidencia is not None)
    motivos = Counter(r.motivo for r in resultado.cargos if r.motivo is not None)
    con_cruce = sum(evidencias.values())
    por_revisar = sum(n for e, n in evidencias.items() if e in EVIDENCIAS_POR_REVISAR)
    return {
        "cargos": len(resultado.cargos),
        "con_cruce": con_cruce,
        "respaldados": con_cruce - por_revisar,
        "por_revisar": por_revisar,
        "sin_cruce": len(resultado.cargos) - con_cruce,
        "por_evidencia": {e: evidencias.get(e, 0) for e in EVIDENCIAS},
        "por_motivo": {m: motivos.get(m, 0) for m in MOTIVOS},
        "cfdis_en_pool": cfdis_en_pool,
        "cfdis_asignados": len(resultado.cfdis_asignados()),
        "advertencias": sum(len(r.advertencias) for r in resultado.cargos),
    }


def armar_salida(
    config: ConfigCruce,
    resultado: ResultadoCruce,
    invariantes: Sequence[Invariante],
    insumos: Mapping[str, Mapping[str, Any]],
    cfdis_en_pool: int,
) -> Dict[str, Any]:
    """El documento `cruce_cfdi/v1`; `insumos` lleva registros y sha256 de cada archivo leído."""
    return {
        "esquema": ESQUEMA_SALIDA,
        "parametros": config_a_dict(config),
        "insumos": {nombre: dict(datos) for nombre, datos in insumos.items()},
        "resumen": _resumen(resultado, cfdis_en_pool),
        "invariantes": [{"nombre": i.nombre, "cumple": i.cumple, "detalle": i.detalle} for i in invariantes],
        "cargos": [_cargo(r) for r in sorted(resultado.cargos, key=lambda r: r.cargo_id)],
    }


def serializar(documento: Mapping[str, Any]) -> bytes:
    """JSON UTF-8 con llaves ordenadas, sangría de 2 y un salto de línea final."""
    return (json.dumps(documento, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
