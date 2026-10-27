"""Empaquetado determinista de un libro openpyxl: mismo contenido, mismos bytes.

Hay dos fuentes de variación entre corridas: openpyxl estampa la hora de guardado en
`docProps/core.xml` y `zipfile` pone la hora actual a cada entrada del archivo. Aquí los
metadatos se fijan a un instante dado, el libro se escribe sin el sello de hora de
guardado y el zip se reempaca con fecha, permisos y sistema de origen fijos.
"""
from __future__ import annotations

import io
from datetime import datetime
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.writer.excel import ExcelWriter

CREADOR = "flujo"
FECHA_ENTRADAS_ZIP = (1980, 1, 1, 0, 0, 0)  # la fecha más antigua que admite el formato zip
SISTEMA_UNIX = 3
PERMISOS_ENTRADA = 0o644 << 16


def fijar_metadatos(libro: Workbook, instante: datetime) -> None:
    """Autor y fechas de creación y modificación fijos en las propiedades del libro."""
    propiedades = libro.properties
    propiedades.creator = CREADOR
    propiedades.lastModifiedBy = CREADOR
    propiedades.created = instante
    propiedades.modified = instante


def _escribir_sin_sello(libro: Workbook) -> bytes:
    """Lo mismo que `Workbook.save`, salvo que no reemplaza `modified` por la hora actual."""
    memoria = io.BytesIO()
    with ZipFile(memoria, "w", ZIP_DEFLATED) as archivo:
        ExcelWriter(libro, archivo).save()
    return memoria.getvalue()


def _reempacar(crudo: bytes) -> bytes:
    """Copia cada entrada, en el mismo orden, con fecha, permisos y sistema fijos."""
    salida = io.BytesIO()
    with ZipFile(io.BytesIO(crudo)) as origen, ZipFile(salida, "w", ZIP_DEFLATED) as destino:
        for entrada in origen.infolist():
            fija = ZipInfo(entrada.filename, date_time=FECHA_ENTRADAS_ZIP)
            fija.compress_type = ZIP_DEFLATED
            fija.create_system = SISTEMA_UNIX
            fija.external_attr = PERMISOS_ENTRADA
            destino.writestr(fija, origen.read(entrada.filename))
    return salida.getvalue()


def bytes_deterministas(libro: Workbook, instante: datetime) -> bytes:
    fijar_metadatos(libro, instante)
    return _reempacar(_escribir_sin_sello(libro))
