"""Lectura y validación de los CFDIs sintéticos (`cfdis.jsonl` de examples/synthetic).

El archivo solo se lee. Cada registro se valida y cualquier falla detiene la lectura con
el número de línea; los registros que no pertenecen al universo se cuentan por motivo.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from frontera import ErrorFrontera, FormaImporte, leer_importe

from netsuite_gl.fechas import fecha_iso
from netsuite_gl.montos import CENTAVO, ErrorMonto, a_decimal

CAMPOS_OBLIGATORIOS: Tuple[str, ...] = (
    "uuid", "serie", "folio", "fecha_emision", "tipo_comprobante", "direccion", "rfc_emisor",
    "nombre_emisor", "rfc_receptor", "moneda", "tipo_cambio", "subtotal", "iva", "total",
    "total_mxn", "concepto", "uuid_relacionado",
)
TIPOS_VALIDOS = frozenset({"I", "E", "T", "N", "P"})
TIPOS_UNIVERSO = frozenset({"I", "E"})
DIRECCIONES = frozenset({"recibido", "emitido"})
MONEDAS = frozenset({"MXN", "USD"})

MOTIVO_EMITIDO = "emitido"
MOTIVO_RECEPTOR_AJENO = "receptor_ajeno"
MOTIVO_TIPO_NO_APLICA = "tipo_no_aplica"


# Tipo de cambio: texto positivo con hasta seis decimales (Anexo 20), sin redondear.
FORMA_TIPO_CAMBIO = FormaImporte(decimales=6, negativo=False)

class ErrorInsumo(ValueError):
    """El archivo de CFDIs no existe o trae un registro inválido."""


@dataclass(frozen=True)
class Cfdi:
    """CFDI del universo, con importes ya convertidos a MXN."""

    uuid: str
    serie: str
    folio: str
    fecha: date
    tipo: str
    rfc_emisor: str
    nombre_emisor: str
    concepto: str
    subtotal_mxn: Decimal
    iva_mxn: Decimal
    total_mxn: Decimal
    uuid_relacionado: Optional[str]

    @property
    def referencia(self) -> str:
        return f"{self.serie}-{self.folio}"

    @property
    def signo(self) -> Decimal:
        """+1 para facturas, −1 para notas de crédito (restan del saldo con el proveedor)."""
        return Decimal("-1") if self.tipo == "E" else Decimal("1")


@dataclass(frozen=True)
class LecturaCfdis:
    leidos: int
    universo: Tuple[Cfdi, ...]
    excluidos: Mapping[str, int]


def leer_cfdis(ruta: Path, rfc_empresa: str) -> LecturaCfdis:
    """Lee el JSONL, valida cada registro y separa el universo de los excluidos."""
    if not ruta.is_file():
        raise ErrorInsumo(f"el archivo de CFDIs no existe: {ruta}")
    universo: List[Cfdi] = []
    excluidos: Counter[str] = Counter()
    vistos: Dict[str, int] = {}
    leidos = 0
    with ruta.open(encoding="utf-8") as archivo:
        for numero, linea in enumerate(archivo, start=1):
            if not linea.strip():
                continue
            leidos += 1
            registro = _parsear_linea(linea, numero)
            cfdi = _validar(registro, numero)
            _registrar_uuid(cfdi.uuid, numero, vistos)
            motivo = _motivo_exclusion(registro, rfc_empresa)
            if motivo is None:
                universo.append(cfdi)
            else:
                excluidos[motivo] += 1
    universo.sort(key=lambda c: c.uuid)
    return LecturaCfdis(leidos, tuple(universo), MappingProxyType(dict(sorted(excluidos.items()))))


def _parsear_linea(linea: str, numero: int) -> Dict[str, Any]:
    try:
        registro = json.loads(linea)
    except json.JSONDecodeError as exc:
        raise ErrorInsumo(f"línea {numero}: JSON inválido ({exc.msg})") from exc
    if not isinstance(registro, dict):
        raise ErrorInsumo(f"línea {numero}: se esperaba un objeto JSON")
    faltantes = [c for c in CAMPOS_OBLIGATORIOS if c not in registro]
    if faltantes:
        raise ErrorInsumo(f"línea {numero}: faltan campos {', '.join(faltantes)}")
    return registro


def _registrar_uuid(uuid: str, numero: int, vistos: Dict[str, int]) -> None:
    if uuid in vistos:
        raise ErrorInsumo(f"línea {numero}: uuid duplicado {uuid} (ya en la línea {vistos[uuid]})")
    vistos[uuid] = numero


def _motivo_exclusion(registro: Dict[str, Any], rfc_empresa: str) -> Optional[str]:
    if registro["direccion"] == "emitido":
        return MOTIVO_EMITIDO
    if registro["rfc_receptor"] != rfc_empresa:
        return MOTIVO_RECEPTOR_AJENO
    if registro["tipo_comprobante"] not in TIPOS_UNIVERSO:
        return MOTIVO_TIPO_NO_APLICA
    return None


def _validar(registro: Dict[str, Any], numero: int) -> Cfdi:
    for campo in ("uuid", "serie", "folio", "rfc_emisor", "nombre_emisor", "rfc_receptor", "concepto"):
        _texto(registro, campo, numero)
    _en_conjunto(registro, "tipo_comprobante", TIPOS_VALIDOS, numero)
    _en_conjunto(registro, "direccion", DIRECCIONES, numero)
    _en_conjunto(registro, "moneda", MONEDAS, numero)
    subtotal, iva, total = (_monto(registro, c, numero) for c in ("subtotal", "iva", "total"))
    total_mxn = _monto(registro, "total_mxn", numero)
    if subtotal + iva != total:
        raise ErrorInsumo(f"línea {numero}: subtotal + iva ({subtotal} + {iva}) no es igual a total ({total})")
    subtotal_mxn = _subtotal_mxn(registro, subtotal, total, total_mxn, numero)
    iva_mxn = total_mxn - subtotal_mxn
    if iva_mxn < 0:
        raise ErrorInsumo(f"línea {numero}: total_mxn menor que el subtotal convertido")
    relacionado = registro["uuid_relacionado"]
    if relacionado is not None and not isinstance(relacionado, str):
        raise ErrorInsumo(f"línea {numero}: uuid_relacionado debe ser texto o null")
    return Cfdi(
        uuid=registro["uuid"],
        serie=registro["serie"],
        folio=registro["folio"],
        fecha=_fecha(registro, numero),
        tipo=registro["tipo_comprobante"],
        rfc_emisor=registro["rfc_emisor"],
        nombre_emisor=registro["nombre_emisor"],
        concepto=registro["concepto"],
        subtotal_mxn=subtotal_mxn,
        iva_mxn=iva_mxn,
        total_mxn=total_mxn,
        uuid_relacionado=relacionado,
    )


def _subtotal_mxn(
    registro: Dict[str, Any], subtotal: Decimal, total: Decimal, total_mxn: Decimal, numero: int
) -> Decimal:
    if registro["moneda"] == "MXN":
        if total_mxn != total:
            raise ErrorInsumo(f"línea {numero}: en MXN total_mxn ({total_mxn}) debe ser igual a total ({total})")
        return subtotal
    tipo_cambio = registro["tipo_cambio"]
    if not isinstance(tipo_cambio, str):
        raise ErrorInsumo(f"línea {numero}: tipo_cambio es obligatorio (texto) en moneda extranjera")
    try:
        tasa = leer_importe(tipo_cambio, FORMA_TIPO_CAMBIO)
    except ErrorFrontera as exc:
        raise ErrorInsumo(f"línea {numero}: tipo_cambio inválido: {exc}") from None
    if tasa <= 0:
        raise ErrorInsumo(f"línea {numero}: tipo_cambio debe ser positivo")
    return (subtotal * tasa).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _texto(registro: Dict[str, Any], campo: str, numero: int) -> str:
    valor = registro[campo]
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorInsumo(f"línea {numero}: {campo} debe ser texto no vacío")
    return valor


def _en_conjunto(registro: Dict[str, Any], campo: str, validos: frozenset[str], numero: int) -> None:
    if registro[campo] not in validos:
        validos_texto = ", ".join(sorted(validos))
        raise ErrorInsumo(f"línea {numero}: {campo} inválido {registro[campo]!r} (válidos: {validos_texto})")


def _monto(registro: Dict[str, Any], campo: str, numero: int) -> Decimal:
    valor = registro[campo]
    if not isinstance(valor, str):
        raise ErrorInsumo(f"línea {numero}: {campo} debe ser texto decimal, no {type(valor).__name__}")
    try:
        monto = a_decimal(valor)
    except ErrorMonto as exc:
        raise ErrorInsumo(f"línea {numero}: {campo} inválido: {exc}") from exc
    if monto < 0:
        raise ErrorInsumo(f"línea {numero}: {campo} no puede ser negativo")
    return monto


def _fecha(registro: Dict[str, Any], numero: int) -> date:
    valor = registro["fecha_emision"]
    try:
        return fecha_iso(valor)
    except ValueError as exc:
        raise ErrorInsumo(f"línea {numero}: fecha_emision debe ser AAAA-MM-DD válida, no {valor!r}") from exc
