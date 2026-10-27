"""Afinidad entre la descripción de un cargo y la razón social de un emisor (helper privado del cruce).

Es una señal heurística y simétrica en [0, 1]. Sirve para desempatar y como
sustituto de un criterio duro relajado (sumas y diagnósticos); por sí sola nunca
produce un cruce.
"""
from __future__ import annotations

import re
import unicodedata
from fractions import Fraction
from functools import lru_cache
from typing import Sequence, Tuple

# Palabras de 3+ letras que no distinguen a un comercio: formas societarias y artículos.
_SIN_PESO = frozenset({
    "SAS", "SAPI", "SAB", "SPR", "LLC", "INC", "LTD", "CORP", "GMBH",
    "DEL", "LAS", "LOS", "THE", "AND",
})
LARGO_MINIMO_PALABRA = 3
PREFIJO_COMPARTIDO = 4
_SEPARADORES = re.compile(r"[^A-Z0-9]+")


def palabras_nombre(texto: str) -> Tuple[str, ...]:
    """Palabras significativas en mayúsculas ASCII, en su orden original."""
    descompuesto = unicodedata.normalize("NFKD", texto)
    sin_acentos = "".join(ch for ch in descompuesto if not unicodedata.combining(ch)).upper()
    return tuple(
        p for p in _SEPARADORES.split(sin_acentos)
        if len(p) >= LARGO_MINIMO_PALABRA and not p.isdigit() and p not in _SIN_PESO
    )


def _letras_en_orden(corta: str, larga: str) -> bool:
    restante = iter(larga)
    return all(letra in restante for letra in corta)


def _largo_prefijo(a: str, b: str) -> int:
    largo = 0
    for x, y in zip(a, b):
        if x != y:
            break
        largo += 1
    return largo


def _compatibles(a: str, b: str) -> bool:
    """Iguales, abreviatura de la misma inicial (HTL/HOTEL, OFI/OFICINA) o prefijo de 4+ letras en común."""
    if a == b:
        return True
    corta, larga = (a, b) if len(a) <= len(b) else (b, a)
    if corta[0] == larga[0] and _letras_en_orden(corta, larga):
        return True
    return _largo_prefijo(a, b) >= PREFIJO_COMPARTIDO


def _cobertura(propias: Sequence[str], ajenas: Sequence[str]) -> Fraction:
    con_pareja = sum(1 for p in propias if any(_compatibles(p, q) for q in ajenas))
    return Fraction(con_pareja, len(propias))


@lru_cache(maxsize=8192)
def afinidad(descripcion: str, razon_social: str) -> Fraction:
    """La mayor de las dos coberturas: qué fracción de un nombre tiene pareja en el otro."""
    uno, otro = palabras_nombre(descripcion), palabras_nombre(razon_social)
    if not uno or not otro:
        return Fraction(0)
    return max(_cobertura(uno, otro), _cobertura(otro, uno))
