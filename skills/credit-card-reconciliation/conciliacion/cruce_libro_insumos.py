"""Frontera de entrada del cruce con libro mayor: lectura y validación de los insumos.

Todo lo que llega de un archivo es dato externo. Cada violación detiene la corrida con
un `ErrorInsumo` que nombra el archivo, la fila y el campo; nada se descarta en silencio.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

from .cruce_libro_modelo import (
    CENTAVO,
    ESTADO_OK,
    TIPOS_MOVIMIENTO,
    VEREDICTO_NO_REGISTRADO,
    VEREDICTO_REGISTRADO,
    VEREDICTOS_VALIDOS,
    Cargo,
    LineaLibro,
    Veredicto,
)

COLUMNAS_LIBRO = ("asiento_id", "linea", "fecha", "cuenta", "proveedor_id", "proveedor_nombre",
                  "debe", "haber", "moneda")
COLUMNAS_VEREDICTOS = ("cargo_id", "veredicto", "asiento_id", "nota")

_MONTO_TEXTO = re.compile(r"^-?\d+(\.\d+)?$")
_FECHA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ENTERO = re.compile(r"^\d+$")


class ErrorInsumo(ValueError):
    """Un insumo no cumple su contrato; la corrida no puede continuar."""


# ------------------------------------------------------------------ primitivas
def a_monto(valor: object, contexto: str) -> Decimal:
    """Única frontera numérica: texto o número a `Decimal` en centavos (ROUND_HALF_UP)."""
    if isinstance(valor, str) and _MONTO_TEXTO.match(valor.strip()):
        numero = Decimal(valor.strip())
    elif isinstance(valor, (int, float, Decimal)) and not isinstance(valor, bool):
        numero = Decimal(str(valor))
    else:
        raise ErrorInsumo(f"{contexto}: monto inválido {valor!r} (se espera texto como -1234.56).")
    if not numero.is_finite():
        raise ErrorInsumo(f"{contexto}: monto no finito {valor!r}.")
    return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def a_fecha(valor: object, contexto: str) -> date:
    if not isinstance(valor, str) or not _FECHA_ISO.match(valor):
        raise ErrorInsumo(f"{contexto}: fecha inválida {valor!r} (se espera AAAA-MM-DD).")
    try:
        return date.fromisoformat(valor)
    except ValueError as exc:
        raise ErrorInsumo(f"{contexto}: fecha imposible {valor!r}.") from exc


def _texto(registro: Mapping[str, object], campo: str, contexto: str, *, vacio: bool = False) -> str:
    valor = registro.get(campo)
    if not isinstance(valor, str) or (not vacio and not valor.strip()):
        raise ErrorInsumo(f"{contexto}: campo {campo} ausente, vacío o no es texto ({valor!r}).")
    return valor if vacio else valor.strip()


def huella(ruta: Path) -> str:
    """SHA-256 de los bytes del archivo, para rastrear qué insumo produjo la salida."""
    try:
        return hashlib.sha256(ruta.read_bytes()).hexdigest()
    except OSError as exc:
        raise ErrorInsumo(f"No se pudo leer {ruta.name}: {exc.strerror}.") from exc


def leer_texto(ruta: Path) -> str:
    try:
        return ruta.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ErrorInsumo(f"No se pudo leer {ruta.name}: {exc.strerror}.") from exc
    except UnicodeDecodeError as exc:
        raise ErrorInsumo(f"{ruta.name} no es texto UTF-8 válido (byte {exc.start}).") from exc


# -------------------------------------------------------------------- universo
def _objeto_json(linea: str, contexto: str) -> Dict[str, object]:
    try:
        valor = json.loads(linea)
    except json.JSONDecodeError as exc:
        raise ErrorInsumo(f"{contexto}: JSON inválido ({exc.msg}).") from exc
    if not isinstance(valor, dict):
        raise ErrorInsumo(f"{contexto}: cada línea debe ser un objeto JSON.")
    return valor


def _cargo_de(registro: Mapping[str, object], contexto: str) -> Cargo:
    cargo_id = _texto(registro, "cargo_id", contexto)
    emisor = _texto(registro, "emisor", contexto)
    estado = _texto(registro, "estado", contexto)
    tipo = _texto(registro, "tipo_movimiento", contexto)
    if tipo not in TIPOS_MOVIMIENTO:
        raise ErrorInsumo(f"{contexto}: tipo_movimiento desconocido {tipo!r}.")
    descripcion = _texto(registro, "descripcion", contexto, vacio=True)
    monto = a_monto(registro.get("monto"), f"{contexto}, campo monto")
    fecha = a_fecha(registro.get("fecha"), f"{contexto}, campo fecha") if estado == ESTADO_OK else None
    return Cargo(cargo_id, emisor, estado, fecha, descripcion, monto, tipo)


def leer_universo(ruta: Path) -> Tuple[Cargo, ...]:
    """Lee el universo normalizado (JSONL); devuelve los cargos ordenados por `cargo_id`."""
    return universo_desde_texto(leer_texto(ruta), ruta.name)


def universo_desde_texto(texto: str, nombre: str) -> Tuple[Cargo, ...]:
    """Igual que `leer_universo`, pero sobre el texto JSONL ya leído; `nombre` va en los mensajes."""
    cargos: List[Cargo] = []
    vistos: Set[str] = set()
    for numero, linea in enumerate(texto.splitlines(), 1):
        if not linea.strip():
            continue
        contexto = f"{nombre}, línea {numero}"
        cargo = _cargo_de(_objeto_json(linea, contexto), contexto)
        if cargo.cargo_id in vistos:
            raise ErrorInsumo(f"{contexto}: cargo_id repetido {cargo.cargo_id}.")
        vistos.add(cargo.cargo_id)
        cargos.append(cargo)
    return tuple(sorted(cargos, key=lambda c: c.cargo_id))


# ------------------------------------------------------------------------ CSV
def _filas_csv(ruta: Path, requeridas: Sequence[str]) -> Iterator[Tuple[int, Dict[str, str]]]:
    """(número de fila, celdas) por cada fila de datos; el encabezado es la fila 1."""
    lector = csv.reader(io.StringIO(leer_texto(ruta), newline=""))
    encabezado = next(lector, None)
    if not encabezado:
        raise ErrorInsumo(f"{ruta.name}: falta el encabezado.")
    columnas = [c.strip() for c in encabezado]
    faltantes = [c for c in requeridas if c not in columnas]
    if faltantes:
        raise ErrorInsumo(f"{ruta.name}: faltan columnas obligatorias: {', '.join(faltantes)}.")
    for numero, celdas in enumerate(lector, 2):
        if not celdas:
            continue
        if len(celdas) != len(columnas):
            raise ErrorInsumo(f"{ruta.name}, fila {numero}: {len(celdas)} columnas, se esperaban {len(columnas)}.")
        yield numero, dict(zip(columnas, celdas))


def _monto_no_negativo(fila: Mapping[str, str], campo: str, contexto: str) -> Decimal:
    monto = a_monto(fila[campo], f"{contexto}, campo {campo}")
    if monto < 0:
        raise ErrorInsumo(f"{contexto}: campo {campo} no puede ser negativo ({monto}).")
    return monto


def _linea_de(fila: Mapping[str, str], contexto: str, moneda: str) -> LineaLibro:
    asiento = _texto(fila, "asiento_id", contexto)
    numero = fila["linea"].strip()
    if not _ENTERO.match(numero):
        raise ErrorInsumo(f"{contexto}: campo linea debe ser un entero ({numero!r}).")
    if fila["moneda"].strip() != moneda:
        raise ErrorInsumo(f"{contexto}: campo moneda {fila['moneda']!r}; el motor solo acepta {moneda}.")
    return LineaLibro(
        asiento_id=asiento, linea=int(numero), fecha=a_fecha(fila["fecha"].strip(), f"{contexto}, campo fecha"),
        cuenta=_texto(fila, "cuenta", contexto), proveedor_id=fila["proveedor_id"].strip(),
        proveedor_nombre=fila["proveedor_nombre"].strip(),
        debe=_monto_no_negativo(fila, "debe", contexto), haber=_monto_no_negativo(fila, "haber", contexto))


def leer_libro(ruta: Path, moneda: str) -> Tuple[LineaLibro, ...]:
    """Lee el libro mayor (CSV); devuelve las líneas ordenadas por asiento y línea."""
    lineas: List[LineaLibro] = []
    vistas: Set[Tuple[str, int]] = set()
    for numero, fila in _filas_csv(ruta, COLUMNAS_LIBRO):
        contexto = f"{ruta.name}, fila {numero}"
        linea = _linea_de(fila, contexto, moneda)
        llave = (linea.asiento_id, linea.linea)
        if llave in vistas:
            raise ErrorInsumo(f"{contexto}: línea repetida {linea.linea} del asiento {linea.asiento_id}.")
        vistas.add(llave)
        lineas.append(linea)
    return tuple(sorted(lineas, key=lambda x: (x.asiento_id, x.linea)))


# ------------------------------------------------------------------ veredictos
def _veredicto_de(fila: Mapping[str, str], contexto: str, cargos: frozenset[str],
                  asientos: frozenset[str]) -> Veredicto:
    cargo_id = _texto(fila, "cargo_id", contexto)
    if cargo_id not in cargos:
        raise ErrorInsumo(f"{contexto}: el cargo {cargo_id} no está en el universo.")
    veredicto = fila["veredicto"].strip()
    if veredicto not in VEREDICTOS_VALIDOS:
        raise ErrorInsumo(f"{contexto}: veredicto {veredicto!r} no es {' ni '.join(VEREDICTOS_VALIDOS)}.")
    asiento: Optional[str] = fila["asiento_id"].strip() or None
    if veredicto == VEREDICTO_REGISTRADO and asiento is None:
        raise ErrorInsumo(f"{contexto}: un veredicto {VEREDICTO_REGISTRADO} exige asiento_id.")
    if veredicto == VEREDICTO_NO_REGISTRADO and asiento is not None:
        raise ErrorInsumo(f"{contexto}: un veredicto {VEREDICTO_NO_REGISTRADO} lleva asiento_id vacío.")
    if asiento is not None and asiento not in asientos:
        raise ErrorInsumo(f"{contexto}: el asiento {asiento} no existe en el libro mayor.")
    return Veredicto(cargo_id, veredicto, asiento, fila["nota"])


def leer_veredictos(ruta: Optional[Path], cargos: frozenset[str],
                    asientos: frozenset[str]) -> Tuple[Veredicto, ...]:
    """Lee los veredictos humanos (CSV); sin archivo, no hay veredictos."""
    if ruta is None:
        return ()
    veredictos: List[Veredicto] = []
    con_veredicto: Set[str] = set()
    for numero, fila in _filas_csv(ruta, COLUMNAS_VEREDICTOS):
        contexto = f"{ruta.name}, fila {numero}"
        veredicto = _veredicto_de(fila, contexto, cargos, asientos)
        if veredicto.cargo_id in con_veredicto:
            raise ErrorInsumo(f"{contexto}: cargo {veredicto.cargo_id} repetido; va un veredicto por cargo.")
        con_veredicto.add(veredicto.cargo_id)
        veredictos.append(veredicto)
    return tuple(sorted(veredictos, key=lambda v: v.cargo_id))


def a_decimal_exacto(valor: object, contexto: str) -> Decimal:
    """Texto decimal sin redondear (umbrales); rechaza números JSON para no admitir floats."""
    if not isinstance(valor, str) or not _MONTO_TEXTO.match(valor.strip()):
        raise ErrorInsumo(f"{contexto}: se espera texto decimal como \"0.50\" ({valor!r}).")
    return Decimal(valor.strip())
