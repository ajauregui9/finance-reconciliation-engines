"""Lector de archivos de liquidación (spec, sección 2.1).

Cada problema detiene la lectura con un `ErrorInsumo` que nombra archivo, fila y columna.
Las únicas líneas que se saltan son las completamente vacías, que no traen datos.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from frontera import ErrorFrontera, leer_entero

from .dinero import a_decimal
from .errores import ErrorInsumo
from .huso import interpretar_huso, leer_fecha_hora, validar_mes
from .modelo import COLUMNAS_MONTO, ArchivoLiquidacion, FilaLiquidacion, Montos

CLAVE_PERIODO = "Periodo"
CLAVE_HUSO = "Huso horario"
CLAVE_MONEDA = "Moneda"

COLUMNA_FECHA = "Fecha y hora"
COLUMNA_FECHA_PEDIDO = "Fecha del pedido"
COLUMNA_CANTIDAD = "Cantidad"
COLUMNA_TOTAL = "Total"
_ENCABEZADOS_MONTO = (
    "Venta de productos", "IVA de la venta", "Envío cobrado", "IVA del envío",
    "Descuento promocional", "IVA del descuento", "Retención de plataforma",
    "Comisión por venta", "Tarifa de logística", "Otras tarifas",
)
ENCABEZADO: Tuple[str, ...] = (
    COLUMNA_FECHA, "Tipo", "Pedido", COLUMNA_FECHA_PEDIDO, "SKU", "Descripción", COLUMNA_CANTIDAD,
    *_ENCABEZADOS_MONTO, COLUMNA_TOTAL,
)
_CAMPO_DE_COLUMNA = dict(zip(_ENCABEZADOS_MONTO, COLUMNAS_MONTO))


class _Contexto:
    """Arma mensajes de error con el nombre del archivo."""

    def __init__(self, nombre: str) -> None:
        self.nombre = nombre

    def error(self, detalle: str, fila: Optional[int] = None, columna: Optional[str] = None) -> ErrorInsumo:
        partes = [self.nombre]
        if fila is not None:
            partes.append(f"fila {fila}")
        if columna is not None:
            partes.append(f"columna '{columna}'")
        return ErrorInsumo(", ".join(partes) + f": {detalle}")


def _preambulo(renglones: Sequence[List[str]], ctx: _Contexto) -> Tuple[Dict[str, str], int]:
    """Pares clave,valor hasta la primera línea vacía. Devuelve también dónde sigue."""
    metadatos: Dict[str, str] = {}
    for indice, renglon in enumerate(renglones):
        if not any(celda.strip() for celda in renglon):
            return metadatos, indice + 1
        if len(renglon) != 2:
            raise ctx.error(f"el preámbulo espera pares clave,valor y la línea {indice + 1} trae {len(renglon)} celdas")
        clave, valor = renglon[0].strip(), renglon[1].strip()
        if clave in metadatos:
            raise ctx.error(f"clave repetida en el preámbulo: '{clave}'")
        metadatos[clave] = valor
    raise ctx.error("no tiene encabezado: falta la línea vacía que cierra el preámbulo")


def _metadato(metadatos: Mapping[str, str], clave: str, ctx: _Contexto) -> str:
    valor = metadatos.get(clave, "")
    if not valor:
        raise ctx.error(f"falta la clave obligatoria '{clave}' en el preámbulo")
    return valor


def _fecha(texto: str, huso: timezone, ctx: _Contexto, numero: int, columna: str) -> datetime:
    try:
        return leer_fecha_hora(texto, huso)
    except ValueError as exc:
        raise ctx.error(str(exc), numero, columna) from exc


def _monto(valores: Mapping[str, str], columna: str, ctx: _Contexto, numero: int) -> Decimal:
    try:
        return a_decimal(valores[columna], vacio_es_cero=True)
    except ValueError as exc:
        raise ctx.error(str(exc), numero, columna) from exc



def _cantidad(texto: str, ctx: _Contexto, numero: int) -> int:
    if not texto.strip():
        return 0
    try:
        return leer_entero(texto, negativo=True)
    except ErrorFrontera as exc:
        raise ctx.error(f"se espera un entero: {exc}", numero, COLUMNA_CANTIDAD) from exc


def _fila(celdas: List[str], numero: int, periodo: str, huso: timezone, ctx: _Contexto) -> FilaLiquidacion:
    if len(celdas) != len(ENCABEZADO):
        raise ctx.error(f"se esperan {len(ENCABEZADO)} columnas y hay {len(celdas)}", numero)
    valores = dict(zip(ENCABEZADO, celdas))
    instante = _fecha(valores[COLUMNA_FECHA], huso, ctx, numero, COLUMNA_FECHA)
    if instante.strftime("%Y-%m") != periodo:
        raise ctx.error(f"fecha local fuera del periodo declarado {periodo}", numero, COLUMNA_FECHA)
    instante_pedido = None
    if valores[COLUMNA_FECHA_PEDIDO].strip():
        instante_pedido = _fecha(valores[COLUMNA_FECHA_PEDIDO], huso, ctx, numero, COLUMNA_FECHA_PEDIDO)
        if instante_pedido > instante:
            raise ctx.error("el pedido es posterior a su liquidación", numero, COLUMNA_FECHA_PEDIDO)
    montos = Montos(**{campo: _monto(valores, columna, ctx, numero) for columna, campo in _CAMPO_DE_COLUMNA.items()})
    total = _monto(valores, COLUMNA_TOTAL, ctx, numero)
    if montos.suma_columnas() != total:
        raise ctx.error(f"la suma de columnas {montos.suma_columnas()} no cuadra con Total {total}", numero)
    return FilaLiquidacion(
        archivo=ctx.nombre, numero=numero, instante=instante, tipo=valores["Tipo"].strip(),
        pedido=valores["Pedido"].strip(), instante_pedido=instante_pedido, sku=valores["SKU"].strip(),
        descripcion=valores["Descripción"].strip(), cantidad=_cantidad(valores[COLUMNA_CANTIDAD], ctx, numero),
        montos=montos, total=total,
    )


def leer_liquidacion_texto(texto: str, nombre: str, moneda: str) -> ArchivoLiquidacion:
    """Interpreta el contenido de un archivo de liquidación."""
    ctx = _Contexto(nombre)
    renglones = list(csv.reader(io.StringIO(texto.lstrip("﻿"))))
    metadatos, inicio = _preambulo(renglones, ctx)
    try:
        periodo = validar_mes(_metadato(metadatos, CLAVE_PERIODO, ctx))
        huso_texto = _metadato(metadatos, CLAVE_HUSO, ctx)
        huso = interpretar_huso(huso_texto)
    except ValueError as exc:
        raise ctx.error(str(exc)) from exc
    moneda_archivo = _metadato(metadatos, CLAVE_MONEDA, ctx)
    if moneda_archivo != moneda:
        raise ctx.error(f"'{CLAVE_MONEDA}' es {moneda_archivo} y la config espera {moneda}")
    if inicio >= len(renglones) or tuple(c.strip() for c in renglones[inicio]) != ENCABEZADO:
        raise ctx.error("el encabezado no es el esperado: " + ",".join(ENCABEZADO))
    datos = renglones[inicio + 1:]
    filas = tuple(
        _fila(celdas, numero, periodo, huso, ctx)
        for numero, celdas in enumerate(datos, start=1)
        if any(celda.strip() for celda in celdas)
    )
    return ArchivoLiquidacion(nombre=nombre, periodo=periodo, huso_texto=huso_texto, huso=huso,
                              moneda=moneda_archivo, filas=filas)


def leer_liquidacion(ruta: Path, moneda: str) -> ArchivoLiquidacion:
    """Lee un archivo de liquidación del disco."""
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ErrorInsumo(f"{ruta.name}: no se pudo leer ({exc})") from exc
    return leer_liquidacion_texto(texto, nombre=ruta.name, moneda=moneda)
