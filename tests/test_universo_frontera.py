"""Contrato de la frontera de entrada del universo de cargos (celdas y resumen).

Fija los casos que comparten todos los motores: dígitos no ASCII, más de dos decimales,
float ambiguo, espacios y comas de miles mal puestas.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import pytest

from conciliacion import layouts, montos

ALFA = layouts.LAYOUTS["ALFA_V1"]


def _alfa(mxn: str) -> tuple:  # type: ignore[type-arg]
    return ("08/07/2026", "09/07/2026", "CAFE DE PRUEBA", "ANA DEMO", "****1001", "MXN", mxn, "", mxn)


@pytest.mark.parametrize("texto, esperado", [
    ("1,250.40", "1250.40"),
    ("  1,250.40\t", "1250.40"),
    ("١٬٢٥٠.٤٠", None),
    ("١٢٥٠.٤٠", None),
    ("1250.405", None),
    ("1 250.40", None),
    ("1,25.40", None),
    ("12,50.40", None),
    (" 1250.40", None),
])
def test_celda_de_importe(texto: str, esperado: Optional[str]) -> None:
    resultado = montos.leer_importe(texto, con_signo=True, con_miles=True)
    assert resultado == (None if esperado is None else Decimal(esperado))


@pytest.mark.parametrize("texto", ["١٢٥٠.٤٠", "1250.405", "1 250.40", "1,25.40"])
def test_fila_con_importe_fuera_de_contrato_queda_marcada(texto: str) -> None:
    lectura = layouts.interpretar_fila(ALFA, _alfa(texto))
    assert "monto_invalido" in lectura.problemas
    assert lectura.monto is None


@pytest.mark.parametrize("valor", ["١٠٠.٥٠", "100.005", 0.1 + 0.2, 100.5, " 100.00", "1,000.00", "1,00.00"])
def test_resumen_rechaza_lo_que_no_es_texto_canonico(valor: object) -> None:
    with pytest.raises(ValueError, match="total_neto"):
        montos.leer_monto_resumen(valor, "total_neto")


@pytest.mark.parametrize("texto", ["١٨.٢٠٠٠", "18.20001", " 18.2000 ", "18 .2"])
def test_tipo_de_cambio(texto: str) -> None:
    esperado = Decimal("18.2000") if texto.strip() == "18.2000" else None
    assert montos.leer_tipo_cambio(texto) == esperado


def test_montos_delega_en_la_frontera_compartida() -> None:
    import frontera

    assert montos.ErrorFrontera is frontera.ErrorFrontera
