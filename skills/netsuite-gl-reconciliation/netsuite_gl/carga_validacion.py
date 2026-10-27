"""Validación previa de un archivo de carga contra los catálogos de la base.

Se revisan todos los asientos y se juntan todos los errores: quien llama rechaza el archivo
completo si hay al menos uno. Ninguna regla corrige datos.
"""
from __future__ import annotations

import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import FrozenSet, List, Mapping, Optional, Sequence, Tuple

from netsuite_gl.carga_modelo import AsientoCarga, ErrorEntrada, LineaCarga
from netsuite_gl.config import TIPO_PROVEEDORES
from netsuite_gl.montos import tiene_centavos_exactos

FORMATO_JOURNAL = "journal"
FORMATO_VENDOR_BILL = "vendor_bill"
FORMATOS: Tuple[str, ...] = (FORMATO_JOURNAL, FORMATO_VENDOR_BILL)

# Una hoja de cálculo interpreta como fórmula un texto que empieza así (inyección en CSV).
PREFIJOS_FORMULA: Tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class CuentaCatalogo:
    numero: str
    nombre: str
    tipo: str
    inactiva: bool

    @property
    def visible(self) -> str:
        return f"{self.numero} {self.nombre}"


@dataclass(frozen=True)
class PeriodoCatalogo:
    nombre: str
    inicio: date
    fin: date
    es_registro: bool
    cerrado: bool


@dataclass(frozen=True)
class Catalogo:
    cuentas: Mapping[str, CuentaCatalogo]
    periodos: Mapping[str, PeriodoCatalogo]
    clases_activas: FrozenSet[str]
    proveedores_activos: FrozenSet[str]


@dataclass(frozen=True)
class ErrorCarga:
    id_externo: str
    linea: Optional[int]  # 1-based; None si el error es del asiento completo
    regla: str
    mensaje: str


def leer_catalogo(conexion: sqlite3.Connection) -> Catalogo:
    cuentas = {
        numero: CuentaCatalogo(numero, nombre, tipo, inactiva == "T")
        for numero, nombre, tipo, inactiva in conexion.execute(
            "SELECT acctnumber, fullname, accttype, isinactive FROM account"
        )
    }
    periodos = {
        nombre: PeriodoCatalogo(
            nombre, date.fromisoformat(inicio), date.fromisoformat(fin), registro == "T", cerrado == "T"
        )
        for nombre, inicio, fin, registro, cerrado in conexion.execute(
            "SELECT periodname, startdate, enddate, isposting, closed FROM accountingperiod"
        )
    }
    clases = frozenset(n for (n,) in conexion.execute("SELECT name FROM classification WHERE isinactive = 'F'"))
    proveedores = frozenset(e for (e,) in conexion.execute("SELECT entityid FROM vendor WHERE isinactive = 'F'"))
    return Catalogo(MappingProxyType(cuentas), MappingProxyType(periodos), clases, proveedores)


def validar_asientos(asientos: Sequence[AsientoCarga], catalogo: Catalogo, formato: str) -> Tuple[ErrorCarga, ...]:
    """Todos los errores del archivo, ordenados por (id_externo, línea, regla)."""
    if formato not in FORMATOS:
        raise ErrorEntrada(f"formato desconocido {formato!r}; válidos: {', '.join(FORMATOS)}")
    if not asientos:
        return (ErrorCarga("", None, "archivo_vacio", "el archivo no tiene asientos"),)
    errores = list(_ids_duplicados(asientos))
    for asiento in asientos:
        errores.extend(_errores_de_asiento(asiento, catalogo, formato))
    return tuple(sorted(errores, key=lambda e: (e.id_externo, e.linea or 0, e.regla, e.mensaje)))


def _ids_duplicados(asientos: Sequence[AsientoCarga]) -> List[ErrorCarga]:
    conteo = Counter(a.id_externo for a in asientos)
    return [
        ErrorCarga(ide, None, "id_externo_duplicado", f"el id externo aparece {n} veces en el archivo")
        for ide, n in sorted(conteo.items())
        if n > 1
    ]


def _errores_de_asiento(asiento: AsientoCarga, catalogo: Catalogo, formato: str) -> List[ErrorCarga]:
    errores = _cuadre(asiento) + _periodo(asiento, catalogo) + _textos(asiento)
    for numero, linea in enumerate(asiento.lineas, start=1):
        errores += _linea(asiento.id_externo, numero, linea, catalogo)
    if formato == FORMATO_VENDOR_BILL:
        errores += _factura(asiento, catalogo)
    return errores


def _cuadre(asiento: AsientoCarga) -> List[ErrorCarga]:
    ide = asiento.id_externo
    if len(asiento.lineas) < 2:
        return [ErrorCarga(ide, None, "lineas_insuficientes", "un asiento necesita al menos dos líneas")]
    errores = [
        ErrorCarga(ide, n, "importe_invalido", motivo)
        for n, linea in enumerate(asiento.lineas, start=1)
        for motivo in _motivos_importe(linea)
    ]
    debe = sum((linea.debito for linea in asiento.lineas), Decimal("0"))
    haber = sum((linea.credito for linea in asiento.lineas), Decimal("0"))
    if debe != haber:
        errores.append(ErrorCarga(ide, None, "asiento_descuadrado", f"débitos {debe} ≠ créditos {haber}"))
    return errores


