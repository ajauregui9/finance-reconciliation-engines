"""Gasto devengado del mes (spec, sección 6, paso 5)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Optional

from .agregacion import GruposMes
from .config import CONCEPTOS_TARIFA
from .dinero import CERO
from .tarifas import SIN_TARIFAS, Tarifas


@dataclass(frozen=True)
class LineaTarifa:
    """Un concepto de tarifa: lo liquidado, lo provisionado y lo revertido."""

    cohorte_mes: Decimal
    provision: Decimal
    cola_real: Decimal
    reverso: Decimal
    total: Decimal


@dataclass(frozen=True)
class GastoDevengado:
    """Líneas del gasto del mes, sin IVA y en signo de gasto."""

    tarifas: Mapping[str, LineaTarifa]
    cargos_periodo: Mapping[str, Decimal]
    publicidad: Decimal
    total: Decimal


def armar_gasto(grupos: GruposMes, provision: Optional[Tarifas], provision_anterior: Optional[Tarifas],
                publicidad: Decimal) -> GastoDevengado:
    """cohorte del mes + provisión del mes + cola real - provisión anterior, por concepto."""
    del_mes = Tarifas.de_agregado(grupos.cohorte_mes)
    cola = Tarifas.de_agregado(grupos.cola)
    nueva = provision or SIN_TARIFAS
    revertida = provision_anterior or SIN_TARIFAS
    lineas = {}
    for concepto in CONCEPTOS_TARIFA:
        partes = (del_mes.concepto(concepto), nueva.concepto(concepto), cola.concepto(concepto),
                  revertida.concepto(concepto))
        lineas[concepto] = LineaTarifa(*partes, total=partes[0] + partes[1] + partes[2] - partes[3])
    cargos = {tipo: -agregado.total for tipo, agregado in grupos.cargos_periodo.items()}
    total = sum((linea.total for linea in lineas.values()), CERO) + sum(cargos.values(), CERO) + publicidad
    return GastoDevengado(tarifas=MappingProxyType(lineas), cargos_periodo=MappingProxyType(cargos),
                          publicidad=publicidad, total=total)
