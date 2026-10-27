"""Utilidades compartidas por las pruebas del cierre de Amazon (no contiene pruebas).

Arma liquidaciones CSV pequeñas en memoria y configs de prueba, para que cada prueba
declare solo lo que le importa.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

RAIZ = Path(__file__).resolve().parents[1]
DIR_AMAZON = RAIZ / "skills" / "marketplace-expenses" / "amazon"
DIR_EJEMPLOS = RAIZ / "examples"
DIR_SINTETICO = DIR_EJEMPLOS / "synthetic_amazon"
CONFIG_EJEMPLO = DIR_AMAZON / "config" / "cierre.example.json"

for _ruta in (DIR_AMAZON, DIR_EJEMPLOS):
    if str(_ruta) not in sys.path:
        sys.path.insert(0, str(_ruta))

COLUMNAS_MONTO = (
    "venta_productos", "iva_venta", "envio_cobrado", "iva_envio", "descuento_promocional",
    "iva_descuento", "retencion", "comision", "logistica", "otras_tarifas",
)
ENCABEZADO = (
    "Fecha y hora,Tipo,Pedido,Fecha del pedido,SKU,Descripción,Cantidad,Venta de productos,"
    "IVA de la venta,Envío cobrado,IVA del envío,Descuento promocional,IVA del descuento,"
    "Retención de plataforma,Comisión por venta,Tarifa de logística,Otras tarifas,Total"
)


def fila(fecha_hora: str, tipo: str = "Pedido", pedido: str = "P-1",
         fecha_pedido: Optional[str] = None, total: Optional[str] = None,
         cantidad: str = "1", sku: str = "SKU-1", **montos: str) -> Dict[str, str]:
    """Una fila de liquidación. El total se calcula si no se da."""
    desconocidas = set(montos) - set(COLUMNAS_MONTO)
    if desconocidas:
        raise KeyError(f"columnas desconocidas: {sorted(desconocidas)}")
    datos = {c: montos.get(c, "") for c in COLUMNAS_MONTO}
    if total is None:
        suma = sum((Decimal(v.replace(",", "")) for v in datos.values() if v), Decimal("0.00"))
        total = f"{suma:.2f}"
    return {
        "fecha_hora": fecha_hora, "tipo": tipo, "pedido": pedido,
        "fecha_pedido": fecha_hora if fecha_pedido is None else fecha_pedido,
        "sku": sku, "descripcion": f"Articulo {sku}", "cantidad": cantidad,
        **datos, "total": total,
    }


def venta(fecha_hora: str, pedido: str, venta_productos: str, fecha_pedido: Optional[str] = None,
          comision: str = "", logistica: str = "", retencion: str = "",
          descuento: str = "", otras: str = "", tipo: str = "Pedido") -> Dict[str, str]:
    """Fila de pedido con los montos más usados."""
    return fila(fecha_hora, tipo=tipo, pedido=pedido, fecha_pedido=fecha_pedido,
                venta_productos=venta_productos, comision=comision, logistica=logistica,
                retencion=retencion, descuento_promocional=descuento, otras_tarifas=otras)


def cargo(fecha_hora: str, tipo: str, monto: str) -> Dict[str, str]:
    """Fila sin pedido (almacenaje, publicidad, transferencia...)."""
    return fila(fecha_hora, tipo=tipo, pedido="", fecha_pedido="", cantidad="", sku="",
                otras_tarifas=monto)


def csv_liquidacion(periodo: str, huso: str, filas: Sequence[Mapping[str, str]],
                    moneda: str = "MXN", preambulo_extra: Sequence[Sequence[str]] = (),
                    encabezado: str = ENCABEZADO) -> str:
    """Texto CSV de una liquidación con preámbulo, fila vacía, encabezado y filas."""
    salida = io.StringIO()
    escritor = csv.writer(salida, lineterminator="\n")
    escritor.writerow(["Reporte de liquidación", "Sintético"])
    escritor.writerow(["Periodo", periodo])
    escritor.writerow(["Huso horario", huso])
    escritor.writerow(["Moneda", moneda])
    for extra in preambulo_extra:
        escritor.writerow(list(extra))
    escritor.writerow([])
    salida.write(encabezado + "\n")
    orden = ("fecha_hora", "tipo", "pedido", "fecha_pedido", "sku", "descripcion", "cantidad",
             *COLUMNAS_MONTO, "total")
    for f in filas:
        escritor.writerow([f[c] for c in orden])
    return salida.getvalue()


def config_dict(**cambios: Any) -> Dict[str, Any]:
    """Config de ejemplo como dict, con cambios de primer nivel."""
    datos: Dict[str, Any] = json.loads(CONFIG_EJEMPLO.read_text(encoding="utf-8"))
    datos.update(cambios)
    return datos


def escribir_insumos(directorio: Path, liquidaciones: Mapping[str, str],
                     consola: Optional[str] = None,
                     facturas: Optional[List[Dict[str, str]]] = None,
                     venta_erp: Optional[Dict[str, str]] = None) -> Path:
    """Escribe un directorio de insumos con los nombres que espera el paquete."""
    directorio.mkdir(parents=True, exist_ok=True)
    for periodo, texto in liquidaciones.items():
        (directorio / f"liquidacion_{periodo}.csv").write_text(texto, encoding="utf-8")
    if consola is not None:
        (directorio / "publicidad_consola.csv").write_text(consola, encoding="utf-8")
    if facturas is not None:
        documento = {"esquema": "facturas_publicidad/v1", "facturas": facturas}
        (directorio / "facturas_publicidad.json").write_text(json.dumps(documento), encoding="utf-8")
    if venta_erp is not None:
        documento_erp = {"esquema": "venta_erp/v1", "venta_neta_por_mes_de_pedido": venta_erp}
        (directorio / "venta_erp.json").write_text(json.dumps(documento_erp), encoding="utf-8")
    return directorio
