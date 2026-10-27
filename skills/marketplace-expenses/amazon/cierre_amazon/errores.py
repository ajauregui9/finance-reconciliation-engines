"""Jerarquía de errores del cierre. Ninguno se atrapa en silencio dentro del paquete."""
from __future__ import annotations


class ErrorCierre(Exception):
    """Base de todos los errores del paquete."""


class ErrorConfig(ErrorCierre):
    """La config no cumple la spec (sección 3)."""


class ErrorInsumo(ErrorCierre):
    """Un archivo de insumo no se puede usar tal como viene."""
