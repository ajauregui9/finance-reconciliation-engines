"""Escritura determinista: UTF-8 sin BOM, LF, llaves ordenadas y archivos en orden.

Rutas relativas a la carpeta de salida:

    documentos/<id>.xml|.txt         lo que lee el modelo
    cfdis_conocidos/<uuid>.xml       el pool que lee el motor (todos menos sin_xml_en_pool)
    respuestas_grabadas/<id>.json    respuestas sintéticas para el modo grabado
    verdad.jsonl                     verdad por documento (solo para evaluar)
    errores_plantados.json           qué respuestas traen errores a propósito
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from .casos import XML
from .fabricas import DatosLlm, DocumentoSintetico
from .plantillas import texto_a, texto_b, xml_cfdi
from .respuestas import error_plantado, respuesta_grabada

DIR_DOCUMENTOS = "documentos"
DIR_POOL = "cfdis_conocidos"
DIR_GRABADAS = "respuestas_grabadas"
ARCHIVO_VERDAD = "verdad.jsonl"
ARCHIVO_ERRORES = "errores_plantados.json"
ESQUEMA_ERRORES = "errores_plantados/v1"
SANGRIA = 2


def _json(objeto: Any) -> str:
    return json.dumps(objeto, ensure_ascii=False, sort_keys=True, indent=SANGRIA) + "\n"


def texto_documento(documento: DocumentoSintetico) -> str:
    plantilla = documento.caso.plantilla
    if plantilla == XML:
        return xml_cfdi(documento.impreso)
    return texto_a(documento.impreso) if plantilla == "texto_a" else texto_b(documento.impreso)


def _nombre_documento(documento: DocumentoSintetico) -> str:
    extension = ".xml" if documento.caso.plantilla == XML else ".txt"
    return f"{DIR_DOCUMENTOS}/{documento.documento_id}{extension}"


def _verdad(documento: DocumentoSintetico) -> Dict[str, Any]:
    return {"documento_id": documento.documento_id, "campos": dict(documento.verdad),
            "inyeccion": documento.caso.inyeccion, "casos_borde": list(documento.casos_borde),
            "revision_esperada": documento.revision_esperada}


def _errores(datos: DatosLlm) -> str:
    errores = [error_plantado(d) for d in datos.documentos]
    filas = [{"documento_id": e.documento_id, "tipo": e.tipo, "campos": list(e.campos),
              "contrafactual": e.contrafactual} for e in errores if e is not None]
    return _json({"esquema": ESQUEMA_ERRORES, "errores": filas})


def contenidos(datos: DatosLlm) -> Dict[str, str]:
    """Ruta relativa -> texto completo, listo para escribirse."""
    salida: Dict[str, str] = {}
    for documento in datos.documentos:
        texto = texto_documento(documento)
        salida[_nombre_documento(documento)] = texto
        salida[f"{DIR_GRABADAS}/{documento.documento_id}.json"] = _json(respuesta_grabada(documento, texto))
        if documento.caso.en_pool:
            salida[f"{DIR_POOL}/{documento.timbrado.uuid}.xml"] = xml_cfdi(documento.timbrado)
    salida[ARCHIVO_VERDAD] = "".join(json.dumps(_verdad(d), ensure_ascii=False, sort_keys=True) + "\n"
                                     for d in datos.documentos)
    salida[ARCHIVO_ERRORES] = _errores(datos)
    return salida


def escribir_salida(datos: DatosLlm, directorio: Path) -> Tuple[Path, ...]:
    textos = contenidos(datos)
    rutas = []
    for relativa in sorted(textos):
        ruta = directorio / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(textos[relativa].encode("utf-8"))
        rutas.append(ruta)
    return tuple(rutas)
