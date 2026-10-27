"""Cuadre CFDI ↔ libro mayor con queries SuiteQL sobre un esquema SQLite sintético (ADR 0002).

Alcance: SuiteQL vía conector MCP y carga por CSV import. El paquete no trae cliente REST,
OAuth ni SuiteScript, y nunca escribe en el ERP.
"""
from __future__ import annotations

__version__ = "0.1.0"
