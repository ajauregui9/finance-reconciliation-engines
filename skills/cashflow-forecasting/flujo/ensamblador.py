"""Ensamblador del flujo de 13 semanas.

Primero valida (presencia de fuentes, esquema de cada fila contrato y cuadre por
fuente al centavo); después arma la tabla semanal y verifica sus invariantes. Si
algo falla, lanza `ErrorInvariante` y no devuelve nada que se pueda escribir.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Dict, List, Sequence, Tuple

from .calendario import SEMANAS_HORIZONTE, Semana, semanas_del_horizonte
from .contrato import (
    CONCEPTO_SALDO,
    CONCEPTOS_ENTRADA,
    CONCEPTOS_FLUJO,
    CONCEPTOS_SALIDA,
    FUENTES,
    FUENTES_ADMITEN_CERO,
    FilaContrato,
    ResultadoFuente,
    ordenar_filas,
    validar_fila,
)
from .dinero import CERO, es_centavos
from .errores import ErrorInvariante


@dataclass(frozen=True)
class SemanaFlujo:
    numero: int
    inicio: date
    fin: date
    saldo_inicial: Decimal
    montos: Tuple[Tuple[str, Decimal], ...]
    saldo_final: Decimal

    def _suma(self, conceptos: Sequence[str]) -> Decimal:
        return sum((m for c, m in self.montos if c in conceptos), CERO)

    @property
    def entradas(self) -> Decimal:
        return self._suma(CONCEPTOS_ENTRADA)

    @property
    def salidas(self) -> Decimal:
        return self._suma(CONCEPTOS_SALIDA)

    @property
    def flujo_neto(self) -> Decimal:
        return sum((m for _, m in self.montos), CERO)


@dataclass(frozen=True)
class Flujo:
    corte: date
    moneda: str
    semanas: Tuple[SemanaFlujo, ...]
    fuentes: Tuple[ResultadoFuente, ...]

    @property
    def filas(self) -> Tuple[FilaContrato, ...]:
        return ordenar_filas([f for r in self.fuentes for f in r.filas])

    @property
    def total_entradas(self) -> Decimal:
        return sum((s.entradas for s in self.semanas), CERO)

    @property
    def total_salidas(self) -> Decimal:
        return sum((s.salidas for s in self.semanas), CERO)

    @property
    def registros_en_cero(self) -> int:
        return sum(r.registros_en_cero for r in self.fuentes)

    def filas_con_marca(self, marca: str) -> Tuple[FilaContrato, ...]:
        return tuple(f for f in self.filas if f.marca == marca)


# --- validaciones previas ---------------------------------------------------------------


def _ordenar_fuentes(resultados: Sequence[ResultadoFuente]) -> Tuple[ResultadoFuente, ...]:
    for resultado in resultados:
        if not isinstance(resultado, ResultadoFuente):
            raise ErrorInvariante(f"se esperaba ResultadoFuente y llegó {type(resultado).__name__}")
    nombres = [r.fuente for r in resultados]
    desconocidas = sorted(set(nombres) - set(FUENTES))
    if desconocidas:
        raise ErrorInvariante(f"fuente desconocida: {', '.join(desconocidas)}")
    repetidas = sorted({n for n in nombres if nombres.count(n) > 1})
    if repetidas:
        raise ErrorInvariante(f"fuente repetida: {', '.join(repetidas)}")
    faltan = [f for f in FUENTES if f not in nombres]
    if faltan:
        raise ErrorInvariante(f"faltan fuentes: {', '.join(faltan)}")
    return tuple(sorted(resultados, key=lambda r: FUENTES.index(r.fuente)))


def _validar_esquema(resultado: ResultadoFuente, semanas: Sequence[Semana]) -> None:
    vistas: Dict[Tuple[int, str], FilaContrato] = {}
    for fila in resultado.filas:
        validar_fila(fila, resultado.fuente, semanas)
        llave = (fila.semana, fila.referencia)
        if llave in vistas:
            raise ErrorInvariante(
                f"{resultado.fuente}: fila contrato repetida para '{fila.referencia}' en la semana {fila.semana}"
            )
        vistas[llave] = fila


def _validar_conteos(resultado: ResultadoFuente) -> None:
    en_cero = resultado.registros_en_cero
    valido = isinstance(en_cero, int) and not isinstance(en_cero, bool) and 0 <= en_cero <= resultado.registros
    if not valido:
        raise ErrorInvariante(
            f"{resultado.fuente}: registros_en_cero {en_cero!r} debe ser un entero entre 0 y "
            f"los {resultado.registros} registros del insumo"
        )
    if en_cero and resultado.fuente not in FUENTES_ADMITEN_CERO:
        raise ErrorInvariante(f"{resultado.fuente}: la fuente no admite registros_en_cero y reporta {en_cero}")


def _validar_cuadre(resultado: ResultadoFuente) -> None:
    partidas = (
        ("total_insumo", resultado.total_insumo),
        ("fuera_horizonte", resultado.fuera_horizonte),
        ("no_cobrable", resultado.no_cobrable),
    )
    for nombre, valor in partidas:
        if not es_centavos(valor):
            raise ErrorInvariante(f"{resultado.fuente}: {nombre} {valor!r} debe ser un Decimal con dos decimales")
    explicado = resultado.en_horizonte + resultado.fuera_horizonte + resultado.no_cobrable
    diferencia = resultado.total_insumo - explicado
    if diferencia != 0:
        raise ErrorInvariante(
            f"{resultado.fuente}: la fuente no cuadra: filas {resultado.en_horizonte} + fuera de horizonte "
            f"{resultado.fuera_horizonte} + no cobrable {resultado.no_cobrable} = {explicado}, pero el insumo "
            f"suma {resultado.total_insumo}; diferencia {diferencia}"
        )


# --- armado de la tabla -----------------------------------------------------------------


def _totales_por_semana(filas: Sequence[FilaContrato]) -> Dict[Tuple[int, str], Decimal]:
    totales: Dict[Tuple[int, str], Decimal] = {}
    for fila in filas:
        llave = (fila.semana, fila.concepto)
        totales[llave] = totales.get(llave, CERO) + fila.monto
    return totales


def _armar_semanas(filas: Sequence[FilaContrato], semanas: Sequence[Semana]) -> Tuple[SemanaFlujo, ...]:
    totales = _totales_por_semana(filas)
    saldo = sum((f.monto for f in filas if f.concepto == CONCEPTO_SALDO), CERO)
    tabla: List[SemanaFlujo] = []
    for semana in semanas:
        montos = tuple((c, totales.get((semana.numero, c), CERO)) for c in CONCEPTOS_FLUJO)
        final = saldo + sum((m for _, m in montos), CERO)
        tabla.append(SemanaFlujo(
            numero=semana.numero, inicio=semana.inicio, fin=semana.fin,
            saldo_inicial=saldo, montos=montos, saldo_final=final,
        ))
        saldo = final
    return tuple(tabla)


def ensamblar(resultados: Sequence[ResultadoFuente], corte: date, moneda: str) -> Flujo:
    semanas = semanas_del_horizonte(corte)
    ordenados = _ordenar_fuentes(resultados)
    for resultado in ordenados:
        _validar_esquema(resultado, semanas)
        _validar_conteos(resultado)
        _validar_cuadre(resultado)
    filas = [f for r in ordenados for f in r.filas]
    flujo = Flujo(corte=corte, moneda=moneda, semanas=_armar_semanas(filas, semanas), fuentes=ordenados)
    verificar_invariantes(flujo)
    return flujo


# --- invariantes de la tabla ------------------------------------------------------------


def _verificar_forma(flujo: Flujo) -> None:
    if len(flujo.semanas) != SEMANAS_HORIZONTE:
        raise ErrorInvariante(
            f"el flujo debe tener exactamente {SEMANAS_HORIZONTE} semanas y tiene {len(flujo.semanas)}"
        )
    for real, esperada in zip(flujo.semanas, semanas_del_horizonte(flujo.corte)):
        if (real.numero, real.inicio, real.fin) != (esperada.numero, esperada.inicio, esperada.fin):
            raise ErrorInvariante(f"la numeración o fechas de la semana {esperada.numero} no siguen el calendario")
        if tuple(c for c, _ in real.montos) != CONCEPTOS_FLUJO:
            raise ErrorInvariante(f"los conceptos de la semana {real.numero} no son {', '.join(CONCEPTOS_FLUJO)}")


def _verificar_saldos(flujo: Flujo) -> None:
    bancos = sum((f.monto for f in flujo.filas if f.concepto == CONCEPTO_SALDO), CERO)
    if flujo.semanas[0].saldo_inicial != bancos:
        raise ErrorInvariante(
            f"el saldo inicial de la semana 1 ({flujo.semanas[0].saldo_inicial}) no es la suma de los "
            f"saldos bancarios ({bancos})"
        )
    for indice, semana in enumerate(flujo.semanas):
        if semana.saldo_final != semana.saldo_inicial + semana.flujo_neto:
            raise ErrorInvariante(
                f"semana {semana.numero}: el saldo final {semana.saldo_final} no es el saldo inicial "
                f"{semana.saldo_inicial} más el flujo neto {semana.flujo_neto}"
            )
        previa = flujo.semanas[indice - 1]
        if indice > 0 and semana.saldo_inicial != previa.saldo_final:
            raise ErrorInvariante(
                f"semana {semana.numero}: el saldo inicial {semana.saldo_inicial} no es el saldo final "
                f"de la semana {previa.numero} ({previa.saldo_final})"
            )


def _verificar_conceptos(flujo: Flujo) -> None:
    filas = flujo.filas
    for concepto in CONCEPTOS_FLUJO:
        en_tabla = sum((m for s in flujo.semanas for c, m in s.montos if c == concepto), CERO)
        en_filas = sum((f.monto for f in filas if f.concepto == concepto), CERO)
        if en_tabla != en_filas:
            raise ErrorInvariante(
                f"el concepto {concepto} suma {en_tabla} en la tabla y {en_filas} en las filas contrato"
            )


def verificar_invariantes(flujo: Flujo) -> None:
    """13 semanas contiguas, saldos encadenados y conceptos que suman sus filas."""
    _verificar_forma(flujo)
    _verificar_saldos(flujo)
    _verificar_conceptos(flujo)
