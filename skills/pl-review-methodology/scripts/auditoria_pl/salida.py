"""Conversión del reporte a JSON canónico: llaves ordenadas, montos como texto, sin marcas de tiempo."""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from decimal import Decimal
from typing import Any, Mapping

from .dinero import texto


def a_json(valor: Any) -> Any:
    """Convierte dataclasses, mapeos, tuplas, `Decimal` y fechas a tipos JSON nativos."""
    if dataclasses.is_dataclass(valor) and not isinstance(valor, type):
        return {campo.name: a_json(getattr(valor, campo.name)) for campo in dataclasses.fields(valor)}
    if isinstance(valor, Mapping):
        return {str(llave): a_json(item) for llave, item in valor.items()}
    if isinstance(valor, (tuple, list)):
        return [a_json(item) for item in valor]
    if isinstance(valor, Decimal):
        return texto(valor)
    if isinstance(valor, date):
        return valor.isoformat()
    if valor is None or isinstance(valor, (bool, int, str)):
        return valor
    raise TypeError(f"No se sabe serializar un valor de tipo {type(valor).__name__}")


def serializar(valor: Any) -> str:
    """JSON UTF-8 determinista: mismas entradas, mismos bytes."""
    return json.dumps(a_json(valor), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
