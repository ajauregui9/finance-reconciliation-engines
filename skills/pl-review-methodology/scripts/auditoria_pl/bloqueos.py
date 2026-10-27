"""Bloqueos: condiciones que vuelven provisional el reporte completo."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

MES_INMADURO = "mes_inmaduro"
NOMINA_SIN_REGISTRAR = "nomina_sin_registrar"
PROVISION_SIN_CREAR = "provision_sin_crear"
CUENTA_SIN_RUBRO = "cuenta_sin_rubro"
PUBLICIDAD_SIN_CUADRE = "publicidad_sin_cuadre"


@dataclass(frozen=True)
class Bloqueo:
    codigo: str
    referencia: str  # periodo o cuenta a la que se refiere
    detalle: str


def ordenar_bloqueos(*grupos: Iterable[Bloqueo]) -> Tuple[Bloqueo, ...]:
    """Une los bloqueos de todas las reglas en un orden estable: código y referencia."""
    return tuple(sorted((b for grupo in grupos for b in grupo), key=lambda b: (b.codigo, b.referencia)))
