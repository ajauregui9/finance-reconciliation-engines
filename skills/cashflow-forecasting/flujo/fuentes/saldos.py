"""Adaptador de saldos bancarios: una fila contrato de saldo inicial por cuenta."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from ..contrato import CONCEPTO_SALDO, FUENTE_SALDOS, FilaContrato, ResultadoFuente, ordenar_filas
from ..dinero import CERO
from ..errores import ErrorInsumo
from ..lectura import Registro, exigir_unicas, leer_tabla

COLUMNAS = ("cuenta", "banco", "fecha_saldo", "moneda", "saldo")


def _fila(registro: Registro, corte: date, moneda: str) -> FilaContrato:
    registro.exigir_moneda("moneda", moneda)
    fecha = registro.fecha("fecha_saldo")
    if fecha != corte:
        raise registro.falla_en(
            "fecha_saldo", f"la fecha {fecha.isoformat()} no es la fecha de corte {corte.isoformat()}"
        )
    return FilaContrato(
        fuente=FUENTE_SALDOS, concepto=CONCEPTO_SALDO, semana=1, fecha=corte,
        referencia=registro.texto("cuenta"), contraparte=registro.texto("banco"), monto=registro.monto("saldo"),
    )


def leer_saldos(ruta: Path, corte: date, moneda: str) -> ResultadoFuente:
    tabla = leer_tabla(ruta, COLUMNAS)
    if not tabla.registros:
        raise ErrorInsumo(f"{tabla.archivo}: se necesita al menos una cuenta con saldo a la fecha de corte")
    filas = tuple(_fila(r, corte, moneda) for r in tabla.registros)
    exigir_unicas(tabla.registros, [f.referencia for f in filas], "la cuenta")
    return ResultadoFuente(
        fuente=FUENTE_SALDOS, archivo=tabla.archivo, sha256=tabla.sha256, registros=len(tabla.registros),
        total_insumo=sum((f.monto for f in filas), CERO), filas=ordenar_filas(filas),
        fuera_horizonte=CERO, no_cobrable=CERO,
    )
