"""Reglas de candidatura del cruce cargo ↔ CFDI e índices del pool por fecha y por monto.

Las definiciones (qué CFDI es candidato, qué tier califica por monto y cuándo la
afinidad de nombre alcanza el mínimo) viven aquí y las comparten el motor y los
invariantes. Los índices evitan recorrer el pool
completo por cada cargo: se localiza por fecha o por monto con búsqueda binaria.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from types import MappingProxyType
from typing import Dict, Iterable, List, Mapping, Optional, Tuple

from .cruce_cfdi_config import ConfigCruce
from .cruce_cfdi_modelo import (
    MONEDA_LOCAL,
    MONEDA_ORIGINAL,
    MONTO_EXACTO,
    MONTO_TOLERANCIA,
    RECIBIDO,
    TIPOS_CON_EVIDENCIA,
    Cargo,
    Cfdi,
)
from .cruce_cfdi_nombres import afinidad

RANGO_TIER = {MONTO_EXACTO: 0, MONEDA_ORIGINAL: 1, MONTO_TOLERANCIA: 2}


@dataclass(frozen=True)
class Calificacion:
    """Cómo califica un CFDI, por sí solo, para respaldar un cargo."""

    evidencia: str
    diferencia: Decimal
    moneda: str

    @property
    def rango(self) -> int:
        return RANGO_TIER[self.evidencia]


def delta_dias(cargo: Cargo, cfdi: Cfdi) -> int:
    if cargo.fecha is None:
        raise ValueError(f"{cargo.cargo_id}: un cargo sin fecha no tiene delta")
    return (cfdi.fecha_emision - cargo.fecha).days


def en_ventana(delta: int, config: ConfigCruce) -> bool:
    return config.ventana_min <= delta <= config.ventana_max


def es_valido(cfdi: Cfdi, config: ConfigCruce) -> bool:
    """Candidato salvo por la fecha: recibido, I o E, a nombre de la empresa y de un emisor identificable."""
    return (cfdi.direccion == RECIBIDO and cfdi.tipo_comprobante in TIPOS_CON_EVIDENCIA
            and cfdi.rfc_receptor == config.rfc_empresa and cfdi.rfc_emisor not in config.rfcs_genericos)


def falla_solo_por_generico(cfdi: Cfdi, config: ConfigCruce) -> bool:
    """Recibido, I o E, y lo único que lo descalifica es un RFC genérico (de emisor o de receptor)."""
    genericos = config.rfcs_genericos
    receptor_aceptable = cfdi.rfc_receptor == config.rfc_empresa or cfdi.rfc_receptor in genericos
    hay_generico = cfdi.rfc_receptor in genericos or cfdi.rfc_emisor in genericos
    return (cfdi.direccion == RECIBIDO and cfdi.tipo_comprobante in TIPOS_CON_EVIDENCIA
            and receptor_aceptable and hay_generico)


def afinidad_de(cargo: Cargo, cfdi: Cfdi) -> Fraction:
    """Afinidad entre la descripción del cargo y la razón social del emisor del CFDI."""
    return afinidad(cargo.descripcion, cfdi.nombre_emisor)


def alcanza_afinidad(parecido: Fraction, config: ConfigCruce) -> bool:
    """True si la afinidad llega a `afinidad_minima` (el umbral es inclusivo)."""
    return parecido >= Fraction(config.afinidad_minima)


def calificar(cargo: Cargo, cfdi: Cfdi, config: ConfigCruce) -> Optional[Calificacion]:
    """Tier uno a uno por monto (no mira fecha ni RFC). None si el monto no alcanza ningún tier."""
    en_pesos = abs(cfdi.valor_mxn - cargo.monto)
    if en_pesos == 0:
        return Calificacion(MONTO_EXACTO, en_pesos, MONEDA_LOCAL)
    if cargo.moneda_original != MONEDA_LOCAL and cfdi.moneda == cargo.moneda_original:
        en_origen = abs(cfdi.valor_original - cargo.monto_original)
        if en_origen <= config.tolerancia_moneda_original:
            return Calificacion(MONEDA_ORIGINAL, en_origen, cfdi.moneda)
    if en_pesos <= config.tolerancia_uno_a_uno:
        return Calificacion(MONTO_TOLERANCIA, en_pesos, MONEDA_LOCAL)
    return None


@dataclass(frozen=True)
class _PorFecha:
    ordinales: Tuple[int, ...]
    cfdis: Tuple[Cfdi, ...]

    @staticmethod
    def armar(cfdis: Iterable[Cfdi]) -> "_PorFecha":
        orden = sorted(cfdis, key=lambda c: (c.fecha_emision, c.uuid))
        return _PorFecha(tuple(c.fecha_emision.toordinal() for c in orden), tuple(orden))

    def entre(self, desde: date, hasta: date) -> Tuple[Cfdi, ...]:
        inicio = bisect_left(self.ordinales, desde.toordinal())
        fin = bisect_right(self.ordinales, hasta.toordinal())
        return self.cfdis[inicio:fin]


@dataclass(frozen=True)
class _PorMonto:
    montos: Tuple[Decimal, ...]
    cfdis: Tuple[Cfdi, ...]

    @staticmethod
    def armar(pares: Iterable[Tuple[Decimal, Cfdi]]) -> "_PorMonto":
        orden = sorted(pares, key=lambda par: (par[0], par[1].uuid))
        return _PorMonto(tuple(m for m, _ in orden), tuple(c for _, c in orden))

    def cerca(self, centro: Decimal, radio: Decimal) -> Tuple[Cfdi, ...]:
        inicio = bisect_left(self.montos, centro - radio)
        fin = bisect_right(self.montos, centro + radio)
        return self.cfdis[inicio:fin]


@dataclass(frozen=True)
class Pool:
    """El pool de CFDIs separado en válidos y descalificados solo por RFC genérico, con sus índices."""

    todos: Mapping[str, Cfdi]
    validos_fecha: _PorFecha
    validos_pesos: _PorMonto
    validos_origen: Mapping[str, _PorMonto]
    genericos_fecha: _PorFecha

    def ventana(self, cargo: Cargo, config: ConfigCruce, margen: int = 0) -> Tuple[date, date]:
        if cargo.fecha is None:
            raise ValueError(f"{cargo.cargo_id}: un cargo sin fecha no tiene ventana")
        return (cargo.fecha + timedelta(days=config.ventana_min - margen),
                cargo.fecha + timedelta(days=config.ventana_max + margen))

    def validos_en_ventana(self, cargo: Cargo, config: ConfigCruce) -> Tuple[Cfdi, ...]:
        return self.validos_fecha.entre(*self.ventana(cargo, config))

    def genericos_en_ventana(self, cargo: Cargo, config: ConfigCruce) -> Tuple[Cfdi, ...]:
        return self.genericos_fecha.entre(*self.ventana(cargo, config))

    def validos_por_monto(self, cargo: Cargo, config: ConfigCruce, radio: Decimal) -> Tuple[Cfdi, ...]:
        """Válidos (en cualquier fecha) cuyo valor en pesos, o en la moneda original del cargo, cae en el radio."""
        encontrados: Dict[str, Cfdi] = {c.uuid: c for c in self.validos_pesos.cerca(cargo.monto, radio)}
        origen = self.validos_origen.get(cargo.moneda_original)
        if origen is not None:
            radio_origen = max(radio, config.tolerancia_moneda_original)
            encontrados.update((c.uuid, c) for c in origen.cerca(cargo.monto_original, radio_origen))
        return tuple(encontrados[u] for u in sorted(encontrados))

    def individuales(self, cargo: Cargo, config: ConfigCruce) -> Tuple[Tuple[Cfdi, Calificacion], ...]:
        """Pares (CFDI candidato en ventana, calificación) para un cargo cruzable."""
        salida: List[Tuple[Cfdi, Calificacion]] = []
        for cfdi in self.validos_por_monto(cargo, config, config.tolerancia_uno_a_uno):
            calificacion = calificar(cargo, cfdi, config)
            if calificacion is not None and en_ventana(delta_dias(cargo, cfdi), config):
                salida.append((cfdi, calificacion))
        return tuple(salida)


def armar_pool(cfdis: Iterable[Cfdi], config: ConfigCruce) -> Pool:
    lista = tuple(cfdis)
    validos = [c for c in lista if es_valido(c, config)]
    por_moneda: Dict[str, List[Tuple[Decimal, Cfdi]]] = {}
    for cfdi in validos:
        if cfdi.moneda != MONEDA_LOCAL:
            por_moneda.setdefault(cfdi.moneda, []).append((cfdi.valor_original, cfdi))
    return Pool(
        todos=MappingProxyType({c.uuid: c for c in lista}),
        validos_fecha=_PorFecha.armar(validos),
        validos_pesos=_PorMonto.armar((c.valor_mxn, c) for c in validos),
        validos_origen=MappingProxyType({m: _PorMonto.armar(p) for m, p in por_moneda.items()}),
        genericos_fecha=_PorFecha.armar(c for c in lista if falla_solo_por_generico(c, config)),
    )
