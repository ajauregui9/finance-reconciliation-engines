"""Candados del cierre (spec, sección 9).

Cada candado vuelve a sumar desde las filas ubicadas, filtrando por categoría y cohorte,
sin usar los agregados que produjo el cierre. Si un paso intermedio perdiera, duplicara o
mezclara filas, el recálculo no coincidiría.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Callable, Iterable, List, Sequence, Tuple

from .agregacion import GruposMes
from .alertas import Candado
from .config import CATEGORIA_CARGO_PERIODO, CATEGORIA_PUBLICIDAD, CATEGORIA_SIN_CLASIFICAR, CONCEPTOS_TARIFA
from .dinero import CERO, texto_monto
from .gasto import GastoDevengado
from .publicidad import ResultadoPublicidad
from .ubicacion import FilaUbicada


def _suma(filas: Iterable[FilaUbicada], valor: Callable[[FilaUbicada], Decimal]) -> Decimal:
    return sum((valor(u) for u in filas), CERO)


def _total(u: FilaUbicada) -> Decimal:
    return u.fila.total


def _venta_neta(u: FilaUbicada) -> Decimal:
    return u.fila.montos.venta_neta


def _comparar(nombre: str, pares: Sequence[Tuple[str, Decimal, Decimal]]) -> Candado:
    """Candado que pasa si cada par (etiqueta, recalculado, reportado) coincide."""
    fallas = [f"{etiqueta}: recalculado {texto_monto(a)} vs reportado {texto_monto(b)}"
              for etiqueta, a, b in pares if a != b]
    if fallas:
        return Candado(nombre, False, "; ".join(fallas))
    return Candado(nombre, True, f"{len(pares)} cuadres al centavo")


def _puente_liquidacion(filas: Sequence[FilaUbicada], grupos: GruposMes) -> Candado:
    por_grupos = (
        grupos.cohorte_mes.total
        + sum((a.total for a in grupos.colas.values()), CERO)
        + sum((a.total for a in grupos.cargos_periodo.values()), CERO)
        + grupos.publicidad.total
        + grupos.transferencias.total
        + sum((a.total for a in grupos.sin_clasificar.values()), CERO)
    )
    return _comparar("puente_liquidacion", [("total liquidado", _suma(filas, _total), por_grupos)])


def _puente_cohortes(filas: Sequence[FilaUbicada], grupos: GruposMes) -> Candado:
    de_pedido = [u for u in filas if u.es_de_pedido]
    colas = list(grupos.colas.values())
    return _comparar("puente_cohortes", [
        ("total de pedidos", _suma(de_pedido, _total),
         grupos.cohorte_mes.total + sum((a.total for a in colas), CERO)),
        ("venta neta", _suma(de_pedido, _venta_neta),
         grupos.cohorte_mes.venta_neta + sum((a.venta_neta for a in colas), CERO)),
    ])


def _gasto_de(filas: Iterable[FilaUbicada], concepto: str) -> Decimal:
    return -_suma(filas, lambda u: getattr(u.fila.montos, concepto))


def _publicidad_una_vez(filas: Sequence[FilaUbicada], grupos: GruposMes, gasto: GastoDevengado,
                        publicidad: ResultadoPublicidad) -> Candado:
    del_mes = [u for u in filas if u.es_de_pedido and u.cohorte == grupos.mes]
    de_cola = [u for u in filas if u.es_de_pedido and u.cohorte != grupos.mes]
    pares: List[Tuple[str, Decimal, Decimal]] = []
    for concepto in CONCEPTOS_TARIFA:
        linea = gasto.tarifas[concepto]
        pares.append((f"{concepto} cohorte del mes", _gasto_de(del_mes, concepto), linea.cohorte_mes))
        pares.append((f"{concepto} cola", _gasto_de(de_cola, concepto), linea.cola_real))
    cargos = [u for u in filas if u.categoria == CATEGORIA_CARGO_PERIODO]
    anuncios = [u for u in filas if u.categoria == CATEGORIA_PUBLICIDAD]
    pares.append(("cargos del periodo", -_suma(cargos, _total), sum(gasto.cargos_periodo.values(), CERO)))
    pares.append(("publicidad en la liquidación", -_suma(anuncios, _total), publicidad.liquidacion_con_iva))
    pares.append(("línea de publicidad", publicidad.monto, gasto.publicidad))
    return _comparar("publicidad_una_vez", pares)


def _gasto_suma_lineas(gasto: GastoDevengado) -> Candado:
    pares: List[Tuple[str, Decimal, Decimal]] = []
    for concepto in CONCEPTOS_TARIFA:
        linea = gasto.tarifas[concepto]
        pares.append((concepto, linea.cohorte_mes + linea.provision + linea.cola_real - linea.reverso, linea.total))
    suma = (sum((linea.total for linea in gasto.tarifas.values()), CERO)
            + sum(gasto.cargos_periodo.values(), CERO) + gasto.publicidad)
    pares.append(("total del gasto devengado", suma, gasto.total))
    return _comparar("gasto_suma_lineas", pares)


def _tipos_clasificados(filas: Sequence[FilaUbicada]) -> Candado:
    sueltas = [u for u in filas if u.categoria == CATEGORIA_SIN_CLASIFICAR]
    if not sueltas:
        return Candado("tipos_clasificados", True, "todas las filas tienen categoría")
    tipos = sorted({u.fila.tipo for u in sueltas})
    return Candado("tipos_clasificados", False,
                   f"{len(sueltas)} filas sin categoría en la config, tipos: {', '.join(tipos)}")


def evaluar_candados(filas: Sequence[FilaUbicada], grupos: GruposMes, gasto: GastoDevengado,
                     publicidad: ResultadoPublicidad) -> Tuple[Candado, ...]:
    """Los cinco candados del mes, en orden fijo."""
    return (
        _puente_liquidacion(filas, grupos),
        _puente_cohortes(filas, grupos),
        _publicidad_una_vez(filas, grupos, gasto, publicidad),
        _gasto_suma_lineas(gasto),
        _tipos_clasificados(filas),
    )
