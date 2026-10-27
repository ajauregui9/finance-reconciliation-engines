"""Adaptadores de egresos programados: proveedores, nómina e impuestos.

Las tres fuentes comparten la misma mecánica (una fecha de pago y un monto positivo
que sale de caja); cada una declara su esquema: columnas, llave única, columna de
fecha y columna de contraparte.

Un pago con fecha anterior al corte sigue pendiente: se trata como vencido, se ubica
en la semana 1 con la fecha de corte y su fila lleva la marca `vencido`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional, Tuple

from ..calendario import SEMANAS_HORIZONTE, indice_semana
from ..contrato import (
    CONCEPTO_IMPUESTOS,
    CONCEPTO_NOMINA,
    CONCEPTO_PROVEEDORES,
    FUENTE_CXP,
    FUENTE_IMPUESTOS,
    FUENTE_NOMINA,
    MARCA_VENCIDO,
    FilaContrato,
    ResultadoFuente,
    ordenar_filas,
)
from ..dinero import CERO
from ..lectura import Registro, exigir_unicas, leer_tabla

COLUMNA_MONTO = "monto"
COLUMNA_MONEDA = "moneda"
SEPARADOR_REFERENCIA = "/"
SEMANA_VENCIDOS = 1


@dataclass(frozen=True)
class EsquemaEgreso:
    fuente: str
    concepto: str
    columnas: Tuple[str, ...]
    llave: Tuple[str, ...]
    columna_fecha: str
    columna_contraparte: str
    descripcion_llave: str


ESQUEMA_CXP = EsquemaEgreso(
    fuente=FUENTE_CXP, concepto=CONCEPTO_PROVEEDORES,
    columnas=("proveedor_id", "proveedor", "factura", "fecha_programada", COLUMNA_MONEDA, COLUMNA_MONTO),
    llave=("proveedor_id", "factura"), columna_fecha="fecha_programada", columna_contraparte="proveedor",
    descripcion_llave="la factura de proveedor",
)
ESQUEMA_NOMINA = EsquemaEgreso(
    fuente=FUENTE_NOMINA, concepto=CONCEPTO_NOMINA,
    columnas=("periodo", "descripcion", "fecha_pago", COLUMNA_MONEDA, COLUMNA_MONTO),
    llave=("periodo",), columna_fecha="fecha_pago", columna_contraparte="descripcion",
    descripcion_llave="el periodo de nómina",
)
ESQUEMA_IMPUESTOS = EsquemaEgreso(
    fuente=FUENTE_IMPUESTOS, concepto=CONCEPTO_IMPUESTOS,
    columnas=("impuesto", "periodo_fiscal", "fecha_limite", COLUMNA_MONEDA, COLUMNA_MONTO),
    llave=("impuesto", "periodo_fiscal"), columna_fecha="fecha_limite", columna_contraparte="impuesto",
    descripcion_llave="el impuesto del periodo",
)


@dataclass(frozen=True)
class Egreso:
    """Un pago programado; `fecha` es la del insumo y `vencido` indica que es anterior al corte."""

    referencia: str
    contraparte: str
    fecha: date
    semana: int
    monto: Decimal
    vencido: bool

    def fila(self, esquema: EsquemaEgreso, corte: date) -> Optional[FilaContrato]:
        """Fila contrato con signo de salida, o `None` si el pago cae después del horizonte."""
        if self.semana > SEMANAS_HORIZONTE:
            return None
        return FilaContrato(
            fuente=esquema.fuente, concepto=esquema.concepto, semana=self.semana,
            fecha=corte if self.vencido else self.fecha, referencia=self.referencia,
            contraparte=self.contraparte, monto=-self.monto, marca=MARCA_VENCIDO if self.vencido else None,
        )


def _egreso(registro: Registro, esquema: EsquemaEgreso, corte: date, moneda: str) -> Egreso:
    registro.exigir_moneda(COLUMNA_MONEDA, moneda)
    monto = registro.monto(COLUMNA_MONTO)
    if monto <= CERO:
        raise registro.falla_en(COLUMNA_MONTO, f"el monto debe ser mayor que cero y vale {monto}")
    fecha = registro.fecha(esquema.columna_fecha)
    vencido = fecha < corte
    return Egreso(
        referencia=SEPARADOR_REFERENCIA.join(registro.texto(c) for c in esquema.llave),
        contraparte=registro.texto(esquema.columna_contraparte),
        fecha=fecha, semana=SEMANA_VENCIDOS if vencido else indice_semana(fecha, corte), monto=monto,
        vencido=vencido,
    )


def leer_egresos(ruta: Path, esquema: EsquemaEgreso, corte: date, moneda: str) -> ResultadoFuente:
    tabla = leer_tabla(ruta, esquema.columnas)
    egresos = tuple(_egreso(r, esquema, corte, moneda) for r in tabla.registros)
    llaves = [tuple(r.texto(c) for c in esquema.llave) for r in tabla.registros]
    exigir_unicas(tabla.registros, llaves, esquema.descripcion_llave)
    filas = tuple(f for f in (e.fila(esquema, corte) for e in egresos) if f is not None)
    return ResultadoFuente(
        fuente=esquema.fuente, archivo=tabla.archivo, sha256=tabla.sha256, registros=len(tabla.registros),
        total_insumo=-sum((e.monto for e in egresos), CERO), filas=ordenar_filas(filas),
        fuera_horizonte=-sum((e.monto for e in egresos if e.semana > SEMANAS_HORIZONTE), CERO),
        no_cobrable=CERO,
    )


def leer_cxp(ruta: Path, corte: date, moneda: str) -> ResultadoFuente:
    return leer_egresos(ruta, ESQUEMA_CXP, corte, moneda)


def leer_nomina(ruta: Path, corte: date, moneda: str) -> ResultadoFuente:
    return leer_egresos(ruta, ESQUEMA_NOMINA, corte, moneda)


def leer_impuestos(ruta: Path, corte: date, moneda: str) -> ResultadoFuente:
    return leer_egresos(ruta, ESQUEMA_IMPUESTOS, corte, moneda)
