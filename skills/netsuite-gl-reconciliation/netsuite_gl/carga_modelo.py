"""Modelo de los asientos a cargar por CSV import y su lectura desde JSON.

La lectura solo revisa la forma (campos, tipos, fechas ISO, montos como texto). Las reglas
contables (cuadre, catálogos, periodo abierto) viven en `carga_validacion`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Dict, Optional, Sequence, Tuple

from frontera import ErrorFrontera, FormaImporte, leer_importe

from netsuite_gl.fechas import fecha_iso

CAMPOS_ASIENTO: Tuple[str, ...] = ("id_externo", "fecha", "periodo", "memo", "referencia", "lineas")
CAMPOS_LINEA: Tuple[str, ...] = ("cuenta", "debito", "credito", "clase", "entidad", "memo")
LLAVE_RAIZ = "asientos"


# Importes de carga: texto decimal exacto, sin redondear; la validación previa reporta más de dos
# decimales como `importe_invalido` (spec, sección 7).
FORMA_IMPORTE_EXACTO = FormaImporte(decimales=None)

class ErrorEntrada(ValueError):
    """El documento de asientos no tiene la forma esperada (se rechaza antes de validar)."""


@dataclass(frozen=True)
class LineaCarga:
    cuenta: str
    debito: Decimal
    credito: Decimal
    clase: Optional[str]
    entidad: Optional[str]
    memo: str


@dataclass(frozen=True)
class AsientoCarga:
    id_externo: str
    fecha: date
    periodo: str
    memo: str
    referencia: Optional[str]
    lineas: Tuple[LineaCarga, ...]


def asientos_desde_json(texto: str) -> Tuple[AsientoCarga, ...]:
    """Lee `{"asientos": [...]}`; cualquier problema de forma es `ErrorEntrada` inmediato."""
    try:
        documento = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ErrorEntrada(f"JSON inválido: {exc.msg} (línea {exc.lineno}, columna {exc.colno})") from exc
    if not isinstance(documento, dict):
        raise ErrorEntrada(f"el documento debe ser un objeto JSON con la llave '{LLAVE_RAIZ}'")
    _llaves_exactas(documento, (LLAVE_RAIZ,), "documento")
    crudos = documento[LLAVE_RAIZ]
    if not isinstance(crudos, list):
        raise ErrorEntrada(f"'{LLAVE_RAIZ}' debe ser una lista")
    return tuple(_asiento(crudo, f"asiento {i}") for i, crudo in enumerate(crudos, start=1))


def _asiento(crudo: Any, donde: str) -> AsientoCarga:
    objeto = _objeto(crudo, donde)
    _llaves_exactas(objeto, CAMPOS_ASIENTO, donde)
    lineas = objeto["lineas"]
    if not isinstance(lineas, list):
        raise ErrorEntrada(f"{donde}: 'lineas' debe ser una lista")
    return AsientoCarga(
        id_externo=_texto(objeto, "id_externo", donde),
        fecha=_fecha(objeto, donde),
        periodo=_texto(objeto, "periodo", donde),
        memo=_texto(objeto, "memo", donde, vacio=True),
        referencia=_texto_opcional(objeto, "referencia", donde),
        lineas=tuple(_linea(linea, f"{donde}, línea {j}") for j, linea in enumerate(lineas, start=1)),
    )


def _linea(crudo: Any, donde: str) -> LineaCarga:
    objeto = _objeto(crudo, donde)
    _llaves_exactas(objeto, CAMPOS_LINEA, donde)
    return LineaCarga(
        cuenta=_texto(objeto, "cuenta", donde),
        debito=_importe(objeto, "debito", donde),
        credito=_importe(objeto, "credito", donde),
        clase=_texto_opcional(objeto, "clase", donde),
        entidad=_texto_opcional(objeto, "entidad", donde),
        memo=_texto(objeto, "memo", donde, vacio=True),
    )


def _objeto(crudo: Any, donde: str) -> Dict[str, Any]:
    if not isinstance(crudo, dict):
        raise ErrorEntrada(f"{donde}: se esperaba un objeto JSON")
    return crudo


def _llaves_exactas(objeto: Dict[str, Any], esperadas: Sequence[str], donde: str) -> None:
    faltantes = [c for c in esperadas if c not in objeto]
    sobrantes = sorted(set(objeto) - set(esperadas))
    if faltantes:
        raise ErrorEntrada(f"{donde}: faltan campos {', '.join(faltantes)}")
    if sobrantes:
        raise ErrorEntrada(f"{donde}: campos desconocidos {', '.join(sobrantes)}")


def _texto(objeto: Dict[str, Any], campo: str, donde: str, vacio: bool = False) -> str:
    valor = objeto[campo]
    if not isinstance(valor, str) or (not vacio and not valor.strip()):
        requisito = "texto" if vacio else "texto no vacío"
        raise ErrorEntrada(f"{donde}: '{campo}' debe ser {requisito}")
    return valor


def _texto_opcional(objeto: Dict[str, Any], campo: str, donde: str) -> Optional[str]:
    if objeto[campo] is None:
        return None
    if not isinstance(objeto[campo], str) or not objeto[campo].strip():
        raise ErrorEntrada(f"{donde}: '{campo}' debe ser texto no vacío o null")
    return str(objeto[campo])


def _importe(objeto: Dict[str, Any], campo: str, donde: str) -> Decimal:
    """Sin cuantizar: la validación debe ver si alguien mandó más de dos decimales."""
    valor = objeto[campo]
    if not isinstance(valor, str):
        raise ErrorEntrada(f"{donde}: '{campo}' debe ser texto decimal (p. ej. \"100.00\"), no {type(valor).__name__}")
    try:
        return leer_importe(valor, FORMA_IMPORTE_EXACTO)
    except ErrorFrontera as exc:
        raise ErrorEntrada(f"{donde}: '{campo}' no es un número decimal: {exc}") from None


def _fecha(objeto: Dict[str, Any], donde: str) -> date:
    valor = objeto["fecha"]
    try:
        return fecha_iso(valor)
    except ValueError as exc:
        raise ErrorEntrada(f"{donde}: 'fecha' debe ser AAAA-MM-DD válida, no {valor!r}") from exc
