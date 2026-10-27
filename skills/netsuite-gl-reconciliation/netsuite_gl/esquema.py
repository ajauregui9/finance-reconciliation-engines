"""DDL del esquema SQLite que imita las tablas de SuiteQL.

`transaction` es palabra reservada en SQLite, por eso aquí va citado. Las queries `.sql`
lo escriben sin comillas, como en SuiteQL, y la capa de compatibilidad lo cita.

Los montos (`COLUMNAS_MONTO`) son centavos enteros: en NetSuite son decimales, pero en
SQLite una columna decimal se guarda como REAL y `SUM` correría en punto flotante. Con
enteros la aritmética es exacta y la conversión a `Decimal` ocurre una sola vez, al leer
(`consultas.ejecutar`). La capa de compatibilidad explica por qué las queries no cambian.
"""
from __future__ import annotations

import sqlite3
from types import MappingProxyType
from typing import FrozenSet, Mapping, Sequence, Tuple, Union

from netsuite_gl.compat import FUNCIONES_SQLITE
from netsuite_gl.errores import ErrorPoblado

ValorFila = Union[str, int, None]

# Orden de creación: primero los catálogos que otras tablas referencian.
DDL: Tuple[str, ...] = (
    """CREATE TABLE account (
        id INTEGER PRIMARY KEY,
        acctnumber TEXT NOT NULL UNIQUE,
        fullname TEXT NOT NULL,
        accttype TEXT NOT NULL,
        isinactive TEXT NOT NULL CHECK (isinactive IN ('T', 'F'))
    )""",
    """CREATE TABLE accountingperiod (
        id INTEGER PRIMARY KEY,
        periodname TEXT NOT NULL UNIQUE,
        startdate TEXT NOT NULL,
        enddate TEXT NOT NULL,
        isposting TEXT NOT NULL CHECK (isposting IN ('T', 'F')),
        isquarter TEXT NOT NULL CHECK (isquarter IN ('T', 'F')),
        isyear TEXT NOT NULL CHECK (isyear IN ('T', 'F')),
        closed TEXT NOT NULL CHECK (closed IN ('T', 'F'))
    )""",
    """CREATE TABLE classification (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        fullname TEXT NOT NULL,
        isinactive TEXT NOT NULL CHECK (isinactive IN ('T', 'F'))
    )""",
    """CREATE TABLE vendor (
        id INTEGER PRIMARY KEY,
        entityid TEXT NOT NULL UNIQUE,
        companyname TEXT NOT NULL,
        custentity_mx_rfc TEXT NOT NULL,
        isinactive TEXT NOT NULL CHECK (isinactive IN ('T', 'F'))
    )""",
    """CREATE TABLE "transaction" (
        id INTEGER PRIMARY KEY,
        tranid TEXT NOT NULL,
        trandate TEXT NOT NULL,
        type TEXT NOT NULL,
        postingperiod INTEGER NOT NULL REFERENCES accountingperiod (id),
        entity INTEGER REFERENCES vendor (id),
        memo TEXT,
        posting TEXT NOT NULL CHECK (posting IN ('T', 'F')),
        custbody_mx_cfdi_uuid TEXT
    )""",
    """CREATE TABLE transactionline (
        "transaction" INTEGER NOT NULL REFERENCES "transaction" (id),
        id INTEGER NOT NULL,
        linesequencenumber INTEGER NOT NULL,
        mainline TEXT NOT NULL CHECK (mainline IN ('T', 'F')),
        taxline TEXT NOT NULL CHECK (taxline IN ('T', 'F')),
        class INTEGER REFERENCES classification (id),
        entity INTEGER REFERENCES vendor (id),
        memo TEXT,
        PRIMARY KEY ("transaction", id)
    )""",
    """CREATE TABLE transactionaccountingline (
        "transaction" INTEGER NOT NULL,
        transactionline INTEGER NOT NULL,
        account INTEGER NOT NULL REFERENCES account (id),
        debit INTEGER CHECK (typeof(debit) IN ('integer', 'null')),
        credit INTEGER CHECK (typeof(credit) IN ('integer', 'null')),
        amount INTEGER NOT NULL CHECK (typeof(amount) = 'integer'),
        posting TEXT NOT NULL CHECK (posting IN ('T', 'F')),
        PRIMARY KEY ("transaction", transactionline),
        FOREIGN KEY ("transaction", transactionline) REFERENCES transactionline ("transaction", id)
    )""",
    """CREATE TABLE customrecord_cfdi_recibido (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        custrecord_cfdi_uuid TEXT NOT NULL UNIQUE,
        custrecord_cfdi_fecha TEXT NOT NULL,
        custrecord_cfdi_tipo TEXT NOT NULL,
        custrecord_cfdi_rfc_emisor TEXT NOT NULL,
        custrecord_cfdi_nombre_emisor TEXT NOT NULL,
        custrecord_cfdi_serie TEXT NOT NULL,
        custrecord_cfdi_folio TEXT NOT NULL,
        custrecord_cfdi_concepto TEXT NOT NULL,
        custrecord_cfdi_subtotal INTEGER NOT NULL CHECK (typeof(custrecord_cfdi_subtotal) = 'integer'),
        custrecord_cfdi_iva INTEGER NOT NULL CHECK (typeof(custrecord_cfdi_iva) = 'integer'),
        custrecord_cfdi_total INTEGER NOT NULL CHECK (typeof(custrecord_cfdi_total) = 'integer'),
        custrecord_cfdi_uuid_relacionado TEXT
    )""",
)

