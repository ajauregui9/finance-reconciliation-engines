"""Respuestas grabadas (`respuesta_grabada/v1`): lectura para el modo grabado y escritura al regrabar.

Una respuesta grabada vale solo para el documento con el que se grabó: guarda el SHA-256
del texto y el extractor la rechaza si el documento cambió. `origen` dice si la escribió el
generador sintético o una corrida en vivo; el reporte lo usa para advertir qué miden sus
métricas.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, FrozenSet, Mapping, Tuple

from .documentos import Documento
from .errores import InsumoInvalido
from .respuesta import Extraida, RespuestaModelo, respuesta_a_dict, respuesta_desde_dict

ESQUEMA_GRABADA = "respuesta_grabada/v1"
ORIGEN_SINTETICO = "sintetico"
ORIGEN_VIVO = "vivo"
ORIGENES: FrozenSet[str] = frozenset({ORIGEN_SINTETICO, ORIGEN_VIVO})
LLAVES: FrozenSet[str] = frozenset({"esquema", "documento_id", "sha256_documento", "origen", "respuesta"})
EXTENSION = ".json"
SANGRIA = 2
_FORMA_SHA = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True)
class Grabada:
    documento_id: str
    sha256_documento: str
    origen: str
    respuesta: RespuestaModelo


def grabada_desde_dict(datos: Any, documento_id: str) -> Grabada:
    """Valida una respuesta grabada; `documento_id` es el que dicta el nombre del archivo."""
    if not isinstance(datos, dict):
        raise InsumoInvalido("se esperaba un objeto JSON")
    if set(datos) != LLAVES:
        raise InsumoInvalido(f"llaves {sorted(datos)}; se esperaban {sorted(LLAVES)}")
    if datos["esquema"] != ESQUEMA_GRABADA:
        raise InsumoInvalido(f"esquema {datos['esquema']!r}; se esperaba {ESQUEMA_GRABADA!r}")
    if datos["documento_id"] != documento_id:
        raise InsumoInvalido(f"documento_id {datos['documento_id']!r} no coincide con el archivo ({documento_id})")
    if not isinstance(datos["sha256_documento"], str) or not _FORMA_SHA.fullmatch(datos["sha256_documento"]):
        raise InsumoInvalido("sha256_documento debe ser un SHA-256 en hexadecimal minúsculo")
    if datos["origen"] not in ORIGENES:
        raise InsumoInvalido(f"origen {datos['origen']!r} fuera de {sorted(ORIGENES)}")
    return Grabada(documento_id, datos["sha256_documento"], datos["origen"], respuesta_desde_dict(datos["respuesta"]))


def grabada_a_dict(grabada: Grabada) -> Dict[str, Any]:
    return {"esquema": ESQUEMA_GRABADA, "documento_id": grabada.documento_id,
            "sha256_documento": grabada.sha256_documento, "origen": grabada.origen,
            "respuesta": respuesta_a_dict(grabada.respuesta)}


def texto_grabada(grabada: Grabada) -> str:
    return json.dumps(grabada_a_dict(grabada), ensure_ascii=False, sort_keys=True, indent=SANGRIA) + "\n"


def escribir_grabada(directorio: Path, grabada: Grabada) -> Path:
    ruta = directorio / f"{grabada.documento_id}{EXTENSION}"
    ruta.write_bytes(texto_grabada(grabada).encode("utf-8"))
    return ruta


def _archivos(directorio: Path) -> Tuple[Path, ...]:
    if not directorio.is_dir():
        raise InsumoInvalido(f"{directorio} no es un directorio")
    rutas = tuple(sorted(p for p in directorio.iterdir() if not p.name.startswith(".")))
    ajenos = [p.name for p in rutas if p.suffix != EXTENSION or not p.is_file()]
    if ajenos:
        raise InsumoInvalido(f"{directorio.name}: archivos que no son respuestas grabadas {ajenos}")
    return rutas


def _leer(ruta: Path) -> Grabada:
    try:
        datos = json.loads(ruta.read_bytes().decode("utf-8"))
        return grabada_desde_dict(datos, ruta.stem)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InsumoInvalido(f"{ruta.name}: JSON ilegible ({exc})") from None
    except InsumoInvalido as exc:
        raise InsumoInvalido(f"{ruta.name}: {exc}") from None


def cargar_grabadas(directorio: Path) -> Mapping[str, Grabada]:
    """Todas las respuestas grabadas del directorio, por id de documento."""
    return MappingProxyType({ruta.stem: _leer(ruta) for ruta in _archivos(directorio)})


def huella_grabadas(directorio: Path) -> str:
    resumen = hashlib.sha256()
    for ruta in _archivos(directorio):
        resumen.update(f"{ruta.name}\0{hashlib.sha256(ruta.read_bytes()).hexdigest()}\n".encode("utf-8"))
    return resumen.hexdigest()


@dataclass(frozen=True)
class ExtractorGrabado:
    """Responde con la grabada del documento; nunca usa red ni llave."""

    grabadas: Mapping[str, Grabada]

    def extraer(self, documento: Documento, solicitud: Mapping[str, Any]) -> Extraida:
        grabada = self.grabadas.get(documento.documento_id)
        if grabada is None:
            raise InsumoInvalido(f"falta la respuesta grabada de {documento.documento_id}; regrábala con "
                                 "--modo vivo --grabar <dir>")
        if grabada.sha256_documento != documento.sha256:
            raise InsumoInvalido(f"la respuesta grabada de {documento.documento_id} no corresponde al documento "
                                 "actual (sha256 distinto): regrábala")
        return Extraida(grabada.respuesta, grabada.origen)
