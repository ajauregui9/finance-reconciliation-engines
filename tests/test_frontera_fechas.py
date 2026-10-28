"""Contrato de la frontera compartida de fechas y horas (`frontera.fechas`)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from frontera import ErrorFrontera, leer_desfase_utc, leer_fecha, leer_fecha_hora, leer_mes


def test_fecha_valida() -> None:
    assert leer_fecha("2026-02-28") == date(2026, 2, 28)


@pytest.mark.parametrize("texto", ["٢٠٢٦-٠٢-٢٨", "２０２６-02-28", "20260228", "2026-W09-6", "2026-2-28",
                                   " 2026-02-28", "2026-02-28\n", "", "2026/02/28"])
def test_fecha_con_forma_invalida(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="AAAA-MM-DD"):
        leer_fecha(texto)


def test_fecha_imposible() -> None:
    with pytest.raises(ErrorFrontera, match="no existe"):
        leer_fecha("2026-02-30")


@pytest.mark.parametrize("valor", [None, 20260228, date(2026, 2, 28)])
def test_fecha_que_no_es_texto(valor: object) -> None:
    with pytest.raises(ErrorFrontera, match="texto"):
        leer_fecha(valor)


def test_fecha_hora_con_espacio_y_con_t() -> None:
    assert leer_fecha_hora("2026-04-03 17:59:20") == datetime(2026, 4, 3, 17, 59, 20)
    assert leer_fecha_hora("2026-04-03T17:59:20", separador="T") == datetime(2026, 4, 3, 17, 59, 20)


@pytest.mark.parametrize("texto", ["2026-4-3 1:2:3", "2026-04-03T17:59:20", "٢٠٢٦-٠٤-٠٣ ١٧:٥٩:٢٠",
                                   "2026-04-03 17:59", "2026-04-03 17:59:20Z", "2026-04-03 17:59:20.5", ""])
def test_fecha_hora_con_forma_invalida(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="AAAA-MM-DD HH:MM:SS"):
        leer_fecha_hora(texto)


@pytest.mark.parametrize("texto", ["2026-04-31 10:00:00", "2026-04-03 24:00:00", "2026-04-03 10:60:00"])
def test_fecha_hora_imposible(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="no existe"):
        leer_fecha_hora(texto)


def test_fecha_hora_que_no_es_texto() -> None:
    with pytest.raises(ErrorFrontera, match="texto"):
        leer_fecha_hora(None)


def test_separador_invalido() -> None:
    with pytest.raises(ValueError):
        leer_fecha_hora("2026-04-03 17:59:20", separador="-")


def test_mes_valido() -> None:
    assert leer_mes("2026-12") == "2026-12"


@pytest.mark.parametrize("valor", ["2026-13", "2026-00", "٢٠٢٦-٠١", "2026-1", " 2026-01", "2026-01-01", None, 202601])
def test_mes_invalido(valor: object) -> None:
    with pytest.raises(ErrorFrontera, match="AAAA-MM"):
        leer_mes(valor)


@pytest.mark.parametrize("texto, horas", [("UTC-07:00", -7), ("UTC+00:00", 0), ("UTC+05:30", 5.5), ("UTC+14:00", 14)])
def test_desfase_fijo(texto: str, horas: float) -> None:
    assert leer_desfase_utc(texto) == timezone(timedelta(hours=horas))


@pytest.mark.parametrize("texto", ["UTC-٠٧:٠٠", "UTC-7:00", "America/Mexico_City", "UTC+0700", " UTC-07:00", None])
def test_desfase_con_forma_invalida(texto: object) -> None:
    with pytest.raises(ErrorFrontera, match="UTC±HH:MM"):
        leer_desfase_utc(texto)


@pytest.mark.parametrize("texto", ["UTC+15:00", "UTC-07:60"])
def test_desfase_fuera_de_rango(texto: str) -> None:
    with pytest.raises(ErrorFrontera, match="fuera de rango"):
        leer_desfase_utc(texto)
