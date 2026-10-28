"""Tipos inmutables compartidos: los doce campos, observaciones, hallazgos, uso y decisiones.

Ocho campos son obligatorios (los de todo CFDI) y cuatro son montos opcionales que solo
aparecen en algunos comprobantes: descuento, IEPS trasladado, ISR retenido e IVA retenido.
En un monto opcional, `null` significa "el documento no lo trae" y equivale a 0.00.

Aquí vive también la única conversión de texto a monto (`monto_estricto`) y la regla de
igualdad por campo que usan el cruce y la evaluación (`mismo_valor`).
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from decimal import ROUND_HALF_UP, Decimal
from typing import Dict, FrozenSet, Mapping, Optional, Tuple

from frontera import ErrorFrontera, FormaImporte, leer_importe

CAMPOS: Tuple[str, ...] = ("rfc_emisor", "rfc_receptor", "uuid", "fecha", "subtotal", "descuento", "iva", "ieps",
                           "isr_retenido", "iva_retenido", "total", "moneda")
CAMPOS_OPCIONALES: Tuple[str, ...] = ("descuento", "ieps", "isr_retenido", "iva_retenido")
CAMPOS_OBLIGATORIOS: Tuple[str, ...] = tuple(c for c in CAMPOS if c not in CAMPOS_OPCIONALES)
CAMPOS_MONTO: FrozenSet[str] = frozenset({"subtotal", "descuento", "iva", "ieps", "isr_retenido", "iva_retenido",
                                          "total"})

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
ERROR_API = "error_api"

CENTAVO = Decimal("0.01")
# Frontera compartida: dígitos ASCII, sin signo, sin miles, sin espacios, hasta dos decimales.
FORMA_MONTO = FormaImporte(decimales=2, negativo=False, recortar=False)


def monto_estricto(texto: Optional[str]) -> Optional[Decimal]:
    """El monto con dos decimales, o None si el texto no es solo dígitos con punto opcional."""
    if not isinstance(texto, str):
        return None
    try:
        return leer_importe(texto, FORMA_MONTO)
    except ErrorFrontera:
        return None


def texto_monto(monto: Decimal) -> str:
    return f"{monto.quantize(CENTAVO, rounding=ROUND_HALF_UP):.2f}"


def efectivo(campo: str, valor: Optional[str]) -> Optional[str]:
    """El valor que cuenta al comparar: en un monto opcional, un cero válido equivale a None."""
    if campo in CAMPOS_OPCIONALES and valor is not None and monto_estricto(valor) == 0:
        return None
    return valor


@dataclass(frozen=True)
class Campos:
    """Los doce campos de un CFDI como texto (o None si no se reportan)."""

    rfc_emisor: Optional[str]
    rfc_receptor: Optional[str]
    uuid: Optional[str]
    fecha: Optional[str]
    subtotal: Optional[str]
    descuento: Optional[str]
    iva: Optional[str]
    ieps: Optional[str]
    isr_retenido: Optional[str]
    iva_retenido: Optional[str]
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
    """Arma `Campos` de un mapa ya validado (exactamente las doce llaves)."""
    return Campos(**{campo: mapa[campo] for campo in CAMPOS})


def mismo_valor(campo: str, a: Optional[str], b: Optional[str]) -> bool:
    """Montos: iguales como Decimal (un texto que no es monto nunca coincide). Lo demás: texto exacto.

    En los montos opcionales, None y un cero válido son el mismo valor (`efectivo`).
    """
    a, b = efectivo(campo, a), efectivo(campo, b)
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
