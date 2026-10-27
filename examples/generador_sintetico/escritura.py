"""Escritura determinista: UTF-8 sin BOM, fin de línea LF, llaves y filas ordenadas.

No escribe marcas de tiempo ni rutas absolutas: dos corridas con la misma
semilla producen archivos idénticos byte a byte.
"""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Sequence, Tuple

from .catalogo import EMISORES
from .dinero import texto, texto_tc
from .estado_cuenta import ENCABEZADOS, fila_cruda, registro_universo, resumen_estado
from .modelo import Asiento, Cfdi, Datos
from .oraculo import construir_oraculo
from .veredictos import ARCHIVO_VEREDICTOS, COLUMNAS_VEREDICTOS

ARCHIVO_RESUMEN = "resumen_estados_cuenta.json"
ARCHIVO_UNIVERSO = "universo_cargos_esperado.jsonl"
ARCHIVO_CFDIS = "cfdis.jsonl"
ARCHIVO_LIBRO = "libro_mayor.csv"
ARCHIVO_ORACULO = "oraculo.json"
NOMBRES_ARCHIVO: Tuple[str, ...] = tuple(sorted(
    [e.archivo for e in EMISORES.values()]
    + [ARCHIVO_RESUMEN, ARCHIVO_UNIVERSO, ARCHIVO_CFDIS, ARCHIVO_LIBRO, ARCHIVO_ORACULO, ARCHIVO_VEREDICTOS]))
COLUMNAS_LIBRO = ("asiento_id", "linea", "fecha", "periodo", "origen", "cuenta", "nombre_cuenta",
                  "proveedor_id", "proveedor_nombre", "proveedor_rfc", "referencia", "memo",
                  "debe", "haber", "moneda")


def _csv(encabezado: Sequence[str], filas: Iterable[Sequence[str]]) -> str:
    buffer = io.StringIO()
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(encabezado)
    escritor.writerows(filas)
    return buffer.getvalue()


def _json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def _jsonl(registros: Iterable[object]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in registros)


def registro_cfdi(c: Cfdi) -> Dict[str, object]:
    return {
        "uuid": c.uuid, "serie": c.serie, "folio": c.folio, "fecha_emision": c.fecha_emision.isoformat(),
        "tipo_comprobante": c.tipo_comprobante, "direccion": c.direccion,
        "rfc_emisor": c.rfc_emisor, "nombre_emisor": c.nombre_emisor,
        "rfc_receptor": c.rfc_receptor, "nombre_receptor": c.nombre_receptor,
        "moneda": c.moneda, "tipo_cambio": texto_tc(c.tipo_cambio) if c.tipo_cambio is not None else None,
        "subtotal": texto(c.subtotal), "iva": texto(c.iva), "total": texto(c.total),
        "total_mxn": texto(c.total_mxn), "forma_pago": c.forma_pago, "metodo_pago": "PUE",
        "uso_cfdi": c.uso_cfdi, "concepto": c.concepto, "uuid_relacionado": c.uuid_relacionado,
    }


def _filas_libro(asientos: Iterable[Asiento]) -> Iterator[Tuple[str, ...]]:
    for a in asientos:
        for n, x in enumerate(a.lineas, 1):
            yield (a.asiento_id, str(n), a.fecha.isoformat(), f"{a.fecha.year:04d}-{a.fecha.month:02d}",
                   a.origen, x.cuenta, x.nombre_cuenta, a.proveedor_id, a.proveedor_nombre,
                   a.proveedor_rfc, a.referencia, a.memo, texto(x.debe), texto(x.haber), "MXN")


def contenidos(datos: Datos) -> Dict[str, str]:
    """Nombre de archivo -> texto completo, listo para escribirse."""
    salida: Dict[str, str] = {}
    resumenes: List[Dict[str, object]] = []
    for clave, emisor in sorted(EMISORES.items()):
        cargos = sorted((c for c in datos.cargos if c.emisor == clave), key=lambda c: c.fila)
        salida[emisor.archivo] = _csv(ENCABEZADOS[emisor.layout], (fila_cruda(c) for c in cargos))
        resumenes.append(resumen_estado(clave, cargos, datos.config))
    salida[ARCHIVO_RESUMEN] = _json({"esquema": "resumen_estados_cuenta/v1", "estados_cuenta": resumenes})
    salida[ARCHIVO_UNIVERSO] = _jsonl(registro_universo(c, datos.config) for c in datos.cargos)
    salida[ARCHIVO_CFDIS] = _jsonl(registro_cfdi(c) for c in datos.cfdis)
    salida[ARCHIVO_LIBRO] = _csv(COLUMNAS_LIBRO, _filas_libro(datos.asientos))
    salida[ARCHIVO_ORACULO] = _json(construir_oraculo(datos))
    salida[ARCHIVO_VEREDICTOS] = _csv(COLUMNAS_VEREDICTOS, ((v.cargo_id, v.veredicto, v.asiento_id or "", v.nota)
                                                            for v in datos.veredictos))
    return salida


def escribir_salida(datos: Datos, carpeta: Path) -> Tuple[Path, ...]:
    """Escribe los ocho archivos en `carpeta` (no toca ningún otro archivo)."""
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    rutas = []
    for nombre, contenido in sorted(contenidos(datos).items()):
        ruta = carpeta / nombre
        ruta.write_bytes(contenido.encode("utf-8"))
        rutas.append(ruta)
    return tuple(rutas)
