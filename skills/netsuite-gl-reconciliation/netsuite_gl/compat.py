"""Capa de compatibilidad: traduce SuiteQL (dialecto estilo Oracle) a SQL que SQLite ejecuta.

Solo se traduce el código; los literales `'…'` y los identificadores `"…"` pasan intactos.
Los comentarios se quitan (`quitar_comentarios` da el texto que iría por el conector MCP).

| SuiteQL                         | SQLite                                               |
|---------------------------------|------------------------------------------------------|
| BUILTIN.DF(x.<campo>)           | subconsulta escalar a la tabla de nombres (CAMPOS_DF) |
| NVL(a, b)                       | COALESCE(a, b)                                       |
| ROUND(x, n)                     | ROUND_CENTAVOS(x, n), registrada en la conexión      |
| transaction (tabla o columna)   | "transaction" (palabra reservada en SQLite)          |

Montos: en NetSuite `debit`, `credit`, `amount` y los campos de moneda son decimales; en la
base sintética son centavos enteros, para que SQLite sume sin punto flotante. Sumar, restar,
negar y comparar contra cero dan lo mismo en pesos que en centavos, así que las queries no
cambian. Lo que sí depende de la escala se rechaza aquí con un error explícito: un literal
decimal (sería un monto en pesos), la división (SQLite trunca entre enteros) y `ROUND` a
menos de dos decimales (que `round_centavos` rechaza al ejecutar).

Cualquier otra construcción `BUILTIN.*` es un error explícito, nunca se deja pasar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable, List, Mapping, Optional, Tuple

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
_RE_ROUND = re.compile(r"\bROUND\s*\(", re.IGNORECASE)
# Número con punto decimal o exponente que no es parte de un identificador (`tal2.debit` no cuenta).
_RE_LITERAL_DECIMAL = re.compile(r"(?<![\w.])(?:\d+\.\d*|\.\d+|\d+(?=[eE][+-]?\d))")
_RE_TRANSACTION = re.compile(r"\btransaction\b", re.IGNORECASE)
_RE_BUILTIN = re.compile(r"\bBUILTIN\s*\.\s*(\w+)", re.IGNORECASE)
_RE_ESPECIAL = re.compile(r"'|\"|--|/\*")


DECIMALES_MINIMOS_ROUND = 2  # redondear centavos enteros a 2 o más decimales no cambia nada
FUNCION_ROUND = "ROUND_CENTAVOS"


class ErrorCompatibilidad(ValueError):
    """El texto SuiteQL usa algo que esta capa no sabe traducir, o está mal cerrado."""


def round_centavos(centavos: object, decimales: object) -> Optional[int]:
    """`ROUND(x, n)` de SuiteQL sobre centavos enteros: con `n >= 2` el valor no cambia.

    Falla con un `float` o un texto (señal de aritmética no exacta) y con `n < 2`, que en
    centavos necesitaría redondear de verdad y no se usa en estas queries.
    """
    if centavos is None:
        return None
    if isinstance(centavos, bool) or not isinstance(centavos, int):
        raise ValueError(f"ROUND recibe centavos enteros y llegó {type(centavos).__name__}: {centavos!r}")
    if isinstance(decimales, bool) or not isinstance(decimales, int):
        raise ValueError(f"ROUND necesita un número entero de decimales, llegó {decimales!r}")
    if decimales < DECIMALES_MINIMOS_ROUND:
        raise ValueError(f"ROUND a {decimales} decimales no está soportado: se requieren al menos "
                         f"{DECIMALES_MINIMOS_ROUND} decimales sobre centavos enteros")
    return centavos


# Funciones que el SQL traducido necesita; `esquema.crear_conexion` las registra.
FUNCIONES_SQLITE: Mapping[str, Tuple[int, Callable[[object, object], Optional[int]]]] = MappingProxyType(
    {FUNCION_ROUND: (2, round_centavos)}
)


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
    _rechazar_aritmetica_de_escala(codigo)
    # El identificador se cita antes de expandir BUILTIN.DF: las plantillas no lo usan.
    citado = _RE_TRANSACTION.sub('"transaction"', codigo)
    expandido = _RE_DF.sub(_expandir_df, citado)
    restante = _RE_BUILTIN.search(expandido)
    if restante:
        raise ErrorCompatibilidad(f"construcción SuiteQL sin traducción: BUILTIN.{restante.group(1).upper()}")
    return _RE_ROUND.sub(FUNCION_ROUND + "(", _RE_NVL.sub("COALESCE(", expandido))


def _rechazar_aritmetica_de_escala(codigo: str) -> None:
    """Lo que daría otro resultado en centavos que en pesos no se traduce: falla aquí."""
    literal = _RE_LITERAL_DECIMAL.search(codigo)
    if literal:
        raise ErrorCompatibilidad(
            f"literal decimal en la posición {literal.start()} del código: los montos de la base sintética "
            "son centavos enteros, así que un monto en pesos no se compararía bien; compara contra 0"
        )
    if "/" in codigo:
        raise ErrorCompatibilidad("la división no se traduce: SQLite trunca entre enteros y los montos son centavos")


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
