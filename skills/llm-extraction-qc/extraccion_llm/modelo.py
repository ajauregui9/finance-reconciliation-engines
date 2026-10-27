"""Tipos inmutables compartidos: los ocho campos, observaciones, hallazgos, uso y decisiones.

Aquí vive también la única conversión de texto a monto (`monto_estricto`) y la regla de
igualdad por campo que usan el cruce y la evaluación (`mismo_valor`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, FrozenSet, Mapping, Optional, Tuple

CAMPOS: Tuple[str, ...] = ("rfc_emisor", "rfc_receptor", "uuid", "fecha", "subtotal", "iva", "total", "moneda")
CAMPOS_MONTO: FrozenSet[str] = frozenset({"subtotal", "iva", "total"})

CONCORDANTE = "concordante"
REVISION_HUMANA = "revision_humana"
DECISIONES: Tuple[str, ...] = (CONCORDANTE, REVISION_HUMANA)

# Códigos de observación (cada uno manda el documento a revisión humana).
BLOQUEADO_POR_GUARDIA = "bloqueado_por_guardia"
RESPUESTA_SIN_HERRAMIENTA = "respuesta_sin_herramienta"
RESPUESTA_FUERA_DE_ESQUEMA = "respuesta_fuera_de_esquema"
CAMPO_AUSENTE = "campo_ausente"
RFC_INVALIDO = "rfc_invalido"
UUID_INVALIDO = "uuid_invalido"
FECHA_INVALIDA = "fecha_invalida"
MONTO_INVALIDO = "monto_invalido"
NO_CUADRA = "no_cuadra"
MONEDA_NO_PERMITIDA = "moneda_no_permitida"
RECEPTOR_DISTINTO = "receptor_distinto_de_empresa"
SIN_RESPALDO = "sin_respaldo_en_pool"
DISCREPANCIA_MOTOR = "discrepancia_motor"

CENTAVO = Decimal("0.01")
# Solo dígitos ASCII: `\d` aceptaría dígitos de otros alfabetos.
_FORMA_MONTO = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")


def monto_estricto(texto: Optional[str]) -> Optional[Decimal]:
    """El monto con dos decimales, o None si el texto no es solo dígitos con punto opcional."""
    if texto is None or not _FORMA_MONTO.fullmatch(texto):
        return None
    return Decimal(texto).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def texto_monto(monto: Decimal) -> str:
    return f"{monto.quantize(CENTAVO, rounding=ROUND_HALF_UP):.2f}"


@dataclass(frozen=True)
class Campos:
    """Los ocho campos de un CFDI como texto (o None si no se reportan)."""

    rfc_emisor: Optional[str]
    rfc_receptor: Optional[str]
    uuid: Optional[str]
    fecha: Optional[str]
    subtotal: Optional[str]
    iva: Optional[str]
    total: Optional[str]
    moneda: Optional[str]

    def valor(self, campo: str) -> Optional[str]:
        if campo not in CAMPOS:
            raise KeyError(f"campo desconocido: {campo}")
        valor: Optional[str] = getattr(self, campo)
        return valor

    def como_dict(self) -> Dict[str, Optional[str]]:
        return {f.name: getattr(self, f.name) for f in fields(self)}


def campos_desde_mapa(mapa: Mapping[str, Optional[str]]) -> Campos:
    """Arma `Campos` de un mapa ya validado (exactamente las ocho llaves)."""
    return Campos(**{campo: mapa[campo] for campo in CAMPOS})


def mismo_valor(campo: str, a: Optional[str], b: Optional[str]) -> bool:
    """Montos: iguales como Decimal (un texto que no es monto nunca coincide). Lo demás: texto exacto."""
    if campo not in CAMPOS_MONTO or a is None or b is None:
        return a == b
    izquierdo = monto_estricto(a)
    return izquierdo is not None and izquierdo == monto_estricto(b)


@dataclass(frozen=True)
class Observacion:
    """Un motivo para mandar el documento a revisión. En `discrepancia_motor`, ambos valores."""

    codigo: str
    campo: Optional[str]
    detalle: str
    propuesta: Optional[str] = None
    motor: Optional[str] = None


@dataclass(frozen=True)
class Hallazgo:
    """Lo que prompt_guard marcó: familia y fragmento (texto de un tercero, se trata como dato)."""

    familia: str
    fragmento: str


@dataclass(frozen=True)
class Uso:
    """Tokens de una respuesta, tal como los reporta `response.usage`."""

    tokens_entrada: int
    tokens_salida: int

    @property
    def total(self) -> int:
        return self.tokens_entrada + self.tokens_salida
