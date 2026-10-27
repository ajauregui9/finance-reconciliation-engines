"""Inspección de un texto libre: a lo más un hallazgo por familia, con el fragmento que lo activó.

El texto se inspecciona por capas: la capa 0 es el texto visible; cada token base64
legible y el texto escondido en etiquetas Unicode abren una capa más, hasta
`MAX_NIVELES`. Por familia gana el candidato de la capa más externa y, dentro de ella,
el que aparece primero. Reglas en `specs/prompt_guard.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple

from .capas import decodificar, tokens_base64
from .familias import FAMILIAS, NO_INSPECCIONABLE, PATRONES, TEXTO_INVISIBLE, VISTA_COMPACTA, VISTA_PLANA
from .normalizacion import Normalizado, Vista, normalizar

MAX_CARACTERES = 20_000
MAX_FRAGMENTO = 120
MAX_NIVELES = 2
MIN_ANCHO_CERO = 2
SEPARADORES_DE_SEGMENTO = frozenset(".;:!?|>-*#\"')]}»“”")
PREFIJO_BASE64 = "base64: "
PREFIJO_ETIQUETAS = "etiquetas: "
PUNTOS = "..."


@dataclass(frozen=True)
class Hallazgo:
    """Una familia detectada y el tramo del texto que la activó (texto de un tercero: es dato)."""

    familia: str
    fragmento: str


@dataclass(frozen=True)
class _Candidato:
    familia: str
    capa: int
    posicion: int
    orden: int
    fragmento: str

    @property
    def prioridad(self) -> Tuple[int, int, int]:
        return self.capa, self.posicion, self.orden


def _recortar(texto: str) -> str:
    if len(texto) <= MAX_FRAGMENTO:
        return texto
    return texto[:MAX_FRAGMENTO - len(PUNTOS)] + PUNTOS


def _inicio_de_segmento(normalizado: Normalizado, posicion: int) -> bool:
    """El tramo empieza el texto, una línea del original o sigue a puntuación de cierre."""
    if posicion in normalizado.inicios_de_linea:
        return True
    previo = normalizado.visible[:posicion].rstrip()
    return not previo or previo[-1] in SEPARADORES_DE_SEGMENTO


def _por_patron(normalizado: Normalizado, capa: int, prefijo: str) -> Iterator[_Candidato]:
    """La primera coincidencia aceptada de cada patrón, como tramo del texto visible."""
    vistas: Dict[str, Vista] = {VISTA_PLANA: normalizado.plana, VISTA_COMPACTA: normalizado.compacta}
    for orden, patron in enumerate(PATRONES):
        vista = vistas[patron.vista]
        for coincidencia in patron.regex.finditer(vista.texto):
            inicio, fin = vista.tramo_visible(coincidencia.start(), coincidencia.end())
            if patron.al_inicio and not _inicio_de_segmento(normalizado, inicio):
                continue
            yield _Candidato(patron.familia, capa, inicio, orden, prefijo + normalizado.visible[inicio:fin])
            break


def _plural(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else plural}"


def _invisibles(normalizado: Normalizado) -> Optional[str]:
    partes: List[str] = []
    if normalizado.ancho_cero >= MIN_ANCHO_CERO:
        partes.append(f"{normalizado.ancho_cero} caracteres de ancho cero")
    if normalizado.bidi:
        partes.append(_plural(normalizado.bidi, "control bidireccional", "controles bidireccionales"))
    if normalizado.etiquetas:
        partes.append(_plural(len(normalizado.etiquetas), "etiqueta Unicode", "etiquetas Unicode"))
    return "; ".join(partes) or None


def _no_inspeccionable(capa: int, posicion: int, detalle: str) -> _Candidato:
    return _Candidato(NO_INSPECCIONABLE, capa, posicion, len(PATRONES), detalle)


def _escondidos(normalizado: Normalizado, capa: int) -> List[_Candidato]:
    """Las capas internas: etiquetas Unicode y cada token base64 legible."""
    candidatos: List[_Candidato] = []
    if normalizado.etiquetas:
        candidatos.extend(_capa(normalizado.etiquetas, capa + 1, PREFIJO_ETIQUETAS))
    for token in tokens_base64(normalizado.visible):
        if token.demasiado_largo:
            candidatos.append(_no_inspeccionable(capa, token.inicio, f"token base64 de {len(token.texto)} "
                                                                     "caracteres sin decodificar"))
            continue
        texto = decodificar(token.texto)
        if texto is None:
            continue
        if capa >= MAX_NIVELES:
            candidatos.append(_no_inspeccionable(capa, token.inicio, f"base64 anidado en más de {MAX_NIVELES} "
                                                                     "niveles"))
            continue
        candidatos.extend(_capa(texto, capa + 1, PREFIJO_BASE64))
    return candidatos


def _capa(texto: str, capa: int, prefijo: str) -> List[_Candidato]:
    candidatos: List[_Candidato] = []
    if len(texto) > MAX_CARACTERES:
        candidatos.append(_no_inspeccionable(capa, MAX_CARACTERES, f"{prefijo}texto de {len(texto)} caracteres; "
                                                                   f"se revisaron los primeros {MAX_CARACTERES}"))
    normalizado = normalizar(texto[:MAX_CARACTERES])
    candidatos.extend(_por_patron(normalizado, capa, prefijo))
    invisibles = _invisibles(normalizado)
    if invisibles is not None:
        candidatos.append(_Candidato(TEXTO_INVISIBLE, capa, 0, len(PATRONES), prefijo + invisibles))
    candidatos.extend(_escondidos(normalizado, capa))
    return candidatos


def inspeccionar(texto: str) -> Tuple[Hallazgo, ...]:
    """Los hallazgos del texto: a lo más uno por familia, en el orden del catálogo."""
    if not isinstance(texto, str):
        raise TypeError(f"se esperaba str; llegó {type(texto).__name__}")
    mejores: Dict[str, _Candidato] = {}
    for candidato in _capa(texto, 0, ""):
        actual = mejores.get(candidato.familia)
        if actual is None or candidato.prioridad < actual.prioridad:
            mejores[candidato.familia] = candidato
    return tuple(Hallazgo(f, _recortar(mejores[f].fragmento)) for f in FAMILIAS if f in mejores)
