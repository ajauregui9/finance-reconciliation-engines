"""Frontera de entrada: lectura estricta de JSON ya decodificado.

Es el único lugar donde un dato externo se convierte a tipos del dominio. Cada
lector recibe la ruta del dato (por ejemplo `cuentas[3].actual`) para que el
mensaje de error diga exactamente qué falló. Una llave desconocida es error: en
este revisor no existen llaves que se lean "por si acaso".
"""

from __future__ import annotations

import calendar
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence, Set, Tuple

from .dinero import CERO, redondear

# Texto decimal plano: signo opcional, dígitos ASCII y parte decimal opcional.
_PATRON_MONTO = re.compile(r"[+-]?[0-9]+(?:\.[0-9]+)?")
_PATRON_PERIODO = re.compile(r"[1-9][0-9]{3}-(?:0[1-9]|1[0-2])")
_PATRON_FECHA = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")


class ErrorEntrada(ValueError):
    """Config, exportación o argumento inválido; el mensaje incluye la ruta del dato."""


def _unir(ruta: str, llave: str) -> str:
    return f"{ruta}.{llave}" if ruta else llave


def exigir_objeto(valor: Any, ruta: str) -> Mapping[str, Any]:
    if not isinstance(valor, dict):
        raise ErrorEntrada(f"{ruta or 'raíz'}: se esperaba un objeto JSON")
    return valor


def exigir_llaves(
    objeto: Mapping[str, Any], ruta: str, obligatorias: Iterable[str], opcionales: Iterable[str] = ()
) -> None:
    """Falla si sobra una llave (no tendría efecto) o si falta una obligatoria."""
    requeridas = frozenset(obligatorias)
    desconocidas = sorted(set(objeto) - requeridas - frozenset(opcionales))
    if desconocidas:
        listado = ", ".join(_unir(ruta, llave) for llave in desconocidas)
        raise ErrorEntrada(f"llave desconocida: {listado} (no se aceptan llaves sin efecto)")
    faltantes = sorted(requeridas - set(objeto))
    if faltantes:
        raise ErrorEntrada(f"falta la llave {_unir(ruta, faltantes[0])}")


def leer_texto(valor: Any, ruta: str) -> str:
    if not isinstance(valor, str):
        raise ErrorEntrada(f"{ruta}: se esperaba texto, llegó {valor!r}")
    return valor


def leer_codigo(valor: Any, ruta: str) -> str:
    """Texto no vacío y sin espacios al borde (cuentas, marcas, prefijos)."""
    codigo = leer_texto(valor, ruta)
    if not codigo.strip():
        raise ErrorEntrada(f"{ruta}: no puede ir vacío")
    if codigo != codigo.strip():
        raise ErrorEntrada(f"{ruta}: tiene espacios al inicio o al final: {codigo!r}")
    return codigo


def leer_entero(valor: Any, ruta: str, minimo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorEntrada(f"{ruta}: se esperaba un entero, llegó {valor!r}")
    entero = int(valor)
    if entero < minimo:
        raise ErrorEntrada(f"{ruta}: debe ser >= {minimo}, llegó {entero}")
    return entero


def leer_monto(valor: Any, ruta: str) -> Decimal:
    """Convierte texto, entero o float a `Decimal` con centavos (única conversión)."""
    if isinstance(valor, bool) or not isinstance(valor, (str, int, float)):
        raise ErrorEntrada(f"{ruta}: monto inválido {valor!r}")
    if isinstance(valor, str) and not _PATRON_MONTO.fullmatch(valor):
        raise ErrorEntrada(f"{ruta}: monto inválido {valor!r} (se espera texto como -1234.56)")
    try:
        numero = Decimal(str(valor))
        if not numero.is_finite():
            raise ErrorEntrada(f"{ruta}: monto inválido {valor!r}")
        return redondear(numero)
    except InvalidOperation:
        raise ErrorEntrada(f"{ruta}: monto inválido o fuera de rango {valor!r}") from None


def leer_porcentaje(valor: Any, ruta: str) -> Decimal:
    """Porcentaje no negativo con dos decimales (`12.5` significa 12.5%)."""
    pct = leer_monto(valor, ruta)
    if pct < CERO:
        raise ErrorEntrada(f"{ruta}: no puede ser negativo, llegó {pct}")
    return pct


def leer_lista(valor: Any, ruta: str) -> Sequence[Any]:
    if not isinstance(valor, list):
        raise ErrorEntrada(f"{ruta}: se esperaba una lista")
    return valor


def exigir_sin_repetidos(valores: Sequence[str], ruta: str, que: str) -> None:
    vistos: Set[str] = set()
    for valor in valores:
        if valor in vistos:
            raise ErrorEntrada(f"{ruta}: {que} repetido {valor!r}")
        vistos.add(valor)


def leer_codigos(valor: Any, ruta: str) -> Tuple[str, ...]:
    """Lista de códigos de texto sin repetidos."""
    codigos = tuple(leer_codigo(item, f"{ruta}[{i}]") for i, item in enumerate(leer_lista(valor, ruta)))
    exigir_sin_repetidos(codigos, ruta, "valor")
    return codigos


def leer_periodo(valor: Any, ruta: str) -> str:
    if not isinstance(valor, str) or not _PATRON_PERIODO.fullmatch(valor):
        raise ErrorEntrada(f"{ruta}: se esperaba un periodo AAAA-MM, llegó {valor!r}")
    return valor


def leer_fecha(valor: Any, ruta: str) -> date:
    if not isinstance(valor, str) or not _PATRON_FECHA.fullmatch(valor):
        raise ErrorEntrada(f"{ruta}: se esperaba una fecha ISO AAAA-MM-DD, llegó {valor!r}")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorEntrada(f"{ruta}: la fecha {valor!r} no existe") from None


def fin_de_periodo(periodo: str) -> date:
    """Último día natural de un periodo `AAAA-MM` ya validado."""
    anio, mes = int(periodo[:4]), int(periodo[5:])
    return date(anio, mes, calendar.monthrange(anio, mes)[1])
