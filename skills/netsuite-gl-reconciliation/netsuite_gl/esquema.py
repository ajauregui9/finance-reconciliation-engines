"""DDL del esquema SQLite que imita las tablas de SuiteQL.

`transaction` es palabra reservada en SQLite, por eso aquí va citado. Las queries `.sql`
lo escriben sin comillas, como en SuiteQL, y la capa de compatibilidad lo cita.
"""
from __future__ import annotations

import sqlite3
from typing import Tuple

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
        debit NUMERIC,
        credit NUMERIC,
        amount NUMERIC NOT NULL,
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
        custrecord_cfdi_subtotal NUMERIC NOT NULL,
        custrecord_cfdi_iva NUMERIC NOT NULL,
        custrecord_cfdi_total NUMERIC NOT NULL,
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


def citar(identificador: str) -> str:
    """Cita un identificador para SQLite (siempre: así `transaction` nunca choca)."""
    return '"' + identificador.replace('"', '""') + '"'


def crear_conexion() -> sqlite3.Connection:
    """Base en memoria con llaves foráneas activas y el esquema creado."""
    conexion = sqlite3.connect(":memory:")
    conexion.execute("PRAGMA foreign_keys = ON")
    for sentencia in DDL:
        conexion.execute(sentencia)
    return conexion


def sentencia_insercion(tabla: str, columnas: Tuple[str, ...]) -> str:
    lista = ", ".join(citar(c) for c in columnas)
    marcas = ", ".join("?" for _ in columnas)
    return f"INSERT INTO {citar(tabla)} ({lista}) VALUES ({marcas})"
