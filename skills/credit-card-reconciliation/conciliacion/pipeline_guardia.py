"""Revisor por omisión del pipeline: prompt_guard como cuarentena con revisión humana.

El paquete `guardia` vive en `skills/security-guardian/guardia` y se carga por ruta
explícita (nunca del primer `guardia` que aparezca en `sys.path`). Cada hallazgo se
vuelve una observación para la cola `revision_humana`; el revisor nunca aprueba ni
cambia un registro. Si el paquete no se puede cargar, la corrida es inválida
(código 2): no se sigue sin revisión en silencio. Contrato en `specs/pipeline.md`.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Callable, Optional, Protocol, Sequence, Tuple, cast

from .pipeline_modelo import ETAPA_REVISION, InsumoPipeline
from .pipeline_revision import Observacion, TextoLibre

NOMBRE_REVISOR = "prompt_guard"
MODULO_GUARDIA = "guardia"
CARPETA_GUARDIA = Path(__file__).resolve().parents[2] / "security-guardian" / MODULO_GUARDIA
INICIO_PAQUETE = "__init__.py"


class HallazgoGuardia(Protocol):
    """Lo que el pipeline lee de cada hallazgo de prompt_guard."""

    @property
    def familia(self) -> str: ...

    @property
    def fragmento(self) -> str: ...


Inspector = Callable[[str], Sequence[HallazgoGuardia]]


def _error(detalle: str) -> InsumoPipeline:
    return InsumoPipeline(f"{ETAPA_REVISION}: no se pudo cargar {NOMBRE_REVISOR}: {detalle}")


def _archivo_de(modulo: ModuleType) -> Optional[Path]:
    archivo = getattr(modulo, "__file__", None)
    return Path(archivo).resolve() if isinstance(archivo, str) else None


def _olvidar_paquete() -> None:
    for nombre in [n for n in sys.modules if n == MODULO_GUARDIA or n.startswith(MODULO_GUARDIA + ".")]:
        del sys.modules[nombre]


def _ejecutar(inicio: Path) -> ModuleType:
    especificacion = importlib.util.spec_from_file_location(MODULO_GUARDIA, inicio,
                                                            submodule_search_locations=[str(inicio.parent)])
    if especificacion is None or especificacion.loader is None:
        raise _error(f"{inicio.parent.name} no es un paquete de Python")
    modulo = importlib.util.module_from_spec(especificacion)
    sys.modules[MODULO_GUARDIA] = modulo
    try:
        especificacion.loader.exec_module(modulo)
    except Exception as error:
        _olvidar_paquete()
        raise _error(f"{type(error).__name__}: {error}") from error
    return modulo


def cargar_paquete(carpeta: Path = CARPETA_GUARDIA) -> ModuleType:
    """El paquete `guardia` de esa carpeta; reutiliza el ya importado solo si es el mismo archivo."""
    inicio = (carpeta / INICIO_PAQUETE).resolve()
    if not inicio.is_file():
        raise _error(f"no existe {carpeta.name}/{INICIO_PAQUETE}")
    previo = sys.modules.get(MODULO_GUARDIA)
    if previo is None:
        return _ejecutar(inicio)
    if _archivo_de(previo) != inicio:
        raise _error(f"ya hay otro módulo '{MODULO_GUARDIA}' importado y no es el de {carpeta.name}")
    return previo


def cargar_inspector(carpeta: Path = CARPETA_GUARDIA) -> Inspector:
    funcion = getattr(cargar_paquete(carpeta), "inspeccionar", None)
    if not callable(funcion):
        raise _error(f"el paquete de {carpeta.name} no ofrece inspeccionar(texto)")
    return cast(Inspector, funcion)


@dataclass(frozen=True)
class RevisorGuardia:
    """Revisa cada texto libre con prompt_guard: una observación por familia detectada."""

    carpeta: Path = CARPETA_GUARDIA
    nombre: str = NOMBRE_REVISOR

    def revisar(self, textos: Tuple[TextoLibre, ...]) -> Tuple[Observacion, ...]:
        if not textos:
            return ()
        inspector = cargar_inspector(self.carpeta)
        return tuple(Observacion(t.origen, t.registro_id, t.campo, h.familia, h.fragmento)
                     for t in textos for h in inspector(t.texto))
