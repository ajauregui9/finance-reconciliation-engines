"""Arma la base SQLite sintética a partir de los CFDIs y devuelve el manifiesto de lo plantado.

La base vive en memoria y se cierra al salir de su bloque::

    with construir_base(ruta_cfdis) as base:
        resultados = ejecutar_todas(base.conexion)
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Dict, List, Optional, Sequence, Type

from netsuite_gl.cfdis import LecturaCfdis, leer_cfdis
from netsuite_gl.config import CONFIG_DEFAULT, ConfigEsquema, PlanDiscrepancias
from netsuite_gl.discrepancias import (
    Asignacion,
    Manifiesto,
    PlantaDuplicado,
    PlantaMonto,
    PlantaPeriodo,
    asignar,
)
from netsuite_gl.errores import ErrorPoblado as ErrorPoblado  # reexportada para quien llama
from netsuite_gl.esquema import crear_conexion, insertar_filas
from netsuite_gl.filas import FilasEsquema, TransaccionArmada, armar_filas
from netsuite_gl.periodos import Periodo, construir_periodos, periodo_de_registro

PLAN_DEFAULT = PlanDiscrepancias()


@dataclass(frozen=True)
class BaseSintetica:
    """La conexión poblada y su manifiesto. Se usa con `with`, que cierra la conexión al salir."""

    conexion: sqlite3.Connection
    manifiesto: Manifiesto

    def cerrar(self) -> None:
        """Cierra la conexión; llamarla otra vez no hace nada."""
        self.conexion.close()

    def __enter__(self) -> "BaseSintetica":
        return self

    def __exit__(
        self,
        tipo: Optional[Type[BaseException]],
        error: Optional[BaseException],
        rastro: Optional[TracebackType],
    ) -> None:
        self.cerrar()


def construir_base(
    ruta_cfdis: Path, config: ConfigEsquema = CONFIG_DEFAULT, plan: PlanDiscrepancias = PLAN_DEFAULT
) -> BaseSintetica:
    """Lee los CFDIs, planta las discrepancias del plan y llena una base en memoria.

    Si algo falla después de abrir la conexión, la conexión se cierra antes de propagar el error.
    """
    lectura = leer_cfdis(ruta_cfdis, config.rfc_empresa)
    periodos = construir_periodos(config)
    asignacion = asignar(lectura.universo, plan)
    filas = armar_filas(lectura.universo, asignacion, config, periodos)
    manifiesto = _manifiesto(lectura, plan, config, asignacion, filas, periodos)
    conexion = crear_conexion()
    try:
        insertar_filas(conexion, filas.por_tabla)
    except BaseException:
        conexion.close()
        raise
    return BaseSintetica(conexion, manifiesto)


def _manifiesto(
    lectura: LecturaCfdis,
    plan: PlanDiscrepancias,
    config: ConfigEsquema,
    asignacion: Asignacion,
    filas: FilasEsquema,
    periodos: Sequence[Periodo],
) -> Manifiesto:
    por_uuid = {c.uuid: c for c in lectura.universo}
    ids: Dict[str, List[int]] = defaultdict(list)
    for tx in filas.transacciones:
        ids[tx.cfdi.uuid].append(tx.id)
    montos = tuple(
        PlantaMonto(uuid, delta, por_uuid[uuid].signo * delta)
        for uuid, delta in sorted(asignacion.monto_distinto.items())
    )
    duplicados = tuple(
        PlantaDuplicado(uuid, (ids[uuid][0], ids[uuid][1]), por_uuid[uuid].signo * por_uuid[uuid].total_mxn)
        for uuid in sorted(asignacion.duplicado)
    )
    equivocados = tuple(
        _planta_periodo(tx, periodos)
        for tx in sorted(filas.transacciones, key=lambda t: (t.cfdi.uuid, t.id))
        if tx.cfdi.uuid in asignacion.periodo_equivocado
    )
    return Manifiesto(
        plan=plan,
        rfc_empresa=config.rfc_empresa,
        cfdis_leidos=lectura.leidos,
        universo=len(lectura.universo),
        transacciones=len(filas.transacciones),
        proveedores=filas.num_proveedores,
        excluidos=lectura.excluidos,
        sin_registro=tuple(sorted(asignacion.sin_registro)),
        monto_distinto=montos,
        duplicado=duplicados,
        periodo_equivocado=equivocados,
    )


def _planta_periodo(tx: TransaccionArmada, periodos: Sequence[Periodo]) -> PlantaPeriodo:
    esperado = periodo_de_registro(tx.cfdi.fecha, periodos)
    if esperado is None:  # armar_filas ya lo garantiza; se revisa para no suponer
        raise ErrorPoblado(f"sin periodo de registro para {tx.cfdi.uuid}")
    return PlantaPeriodo(tx.cfdi.uuid, tx.id, esperado.nombre, tx.periodo.nombre)
