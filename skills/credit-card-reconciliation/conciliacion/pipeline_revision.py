"""Etapa de revisión del texto libre antes de los cruces: cuarentena con revisión humana.

La etapa recibe solo textos (descripciones de cargos y conceptos de CFDI) y devuelve
observaciones para la cola de revisión humana. No recibe los registros, así que no
puede cambiarlos ni quitarlos: los cruces corren igual con o sin observaciones; lo
que cambia es que el cargo observado queda en revisión. El revisor por omisión es
prompt_guard (`pipeline_guardia.py`); `RevisorIdentidad` lo desactiva. Contrato en
`specs/pipeline.md`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Protocol, Sequence, Tuple

from . import universo as uv
from .pipeline_modelo import ARCHIVO_CFDIS, ETAPA_REVISION, Candado, InsumoPipeline

ORIGEN_CARGO = "cargo"
ORIGEN_CFDI = "cfdi"
CAMPO_DESCRIPCION = "descripcion"
CAMPO_CONCEPTO = "concepto"
CANDADO_REVISION = "observaciones_conocidas"
NOMBRE_IDENTIDAD = "identidad"
MAX_EJEMPLOS = 5

Llave = Tuple[str, str, str]


@dataclass(frozen=True)
class TextoLibre:
    """Un texto que escribió un tercero y que podría llegar a un modelo de lenguaje."""

    origen: str
    registro_id: str
    campo: str
    texto: str

    @property
    def llave(self) -> Llave:
        return (self.origen, self.registro_id, self.campo)


@dataclass(frozen=True)
class Observacion:
    """Un elemento de la cola de revisión humana: qué texto, qué familia y el fragmento que la activó."""

    origen: str
    registro_id: str
    campo: str
    familia: str
    fragmento: str = ""

    @property
    def llave(self) -> Llave:
        return (self.origen, self.registro_id, self.campo)


class Revisor(Protocol):
    """Lo que el pipeline exige de un revisor de texto libre."""

    @property
    def nombre(self) -> str: ...

    def revisar(self, textos: Tuple[TextoLibre, ...]) -> Sequence[Observacion]: ...


@dataclass(frozen=True)
class RevisorIdentidad:
    """Revisor que no observa nada: desactiva la revisión de texto libre."""

    nombre: str = NOMBRE_IDENTIDAD

    def revisar(self, textos: Tuple[TextoLibre, ...]) -> Tuple[Observacion, ...]:
        return ()


@dataclass(frozen=True)
class Revision:
    revisor: str
    textos: Tuple[TextoLibre, ...]
    cola: Tuple[Observacion, ...]
    candado: Candado


# --- textos que se envían -------------------------------------------------------


def _ordenados(textos: Sequence[TextoLibre]) -> Tuple[TextoLibre, ...]:
    return tuple(sorted(textos, key=lambda t: t.llave))


def textos_de_cargos(cargos: Sequence[uv.Cargo]) -> Tuple[TextoLibre, ...]:
    """La descripción de cada cargo del universo; una descripción nula o vacía no se envía."""
    return _ordenados([TextoLibre(ORIGEN_CARGO, c.cargo_id, CAMPO_DESCRIPCION, c.descripcion)
                       for c in cargos if c.descripcion])


def _concepto(numero: int, registro: Mapping[str, Any]) -> Optional[str]:
    valor = registro.get(CAMPO_CONCEPTO)
    if valor is not None and not isinstance(valor, str):
        raise InsumoPipeline(f"{ETAPA_REVISION}: {ARCHIVO_CFDIS}, línea {numero}: el campo {CAMPO_CONCEPTO} debe ser "
                             f"texto o null; llegó {type(valor).__name__}")
    return valor or None


def textos_de_cfdis(registros: Sequence[Tuple[int, Mapping[str, Any]]]) -> Tuple[TextoLibre, ...]:
    """El concepto de cada registro crudo de CFDI (número de línea, objeto); nulo o ausente no se envía."""
    textos: List[TextoLibre] = []
    for numero, registro in registros:
        concepto = _concepto(numero, registro)
        if concepto is not None:
            textos.append(TextoLibre(ORIGEN_CFDI, str(registro.get("uuid")), CAMPO_CONCEPTO, concepto))
    return _ordenados(textos)


# --- revisión -------------------------------------------------------------------


def _problemas(cola: Sequence[Observacion], enviados: FrozenSet[Llave]) -> List[str]:
    problemas = [f"{'/'.join(o.llave)}: no cita un texto enviado" for o in cola if o.llave not in enviados]
    problemas.extend(f"{'/'.join(o.llave)}: familia vacía" for o in cola
                     if not isinstance(o.familia, str) or not o.familia.strip())
    return sorted(problemas)


def _candado(problemas: Sequence[str]) -> Candado:
    if not problemas:
        return Candado(ETAPA_REVISION, CANDADO_REVISION, True, "sin observaciones inválidas")
    ejemplos = "; ".join(problemas[:MAX_EJEMPLOS])
    return Candado(ETAPA_REVISION, CANDADO_REVISION, False, f"{len(problemas)} casos: {ejemplos}")


def revisar_texto_libre(revisor: Revisor, textos: Tuple[TextoLibre, ...]) -> Revision:
    """Pasa los textos al revisor, ordena su cola y verifica que cada observación sea válida."""
    cola = tuple(sorted(revisor.revisar(textos), key=lambda o: (o.llave, o.familia, o.fragmento)))
    problemas = _problemas(cola, frozenset(t.llave for t in textos))
    return Revision(revisor.nombre, textos, cola, _candado(problemas))


def observaciones_de(cola: Sequence[Observacion], cargo_id: str, uuids: Sequence[str]) -> Tuple[Observacion, ...]:
    """Las observaciones de un cargo: las de su descripción y las de los conceptos de sus CFDIs."""
    propios = {(ORIGEN_CARGO, cargo_id)} | {(ORIGEN_CFDI, u) for u in uuids}
    return tuple(o for o in cola if (o.origen, o.registro_id) in propios)


def observacion_a_dict(observacion: Observacion) -> Dict[str, str]:
    return {"origen": observacion.origen, "registro_id": observacion.registro_id, "campo": observacion.campo,
            "familia": observacion.familia, "fragmento": observacion.fragmento}
