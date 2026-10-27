"""Similitud de nombres entre descriptores bancarios y proveedores del ERP.

La medida está definida en `specs/cruce_libro.md` ("Similitud de nombres"). Solo usa
enteros y `Fraction`: el mismo par de textos da el mismo valor en cualquier versión
de Python. No se usa `difflib` (devuelve float y su heurística depende del largo).
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from typing import Iterable, List, Sequence, Tuple

ESCALA_CUATRO = 10_000
_NO_ALFANUMERICO = re.compile(r"[^A-Z0-9]+")

FORMAS_SOCIETARIAS = frozenset({"CV", "DE", "INC", "LLC", "LTD", "RL", "SA", "SAPI", "SC"})


@dataclass(frozen=True)
class ReglasNombres:
    """Largos mínimos y vocabulario fijo de la comparación (valores de ejemplo)."""

    min_nombres_stopword: int = 4
    stopwords_fijas: frozenset[str] = field(default=FORMAS_SOCIETARIAS)
    largo_min_prefijo: int = 3
    largo_max_abreviatura: int = 3
    largo_min_raiz: int = 4
    largo_min_pieza: int = 3


@dataclass(frozen=True)
class _Enlace:
    """Un enlace candidato entre tokens de ambos lados y sus créditos."""

    credito_izq: int
    credito_der: int
    tokens_izq: Tuple[int, ...]
    tokens_der: Tuple[int, ...]

    @property
    def llave(self) -> Tuple[int, Tuple[int, ...], Tuple[int, ...]]:
        return (-(self.credito_izq + self.credito_der), self.tokens_izq, self.tokens_der)


@dataclass(frozen=True)
class _Lado:
    """Tokens de un nombre y cuáles cuentan (no son stopword de su lado)."""

    tokens: Tuple[str, ...]
    cuenta: Tuple[bool, ...]

    @property
    def largo(self) -> int:
        return sum(len(t) for t, c in zip(self.tokens, self.cuenta) if c)


def tokenizar(texto: str) -> Tuple[str, ...]:
    """Mayúsculas sin acentos; descarta tokens de puro dígito y de una letra."""
    descompuesto = unicodedata.normalize("NFKD", texto.upper())
    sin_marcas = "".join(c for c in descompuesto if not unicodedata.combining(c))
    crudos = _NO_ALFANUMERICO.sub(" ", sin_marcas).split()
    return tuple(t for t in crudos if len(t) > 1 and not t.isdigit())


def stopwords_de_lado(nombres: Iterable[str], reglas: ReglasNombres) -> frozenset[str]:
    """Tokens presentes en al menos `min_nombres_stopword` nombres distintos, más las fijas."""
    frecuencia: Counter[str] = Counter()
    for nombre in sorted(set(nombres)):
        frecuencia.update(set(tokenizar(nombre)))
    frecuentes = {t for t, n in frecuencia.items() if n >= reglas.min_nombres_stopword}
    return frozenset(frecuentes) | reglas.stopwords_fijas


def _prefijo_comun(a: str, b: str) -> int:
    largo = 0
    for x, y in zip(a, b):
        if x != y:
            break
        largo += 1
    return largo


def _es_subsecuencia(corto: str, largo: str) -> bool:
    restante = iter(largo)
    return all(letra in restante for letra in corto)


def credito_tokens(a: str, b: str, reglas: ReglasNombres) -> int:
    """Caracteres que comparten dos tokens según la primera regla de enlace que aplique."""
    if a == b:
        return len(a)
    corto, largo = (a, b) if len(a) <= len(b) else (b, a)
    if corto[0] != largo[0]:
        return 0
    if len(corto) >= reglas.largo_min_prefijo and largo.startswith(corto):
        return len(corto)
    if 2 <= len(corto) <= reglas.largo_max_abreviatura and _es_subsecuencia(corto, largo):
        return len(corto)
    raiz = _prefijo_comun(a, b)
    return raiz if raiz >= reglas.largo_min_raiz else 0


def _corte_pegado(token: str, primero: str, segundo: str, minimo: int) -> int:
    """Posición donde `token` se parte en prefijos de `primero` y `segundo`; 0 si no hay."""
    for corte in range(minimo, len(token) - minimo + 1):
        if primero.startswith(token[:corte]) and segundo.startswith(token[corte:]):
            return corte
    return 0


def _lado(nombre: str, stopwords: frozenset[str]) -> _Lado:
    tokens = tokenizar(nombre)
    cuenta = tuple(t not in stopwords for t in tokens)
    if tokens and not any(cuenta):
        cuenta = tuple(True for _ in tokens)
    return _Lado(tokens, cuenta)


def _enlaces_simples(izq: _Lado, der: _Lado, reglas: ReglasNombres) -> List[_Enlace]:
    salida = []
    for i, a in enumerate(izq.tokens):
        for j, b in enumerate(der.tokens):
            if not (izq.cuenta[i] and der.cuenta[j]):
                continue
            credito = credito_tokens(a, b, reglas)
            if credito:
                salida.append(_Enlace(credito, credito, (i,), (j,)))
    return salida


def _enlaces_pegados(unido: _Lado, partido: _Lado, minimo: int) -> List[Tuple[int, int, int, int]]:
    """(token unido, primer token partido, crédito unido, crédito partido) por cada palabra pegada."""
    salida = []
    for i, token in enumerate(unido.tokens):
        if not unido.cuenta[i]:
            continue
        for j in range(len(partido.tokens) - 1):
            corte = _corte_pegado(token, partido.tokens[j], partido.tokens[j + 1], minimo)
            if corte:
                credito = (corte if partido.cuenta[j] else 0) + (
                    (len(token) - corte) if partido.cuenta[j + 1] else 0)
                salida.append((i, j, len(token), credito))
    return salida


def _todos_los_enlaces(izq: _Lado, der: _Lado, reglas: ReglasNombres) -> List[_Enlace]:
    minimo = reglas.largo_min_pieza
    enlaces = _enlaces_simples(izq, der, reglas)
    enlaces += [_Enlace(cu, cp, (i,), (j, j + 1)) for i, j, cu, cp in _enlaces_pegados(izq, der, minimo)]
    enlaces += [_Enlace(cp, cu, (j, j + 1), (i,)) for i, j, cu, cp in _enlaces_pegados(der, izq, minimo)]
    return sorted(enlaces, key=lambda e: e.llave)


def _creditos_aceptados(enlaces: Sequence[_Enlace]) -> Tuple[int, int]:
    usados_izq: set[int] = set()
    usados_der: set[int] = set()
    total_izq = total_der = 0
    for enlace in enlaces:
        if usados_izq.intersection(enlace.tokens_izq) or usados_der.intersection(enlace.tokens_der):
            continue
        usados_izq.update(enlace.tokens_izq)
        usados_der.update(enlace.tokens_der)
        total_izq += enlace.credito_izq
        total_der += enlace.credito_der
    return total_izq, total_der


@dataclass(frozen=True)
class ComparadorNombres:
    """Compara un nombre del lado izquierdo (banco) contra uno del derecho (ERP)."""

    stop_izq: frozenset[str]
    stop_der: frozenset[str]
    reglas: ReglasNombres

    @classmethod
    def desde_vocabularios(cls, izquierda: Iterable[str], derecha: Iterable[str],
                           reglas: ReglasNombres) -> ComparadorNombres:
        return cls(stopwords_de_lado(izquierda, reglas), stopwords_de_lado(derecha, reglas), reglas)

    def similitud(self, izquierda: str, derecha: str) -> Fraction:
        izq, der = _lado(izquierda, self.stop_izq), _lado(derecha, self.stop_der)
        denominador = izq.largo + der.largo
        if not izq.largo or not der.largo:
            return Fraction(0)
        credito_izq, credito_der = _creditos_aceptados(_todos_los_enlaces(izq, der, self.reglas))
        return Fraction(credito_izq + credito_der, denominador)


def a_decimal4(valor: Fraction) -> Decimal:
    """Fracción no negativa a cuatro decimales, ROUND_HALF_UP, con aritmética entera."""
    if valor < 0:
        raise ValueError(f"La similitud no puede ser negativa: {valor}")
    cociente, residuo = divmod(valor.numerator * ESCALA_CUATRO, valor.denominator)
    if 2 * residuo >= valor.denominator:
        cociente += 1
    return Decimal(cociente).scaleb(-4)
