"""prompt_guard: filtro de cuarentena para texto libre, con revisión humana.

Marca el texto sospechoso (nunca lo aprueba, corrige ni borra) y ofrece los controles
que no dependen del texto: allowlist de dominios y filtro de rutas sensibles. Solo
biblioteca estándar. Contrato en `specs/prompt_guard.md`.
"""
from __future__ import annotations

from .accesos import DOMINIOS_PERMITIDOS, Decision, dominio_permitido, ruta_permitida, validar_allowlist
from .familias import FAMILIAS
from .inspeccion import Hallazgo, inspeccionar
from .normalizacion import Normalizado, normalizar

ESQUEMA = "prompt_guard/v1"

__all__ = ["DOMINIOS_PERMITIDOS", "ESQUEMA", "FAMILIAS", "Decision", "Hallazgo", "Normalizado", "dominio_permitido",
           "inspeccionar", "normalizar", "ruta_permitida", "validar_allowlist"]
