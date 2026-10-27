"""Excepciones compartidas por varios módulos del paquete."""
from __future__ import annotations


class ErrorPoblado(ValueError):
    """La config o el plan de discrepancias no permiten poblar el esquema sin ajustes silenciosos."""
