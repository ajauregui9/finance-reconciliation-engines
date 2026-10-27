"""Propuestas de carga derivadas del cuadre: un vendor bill por cada factura sin registro.

Una propuesta es solo un borrador para revisión humana; pasa por la misma validación que
cualquier otro archivo de carga.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from netsuite_gl.carga_modelo import AsientoCarga, LineaCarga
from netsuite_gl.carga_validacion import Catalogo, leer_catalogo
from netsuite_gl.config import ConfigEsquema
from netsuite_gl.consultas import ErrorConsulta, Valor, ejecutar_por_nombre
from netsuite_gl.filas import MEMO_IVA

MOTIVO_NOTA_CREDITO = "nota_credito_requiere_vendor_credit"
MOTIVO_SIN_PROVEEDOR = "proveedor_no_existe_en_catalogo"
PREFIJO_ID_EXTERNO = "CFDI-"
CONSULTA_ORIGEN = "cfdi_sin_registro"


@dataclass(frozen=True)
class Pendiente:
    """Un CFDI sin registro que no se puede proponer como vendor bill, con su motivo."""

    uuid: str
    motivo: str


@dataclass(frozen=True)
class Propuesta:
    asientos: Tuple[AsientoCarga, ...]
    pendientes: Tuple[Pendiente, ...]


def proponer_facturas_sin_registro(conexion: sqlite3.Connection, config: ConfigEsquema) -> Propuesta:
    """Convierte cada factura (tipo I) de `cfdi_sin_registro` en un vendor bill propuesto."""
    resultado = ejecutar_por_nombre(conexion, CONSULTA_ORIGEN)
    catalogo = leer_catalogo(conexion)
    asientos: List[AsientoCarga] = []
    pendientes: List[Pendiente] = []
    for valores in resultado.filas:
        fila = dict(zip(resultado.columnas, valores))
        uuid = _texto(fila, "uuid")
        if _texto(fila, "tipo") != "I":
            pendientes.append(Pendiente(uuid, MOTIVO_NOTA_CREDITO))
            continue
        entidad = _proveedor(conexion, _texto(fila, "rfc_emisor"), _texto(fila, "emisor"))
        if entidad is None:
            pendientes.append(Pendiente(uuid, MOTIVO_SIN_PROVEEDOR))
            continue
        asientos.append(_vendor_bill(fila, entidad, catalogo, config))
    return Propuesta(tuple(asientos), tuple(pendientes))


def _vendor_bill(fila: Dict[str, Valor], entidad: str, catalogo: Catalogo, config: ConfigEsquema) -> AsientoCarga:
    concepto = _texto(fila, "concepto")
    regla = config.gasto_por_concepto.get(concepto, config.gasto_default)
    fecha = date.fromisoformat(_texto(fila, "fecha"))
    iva = _monto(fila, "iva")
    lineas = [_linea(regla.cuenta, _monto(fila, "subtotal"), None, regla.clase, concepto)]
    if iva > 0:
        lineas.append(_linea(config.cuenta_iva, iva, None, regla.clase, MEMO_IVA))
    lineas.append(_linea(config.cuenta_proveedores, None, _monto(fila, "total"), regla.clase, concepto, entidad))
    return AsientoCarga(
        id_externo=PREFIJO_ID_EXTERNO + _texto(fila, "uuid"),
        fecha=fecha,
        periodo=_periodo_de(fecha, catalogo),
        memo=concepto,
        referencia=_texto(fila, "referencia"),
        lineas=tuple(lineas),
    )


def _linea(
    cuenta: str, debito: Optional[Decimal], credito: Optional[Decimal], clase: str, memo: str,
    entidad: Optional[str] = None,
) -> LineaCarga:
    cero = Decimal("0.00")
    return LineaCarga(cuenta, debito or cero, credito or cero, clase, entidad, memo)


def _periodo_de(fecha: date, catalogo: Catalogo) -> str:
    """Nombre del mes de registro que contiene la fecha; vacío si no existe (la validación lo rechaza)."""
    return next(
        (p.nombre for p in sorted(catalogo.periodos.values(), key=lambda x: x.inicio)
         if p.es_registro and p.inicio <= fecha <= p.fin),
        "",
    )


def _proveedor(conexion: sqlite3.Connection, rfc: str, nombre: str) -> Optional[str]:
    fila = conexion.execute(
        "SELECT entityid FROM vendor WHERE custentity_mx_rfc = ? AND companyname = ? AND isinactive = 'F' "
        "ORDER BY entityid LIMIT 1",
        (rfc, nombre),
    ).fetchone()
    return None if fila is None else str(fila[0])


def _texto(fila: Dict[str, Valor], columna: str) -> str:
    valor = fila[columna]
    if not isinstance(valor, str):
        raise ErrorConsulta(f"{CONSULTA_ORIGEN}: la columna {columna} debería ser texto, trae {valor!r}")
    return valor


def _monto(fila: Dict[str, Valor], columna: str) -> Decimal:
    valor = fila[columna]
    if not isinstance(valor, Decimal):
        raise ErrorConsulta(f"{CONSULTA_ORIGEN}: la columna {columna} debería ser monto, trae {valor!r}")
    return valor
