"""Guardado del libro con bytes reproducibles: el mismo contenido da el mismo archivo.

Un xlsx es un zip, y dos cosas lo hacen depender del reloj: `Workbook.save` anota la hora
actual como fecha de modificación en `docProps/core.xml`, y `zipfile` sella cada entrada
con la hora del sistema. Aquí las propiedades del documento se arman con una fecha que da
quien llama, el libro se serializa sin pasar por `Workbook.save` y cada entrada se copia a
un zip nuevo con fecha, permisos y sistema de origen constantes.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook
from openpyxl.packaging.core import DocumentProperties
from openpyxl.writer.excel import ExcelWriter

AUTOR = "cierre_amazon"
FECHA_ENTRADA_ZIP = (1980, 1, 1, 0, 0, 0)  # la mínima que admite el formato zip
SISTEMA_ORIGEN_UNIX = 3
MODO_ENTRADA = 0o100644  # archivo regular, lectura y escritura para el dueño, lectura para el resto


def guardar_reproducible(libro: Workbook, ruta: Path, fecha_documento: datetime) -> None:
    """Escribe `libro` en `ruta`; dos llamadas con el mismo libro y la misma fecha dan los mismos bytes."""
    libro.properties = DocumentProperties(creator=AUTOR, lastModifiedBy=AUTOR,
                                          created=fecha_documento, modified=fecha_documento)
    ruta.write_bytes(_normalizar_zip(_serializar(libro)))


def _serializar(libro: Workbook) -> bytes:
    """El zip que escribiría `Workbook.save`, salvo el sello de la hora de guardado."""
    memoria = io.BytesIO()
    with ZipFile(memoria, "w", ZIP_DEFLATED) as zip_crudo:
        ExcelWriter(libro, zip_crudo).save()
    return memoria.getvalue()


def _normalizar_zip(crudo: bytes) -> bytes:
    """Mismas entradas en el mismo orden; solo cambian los metadatos que dependen del sistema."""
    destino = io.BytesIO()
    with ZipFile(io.BytesIO(crudo)) as origen, ZipFile(destino, "w", ZIP_DEFLATED) as normalizado:
        for entrada in origen.infolist():
            fija = ZipInfo(entrada.filename, date_time=FECHA_ENTRADA_ZIP)
            fija.compress_type = ZIP_DEFLATED
            fija.create_system = SISTEMA_ORIGEN_UNIX
            fija.external_attr = MODO_ENTRADA << 16
            normalizado.writestr(fija, origen.read(entrada.filename))
    return destino.getvalue()
