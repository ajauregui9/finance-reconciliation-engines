"""Texto de cada archivo de salida: UTF-8 sin BOM, fin de línea LF, sin marcas de tiempo."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any, Iterable, List, Mapping, Sequence

from .consola import GastoDiario
from .filas import COLUMNAS, Fila
from .montos import texto_csv
from .tiempo import FORMATO, huso

ENCABEZADO_LIQUIDACION = (
    "Fecha y hora", "Tipo", "Pedido", "Fecha del pedido", "SKU", "Descripción", "Cantidad", "Venta de productos",
    "IVA de la venta", "Envío cobrado", "IVA del envío", "Descuento promocional", "IVA del descuento",
    "Retención de plataforma", "Comisión por venta", "Tarifa de logística", "Otras tarifas", "Total",
)


def _csv(renglones: Iterable[Sequence[str]]) -> str:
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    for renglon in renglones:
        escritor.writerow(list(renglon))
    return salida.getvalue()


def texto_liquidacion(periodo: str, huso_texto: str, filas: Sequence[Fila]) -> str:
    zona = huso(huso_texto)
    renglones: List[Sequence[str]] = [
        ("Reporte de liquidación", "Sintético"), ("Cuenta", "VENDEDOR-DEMO"), ("Periodo", periodo),
        ("Huso horario", huso_texto), ("Moneda", "MXN"), (), ENCABEZADO_LIQUIDACION,
    ]
    for f in filas:
        renglones.append((
            f.instante.astimezone(zona).strftime(FORMATO), f.tipo, f.pedido,
            "" if f.pedido_en is None else f.pedido_en.astimezone(zona).strftime(FORMATO),
            f.sku, f.descripcion, "" if f.cantidad is None else str(f.cantidad),
            *(texto_csv(f.monto(c)) for c in COLUMNAS), f"{f.total:,.2f}",
        ))
    return _csv(renglones)


def texto_consola(gastos: Sequence[GastoDiario]) -> str:
    ordenados = sorted(gastos, key=lambda g: (g.fecha, g.campana))
    return _csv([("Fecha", "Campaña", "Gasto")] + [(g.fecha.isoformat(), g.campana, f"{g.gasto:.2f}")
                                                   for g in ordenados])


def texto_json(documento: Mapping[str, Any]) -> str:
    return json.dumps(documento, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def escribir(archivos: Mapping[str, str], directorio: Path) -> List[Path]:
    """Escribe cada archivo en bytes UTF-8 exactos y devuelve las rutas ordenadas."""
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = []
    for nombre in sorted(archivos):
        ruta = directorio / nombre
        ruta.write_bytes(archivos[nombre].encode("utf-8"))
        rutas.append(ruta)
    return rutas
