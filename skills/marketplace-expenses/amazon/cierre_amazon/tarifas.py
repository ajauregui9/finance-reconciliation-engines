"""Tarifas por pedido: tasa efectiva, provisión y referencias (spec, sección 6).

Aquí los montos van en signo de gasto: positivo es costo para el vendedor.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from .agregacion import Agregado
from .alertas import Alerta, alerta
from .config import CONCEPTOS_TARIFA, RangoTasa
from .dinero import CERO, q2, texto_tasa


@dataclass(frozen=True)
class Tarifas:
    """Gasto por concepto de tarifa, en signo de gasto."""

    comision: Decimal = CERO
    logistica: Decimal = CERO
    otras_tarifas: Decimal = CERO

    @classmethod
    def de_agregado(cls, agregado: Agregado) -> Tarifas:
        """La liquidación trae las tarifas en negativo; el gasto es su opuesto."""
        montos = agregado.montos
        return cls(comision=-montos.comision, logistica=-montos.logistica, otras_tarifas=-montos.otras_tarifas)

    def concepto(self, nombre: str) -> Decimal:
        if nombre not in CONCEPTOS_TARIFA:
            raise KeyError(f"concepto de tarifa desconocido: {nombre}")
        valor: Decimal = getattr(self, nombre)
        return valor

    @property
    def total(self) -> Decimal:
        return self.comision + self.logistica + self.otras_tarifas


SIN_TARIFAS = Tarifas()


def tasas_efectivas(cohorte_mes: Agregado) -> Optional[Mapping[str, Decimal]]:
    """Gasto de cada concepto entre la venta neta de la cohorte del mes; `None` sin venta."""
    venta = cohorte_mes.venta_neta
    if venta == 0:
        return None
    gasto = Tarifas.de_agregado(cohorte_mes)
    return MappingProxyType({c: gasto.concepto(c) / venta for c in CONCEPTOS_TARIFA})


def provision(venta_pendiente: Decimal, cohorte_mes: Agregado) -> Optional[Tarifas]:
    """Provisión de tarifas para la venta pendiente; se redondea una sola vez por concepto."""
    venta = cohorte_mes.venta_neta
    if venta == 0:
        return None
    gasto = Tarifas.de_agregado(cohorte_mes)
    calculadas = {c: q2(venta_pendiente * gasto.concepto(c) / venta) for c in CONCEPTOS_TARIFA}
    return Tarifas(**calculadas)


def alertas_referencia(mes: str, tasas: Mapping[str, Decimal],
                       referencias: Mapping[str, RangoTasa]) -> Tuple[Alerta, ...]:
    """Una alerta por cada tasa efectiva fuera de su rango de referencia."""
    alertas = []
    for concepto in sorted(referencias):
        rango = referencias[concepto]
        tasa = tasas[concepto]
        if rango.contiene(tasa):
            continue
        alertas.append(alerta(
            "tasa_fuera_de_referencia", mes,
            f"La tasa efectiva de {concepto} ({texto_tasa(tasa)}) está fuera de su referencia "
            f"[{texto_tasa(rango.minimo)}, {texto_tasa(rango.maximo)}].",
            concepto=concepto, tasa=texto_tasa(tasa), minimo=texto_tasa(rango.minimo),
            maximo=texto_tasa(rango.maximo)))
    return tuple(alertas)
