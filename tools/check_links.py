#!/usr/bin/env python3
"""Verificador de referencias de la documentación publicable (`check_links.py`).

Recorre los archivos Markdown que viven dentro de las rutas publicables y falla si una
referencia apunta a un archivo o carpeta que no existe, o que existe pero no se publica.

Qué cuenta como referencia:
  1. Enlaces relativos de Markdown, en línea (`[texto](ruta)`, `![alt](ruta)`) o de
     referencia (`[id]: ruta`). Se resuelven contra la carpeta del documento, igual que
     un visor de Markdown. Se ignoran URLs con esquema, anclas puras y rutas absolutas;
     de `ruta#ancla` solo se verifica la ruta.
  2. Código en línea con forma de ruta del repo: contiene "/" y además termina en una
     extensión conocida, termina en "/" o empieza con una carpeta raíz publicada. Un
     primer tramo en mayúsculas (`DIR/x.json`) es un marcador de CLI y se ignora. Se
     resuelve contra la carpeta del documento y cada carpeta superior hasta la raíz,
     porque una spec cita rutas relativas a su skill y un README, relativas a la raíz.
  3. En bloques de código cercados, los tokens que empiezan con una carpeta raíz
     publicada (los comandos de ejemplo se escriben desde la raíz del repo).

Un patrón con `*`, `?` o `[...]` debe coincidir con al menos una ruta. La comparación
distingue mayúsculas en todos los sistemas, como el CI en Linux. No se validan anclas.

Uso:
    python3 tools/check_links.py                         # rutas publicables por omisión
    python3 tools/check_links.py --raiz . README.md skills

Las rutas posicionales son el conjunto publicado: solo se revisan los Markdown que viven
dentro de ellas y solo cuentan como válidos los destinos dentro de ellas.

Códigos de salida:
    0  ninguna referencia rota.
    1  al menos una referencia rota (se listan en la salida estándar).
    2  configuración inválida: raíz o ruta publicable inexistente, ruta fuera de la raíz,
       documento que no es UTF-8.
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import unquote

# Lo que se publica del repo. De docs/ solo se publican los ADRs.
PUBLICABLES: Tuple[str, ...] = (
    "README.md",
    "GLOSSARY.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-llm.txt",
    ".gitignore",
    ".github",
    "docs/adr",
    "examples",
    "skills",
    "tests",
    "tools",
)

EXTENSIONES_CONOCIDAS: FrozenSet[str] = frozenset({
    ".cfg", ".csv", ".html", ".ini", ".json", ".jsonl", ".md", ".py", ".sh", ".sql",
    ".toml", ".txt", ".xlsx", ".xml", ".yaml", ".yml",
})
# Carpetas que nunca se recorren ni cuentan como destino publicado (además de toda carpeta
# oculta que no sea una ruta publicable explícita, como .github).
CARPETAS_RUIDO: FrozenSet[str] = frozenset({"__pycache__", "venv", "node_modules", "htmlcov", "build", "dist"})

MOTIVO_INEXISTENTE = "inexistente"
MOTIVO_NO_PUBLICADA = "no_publicada"
MOTIVO_FUERA = "fuera_de_la_raiz"

TIPO_ENLACE = "enlace"
TIPO_CODIGO = "codigo"
TIPO_BLOQUE = "bloque"

CODIGO_LIMPIO = 0
CODIGO_ROTAS = 1
CODIGO_CONFIGURACION = 2

_ENLACE_EN_LINEA = re.compile(r"!?\[[^\]]*\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_ENLACE_REFERENCIA = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(\S+)")
_CODIGO_EN_LINEA = re.compile(r"`([^`\n]+)`")
_CERCA = re.compile(r"^\s{0,3}(```+|~~~+)")
_FORMA_DE_RUTA = re.compile(r"^[A-Za-z0-9_.\-/*?\[\]]+$")
_ESQUEMA = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_SEPARADORES_BLOQUE = re.compile(r"[\s=:,;()]+")
_COMODINES = re.compile(r"[*?\[]")
# Un primer tramo en mayúsculas es un marcador de ayuda de CLI (`DIR/x.json`, `AAAA/MM`).
_MARCADOR = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ErrorConfiguracion(Exception):
    """Raíz, ruta publicable o documento inválidos: la verificación no puede hacerse."""


@dataclass(frozen=True)
class Referencia:
    documento: str  # relativo a la raíz, con "/"
    linea: int
    tipo: str
    destino: str  # texto tal como aparece en el documento


@dataclass(frozen=True)
class Rota:
    referencia: Referencia
    motivo: str


@dataclass(frozen=True)
class Publicado:
    """Conjunto publicado: rutas relativas a la raíz y sus carpetas de primer nivel."""

    rutas: Tuple[str, ...]

    @property
    def carpetas_raiz(self) -> FrozenSet[str]:
        return frozenset(r.split("/")[0] for r in self.rutas)

    def contiene(self, relativa: str) -> bool:
        if any(_es_ruido(parte, self.rutas) for parte in relativa.split("/")[:-1]):
            return False
        return any(relativa == r or relativa.startswith(r + "/") for r in self.rutas)


# --- extracción -----------------------------------------------------------------


def _es_ruido(nombre: str, publicadas: Sequence[str]) -> bool:
    if nombre in CARPETAS_RUIDO:
        return True
    return nombre.startswith(".") and nombre not in {r.split("/")[0] for r in publicadas}


def _es_ruta_de_codigo(texto: str, carpetas_raiz: FrozenSet[str]) -> bool:
    if "/" not in texto or not _FORMA_DE_RUTA.match(texto) or texto.startswith("/"):
        return False
    if _MARCADOR.match(_quitar_punto(texto).split("/")[0]):
        return False
    if texto.endswith("/"):
        return True
    ultima = texto.rsplit("/", 1)[1]
    if os.path.splitext(ultima)[1].lower() in EXTENSIONES_CONOCIDAS:
        return True
    return _quitar_punto(texto).split("/")[0] in carpetas_raiz


def _es_ruta_de_bloque(token: str, carpetas_raiz: FrozenSet[str]) -> bool:
    if "/" not in token or not _FORMA_DE_RUTA.match(token):
        return False
    return token.split("/")[0] in carpetas_raiz


def _es_enlace_local(destino: str) -> bool:
    return not (destino.startswith(("#", "/", "<")) or _ESQUEMA.match(destino))


def _quitar_punto(texto: str) -> str:
    return texto[2:] if texto.startswith("./") else texto


def _tokens_de_bloque(linea: str) -> Iterator[str]:
    for crudo in _SEPARADORES_BLOQUE.split(linea):
        token = crudo.strip("`\"'\\")
        if token:
            yield token


def extraer_referencias(texto: str, documento: str, carpetas_raiz: FrozenSet[str]) -> Tuple[Referencia, ...]:
    """Referencias de un documento Markdown, en orden de aparición."""
    referencias: List[Referencia] = []
    cerca: Optional[str] = None
    for numero, linea in enumerate(texto.splitlines(), start=1):
        marca = _CERCA.match(linea)
        if cerca is not None:
            if marca and marca.group(1)[0] == cerca[0] and len(marca.group(1)) >= len(cerca):
                cerca = None
                continue
            referencias.extend(Referencia(documento, numero, TIPO_BLOQUE, t)
                               for t in _tokens_de_bloque(linea) if _es_ruta_de_bloque(t, carpetas_raiz))
            continue
        if marca:
            cerca = marca.group(1)
            continue
        referencias.extend(_referencias_de_prosa(linea, numero, documento, carpetas_raiz))
    return tuple(referencias)


def _referencias_de_prosa(linea: str, numero: int, documento: str,
                          carpetas_raiz: FrozenSet[str]) -> Iterator[Referencia]:
    sin_codigo = _CODIGO_EN_LINEA.sub(lambda m: " " * len(m.group(0)), linea)
    enlaces: List[Tuple[int, int]] = []
    for patron in (_ENLACE_EN_LINEA, _ENLACE_REFERENCIA):
        for hallado in patron.finditer(sin_codigo):
            enlaces.append(hallado.span())
            if _es_enlace_local(hallado.group(1)):
                yield Referencia(documento, numero, TIPO_ENLACE, hallado.group(1))
    for hallado in _CODIGO_EN_LINEA.finditer(linea):
        candidato = hallado.group(1).strip()
        # El código dentro de la etiqueta de un enlace es texto para leer: se verifica el destino.
        if any(inicio <= hallado.start() < fin for inicio, fin in enlaces):
            continue
        if _es_ruta_de_codigo(candidato, carpetas_raiz):
            yield Referencia(documento, numero, TIPO_CODIGO, candidato)


# --- resolución -----------------------------------------------------------------


def _coincidencias(raiz: Path, partes: Sequence[str]) -> List[str]:
    """Rutas relativas que existen con exactamente esos nombres (o que casan el patrón)."""
    actuales: List[str] = [""]
    for parte in partes:
        siguientes: List[str] = []
        for actual in actuales:
            carpeta = raiz / actual if actual else raiz
            if not carpeta.is_dir():
                continue
            nombres = sorted(os.listdir(carpeta))
            elegidos = (fnmatch.filter(nombres, parte) if _COMODINES.search(parte)
                        else [n for n in nombres if n == parte])
            siguientes.extend(f"{actual}/{n}" if actual else n for n in elegidos)
        actuales = siguientes
    return actuales


def _normalizar(base: str, destino: str) -> Optional[Tuple[str, ...]]:
    """Partes de `base/destino` relativas a la raíz, o None si sale de ella."""
    combinada = os.path.normpath(os.path.join(base, destino)) if base else os.path.normpath(destino)
    partes = tuple(p for p in combinada.replace(os.sep, "/").split("/") if p not in ("", "."))
    if partes and partes[0] == "..":
        return None
    return partes


def _motivo(raiz: Path, publicado: Publicado, bases: Sequence[str], destino: str) -> Optional[str]:
    """None si alguna base resuelve el destino a una ruta publicada; si no, el motivo."""
    existe_sin_publicar = False
    alguna_dentro = False
    for base in bases:
        partes = _normalizar(base, destino)
        if partes is None:
            continue
        alguna_dentro = True
        if not partes:  # la raíz misma del repo
            return None
        encontradas = _coincidencias(raiz, partes)
        if any(publicado.contiene(e) for e in encontradas):
            return None
        existe_sin_publicar = existe_sin_publicar or bool(encontradas)
    if not alguna_dentro:
        return MOTIVO_FUERA
    return MOTIVO_NO_PUBLICADA if existe_sin_publicar else MOTIVO_INEXISTENTE


def _bases(referencia: Referencia) -> Tuple[str, ...]:
    carpeta = referencia.documento.rsplit("/", 1)[0] if "/" in referencia.documento else ""
    if referencia.tipo == TIPO_ENLACE:
        return (carpeta,)
    if referencia.tipo == TIPO_BLOQUE:
        return ("",)
    ancestros: List[str] = []
    partes = carpeta.split("/") if carpeta else []
    for corte in range(len(partes), -1, -1):
        ancestros.append("/".join(partes[:corte]))
    return tuple(ancestros)


def _destino_limpio(referencia: Referencia) -> str:
    if referencia.tipo != TIPO_ENLACE:
        return _quitar_punto(referencia.destino)
    return unquote(referencia.destino.split("#", 1)[0])


# --- recorrido ------------------------------------------------------------------


def _validar(raiz: Path, publicables: Sequence[str]) -> Publicado:
    if not raiz.is_dir():
        raise ErrorConfiguracion(f"la raíz no existe o no es carpeta: {raiz}")
    limpias: List[str] = []
    for ruta in publicables:
        partes = _normalizar("", ruta)
        if partes is None or not partes:
            raise ErrorConfiguracion(f"ruta publicable fuera de la raíz: {ruta}")
        relativa = "/".join(partes)
        if not _coincidencias(raiz, partes) or _COMODINES.search(relativa):
            raise ErrorConfiguracion(f"la ruta publicable no existe: {ruta}")
        limpias.append(relativa)
    return Publicado(tuple(sorted(set(limpias))))


def documentos_publicados(raiz: Path, publicado: Publicado) -> Tuple[str, ...]:
    """Markdown dentro del conjunto publicado, relativos a la raíz y ordenados."""
    hallados: List[str] = []
    for ruta in publicado.rutas:
        absoluta = raiz / ruta
        if absoluta.is_file():
            hallados.extend([ruta] if ruta.endswith(".md") else [])
            continue
        for actual, carpetas, archivos in os.walk(absoluta):
            carpetas[:] = sorted(c for c in carpetas if not _es_ruido(c, publicado.rutas))
            relativa = Path(actual).relative_to(raiz).as_posix()
            hallados.extend(f"{relativa}/{a}" for a in archivos if a.endswith(".md"))
    return tuple(sorted(set(hallados)))


def _leer(raiz: Path, documento: str) -> str:
    try:
        return (raiz / documento).read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ErrorConfiguracion(f"{documento}: no es UTF-8 válido ({error.reason})") from error


def verificar(raiz: Path, publicables: Sequence[str] = PUBLICABLES) -> Tuple[Rota, ...]:
    """Referencias rotas de los documentos publicados, ordenadas por documento y línea."""
    publicado = _validar(raiz, publicables)
    rotas: List[Rota] = []
    for documento in documentos_publicados(raiz, publicado):
        for referencia in extraer_referencias(_leer(raiz, documento), documento, publicado.carpetas_raiz):
            motivo = _motivo(raiz, publicado, _bases(referencia), _destino_limpio(referencia))
            if motivo is not None:
                rotas.append(Rota(referencia, motivo))
    return tuple(sorted(rotas, key=lambda r: (r.referencia.documento, r.referencia.linea)))


def formatear(rota: Rota) -> str:
    ref = rota.referencia
    return f"{ref.documento}:{ref.linea}: {ref.tipo} {ref.destino} ({rota.motivo})"


def _argumentos(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verifica las referencias de la documentación publicable.")
    parser.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parents[1],
                        help="Raíz del repo (por omisión, la carpeta superior de tools/).")
    parser.add_argument("rutas", nargs="*", help="Rutas publicables relativas a la raíz (por omisión, PUBLICABLES).")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _argumentos(argv)
    publicables = tuple(args.rutas) or PUBLICABLES
    try:
        rotas = verificar(args.raiz, publicables)
    except ErrorConfiguracion as error:
        print(f"check_links: {error}", file=sys.stderr)
        return CODIGO_CONFIGURACION
    for rota in rotas:
        print(formatear(rota))
    print(f"check_links: {len(rotas)} referencias rotas")
    return CODIGO_ROTAS if rotas else CODIGO_LIMPIO


if __name__ == "__main__":
    sys.exit(main())
