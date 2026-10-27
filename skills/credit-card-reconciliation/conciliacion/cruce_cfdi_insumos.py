"""Frontera de entrada del cruce cargo ↔ CFDI: JSONL a tipos inmutables, con validación estricta.

Aquí, y solo aquí, los montos dejan de ser texto o número y pasan a `Decimal`.
Cualquier registro que no cumpla el formato detiene la lectura con un mensaje
que nombra el archivo, la línea y el campo; ninguna línea se salta.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple, Type, TypeVar

from .cruce_cfdi_modelo import (
    DIRECCIONES,
    ESTADO_OK,
    ESTADOS,
    TIPOS_COMPROBANTE,
    TIPOS_MOVIMIENTO,
    Cargo,
    Cfdi,
    InsumoInvalido,
)

CENTAVO = Decimal("0.01")
LARGO_FECHA_ISO = 10

T = TypeVar("T")
Registro = Tuple[int, Dict[str, Any]]


def a_monto(valor: object, campo: str, error: Type[InsumoInvalido] = InsumoInvalido) -> Decimal:
    """Convierte un monto de entrada (cadena o número) a Decimal con dos decimales, redondeo half-up."""
    if isinstance(valor, bool) or not isinstance(valor, (str, int, float, Decimal)):
        raise error(f"{campo}: se esperaba un monto (cadena o número) y llegó {type(valor).__name__}")
    try:
        numero = Decimal(str(valor).strip())
    except InvalidOperation:
        raise error(f"{campo}: monto ilegible {valor!r}") from None
    if not numero.is_finite():
        raise error(f"{campo}: monto no finito {valor!r}")
    return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _valor(datos: Mapping[str, Any], campo: str) -> Any:
    if campo not in datos:
        raise InsumoInvalido(f"campo faltante: {campo}")
    return datos[campo]


def _texto(datos: Mapping[str, Any], campo: str, admite_vacio: bool = False) -> str:
    valor = _valor(datos, campo)
    if not isinstance(valor, str) or (not admite_vacio and not valor.strip()):
        raise InsumoInvalido(f"{campo}: se esperaba texto no vacío y llegó {valor!r}")
    return valor


def _texto_opcional(datos: Mapping[str, Any], campo: str) -> Optional[str]:
    if datos.get(campo) is None:
        return None
    return _texto(datos, campo)


def _opcion(datos: Mapping[str, Any], campo: str, permitidas: FrozenSet[str]) -> str:
    valor = _valor(datos, campo)
    if valor not in permitidas:
        raise InsumoInvalido(f"{campo}: valor {valor!r} fuera de {sorted(permitidas)}")
    return str(valor)


def _fecha(datos: Mapping[str, Any], campo: str, admite_hora: bool = False) -> Optional[date]:
    valor = _valor(datos, campo)
    if valor is None:
        return None
    if not isinstance(valor, str):
        raise InsumoInvalido(f"{campo}: se esperaba una fecha ISO y llegó {valor!r}")
    try:
        if admite_hora and len(valor) > LARGO_FECHA_ISO:
            return datetime.fromisoformat(valor).date()
        return date.fromisoformat(valor)
    except ValueError:
        raise InsumoInvalido(f"{campo}: fecha ISO inválida {valor!r}") from None


def _no_negativo(datos: Mapping[str, Any], campo: str) -> Decimal:
    monto = a_monto(_valor(datos, campo), campo)
    if monto < 0:
        raise InsumoInvalido(f"{campo}: un CFDI no lleva montos negativos (el signo lo da el tipo); llegó {monto}")
    return monto


def cargo_desde_dict(datos: Mapping[str, Any]) -> Cargo:
    """Un renglón del universo de cargos; los campos que el motor no usa se ignoran."""
    estado = _opcion(datos, "estado", ESTADOS)
    fecha = _fecha(datos, "fecha")
    if estado == ESTADO_OK and fecha is None:
        raise InsumoInvalido("fecha: obligatoria cuando estado = ok")
    return Cargo(
        cargo_id=_texto(datos, "cargo_id"),
        fecha=fecha,
        descripcion=_texto(datos, "descripcion", admite_vacio=True),
        monto=a_monto(_valor(datos, "monto"), "monto"),
        moneda_original=_texto(datos, "moneda_original"),
        monto_original=a_monto(_valor(datos, "monto_original"), "monto_original"),
        tipo_movimiento=_opcion(datos, "tipo_movimiento", TIPOS_MOVIMIENTO),
        estado=estado,
    )


def cfdi_desde_dict(datos: Mapping[str, Any]) -> Cfdi:
    """Un CFDI del pool, con el formato de `cfdis.jsonl`."""
    fecha = _fecha(datos, "fecha_emision", admite_hora=True)
    if fecha is None:
        raise InsumoInvalido("fecha_emision: obligatoria")
    return Cfdi(
        uuid=_texto(datos, "uuid"),
        fecha_emision=fecha,
        tipo_comprobante=_opcion(datos, "tipo_comprobante", TIPOS_COMPROBANTE),
        direccion=_opcion(datos, "direccion", DIRECCIONES),
        rfc_emisor=_texto(datos, "rfc_emisor"),
        nombre_emisor=_texto(datos, "nombre_emisor", admite_vacio=True),
        rfc_receptor=_texto(datos, "rfc_receptor"),
        moneda=_texto(datos, "moneda"),
        total=_no_negativo(datos, "total"),
        total_mxn=_no_negativo(datos, "total_mxn"),
        uuid_relacionado=_texto_opcional(datos, "uuid_relacionado"),
    )


def leer_jsonl(ruta: Path) -> Tuple[Registro, ...]:
    """Lee un JSONL completo: cada línea es un objeto; una línea vacía o ilegible es un error."""
    try:
        crudo = ruta.read_bytes()
    except OSError as exc:
        raise InsumoInvalido(f"no se puede leer {ruta}: {exc.strerror or exc}") from None
    try:
        texto = crudo.decode("utf-8")
    except UnicodeDecodeError:
        raise InsumoInvalido(f"{ruta.name}: el archivo no es UTF-8 válido") from None
    lineas = texto.split("\n")
    if lineas and lineas[-1] == "":
        lineas = lineas[:-1]
    return tuple(_registro(ruta.name, numero, linea) for numero, linea in enumerate(lineas, start=1))


def _registro(nombre: str, numero: int, linea: str) -> Registro:
    contenido = linea.rstrip("\r")
    if not contenido.strip():
        raise InsumoInvalido(f"{nombre}, línea {numero}: línea vacía")
    try:
        objeto = json.loads(contenido)
    except json.JSONDecodeError as exc:
        raise InsumoInvalido(f"{nombre}, línea {numero}: JSON inválido ({exc.msg})") from None
    if not isinstance(objeto, dict):
        raise InsumoInvalido(f"{nombre}, línea {numero}: se esperaba un objeto JSON")
    return numero, objeto


def verificar_unicos(claves: Iterable[Tuple[str, str]], campo: str) -> None:
    """Falla si una clave se repite; cada par es (clave, dónde apareció)."""
    vistas: Dict[str, str] = {}
    for clave, lugar in claves:
        if clave in vistas:
            raise InsumoInvalido(f"{campo} duplicado {clave!r} ({vistas[clave]} y {lugar})")
        vistas[clave] = lugar


def _convertir(ruta: Path, armar: Callable[[Mapping[str, Any]], T]) -> Tuple[Tuple[int, T], ...]:
    convertidos = []
    for numero, datos in leer_jsonl(ruta):
        try:
            convertidos.append((numero, armar(datos)))
        except InsumoInvalido as exc:
            raise InsumoInvalido(f"{ruta.name}, línea {numero}: {exc}") from None
    return tuple(convertidos)


def leer_cargos(ruta: Path) -> Tuple[Cargo, ...]:
    filas = _convertir(ruta, cargo_desde_dict)
    verificar_unicos(((c.cargo_id, f"línea {n}") for n, c in filas), f"{ruta.name}: cargo_id")
    return tuple(c for _, c in filas)


def leer_cfdis(ruta: Path) -> Tuple[Cfdi, ...]:
    filas = _convertir(ruta, cfdi_desde_dict)
    verificar_unicos(((f.uuid, f"línea {n}") for n, f in filas), f"{ruta.name}: uuid")
    return tuple(f for _, f in filas)
