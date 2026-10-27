"""Insumos de la corrida: documentos que lee el modelo y verdad conocida para evaluar.

Un documento es un archivo `<id>.xml` (CFDI) o `<id>.txt` (texto de una representación
impresa). El id se usa para nombrar respuestas grabadas, así que solo admite letras,
dígitos, `_` y `-`. Ningún archivo se salta en silencio: una extensión desconocida, un id
inválido o repetido o un archivo que no es UTF-8 detienen la lectura. Los ocultos
(`.DS_Store` y similares) se ignoran.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

from .errores import InsumoInvalido
from .modelo import CAMPOS, Campos, campos_desde_mapa

FORMATO_XML = "cfdi_xml"
FORMATO_IMPRESO = "representacion_impresa"
FORMATOS: Mapping[str, str] = {".xml": FORMATO_XML, ".txt": FORMATO_IMPRESO}
_FORMA_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
LLAVES_VERDAD: FrozenSet[str] = frozenset({"documento_id", "campos", "inyeccion", "casos_borde",
                                           "revision_esperada"})


@dataclass(frozen=True)
class Documento:
    documento_id: str
    formato: str
    texto: str
    sha256: str


@dataclass(frozen=True)
class Verdad:
    documento_id: str
    campos: Campos
    inyeccion: Optional[str]
    casos_borde: Tuple[str, ...]
    revision_esperada: bool


def sha256_texto(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def documento_desde_texto(documento_id: str, formato: str, texto: str) -> Documento:
    if not _FORMA_ID.fullmatch(documento_id):
        raise InsumoInvalido(f"id de documento inválido {documento_id!r}: solo letras, dígitos, _ y - (máx. 64)")
    if formato not in FORMATOS.values():
        raise InsumoInvalido(f"{documento_id}: formato desconocido {formato!r}")
    return Documento(documento_id, formato, texto, sha256_texto(texto))


def _visibles(directorio: Path) -> Tuple[Path, ...]:
    if not directorio.is_dir():
        raise InsumoInvalido(f"{directorio} no es un directorio")
    return tuple(sorted(p for p in directorio.iterdir() if not p.name.startswith(".")))


def _leer_documento(ruta: Path) -> Documento:
    formato = FORMATOS.get(ruta.suffix.lower())
    if not ruta.is_file() or formato is None:
        raise InsumoInvalido(f"{ruta.name}: extensión no admitida (solo .xml y .txt)")
    try:
        texto = ruta.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise InsumoInvalido(f"{ruta.name}: el archivo no es UTF-8 válido") from None
    except OSError as exc:  # pragma: no cover - depende del sistema de archivos
        raise InsumoInvalido(f"no se puede leer {ruta.name}: {exc.strerror or exc}") from None
    try:
        return documento_desde_texto(ruta.stem, formato, texto)
    except InsumoInvalido as exc:
        raise InsumoInvalido(f"{ruta.name}: {exc}") from None


def _sin_repetidos(ids: Iterable[str], contexto: str) -> None:
    vistos: Dict[str, int] = {}
    for documento_id in ids:
        vistos[documento_id] = vistos.get(documento_id, 0) + 1
    repetidos = sorted(i for i, n in vistos.items() if n > 1)
    if repetidos:
        raise InsumoInvalido(f"{contexto}: id repetido {repetidos}")


def cargar_documentos(directorio: Path) -> Tuple[Documento, ...]:
    """Todos los documentos del directorio, ordenados por id."""
    rutas = _visibles(directorio)
    if not rutas:
        raise InsumoInvalido(f"{directorio.name}: no contiene documentos")
    documentos = tuple(_leer_documento(ruta) for ruta in rutas)
    _sin_repetidos((d.documento_id for d in documentos), directorio.name)
    return tuple(sorted(documentos, key=lambda d: d.documento_id))


def huella_documentos(documentos: Iterable[Documento]) -> str:
    """SHA-256 estable del conjunto: id, formato y huella de cada texto, en orden de id."""
    resumen = hashlib.sha256()
    for documento in sorted(documentos, key=lambda d: d.documento_id):
        resumen.update(f"{documento.documento_id}\0{documento.formato}\0{documento.sha256}\n".encode("utf-8"))
    return resumen.hexdigest()


def huella_archivo(ruta: Path) -> str:
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except OSError as exc:
        raise InsumoInvalido(f"no se puede leer {ruta}: {exc.strerror or exc}") from None


def _campos(valor: Any) -> Campos:
    if not isinstance(valor, dict) or set(valor) != set(CAMPOS):
        raise InsumoInvalido(f"campos: se esperaba un objeto con exactamente {list(CAMPOS)}")
    if not all(v is None or isinstance(v, str) for v in valor.values()):
        raise InsumoInvalido("campos: cada valor debe ser texto o null")
    return campos_desde_mapa(valor)


def _verdad(datos: Any) -> Verdad:
    if not isinstance(datos, dict):
        raise InsumoInvalido("se esperaba un objeto JSON")
    if set(datos) != LLAVES_VERDAD:
        raise InsumoInvalido(f"llaves {sorted(datos)}; se esperaban {sorted(LLAVES_VERDAD)}")
    documento_id, inyeccion, bordes = datos["documento_id"], datos["inyeccion"], datos["casos_borde"]
    if not isinstance(documento_id, str) or not _FORMA_ID.fullmatch(documento_id):
        raise InsumoInvalido(f"documento_id inválido {documento_id!r}")
    if inyeccion is not None and not isinstance(inyeccion, str):
        raise InsumoInvalido(f"inyeccion: se esperaba texto o null; llegó {inyeccion!r}")
    if not isinstance(bordes, list) or not all(isinstance(b, str) for b in bordes):
        raise InsumoInvalido(f"casos_borde: se esperaba una lista de textos; llegó {bordes!r}")
    if not isinstance(datos["revision_esperada"], bool):
        raise InsumoInvalido(f"revision_esperada: se esperaba true o false; llegó {datos['revision_esperada']!r}")
    return Verdad(documento_id, _campos(datos["campos"]), inyeccion, tuple(bordes), datos["revision_esperada"])


def _linea(nombre: str, numero: int, linea: str) -> Verdad:
    contenido = linea.rstrip("\r")
    if not contenido.strip():
        raise InsumoInvalido(f"{nombre}, línea {numero}: línea vacía")
    try:
        datos = json.loads(contenido)
    except json.JSONDecodeError as exc:
        raise InsumoInvalido(f"{nombre}, línea {numero}: JSON inválido ({exc.msg})") from None
    try:
        return _verdad(datos)
    except InsumoInvalido as exc:
        raise InsumoInvalido(f"{nombre}, línea {numero}: {exc}") from None


def cargar_verdad(ruta: Path) -> Tuple[Verdad, ...]:
    """La verdad completa (JSONL); una línea vacía o ilegible es un error, nunca se salta."""
    try:
        texto = ruta.read_bytes().decode("utf-8")
    except OSError as exc:
        raise InsumoInvalido(f"no se puede leer {ruta}: {exc.strerror or exc}") from None
    except UnicodeDecodeError:
        raise InsumoInvalido(f"{ruta.name}: el archivo no es UTF-8 válido") from None
    lineas = texto.split("\n")
    if lineas[-1] == "":
        lineas = lineas[:-1]
    verdades = tuple(_linea(ruta.name, numero, linea) for numero, linea in enumerate(lineas, start=1))
    _sin_repetidos((v.documento_id for v in verdades), f"{ruta.name}: documento_id")
    return verdades


def verificar_alineacion(documentos: Iterable[Documento], verdades: Iterable[Verdad]) -> None:
    """Documentos y verdad deben tener exactamente los mismos ids."""
    ids_documentos = {d.documento_id for d in documentos}
    ids_verdad = {v.documento_id for v in verdades}
    sin_verdad, sin_documento = sorted(ids_documentos - ids_verdad), sorted(ids_verdad - ids_documentos)
    if sin_verdad or sin_documento:
        raise InsumoInvalido(f"documentos y verdad no coinciden: sin verdad {sin_verdad}, "
                             f"sin documento {sin_documento}")
