"""Representación determinista de resultados y del manifiesto (sin marcas de tiempo)."""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence, Union

from netsuite_gl.consultas import ResultadoConsulta
from netsuite_gl.discrepancias import Manifiesto
from netsuite_gl.montos import formatear

ESQUEMA_MANIFIESTO = "netsuite_discrepancias/v1"
ValorCelda = Union[str, int, Decimal, None]


def celda(valor: ValorCelda) -> str:
    """Texto de una celda: montos a dos decimales y `None` como vacío."""
    if valor is None:
        return ""
    if isinstance(valor, Decimal):
        return formatear(valor)
    return str(valor)


def tabla_a_csv(columnas: Sequence[str], filas: Sequence[Sequence[ValorCelda]]) -> str:
    buffer = io.StringIO()
    escritor = csv.writer(buffer, lineterminator="\n")
    escritor.writerow(columnas)
    for fila in filas:
        escritor.writerow([celda(v) for v in fila])
    return buffer.getvalue()


def resultado_a_csv(resultado: ResultadoConsulta) -> str:
    """CSV de un resultado, con columnas y filas en el orden que dio la query."""
    return tabla_a_csv(resultado.columnas, resultado.filas)


def manifiesto_a_dict(m: Manifiesto) -> Dict[str, Any]:
    return {
        "esquema": ESQUEMA_MANIFIESTO,
        "parametros": {
            "semilla": m.plan.semilla,
            "sin_registro": m.plan.sin_registro,
            "monto_distinto": m.plan.monto_distinto,
            "duplicado": m.plan.duplicado,
            "periodo_equivocado": m.plan.periodo_equivocado,
            "deltas_monto": [formatear(d) for d in m.plan.deltas_monto],
            "rfc_empresa": m.rfc_empresa,
        },
        "resumen": {
            "cfdis_leidos": m.cfdis_leidos,
            "universo": m.universo,
            "transacciones": m.transacciones,
            "proveedores": m.proveedores,
            "excluidos": dict(m.excluidos),
        },
        "discrepancias": {
            "sin_registro": [{"uuid": u} for u in m.sin_registro],
            "monto_distinto": [
                {"uuid": p.uuid, "delta": formatear(p.delta), "diferencia_esperada": formatear(p.diferencia_esperada)}
                for p in m.monto_distinto
            ],
            "duplicado": [
                {"uuid": p.uuid, "transacciones": list(p.transacciones),
                 "diferencia_esperada": formatear(p.diferencia_esperada)}
                for p in m.duplicado
            ],
            "periodo_equivocado": [
                {"uuid": p.uuid, "transaccion": p.transaccion, "periodo_esperado": p.periodo_esperado,
                 "periodo_registrado": p.periodo_registrado}
                for p in m.periodo_equivocado
            ],
        },
    }


def manifiesto_a_json(m: Manifiesto) -> str:
    return json_determinista(manifiesto_a_dict(m))


def json_determinista(datos: Any, sangria: Optional[int] = 2) -> str:
    return json.dumps(datos, ensure_ascii=False, indent=sangria, sort_keys=True) + "\n"
