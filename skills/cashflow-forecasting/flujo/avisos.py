"""Avisos de la corrida: lo que entró al flujo por una regla especial o no generó filas.

Ningún caso se resuelve en silencio: los egresos vencidos y los saldos acreedores de
CxC llevan marca en sus filas y aquí se cuentan; los registros de CxC en cero no generan
filas y aquí se cuentan. Las tres salidas (JSON, xlsx y resumen del CLI) leen esta lista.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

from .contrato import MARCA_SALDO_ACREEDOR, MARCA_VENCIDO
from .dinero import CERO
from .ensamblador import Flujo

AVISO_SALDO_ACREEDOR = "cxc_saldo_acreedor"
AVISO_SALDO_CERO = "cxc_saldo_cero"
AVISO_VENCIDOS = "egresos_vencidos"


@dataclass(frozen=True)
class Aviso:
    clave: str
    descripcion: str
    registros: int
    monto: Decimal


def _por_marca(flujo: Flujo, clave: str, marca: str, descripcion: str) -> Aviso:
    filas = flujo.filas_con_marca(marca)
    return Aviso(clave=clave, descripcion=descripcion, registros=len(filas),
                 monto=sum((f.monto for f in filas), CERO))


def avisos(flujo: Flujo) -> Tuple[Aviso, ...]:
    """Los tres avisos, siempre presentes y en orden alfabético de clave (en cero si no hay casos)."""
    return (
        _por_marca(flujo, AVISO_SALDO_ACREEDOR, MARCA_SALDO_ACREEDOR,
                   "CxC con saldo acreedor, restado en la semana 1"),
        Aviso(clave=AVISO_SALDO_CERO, descripcion="CxC con saldo cero, sin filas",
              registros=flujo.registros_en_cero, monto=CERO),
        _por_marca(flujo, AVISO_VENCIDOS, MARCA_VENCIDO, "Egresos vencidos, pagados en la semana 1"),
    )
