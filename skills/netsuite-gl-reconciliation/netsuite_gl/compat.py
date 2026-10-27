"""Capa de compatibilidad: traduce SuiteQL (dialecto estilo Oracle) a SQL que SQLite ejecuta.

Solo se traduce el código; los literales `'…'` y los identificadores `"…"` pasan intactos.
Los comentarios se quitan (`quitar_comentarios` da el texto que iría por el conector MCP).

| SuiteQL                         | SQLite                                               |
|---------------------------------|------------------------------------------------------|
| BUILTIN.DF(x.<campo>)           | subconsulta escalar a la tabla de nombres (CAMPOS_DF) |
| NVL(a, b)                       | COALESCE(a, b)                                       |
| transaction (tabla o columna)   | "transaction" (palabra reservada en SQLite)          |

Cualquier otra construcción `BUILTIN.*` es un error explícito, nunca se deja pasar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import List, Mapping, Optional, Tuple

CODIGO = "codigo"
LITERAL = "literal"
IDENTIFICADOR = "identificador"

# Plantillas de nombre visible por campo referenciado; `{ref}` es la expresión original.
CAMPOS_DF: Mapping[str, str] = MappingProxyType(
    {
        "account": "(SELECT dfx.acctnumber || ' ' || dfx.fullname FROM account dfx WHERE dfx.id = {ref})",
        "class": "(SELECT dfx.fullname FROM classification dfx WHERE dfx.id = {ref})",
        "postingperiod": "(SELECT dfx.periodname FROM accountingperiod dfx WHERE dfx.id = {ref})",
        "entity": "(SELECT dfx.entityid || ' ' || dfx.companyname FROM vendor dfx WHERE dfx.id = {ref})",
        "type": (
            "(CASE {ref} WHEN 'VendBill' THEN 'Bill' WHEN 'VendCred' THEN 'Bill Credit' "
            "WHEN 'Journal' THEN 'Journal' ELSE {ref} END)"
        ),
    }
)

_RE_DF = re.compile(r"\bBUILTIN\s*\.\s*DF\s*\(\s*((?:[A-Za-z_]\w*\s*\.\s*)?([A-Za-z_]\w*))\s*\)", re.IGNORECASE)
_RE_NVL = re.compile(r"\bNVL\s*\(", re.IGNORECASE)
_RE_TRANSACTION = re.compile(r"\btransaction\b", re.IGNORECASE)
_RE_BUILTIN = re.compile(r"\bBUILTIN\s*\.\s*(\w+)", re.IGNORECASE)
_RE_ESPECIAL = re.compile(r"'|\"|--|/\*")


class ErrorCompatibilidad(ValueError):
    """El texto SuiteQL usa algo que esta capa no sabe traducir, o está mal cerrado."""


@dataclass(frozen=True)
class Segmento:
    tipo: str
    texto: str


def segmentar(suiteql: str) -> Tuple[Segmento, ...]:
    """Parte el texto en código, literales e identificadores citados; descarta comentarios."""
    piezas: List[Segmento] = []
    i = 0
    while i < len(suiteql):
        especial = _RE_ESPECIAL.search(suiteql, i)
        fin_codigo = especial.start() if especial else len(suiteql)
        if fin_codigo > i:
            piezas.append(Segmento(CODIGO, suiteql[i:fin_codigo]))
        if especial is None:
            break
        pieza, i = _consumir_especial(suiteql, especial.start(), especial.group(0))
        if pieza is not None:
            piezas.append(pieza)
    return _fusionar_codigo(piezas)


def _consumir_especial(texto: str, inicio: int, marca: str) -> Tuple[Optional[Segmento], int]:
    """El segmento que empieza en `inicio` (o `None` si es un comentario de línea) y dónde seguir."""
    if marca in ("'", '"'):
        fin = _cierre_de_cita(texto, inicio)
        return Segmento(LITERAL if marca == "'" else IDENTIFICADOR, texto[inicio:fin]), fin
    if marca == "--":
        salto = texto.find("\n", inicio)
        return None, len(texto) if salto < 0 else salto
    cierre = texto.find("*/", inicio + 2)
    if cierre < 0:
        raise ErrorCompatibilidad(f"comentario /* sin cerrar desde la posición {inicio}")
    return Segmento(CODIGO, " "), cierre + 2  # el espacio evita pegar dos palabras


def _fusionar_codigo(piezas: List[Segmento]) -> Tuple[Segmento, ...]:
    """Une tramos de código contiguos para que una traducción no quede partida por un comentario."""
    fusionadas: List[Segmento] = []
    for pieza in piezas:
        if fusionadas and pieza.tipo == CODIGO and fusionadas[-1].tipo == CODIGO:
            fusionadas[-1] = Segmento(CODIGO, fusionadas[-1].texto + pieza.texto)
        else:
            fusionadas.append(pieza)
    return tuple(fusionadas)


def quitar_comentarios(suiteql: str) -> str:
    """El SuiteQL sin comentarios: lo que se mandaría tal cual por el conector MCP."""
    return "".join(s.texto for s in segmentar(suiteql))


def traducir(suiteql: str) -> str:
    """SQL ejecutable en SQLite, equivalente al SuiteQL recibido."""
    partes = [
        _traducir_codigo(s.texto) if s.tipo == CODIGO else s.texto
        for s in segmentar(suiteql)
    ]
    return "".join(partes)


def _traducir_codigo(codigo: str) -> str:
    # El identificador se cita antes de expandir BUILTIN.DF: las plantillas no lo usan.
    citado = _RE_TRANSACTION.sub('"transaction"', codigo)
    expandido = _RE_DF.sub(_expandir_df, citado)
    restante = _RE_BUILTIN.search(expandido)
    if restante:
        raise ErrorCompatibilidad(f"construcción SuiteQL sin traducción: BUILTIN.{restante.group(1).upper()}")
    return _RE_NVL.sub("COALESCE(", expandido)


def _expandir_df(coincidencia: "re.Match[str]") -> str:
    referencia = re.sub(r"\s+", "", coincidencia.group(1))
    campo = coincidencia.group(2).lower()
    plantilla = CAMPOS_DF.get(campo)
    if plantilla is None:
        soportados = ", ".join(sorted(CAMPOS_DF))
        raise ErrorCompatibilidad(f"BUILTIN.DF sobre '{campo}' no tiene traducción (soportados: {soportados})")
    return plantilla.format(ref=referencia)


def _cierre_de_cita(texto: str, inicio: int) -> int:
    """Índice siguiente a la comilla que cierra; la comilla doble interna (`''`) es escape."""
    comilla = texto[inicio]
    i = inicio + 1
    while i < len(texto):
        if texto[i] == comilla:
            if texto[i + 1:i + 2] == comilla:
                i += 2
                continue
            return i + 1
        i += 1
    tipo = "literal" if comilla == "'" else "identificador"
    raise ErrorCompatibilidad(f"{tipo} sin cerrar desde la posición {inicio}")
