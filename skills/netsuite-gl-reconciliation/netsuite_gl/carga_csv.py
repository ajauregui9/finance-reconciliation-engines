"""CSV de carga para el CSV import de NetSuite, solo después de una validación sin errores.

El archivo es para revisión humana: este módulo nunca lo sube ni escribe en el ERP.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Sequence, Tuple

from netsuite_gl.carga_modelo import AsientoCarga, LineaCarga
from netsuite_gl.carga_validacion import (
    FORMATO_JOURNAL,
    Catalogo,
    ErrorCarga,
    es_linea_de_proveedores,
    validar_asientos,
)
from netsuite_gl.montos import formatear
from netsuite_gl.salida import tabla_a_csv

ENCABEZADO_JOURNAL: Tuple[str, ...] = (
    "External ID", "Date", "Posting Period", "Memo", "Account", "Debit", "Credit", "Class", "Name", "Line Memo",
)
ENCABEZADO_VENDOR_BILL: Tuple[str, ...] = (
    "External ID", "Vendor", "Date", "Posting Period", "Reference No.", "Memo", "Account", "Amount", "Class",
    "Line Memo",
)
# Preferencia de fecha de la cuenta de ejemplo (DD/MM/AAAA). Debe coincidir con la del usuario que importa.
FORMATO_FECHA = "%d/%m/%Y"


class CargaRechazada(Exception):
    """El archivo completo se rechaza; `errores` trae todos los problemas encontrados."""

    def __init__(self, errores: Sequence[ErrorCarga]) -> None:
        self.errores: Tuple[ErrorCarga, ...] = tuple(errores)
        sufijo = "error" if len(self.errores) == 1 else "errores"
        super().__init__(f"CSV de carga rechazado completo: {len(self.errores)} {sufijo}")


def generar_csv(asientos: Sequence[AsientoCarga], catalogo: Catalogo, formato: str) -> str:
    """Valida todo y, solo si no hay errores, devuelve el texto CSV (UTF-8, LF)."""
    errores = validar_asientos(asientos, catalogo, formato)
    if errores:
        raise CargaRechazada(errores)
    if formato == FORMATO_JOURNAL:
        return tabla_a_csv(ENCABEZADO_JOURNAL, _filas_journal(asientos, catalogo))
    return tabla_a_csv(ENCABEZADO_VENDOR_BILL, _filas_vendor_bill(asientos, catalogo))


def describir_errores(errores: Sequence[ErrorCarga]) -> List[str]:
    """Una línea legible por error, en el orden recibido."""
    return [
        f"{e.id_externo or '(archivo)'}"
        f"{'' if e.linea is None else f' línea {e.linea}'}: [{e.regla}] {e.mensaje}"
        for e in errores
    ]


def _filas_journal(asientos: Sequence[AsientoCarga], catalogo: Catalogo) -> List[List[str]]:
    return [
        [
            a.id_externo, a.fecha.strftime(FORMATO_FECHA), a.periodo, a.memo,
            catalogo.cuentas[linea.cuenta].visible, _importe(linea.debito), _importe(linea.credito),
            linea.clase or "", linea.entidad or "", linea.memo,
        ]
        for a in asientos
        for linea in a.lineas
    ]


def _filas_vendor_bill(asientos: Sequence[AsientoCarga], catalogo: Catalogo) -> List[List[str]]:
    filas: List[List[str]] = []
    for a in asientos:
        proveedor = _proveedor(a, catalogo)
        filas.extend(
            [
                a.id_externo, proveedor, a.fecha.strftime(FORMATO_FECHA), a.periodo, a.referencia or "", a.memo,
                catalogo.cuentas[linea.cuenta].visible, formatear(linea.debito), linea.clase or "", linea.memo,
            ]
            for linea in a.lineas
            if not es_linea_de_proveedores(linea, catalogo)
        )
    return filas


def _proveedor(asiento: AsientoCarga, catalogo: Catalogo) -> str:
    """La entidad de la única línea de proveedores (la validación ya garantizó que existe)."""
    linea: LineaCarga = next(x for x in asiento.lineas if es_linea_de_proveedores(x, catalogo))
    return linea.entidad or ""


def _importe(monto: Decimal) -> str:
    """Celda de débito o crédito: vacía cuando el lado no aplica."""
    return "" if monto == 0 else formatear(monto)