def _motivos_importe(linea: LineaCarga) -> List[str]:
    motivos: List[str] = []
    if linea.debito < 0 or linea.credito < 0:
        motivos.append("los importes no pueden ser negativos")
    if not (tiene_centavos_exactos(linea.debito) and tiene_centavos_exactos(linea.credito)):
        motivos.append("los importes admiten a lo sumo dos decimales")
    if linea.debito != 0 and linea.credito != 0:
        motivos.append("una línea lleva débito o crédito, no ambos")
    if linea.debito == 0 and linea.credito == 0:
        motivos.append("la línea no tiene importe")
    return motivos


def _periodo(asiento: AsientoCarga, catalogo: Catalogo) -> List[ErrorCarga]:
    ide = asiento.id_externo
    periodo = catalogo.periodos.get(asiento.periodo)
    if periodo is None:
        return [ErrorCarga(ide, None, "periodo_inexistente", f"el periodo {asiento.periodo!r} no existe")]
    errores: List[ErrorCarga] = []
    if not periodo.es_registro:
        errores.append(ErrorCarga(ide, None, "periodo_no_registro", f"{periodo.nombre} es un periodo de resumen"))
    if periodo.cerrado:
        errores.append(ErrorCarga(ide, None, "periodo_cerrado", f"{periodo.nombre} está cerrado"))
    if not periodo.inicio <= asiento.fecha <= periodo.fin:
        errores.append(
            ErrorCarga(ide, None, "fecha_fuera_de_periodo", f"la fecha {asiento.fecha} no cae en {periodo.nombre}")
        )
    return errores


def _textos(asiento: AsientoCarga) -> List[ErrorCarga]:
    candidatos: List[Tuple[Optional[int], str, str]] = [
        (None, "id_externo", asiento.id_externo),
        (None, "memo", asiento.memo),
        (None, "referencia", asiento.referencia or ""),
    ]
    candidatos += [(n, "memo de línea", linea.memo) for n, linea in enumerate(asiento.lineas, start=1)]
    return [
        ErrorCarga(asiento.id_externo, numero, "texto_formula", f"{campo} empieza con un carácter de fórmula")
        for numero, campo, texto in candidatos
        if texto.startswith(PREFIJOS_FORMULA)
    ]


def _linea(ide: str, numero: int, linea: LineaCarga, catalogo: Catalogo) -> List[ErrorCarga]:
    errores: List[ErrorCarga] = []
    cuenta = catalogo.cuentas.get(linea.cuenta)
    if cuenta is None:
        errores.append(ErrorCarga(ide, numero, "cuenta_inexistente", f"la cuenta {linea.cuenta} no existe"))
    elif cuenta.inactiva:
        errores.append(ErrorCarga(ide, numero, "cuenta_inactiva", f"la cuenta {linea.cuenta} está inactiva"))
    if linea.clase is not None and linea.clase not in catalogo.clases_activas:
        errores.append(
            ErrorCarga(ide, numero, "clase_inexistente", f"la clase {linea.clase!r} no existe o está inactiva")
        )
    if linea.entidad is not None and linea.entidad not in catalogo.proveedores_activos:
        errores.append(
            ErrorCarga(
                ide, numero, "proveedor_inexistente", f"el proveedor {linea.entidad!r} no existe o está inactivo"
            )
        )
    if cuenta is not None and cuenta.tipo == TIPO_PROVEEDORES and linea.entidad is None:
        errores.append(
            ErrorCarga(ide, numero, "proveedor_requerido", f"la cuenta {linea.cuenta} exige un proveedor en la línea")
        )
    return errores


def _factura(asiento: AsientoCarga, catalogo: Catalogo) -> List[ErrorCarga]:
    ide = asiento.id_externo
    errores: List[ErrorCarga] = []
    if asiento.referencia is None:
        errores.append(
            ErrorCarga(ide, None, "referencia_requerida", "un vendor bill necesita referencia (serie-folio)")
        )
    de_proveedores = [n for n, linea in enumerate(asiento.lineas, start=1) if es_linea_de_proveedores(linea, catalogo)]
    principal_ok = len(de_proveedores) == 1 and asiento.lineas[de_proveedores[0] - 1].credito > 0
    if not principal_ok:
        errores.append(
            ErrorCarga(
                ide, None, "factura_sin_proveedores",
                "un vendor bill lleva exactamente una línea de proveedores al haber",
            )
        )
    errores.extend(
        ErrorCarga(ide, n, "factura_linea_credito", "en un vendor bill solo la línea de proveedores va al haber")
        for n, linea in enumerate(asiento.lineas, start=1)
        if n not in de_proveedores and linea.credito > 0
    )
    return errores


def es_linea_de_proveedores(linea: LineaCarga, catalogo: Catalogo) -> bool:
    cuenta = catalogo.cuentas.get(linea.cuenta)
    return cuenta is not None and cuenta.tipo == TIPO_PROVEEDORES

