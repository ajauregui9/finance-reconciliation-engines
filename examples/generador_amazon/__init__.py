"""Generador determinista de meses sintéticos de liquidación de Amazon.

Produce cuatro liquidaciones con husos distintos, cohorte cola (una negativa), publicidad
en tres fuentes, un mes con retención fuera de banda, la venta del ERP y un oráculo con
la respuesta esperada. Todos los nombres y montos son ficticios.
"""
from __future__ import annotations

import random
from decimal import Decimal
from typing import Dict, List, Mapping, Sequence

from .consola import facturas, gasto_consola, total_por_mes
from .escritura import escribir, texto_consola, texto_json, texto_liquidacion
from .filas import Fila, con_transferencias, fila_reembolso, fila_venta, filas_cargos, filas_publicidad
from .montos import CERO, texto
from .oraculo import armar_oraculo
from .parametros import ParametrosGenerador
from .pedidos import Venta, generar_reembolsos, generar_ventas
from .tiempo import huso, mes_de

__all__ = ["ParametrosGenerador", "escribir", "generar"]


def _venta_erp(filas_por_archivo: Mapping[str, Sequence[Fila]], ventas: Sequence[Venta],
               p: ParametrosGenerador) -> Dict[str, Decimal]:
    """Venta neta por mes de pedido: lo liquidado más lo que sigue pendiente."""
    cierre = huso(p.huso_cierre)
    venta = {mes: CERO for mes in p.meses}
    for filas in filas_por_archivo.values():
        for f in filas:
            if f.es_de_pedido and f.pedido_en is not None:
                cohorte = mes_de(f.pedido_en, cierre)
                venta[cohorte] = venta[cohorte] + f.monto("venta_productos") + f.monto("descuento_promocional")
    for v in ventas:
        if v.liquidada_en is None:
            cohorte = mes_de(v.pedido_en, cierre)
            venta[cohorte] = venta[cohorte] + v.venta_neta(p.descuento)
    return venta


def _verificar_periodo(filas: Sequence[Fila], periodo: str, huso_texto: str) -> None:
    zona = huso(huso_texto)
    ajenas = [f.pedido or f.tipo for f in filas if mes_de(f.instante, zona) != periodo]
    if ajenas:
        raise RuntimeError(f"autoverificación: filas fuera del periodo local {periodo}: {ajenas}")


def generar(p: ParametrosGenerador) -> Dict[str, str]:
    """Devuelve nombre de archivo -> contenido, sin tocar el disco."""
    rng = random.Random(p.semilla)
    ventas = generar_ventas(rng, p)
    reembolsos = generar_reembolsos(rng, ventas, p)
    consola = gasto_consola(rng, p)
    gasto_mes = total_por_mes(consola, p)
    filas_por_archivo: Dict[str, List[Fila]] = {}
    for periodo in p.meses:
        zona = huso(p.huso_de[periodo])
        filas = [fila_venta(v, p) for v in ventas if v.periodo_archivo == periodo]
        filas += [fila_reembolso(r, p) for r in reembolsos if r.periodo_archivo == periodo]
        filas += filas_cargos(rng, periodo, zona, p) + filas_publicidad(periodo, zona, gasto_mes[periodo], p)
        filas_por_archivo[periodo] = con_transferencias(filas, periodo, zona)
        _verificar_periodo(filas_por_archivo[periodo], periodo, p.huso_de[periodo])
    venta_erp = _venta_erp(filas_por_archivo, ventas, p)
    archivos = {f"liquidacion_{periodo}.csv": texto_liquidacion(periodo, p.huso_de[periodo], filas)
                for periodo, filas in filas_por_archivo.items()}
    archivos["publicidad_consola.csv"] = texto_consola(consola)
    archivos["facturas_publicidad.json"] = texto_json(
        {"esquema": "facturas_publicidad/v1", "facturas": facturas(gasto_mes, p)})
    archivos["venta_erp.json"] = texto_json({
        "esquema": "venta_erp/v1",
        "nota": "Venta neta sin IVA por mes de pedido (huso de cierre), incluye lo que aún no se liquida.",
        "venta_neta_por_mes_de_pedido": {mes: texto(v) for mes, v in venta_erp.items()},
    })
    archivos["oraculo.json"] = texto_json(armar_oraculo(filas_por_archivo, ventas, gasto_mes, venta_erp, p))
    return archivos
