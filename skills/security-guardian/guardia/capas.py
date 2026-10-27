"""Texto escondido dentro de un texto libre: tokens base64 que decodifican a texto legible.

Un token se decodifica solo si tiene forma de base64, longitud razonable y su
contenido es UTF-8 casi todo imprimible. Lo demás (folios, UUIDs, referencias) se
ignora: no es sospechoso por sí solo. Reglas en `specs/prompt_guard.md`.
"""
from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Optional, Tuple

MIN_BASE64 = 16
MAX_BASE64 = 4096
PROPORCION_IMPRIMIBLE = Fraction(9, 10)
ALFABETO_URL = frozenset("-_")
ALFABETO_ESTANDAR = frozenset("+/")

_TOKEN = re.compile(r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/_-]{%d,}={0,2}(?![A-Za-z0-9+/=_-])" % MIN_BASE64)


@dataclass(frozen=True)
class Token:
    inicio: int
    fin: int
    texto: str

    @property
    def demasiado_largo(self) -> bool:
        return len(self.texto) > MAX_BASE64


def tokens_base64(texto: str) -> Tuple[Token, ...]:
    """Cada tramo del texto con forma de base64 y al menos `MIN_BASE64` caracteres."""
    return tuple(Token(m.start(), m.end(), m.group(0)) for m in _TOKEN.finditer(texto))


def _bytes(token: str) -> Optional[bytes]:
    cuerpo = token.rstrip("=")
    caracteres = set(cuerpo)
    if caracteres & ALFABETO_URL and caracteres & ALFABETO_ESTANDAR:
        return None
    if len(cuerpo) % 4 == 1:
        return None
    relleno = cuerpo + "=" * (-len(cuerpo) % 4)
    alterno = b"-_" if caracteres & ALFABETO_URL else None
    try:
        return base64.b64decode(relleno, altchars=alterno, validate=True)
    except (binascii.Error, ValueError):
        return None


def _legible(texto: str) -> bool:
    if not texto or not any(c.isalpha() for c in texto):
        return False
    imprimibles = sum(1 for c in texto if c.isprintable() or c in "\n\r\t")
    return Fraction(imprimibles, len(texto)) >= PROPORCION_IMPRIMIBLE


def decodificar(token: str) -> Optional[str]:
    """El texto escondido en el token, o None si no decodifica a UTF-8 legible."""
    crudo = _bytes(token)
    if crudo is None:
        return None
    try:
        texto = crudo.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return texto if _legible(texto) else None
