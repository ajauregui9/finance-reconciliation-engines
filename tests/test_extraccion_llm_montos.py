"""Contrato de la única conversión de texto a monto de la extracción con LLM (`monto_estricto`).

El modelo propone texto; aquí solo pasa un monto no negativo con dígitos ASCII, punto
decimal opcional y hasta dos decimales, sin espacios ni separador de miles. Cualquier otra
forma es `None` (el campo va a revisión), nunca un monto redondeado.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import pytest

from extraccion_llm.modelo import monto_estricto


@pytest.mark.parametrize("texto, esperado", [("1234.5", "1234.50"), ("0", "0.00"), ("16.00", "16.00")])
def test_monto_valido(texto: str, esperado: str) -> None:
    assert str(monto_estricto(texto)) == esperado


@pytest.mark.parametrize("texto", ["١٠٠.٠٠", "100.005", " 100.00", "100.00 ", "1 000.00", "1,000.00", "1,00.00",
                                   "-5.00", "+5.00", "1e2", "", None])
def test_monto_fuera_de_contrato_es_none(texto: Optional[str]) -> None:
    assert monto_estricto(texto) is None


def test_un_numero_no_es_texto() -> None:
    assert monto_estricto(0.1 + 0.2) is None  # type: ignore[arg-type]
    assert monto_estricto(Decimal("1.00")) is None  # type: ignore[arg-type]


def test_delega_en_la_frontera_compartida() -> None:
    from extraccion_llm import modelo

    assert modelo.FORMA_MONTO.decimales == 2 and not modelo.FORMA_MONTO.recortar
