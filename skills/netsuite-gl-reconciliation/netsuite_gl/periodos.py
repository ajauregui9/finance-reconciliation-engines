"""Periodos contables al estilo NetSuite: anual y trimestres de resumen, meses de registro."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Dict, Optional, Sequence, Tuple

from netsuite_gl.config import ConfigEsquema
from netsuite_gl.errores import ErrorPoblado

# Abreviaturas fijas (no dependen del locale), como las muestra NetSuite.
ABREVIATURAS_MES: Tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)
BASE_ID_ANUAL = 1
BASE_ID_TRIMESTRE = 11
BASE_ID_MES = 101


@dataclass(frozen=True)
class Periodo:
    id: int
    nombre: str
    inicio: date
    fin: date
    es_registro: bool
    es_trimestre: bool
    es_anual: bool
    cerrado: bool

    def contiene(self, dia: date) -> bool:
        return self.inicio <= dia <= self.fin


def construir_periodos(config: ConfigEsquema) -> Tuple[Periodo, ...]:
    """Anuales, trimestres y meses de la config, en ese orden y con ids estables."""
    meses = _meses_validos(config)
    cerrados = set(config.meses_cerrados)
    anios = sorted({anio for anio, _ in meses})
    trimestres = sorted({(anio, _trimestre(mes)) for anio, mes in meses})
    anuales = tuple(
        Periodo(
            BASE_ID_ANUAL + i, f"FY {anio}", date(anio, 1, 1), date(anio, 12, 31),
            False, False, True, all(m in cerrados for m in meses if m[0] == anio),
        )
        for i, anio in enumerate(anios)
    )
    de_trimestre = tuple(
        Periodo(
            BASE_ID_TRIMESTRE + i, f"Q{trim} {anio}", date(anio, 3 * trim - 2, 1), _fin_de_mes(anio, 3 * trim),
            False, True, False, all(m in cerrados for m in meses if (m[0], _trimestre(m[1])) == (anio, trim)),
        )
        for i, (anio, trim) in enumerate(trimestres)
    )
    mensuales = tuple(
        Periodo(
            BASE_ID_MES + i, f"{ABREVIATURAS_MES[mes - 1]} {anio}", date(anio, mes, 1), _fin_de_mes(anio, mes),
            True, False, False, (anio, mes) in cerrados,
        )
        for i, (anio, mes) in enumerate(meses)
    )
    return anuales + de_trimestre + mensuales


def periodo_de_registro(dia: date, periodos: Sequence[Periodo]) -> Optional[Periodo]:
    """El mes de registro que contiene la fecha, o `None` si la config no lo tiene."""
    return next((p for p in periodos if p.es_registro and p.contiene(dia)), None)


def mes_siguiente(periodo: Periodo, periodos: Sequence[Periodo]) -> Optional[Periodo]:
    """El mes de registro que empieza justo después de `periodo`, si existe en la config."""
    return periodo_de_registro(periodo.fin + timedelta(days=1), periodos)


def por_nombre(periodos: Sequence[Periodo]) -> Dict[str, Periodo]:
    return {p.nombre: p for p in periodos}


def _meses_validos(config: ConfigEsquema) -> Tuple[Tuple[int, int], ...]:
    meses = tuple(sorted(set(config.meses)))
    if not meses:
        raise ErrorPoblado("la config no define meses de registro")
    invalidos = [m for m in meses if not 1 <= m[1] <= 12]
    if invalidos:
        raise ErrorPoblado(f"meses inválidos en la config: {invalidos}")
    sobrantes = sorted(set(config.meses_cerrados) - set(meses))
    if sobrantes:
        raise ErrorPoblado(f"meses cerrados que no están en la config: {sobrantes}")
    return meses


def _trimestre(mes: int) -> int:
    return (mes - 1) // 3 + 1


def _fin_de_mes(anio: int, mes: int) -> date:
    primero_siguiente = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
    return primero_siguiente - timedelta(days=1)