# Columnas por tabla en el orden de inserción (el mismo de la DDL).
COLUMNAS: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
    ("account", ("id", "acctnumber", "fullname", "accttype", "isinactive")),
    ("accountingperiod", ("id", "periodname", "startdate", "enddate", "isposting", "isquarter", "isyear", "closed")),
    ("classification", ("id", "name", "fullname", "isinactive")),
    ("vendor", ("id", "entityid", "companyname", "custentity_mx_rfc", "isinactive")),
    ("transaction", (
        "id", "tranid", "trandate", "type", "postingperiod", "entity", "memo", "posting", "custbody_mx_cfdi_uuid",
    )),
    ("transactionline", (
        "transaction", "id", "linesequencenumber", "mainline", "taxline", "class", "entity", "memo",
    )),
    ("transactionaccountingline", (
        "transaction", "transactionline", "account", "debit", "credit", "amount", "posting",
    )),
    ("customrecord_cfdi_recibido", (
        "id", "name", "custrecord_cfdi_uuid", "custrecord_cfdi_fecha", "custrecord_cfdi_tipo",
        "custrecord_cfdi_rfc_emisor", "custrecord_cfdi_nombre_emisor", "custrecord_cfdi_serie",
        "custrecord_cfdi_folio", "custrecord_cfdi_concepto", "custrecord_cfdi_subtotal", "custrecord_cfdi_iva",
        "custrecord_cfdi_total", "custrecord_cfdi_uuid_relacionado",
    )),
)


# Columnas monetarias, en centavos enteros. Cualquier otro tipo se rechaza antes de insertar:
# la afinidad INTEGER de SQLite convertiría el texto "116.00" en 116 sin avisar.
COLUMNAS_MONTO: Mapping[str, FrozenSet[str]] = MappingProxyType({
    "transactionaccountingline": frozenset({"debit", "credit", "amount"}),
    "customrecord_cfdi_recibido": frozenset({
        "custrecord_cfdi_subtotal", "custrecord_cfdi_iva", "custrecord_cfdi_total",
    }),
})


def citar(identificador: str) -> str:
    """Cita un identificador para SQLite (siempre: así `transaction` nunca choca)."""
    return '"' + identificador.replace('"', '""') + '"'


def crear_conexion() -> sqlite3.Connection:
    """Base en memoria con llaves foráneas, el esquema y las funciones de la capa de compatibilidad.

    Quien la recibe la cierra (`BaseSintetica` lo hace al salir de su bloque `with`).
    """
    conexion = sqlite3.connect(":memory:")
    try:
        conexion.execute("PRAGMA foreign_keys = ON")
        for nombre, (argumentos, funcion) in FUNCIONES_SQLITE.items():
            conexion.create_function(nombre, argumentos, funcion, deterministic=True)
        for sentencia in DDL:
            conexion.execute(sentencia)
    except BaseException:
        conexion.close()
        raise
    return conexion


def insertar_filas(conexion: sqlite3.Connection, por_tabla: Mapping[str, Sequence[Sequence[ValorFila]]]) -> None:
    """Inserta las filas en el orden de la DDL, en una sola transacción; nada se inserta si algo falla."""
    columnas_por_tabla = dict(COLUMNAS)
    desconocidas = sorted(set(por_tabla) - set(columnas_por_tabla))
    if desconocidas:
        raise ErrorPoblado(f"tablas que no están en el esquema: {', '.join(desconocidas)}")
    for tabla, filas in por_tabla.items():
        _validar_montos(tabla, columnas_por_tabla[tabla], filas)
    try:
        with conexion:
            for tabla, columnas in COLUMNAS:
                conexion.executemany(sentencia_insercion(tabla, columnas), por_tabla.get(tabla, ()))
    except sqlite3.Error as exc:
        raise ErrorPoblado(f"el esquema rechazó las filas a insertar: {exc}") from exc


def _validar_montos(tabla: str, columnas: Tuple[str, ...], filas: Sequence[Sequence[ValorFila]]) -> None:
    monetarias = COLUMNAS_MONTO.get(tabla, frozenset())
    for numero, fila in enumerate(filas, start=1):
        for columna, valor in zip(columnas, fila):
            if columna in monetarias and valor is not None and type(valor) is not int:
                raise ErrorPoblado(
                    f"{tabla}.{columna}, fila {numero}: un monto se guarda como centavos enteros, "
                    f"llegó {type(valor).__name__} {valor!r}"
                )


def sentencia_insercion(tabla: str, columnas: Tuple[str, ...]) -> str:
    lista = ", ".join(citar(c) for c in columnas)
    marcas = ", ".join("?" for _ in columnas)
    return f"INSERT INTO {citar(tabla)} ({lista}) VALUES ({marcas})"
