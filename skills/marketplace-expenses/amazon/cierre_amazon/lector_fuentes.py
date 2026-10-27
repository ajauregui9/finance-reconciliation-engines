"""Lectores de las fuentes que acompañan a la liquidación (spec, secciones 2.2 a 2.4)."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Tuple

from .dinero import a_decimal
from .errores import ErrorInsumo
from .huso import validar_mes
from .modelo import FacturaPublicidad, GastoConsola

ENCABEZADO_CONSOLA = ("Fecha", "Campaña", "Gasto")
ESQUEMA_FACTURAS = "facturas_publicidad/v1"
ESQUEMA_VENTA_ERP = "venta_erp/v1"
CLAVE_VENTA_ERP = "venta_neta_por_mes_de_pedido"


def leer_texto(ruta: Path) -> str:
    """Lee un archivo de texto UTF-8 con un error claro si no se puede."""
    try:
        return ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ErrorInsumo(f"{ruta.name}: no se pudo leer ({exc})") from exc


def leer_json(ruta: Path) -> Any:
    """Lee un archivo JSON; uno mal formado es un `ErrorInsumo`."""
    try:
        return json.loads(leer_texto(ruta))
    except json.JSONDecodeError as exc:
        raise ErrorInsumo(f"{ruta.name}: no es un JSON válido ({exc})") from exc


def _monto(valor: Any, nombre: str, campo: str) -> Decimal:
    try:
        return a_decimal(valor)
    except ValueError as exc:
        raise ErrorInsumo(f"{nombre}: {campo}: {exc}") from exc


def _mes(valor: Any, nombre: str, campo: str) -> str:
    if not isinstance(valor, str):
        raise ErrorInsumo(f"{nombre}: {campo}: el mes debe ser texto AAAA-MM")
    try:
        return validar_mes(valor)
    except ValueError as exc:
        raise ErrorInsumo(f"{nombre}: {campo}: {exc}") from exc


# ------------------------------------------------------------------ consola


def _gasto_consola(celdas: List[str], numero: int, nombre: str) -> GastoConsola:
    lugar = f"{nombre}: fila {numero}"
    if len(celdas) != len(ENCABEZADO_CONSOLA):
        raise ErrorInsumo(f"{lugar}: se esperan {len(ENCABEZADO_CONSOLA)} columnas y hay {len(celdas)}")
    texto_fecha, campana, texto_gasto = (c.strip() for c in celdas)
    try:
        fecha = datetime.strptime(texto_fecha, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ErrorInsumo(f"{lugar}, columna 'Fecha': fecha inválida {texto_fecha!r}") from exc
    if not campana:
        raise ErrorInsumo(f"{lugar}, columna 'Campaña': vacía")
    return GastoConsola(fecha=fecha, campana=campana, gasto=_monto(texto_gasto, lugar, "columna 'Gasto'"))


def leer_consola_texto(texto: str, nombre: str) -> Tuple[GastoConsola, ...]:
    """Interpreta el CSV de la consola de publicidad."""
    renglones = [r for r in csv.reader(io.StringIO(texto.lstrip("﻿"))) if any(c.strip() for c in r)]
    if not renglones:
        raise ErrorInsumo(f"{nombre}: archivo vacío")
    if tuple(c.strip() for c in renglones[0]) != ENCABEZADO_CONSOLA:
        raise ErrorInsumo(f"{nombre}: el encabezado debe ser {','.join(ENCABEZADO_CONSOLA)}")
    return tuple(_gasto_consola(celdas, numero, nombre) for numero, celdas in enumerate(renglones[1:], start=1))


def leer_consola(ruta: Path) -> Tuple[GastoConsola, ...]:
    return leer_consola_texto(leer_texto(ruta), ruta.name)


# ------------------------------------------------------------------ facturas


def _documento(documento: Any, nombre: str, esquema: str) -> Dict[str, Any]:
    if not isinstance(documento, dict):
        raise ErrorInsumo(f"{nombre}: se espera un objeto JSON")
    if documento.get("esquema") != esquema:
        raise ErrorInsumo(f"{nombre}: 'esquema' debe ser {esquema!r}")
    return documento


def _factura(item: Any, indice: int, nombre: str) -> FacturaPublicidad:
    lugar = f"{nombre}: facturas[{indice}]"
    if not isinstance(item, dict):
        raise ErrorInsumo(f"{lugar}: se espera un objeto")
    mes = _mes(item.get("mes"), lugar, "mes")
    folio = item.get("folio")
    if not isinstance(folio, str) or not folio.strip():
        raise ErrorInsumo(f"{lugar}: 'folio' debe ser un texto no vacío")
    importes = {campo: _monto(item.get(campo), lugar, campo) for campo in ("subtotal", "iva", "total")}
    return FacturaPublicidad(mes=mes, folio=folio.strip(), **importes)


def facturas_desde_dict(documento: Any, nombre: str) -> Tuple[FacturaPublicidad, ...]:
    """Valida el documento de facturas de publicidad; un mes repetido es un error."""
    crudas = _documento(documento, nombre, ESQUEMA_FACTURAS).get("facturas")
    if not isinstance(crudas, list):
        raise ErrorInsumo(f"{nombre}: 'facturas' debe ser una lista")
    facturas = tuple(_factura(item, indice, nombre) for indice, item in enumerate(crudas))
    meses = [f.mes for f in facturas]
    repetidos = sorted({m for m in meses if meses.count(m) > 1})
    if repetidos:
        raise ErrorInsumo(f"{nombre}: mes repetido en facturas: {repetidos}")
    return tuple(sorted(facturas, key=lambda f: f.mes))


def leer_facturas(ruta: Path) -> Tuple[FacturaPublicidad, ...]:
    return facturas_desde_dict(leer_json(ruta), ruta.name)


# ------------------------------------------------------------------ venta ERP


def venta_erp_desde_dict(documento: Any, nombre: str) -> Mapping[str, Decimal]:
    """Valida la venta neta del ERP por mes de pedido y la devuelve de solo lectura."""
    crudo = _documento(documento, nombre, ESQUEMA_VENTA_ERP).get(CLAVE_VENTA_ERP)
    if not isinstance(crudo, dict):
        raise ErrorInsumo(f"{nombre}: '{CLAVE_VENTA_ERP}' debe ser un objeto mes -> monto")
    venta = {
        _mes(mes, nombre, f"{CLAVE_VENTA_ERP} (mes)"): _monto(valor, nombre, f"{CLAVE_VENTA_ERP}['{mes}'] (monto)")
        for mes, valor in crudo.items()
    }
    return MappingProxyType(dict(sorted(venta.items())))


def leer_venta_erp(ruta: Path) -> Mapping[str, Decimal]:
    return venta_erp_desde_dict(leer_json(ruta), ruta.name)

