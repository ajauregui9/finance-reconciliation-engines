"""Carga de las queries `.sql` (SuiteQL) y su ejecución contra la base sintética.

Cada archivo empieza con un encabezado de comentarios `-- @clave: valor`:
`descripcion` (obligatoria) y `montos` (columnas que se convierten a `Decimal`).

La base guarda los montos en centavos enteros, así que una columna de `@montos` debe llegar
como entero (o `NULL`) y se convierte una sola vez con `desde_centavos`. Un `float` en
cualquier columna es un error: indicaría aritmética no exacta en la query.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Union

from netsuite_gl.compat import ErrorCompatibilidad, traducir
from netsuite_gl.montos import ErrorMonto, desde_centavos

DIR_QUERIES = Path(__file__).resolve().parent.parent / "queries"

# Orden fijo de ejecución y de salida; también es el registro de queries válidas.
ORDEN_CONSULTAS: Tuple[str, ...] = (
    "saldos_cuenta_periodo_clase",
    "cfdi_sin_registro",
    "cuadre_cfdi_gl",
    "duplicados_registro",
    "periodo_equivocado",
)

CLAVE_DESCRIPCION = "descripcion"
CLAVE_MONTOS = "montos"
_CLAVES = frozenset({CLAVE_DESCRIPCION, CLAVE_MONTOS})
_RE_NOMBRE = re.compile(r"^[a-z][a-z0-9_]*$")
_RE_META = re.compile(r"^--\s*@(\w+)\s*:(.*)$")

Valor = Union[str, int, Decimal, None]


class ErrorConsulta(ValueError):
    """Query desconocida, encabezado inválido o resultado que no cumple su contrato."""


@dataclass(frozen=True)
class Consulta:
    nombre: str
    descripcion: str
    columnas_monto: Tuple[str, ...]
    suiteql: str


@dataclass(frozen=True)
class ResultadoConsulta:
    nombre: str
    columnas: Tuple[str, ...]
    filas: Tuple[Tuple[Valor, ...], ...]


def cargar_consulta(nombre: str) -> Consulta:
    """Lee `queries/<nombre>.sql`; solo acepta nombres registrados en `ORDEN_CONSULTAS`."""
    if not _RE_NOMBRE.match(nombre) or nombre not in ORDEN_CONSULTAS:
        raise ErrorConsulta(f"consulta desconocida {nombre!r}; disponibles: {', '.join(ORDEN_CONSULTAS)}")
    ruta = DIR_QUERIES / f"{nombre}.sql"
    if not ruta.is_file():
        raise ErrorConsulta(f"la consulta {nombre} está registrada pero falta su archivo {ruta.name}")
    return parsear_consulta(nombre, ruta.read_text(encoding="utf-8"))


def parsear_consulta(nombre: str, texto: str) -> Consulta:
    metadatos = _leer_encabezado(nombre, texto)
    descripcion = metadatos.get(CLAVE_DESCRIPCION, "")
    if not descripcion:
        raise ErrorConsulta(f"{nombre}: falta '-- @{CLAVE_DESCRIPCION}: ...' en el encabezado")
    montos: Tuple[str, ...] = ()
    if CLAVE_MONTOS in metadatos:
        montos = tuple(c.strip() for c in metadatos[CLAVE_MONTOS].split(","))
        if any(not c for c in montos):
            raise ErrorConsulta(f"{nombre}: la lista de @{CLAVE_MONTOS} tiene un elemento vacío")
    return Consulta(nombre, descripcion, montos, texto)


def ejecutar(conexion: sqlite3.Connection, consulta: Consulta) -> ResultadoConsulta:
    """Traduce, ejecuta y convierte los montos en la frontera única `centavos enteros → Decimal`."""
    try:
        cursor = conexion.execute(traducir(consulta.suiteql))
    except ErrorCompatibilidad as exc:
        raise ErrorConsulta(f"{consulta.nombre}: {exc}") from exc
    except sqlite3.Error as exc:
        raise ErrorConsulta(f"la consulta {consulta.nombre} falló en SQLite: {exc}") from exc
    if cursor.description is None:
        raise ErrorConsulta(f"la consulta {consulta.nombre} no devuelve columnas")
    columnas = tuple(str(d[0]) for d in cursor.description)
    faltantes = [c for c in consulta.columnas_monto if c not in columnas]
    if faltantes:
        raise ErrorConsulta(f"{consulta.nombre}: columnas de @montos ausentes del resultado: {', '.join(faltantes)}")
    filas = tuple(_convertir(consulta, columnas, fila) for fila in cursor.fetchall())
    return ResultadoConsulta(consulta.nombre, columnas, filas)


def ejecutar_por_nombre(conexion: sqlite3.Connection, nombre: str) -> ResultadoConsulta:
    return ejecutar(conexion, cargar_consulta(nombre))


def ejecutar_todas(
    conexion: sqlite3.Connection, nombres: Sequence[str] = ORDEN_CONSULTAS
) -> Tuple[ResultadoConsulta, ...]:
    return tuple(ejecutar_por_nombre(conexion, n) for n in nombres)


def _leer_encabezado(nombre: str, texto: str) -> Dict[str, str]:
    metadatos: Dict[str, str] = {}
    for linea in texto.splitlines():
        limpia = linea.strip()
        if not limpia:
            continue
        if not limpia.startswith("--"):
            break
        coincidencia = _RE_META.match(limpia)
        if coincidencia is None:
            continue  # comentario libre del encabezado
        clave, valor = coincidencia.group(1), coincidencia.group(2).strip()
        if clave not in _CLAVES:
            raise ErrorConsulta(f"{nombre}: clave de encabezado desconocida @{clave}")
        metadatos[clave] = valor
    return metadatos


def _convertir(consulta: Consulta, columnas: Tuple[str, ...], fila: Sequence[object]) -> Tuple[Valor, ...]:
    convertidos: List[Valor] = []
    for columna, valor in zip(columnas, fila):
        if columna in consulta.columnas_monto:
            convertidos.append(_monto(consulta.nombre, columna, valor))
        elif valor is None or isinstance(valor, (str, int)) and not isinstance(valor, bool):
            convertidos.append(valor)
        else:
            raise ErrorConsulta(
                f"{consulta.nombre}: la columna {columna} trae {type(valor).__name__}; "
                f"si es un monto, decláralo en @{CLAVE_MONTOS}"
            )
    return tuple(convertidos)


def _monto(nombre: str, columna: str, valor: object) -> Union[Decimal, None]:
    if valor is None:
        return None
    if isinstance(valor, float):
        raise ErrorConsulta(
            f"{nombre}: la columna monetaria {columna} trae un float ({valor!r}); la base guarda centavos "
            "enteros, así que la query hizo aritmética no exacta (por ejemplo AVG o una conversión a REAL)"
        )
    try:
        return desde_centavos(valor)
    except ErrorMonto as exc:
        raise ErrorConsulta(f"{nombre}: la columna monetaria {columna} no trae centavos enteros: {exc}") from exc
