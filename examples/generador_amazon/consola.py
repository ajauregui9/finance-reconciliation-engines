"""Gasto diario de publicidad por campaña (sin IVA) y su factura mensual."""
from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Sequence

from .montos import CERO, q2, texto
from .parametros import CAMPANAS, ParametrosGenerador
from .tiempo import dias_del_mes, partes_mes

GASTO_MIN_CENTAVOS, GASTO_MAX_CENTAVOS = 2000, 12000


@dataclass(frozen=True)
class GastoDiario:
    fecha: date
    campana: str
    gasto: Decimal


def gasto_consola(rng: random.Random, p: ParametrosGenerador) -> List[GastoDiario]:
    gastos = []
    for mes in p.meses:
        anio, numero = partes_mes(mes)
        for dia in range(1, dias_del_mes(mes) + 1):
            for campana in CAMPANAS:
                gasto = q2(Decimal(rng.randint(GASTO_MIN_CENTAVOS, GASTO_MAX_CENTAVOS)) / 100)
                gastos.append(GastoDiario(date(anio, numero, dia), campana, gasto))
    return gastos


def total_por_mes(gastos: Sequence[GastoDiario], p: ParametrosGenerador) -> Dict[str, Decimal]:
    return {mes: sum((g.gasto for g in gastos if g.fecha.strftime("%Y-%m") == mes), CERO) for mes in p.meses}


def facturas(totales: Dict[str, Decimal], p: ParametrosGenerador) -> List[Dict[str, str]]:
    documentos = []
    for mes, subtotal in sorted(totales.items()):
        iva = q2(subtotal * p.tasa_iva)
        documentos.append({"mes": mes, "folio": f"PUB-SINT-{mes.replace('-', '')}", "subtotal": texto(subtotal),
                           "iva": texto(iva), "total": texto(subtotal + iva)})
    return documentos
