"""Revisor por omisión del pipeline: prompt_guard como cuarentena con revisión humana.

El paquete `guardia` (`skills/security-guardian/guardia`) se importa como cualquier
paquete instalado: `pip install -e .` lo expone junto con `conciliacion`. Cada hallazgo
se vuelve una observación para la cola `revision_humana`; el revisor nunca aprueba ni
cambia un registro. Si el paquete no se puede importar, la corrida es inválida
(código 2): no se sigue sin revisión en silencio. Contrato en `specs/pipeline.md`.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType
from typing import Callable, Protocol, Sequence, Tuple, cast

from .pipeline_modelo import ETAPA_REVISION, InsumoPipeline
from .pipeline_revision import Observacion, TextoLibre

NOMBRE_REVISOR = "prompt_guard"
MODULO_GUARDIA = "guardia"
SUGERENCIA_INSTALACION = "instala el repo con `pip install -e .`"


class HallazgoGuardia(Protocol):
    """Lo que el pipeline lee de cada hallazgo de prompt_guard."""

    @property
    def familia(self) -> str: ...

    @property
    def fragmento(self) -> str: ...


Inspector = Callable[[str], Sequence[HallazgoGuardia]]


def _error(detalle: str) -> InsumoPipeline:
    return InsumoPipeline(f"{ETAPA_REVISION}: no se pudo cargar {NOMBRE_REVISOR}: {detalle}")


def cargar_paquete(modulo: str = MODULO_GUARDIA) -> ModuleType:
    """Importa el paquete del guard; cualquier falla se vuelve `InsumoPipeline`."""
    try:
        return importlib.import_module(modulo)
    except ImportError as error:
        raise _error(f"no se puede importar '{modulo}' ({error}); {SUGERENCIA_INSTALACION}") from error
    except Exception as error:
        raise _error(f"{type(error).__name__}: {error}") from error


def cargar_inspector(modulo: str = MODULO_GUARDIA) -> Inspector:
    funcion = getattr(cargar_paquete(modulo), "inspeccionar", None)
    if not callable(funcion):
        raise _error(f"el paquete '{modulo}' no ofrece inspeccionar(texto)")
    return cast(Inspector, funcion)


@dataclass(frozen=True)
class RevisorGuardia:
    """Revisa cada texto libre con prompt_guard: una observación por familia detectada."""

    modulo: str = MODULO_GUARDIA
    nombre: str = NOMBRE_REVISOR

    def revisar(self, textos: Tuple[TextoLibre, ...]) -> Tuple[Observacion, ...]:
        if not textos:
            return ()
        inspector = cargar_inspector(self.modulo)
        return tuple(Observacion(t.origen, t.registro_id, t.campo, h.familia, h.fragmento)
                     for t in textos for h in inspector(t.texto))
