"""Escritura determinista de los insumos sintéticos: CSV UTF-8 sin BOM, LF y filas ordenadas.

Además de los cinco CSV escribe `totales_control.json`, la verdad conocida (registros y
suma por archivo, más el conteo de casos especiales plantados) contra la que las
pruebas cuadran al motor.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Dict, Iterable, Sequence, Tuple

from .fabricas import DatosFlujo

CENTAVO = Decimal("0.01")
ESQUEMA_CONTROL = "totales_control_flujo/v2"
SANGRIA = 2
FUENTE_SALDOS = "saldos_bancarios"
FUENTE_CXC = "cxc_antiguedad"
FUENTE_CXP = "cxp_programadas"
FUENTE_NOMINA = "nomina"
FUENTE_IMPUESTOS = "impuestos"
ARCHIVO_CONTROL = "totales_control.json"
ENCABEZADOS: Dict[str, Tuple[str, ...]] = {
    FUENTE_SALDOS: ("cuenta", "banco", "fecha_saldo", "moneda", "saldo"),
    FUENTE_CXC: ("cliente_id", "cliente", "factura", "fecha_factura", "fecha_vencimiento", "moneda", "saldo"),
    FUENTE_CXP: ("proveedor_id", "proveedor", "factura", "fecha_programada", "moneda", "monto"),
    FUENTE_NOMINA: ("periodo", "descripcion", "fecha_pago", "moneda", "monto"),
    FUENTE_IMPUESTOS: ("impuesto", "periodo_fiscal", "fecha_limite", "moneda", "monto"),
}
ARCHIVOS: Tuple[str, ...] = tuple(sorted([f"{f}.csv" for f in ENCABEZADOS] + [ARCHIVO_CONTROL]))

Filas = Tuple[Tuple[str, ...], ...]


def _texto(monto: Decimal) -> str:
    return f"{monto.quantize(CENTAVO, rounding=ROUND_HALF_UP):.2f}"


def _csv(encabezado: Sequence[str], filas: Iterable[Sequence[str]]) -> str:
    memoria = io.StringIO()
    escritor = csv.writer(memoria, lineterminator="\n")
    escritor.writerow(encabezado)
    escritor.writerows(filas)
    return memoria.getvalue()


def _filas(datos: DatosFlujo) -> Dict[str, Filas]:
    """Filas de texto por fuente, ordenadas por su llave natural."""
    m = datos.parametros.moneda
    corte = datos.parametros.corte.isoformat()
    saldos = sorted(datos.saldos, key=lambda s: s.cuenta)
    cxc = sorted(datos.cxc, key=lambda f: f.factura)
    cxp = sorted(datos.cxp, key=lambda f: (f.proveedor_id, f.factura))
    nomina = sorted(datos.nomina, key=lambda n: (n.fecha_pago, n.periodo))
    impuestos = sorted(datos.impuestos, key=lambda i: (i.fecha_limite, i.impuesto, i.periodo_fiscal))
    return {
        FUENTE_SALDOS: tuple((s.cuenta, s.banco, corte, m, _texto(s.saldo)) for s in saldos),
        FUENTE_CXC: tuple(
            (f.cliente_id, f.cliente, f.factura, f.fecha_factura.isoformat(), f.fecha_vencimiento.isoformat(), m,
             _texto(f.saldo)) for f in cxc
        ),
        FUENTE_CXP: tuple(
            (f.proveedor_id, f.proveedor, f.factura, f.fecha_programada.isoformat(), m, _texto(f.monto)) for f in cxp
        ),
        FUENTE_NOMINA: tuple((n.periodo, n.descripcion, n.fecha_pago.isoformat(), m, _texto(n.monto)) for n in nomina),
        FUENTE_IMPUESTOS: tuple(
            (i.impuesto, i.periodo_fiscal, i.fecha_limite.isoformat(), m, _texto(i.monto)) for i in impuestos
        ),
    }


def _casos(datos: DatosFlujo) -> Dict[str, Dict[str, object]]:
    """Casos especiales plantados: CxC con saldo acreedor o cero y egresos anteriores al corte."""
    corte = datos.parametros.corte
    acreedores = [f.saldo for f in datos.cxc if f.saldo < 0]
    egresos = (
        [(f.fecha_programada, f.monto) for f in datos.cxp]
        + [(n.fecha_pago, n.monto) for n in datos.nomina]
        + [(i.fecha_limite, i.monto) for i in datos.impuestos]
    )
    vencidos = [monto for fecha, monto in egresos if fecha < corte]
    return {
        "cxc_saldo_acreedor": {"registros": len(acreedores), "suma": _texto(sum(acreedores, Decimal(0)))},
        "cxc_saldo_cero": {"registros": sum(1 for f in datos.cxc if f.saldo == 0)},
        "egresos_vencidos": {"registros": len(vencidos), "suma": _texto(sum(vencidos, Decimal(0)))},
    }


def _control(datos: DatosFlujo, filas: Dict[str, Filas]) -> str:
    fuentes = {
        fuente: {
            "archivo": f"{fuente}.csv",
            "registros": len(filas[fuente]),
            "suma": _texto(sum((Decimal(fila[-1]) for fila in filas[fuente]), Decimal(0))),
        }
        for fuente in ENCABEZADOS
    }
    documento = {
        "esquema": ESQUEMA_CONTROL,
        "corte": datos.parametros.corte.isoformat(),
        "moneda": datos.parametros.moneda,
        "semilla": datos.parametros.semilla,
        "fuentes": fuentes,
        "casos": _casos(datos),
    }
    return json.dumps(documento, ensure_ascii=False, sort_keys=True, indent=SANGRIA) + "\n"


def contenidos(datos: DatosFlujo) -> Dict[str, str]:
    """Nombre de archivo -> texto completo, listo para escribirse."""
    filas = _filas(datos)
    salida = {f"{fuente}.csv": _csv(ENCABEZADOS[fuente], filas[fuente]) for fuente in ENCABEZADOS}
    return {**salida, ARCHIVO_CONTROL: _control(datos, filas)}


def escribir_salida(datos: DatosFlujo, directorio: Path) -> Tuple[Path, ...]:
    textos = contenidos(datos)
    directorio.mkdir(parents=True, exist_ok=True)
    rutas = tuple(directorio / nombre for nombre in sorted(textos))
    for ruta in rutas:
        ruta.write_bytes(textos[ruta.name].encode("utf-8"))
    return rutas
