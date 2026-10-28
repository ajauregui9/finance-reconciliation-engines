"""Lectura estricta de insumos CSV con mensajes que señalan archivo, fila y columna.

Ningún registro se descarta: o se interpreta completo, o la lectura falla.
"""
from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Dict, Hashable, Mapping, Sequence, Tuple

from frontera import ErrorFrontera, leer_fecha

from .dinero import a_monto
from .errores import ErrorInsumo

CODIFICACION = "utf-8-sig"


@dataclass(frozen=True)
class Registro:
    """Una fila de datos (base 1, sin contar el encabezado) de un archivo de insumo."""

    archivo: str
    numero: int
    valores: Mapping[str, str]

    def falla(self, detalle: str) -> ErrorInsumo:
        return ErrorInsumo(f"{self.archivo}, fila {self.numero}: {detalle}")

    def falla_en(self, columna: str, detalle: str) -> ErrorInsumo:
        return ErrorInsumo(f"{self.archivo}, fila {self.numero}, columna '{columna}': {detalle}")

    def texto(self, columna: str) -> str:
        valor = self.valores[columna].strip()
        if not valor:
            raise self.falla_en(columna, "el valor está vacío")
        return valor

    def fecha(self, columna: str) -> date:
        valor = self.texto(columna)
        try:
            return leer_fecha(valor)
        except ErrorFrontera as exc:
            raise self.falla_en(columna, str(exc)) from None

    def monto(self, columna: str) -> Decimal:
        valor = self.texto(columna)
        try:
            return a_monto(valor)
        except ValueError as exc:
            raise self.falla_en(columna, str(exc)) from None

    def exigir_moneda(self, columna: str, moneda: str) -> None:
        valor = self.texto(columna)
        if valor != moneda:
            raise self.falla_en(columna, f"la moneda '{valor}' no es la de la config ('{moneda}')")


@dataclass(frozen=True)
class TablaCsv:
    archivo: str
    sha256: str
    registros: Tuple[Registro, ...]


def _decodificar(ruta: Path) -> Tuple[str, str]:
    try:
        crudo = ruta.read_bytes()
    except OSError as exc:
        raise ErrorInsumo(f"no se pudo leer el insumo {ruta}: {exc.strerror or exc}") from exc
    try:
        return crudo.decode(CODIFICACION), hashlib.sha256(crudo).hexdigest()
    except UnicodeDecodeError as exc:
        raise ErrorInsumo(f"{ruta.name} no es UTF-8 válido (byte {exc.start})") from exc


def _validar_encabezado(archivo: str, encabezado: Sequence[str], columnas: Sequence[str]) -> None:
    repetidas = sorted({c for c in encabezado if encabezado.count(c) > 1})
    if repetidas:
        raise ErrorInsumo(f"{archivo}: columna repetida en el encabezado: {', '.join(repetidas)}")
    faltan = [c for c in columnas if c not in encabezado]
    if faltan:
        raise ErrorInsumo(f"{archivo}: faltan columnas {', '.join(faltan)}")
    sobran = [c for c in encabezado if c not in columnas]
    if sobran:
        raise ErrorInsumo(f"{archivo}: columnas no esperadas {', '.join(sobran)}")


def _registro(archivo: str, numero: int, encabezado: Sequence[str], fila: Sequence[str]) -> Registro:
    if len(fila) != len(encabezado):
        raise ErrorInsumo(f"{archivo}, fila {numero}: se esperaban {len(encabezado)} campos y hay {len(fila)}")
    return Registro(archivo=archivo, numero=numero, valores=MappingProxyType(dict(zip(encabezado, fila))))


def leer_tabla(ruta: Path, columnas: Sequence[str]) -> TablaCsv:
    """Lee un CSV cuyo encabezado debe tener exactamente `columnas` (en cualquier orden)."""
    texto, huella = _decodificar(ruta)
    try:
        filas = list(csv.reader(io.StringIO(texto, newline=""), strict=True))
    except csv.Error as exc:
        raise ErrorInsumo(f"{ruta.name}: CSV mal formado: {exc}") from exc
    if not filas:
        raise ErrorInsumo(f"{ruta.name}: el archivo está vacío; falta el encabezado")
    encabezado = filas[0]
    _validar_encabezado(ruta.name, encabezado, columnas)
    registros = tuple(_registro(ruta.name, n, encabezado, f) for n, f in enumerate(filas[1:], start=1))
    return TablaCsv(archivo=ruta.name, sha256=huella, registros=registros)


def exigir_unicas(registros: Sequence[Registro], llaves: Sequence[Hashable], descripcion: str) -> None:
    """Falla en el primer registro cuya llave ya apareció antes."""
    vistas: Dict[Hashable, int] = {}
    for registro, llave in zip(registros, llaves):
        if llave in vistas:
            raise registro.falla(f"{descripcion} {llave!r} está repetida (ya aparece en la fila {vistas[llave]})")
        vistas[llave] = registro.numero
