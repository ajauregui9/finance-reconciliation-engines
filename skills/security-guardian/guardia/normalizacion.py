"""Vistas de un texto libre para buscar patrones sin que lo despisten Unicode ni el formato.

El texto visible es NFKC, sin caracteres invisibles y con los espacios aplanados; es
lo que se muestra en los fragmentos. Las vistas plana y compacta sirven para buscar y
guardan, para cada carácter, su posición en el texto visible. Reglas en
`specs/prompt_guard.md`.
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Tuple

ANCHO_CERO: FrozenSet[str] = frozenset("​‌‍⁠﻿᠎")
BIDI: FrozenSet[str] = frozenset("؜‎‏‪‫‬‭‮⁦⁧⁨⁩")
BOM = "﻿"
SALTOS: FrozenSet[str] = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")
ETIQUETA_INICIO, ETIQUETA_FIN = 0xE0000, 0xE007F
ASCII_IMPRIMIBLE = range(0x20, 0x7F)

# Letras cirílicas y griegas (ya en minúscula) que se confunden con una latina.
HOMOGLIFOS: Dict[str, str] = {
    "а": "a", "в": "b", "е": "e", "һ": "h", "н": "h", "і": "i", "ј": "j", "к": "k", "ӏ": "l", "м": "m",
    "о": "o", "р": "p", "ԛ": "q", "с": "c", "ѕ": "s", "т": "t", "у": "y", "х": "x", "ԁ": "d", "ԝ": "w",
    "α": "a", "β": "b", "ε": "e", "η": "h", "ι": "i", "κ": "k", "μ": "m", "ο": "o", "ρ": "p", "τ": "t",
    "υ": "u", "χ": "x", "ı": "i", "ɡ": "g",
}


@dataclass(frozen=True)
class Vista:
    """Un texto derivado del visible y, por cada carácter, su posición en el visible."""

    texto: str
    origen: Tuple[int, ...]

    def tramo_visible(self, inicio: int, fin: int) -> Tuple[int, int]:
        """El tramo [inicio, fin) de esta vista como tramo del texto visible."""
        return self.origen[inicio], self.origen[fin - 1] + 1


@dataclass(frozen=True)
class Normalizado:
    visible: str
    plana: Vista
    compacta: Vista
    inicios_de_linea: FrozenSet[int]
    ancho_cero: int
    bidi: int
    etiquetas: str
    otros_invisibles: int


@dataclass(frozen=True)
class _Limpio:
    texto: str
    ancho_cero: int
    bidi: int
    etiquetas: str
    otros: int


def _es_invisible(caracter: str) -> bool:
    categoria = unicodedata.category(caracter)
    return categoria == "Cf" or (categoria == "Cc" and not caracter.isspace())


def _quitar_invisibles(texto: str) -> _Limpio:
    """Quita formato y controles; cuenta cada clase y traduce las etiquetas a ASCII."""
    conservados: List[str] = []
    escondido: List[str] = []
    ancho_cero = bidi = otros = 0
    for posicion, caracter in enumerate(texto):
        punto = ord(caracter)
        if not _es_invisible(caracter):
            conservados.append(caracter)
        elif ETIQUETA_INICIO <= punto <= ETIQUETA_FIN:
            if punto - ETIQUETA_INICIO in ASCII_IMPRIMIBLE:
                escondido.append(chr(punto - ETIQUETA_INICIO))
        elif caracter in BIDI:
            bidi += 1
        elif caracter in ANCHO_CERO:
            ancho_cero += 0 if (posicion == 0 and caracter == BOM) else 1
        else:
            otros += 1
    return _Limpio("".join(conservados), ancho_cero, bidi, "".join(escondido), otros)


def _aplanar(texto: str) -> Tuple[str, FrozenSet[int]]:
    """Un solo espacio por cada tramo de espacios; recuerda dónde empezaba cada línea."""
    salida: List[str] = []
    inicios: List[int] = []
    en_espacio = hubo_salto = False
    for caracter in texto:
        if caracter.isspace():
            en_espacio = True
            hubo_salto = hubo_salto or caracter in SALTOS
            continue
        if en_espacio and salida:
            salida.append(" ")
        if hubo_salto and salida:
            inicios.append(len(salida))
        en_espacio = hubo_salto = False
        salida.append(caracter)
    return "".join(salida), frozenset(inicios)


def _plegar(caracter: str) -> str:
    """Minúscula sin diacríticos y con homoglifos plegados; puede quedar vacío (marca suelta)."""
    base = "".join(c for c in unicodedata.normalize("NFD", caracter) if not unicodedata.combining(c))
    return "".join(HOMOGLIFOS.get(c, c) for c in base.lower())


def _vista_plana(visible: str) -> Vista:
    caracteres: List[str] = []
    origen: List[int] = []
    for posicion, caracter in enumerate(visible):
        for plegado in _plegar(caracter):
            caracteres.append(plegado)
            origen.append(posicion)
    return Vista("".join(caracteres), tuple(origen))


def _vista_compacta(plana: Vista) -> Vista:
    pares = [(c, o) for c, o in zip(plana.texto, plana.origen) if c.isascii() and c.isalnum()]
    return Vista("".join(c for c, _ in pares), tuple(o for _, o in pares))


def normalizar(texto: str) -> Normalizado:
    """NFKC, quita invisibles, aplana espacios y deriva las vistas plana y compacta."""
    if not isinstance(texto, str):
        raise TypeError(f"se esperaba str; llegó {type(texto).__name__}")
    limpio = _quitar_invisibles(unicodedata.normalize("NFKC", texto))
    visible, inicios = _aplanar(limpio.texto)
    plana = _vista_plana(visible)
    return Normalizado(visible=visible, plana=plana, compacta=_vista_compacta(plana), inicios_de_linea=inicios,
                       ancho_cero=limpio.ancho_cero, bidi=limpio.bidi, etiquetas=limpio.etiquetas,
                       otros_invisibles=limpio.otros)
