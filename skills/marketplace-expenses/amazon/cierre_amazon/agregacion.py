"""Agregados por grupo de filas dentro de un mes contable (spec, sección 5)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Callable, Dict, Iterable, List, Mapping, Sequence

from .config import (
    CATEGORIA_CARGO_PERIODO,
    CATEGORIA_PUBLICIDAD,
    CATEGORIA_SIN_CLASIFICAR,
    CATEGORIA_TRANSFERENCIA,
    CATEGORIA_VENTA,
)
from .dinero import CERO
from .modelo import Montos
from .ubicacion import FilaUbicada


@dataclass(frozen=True)
class Agregado:
    """Sumas de un grupo de filas, con el signo de la liquidación."""

    filas: int
    pedidos: int
    montos: Montos
    total: Decimal

    @property
    def venta_neta(self) -> Decimal:
        return self.montos.venta_neta


VACIO = Agregado(filas=0, pedidos=0, montos=Montos(), total=CERO)


def agregar(filas: Iterable[FilaUbicada]) -> Agregado:
    """Suma montos y totales; cuenta filas y pedidos distintos de las filas de venta."""
    lista = list(filas)
    montos = Montos()
    for ubicada in lista:
        montos = montos.mas(ubicada.fila.montos)
    pedidos = {u.fila.pedido for u in lista if u.categoria == CATEGORIA_VENTA}
    return Agregado(filas=len(lista), pedidos=len(pedidos), montos=montos,
                    total=sum((u.fila.total for u in lista), CERO))


def _por_llave(filas: Sequence[FilaUbicada], llave: Callable[[FilaUbicada], str]) -> Mapping[str, Agregado]:
    grupos: Dict[str, List[FilaUbicada]] = {}
    for ubicada in filas:
        grupos.setdefault(llave(ubicada), []).append(ubicada)
    return MappingProxyType({clave: agregar(grupos[clave]) for clave in sorted(grupos)})


def _cohorte(ubicada: FilaUbicada) -> str:
    return ubicada.cohorte or ""


def _tipo(ubicada: FilaUbicada) -> str:
    return ubicada.fila.tipo


@dataclass(frozen=True)
class GruposMes:
    """Las filas liquidadas en un mes contable, repartidas por grupo."""

    mes: str
    todas: Agregado
    pedidos: Agregado
    cohorte_mes: Agregado
    cola: Agregado
    colas: Mapping[str, Agregado]
    cargos_periodo: Mapping[str, Agregado]
    publicidad: Agregado
    transferencias: Agregado
    sin_clasificar: Mapping[str, Agregado]


def agrupar_mes(mes: str, filas: Sequence[FilaUbicada]) -> GruposMes:
    """Reparte las filas de un mes. Las filas deben ser todas de ese mes."""
    ajenas = [u for u in filas if u.mes != mes]
    if ajenas:
        raise ValueError(f"agrupar_mes({mes}) recibió {len(ajenas)} filas de otro mes")
    de_pedido = [u for u in filas if u.es_de_pedido]
    del_mes = [u for u in de_pedido if u.cohorte == mes]
    de_cola = [u for u in de_pedido if u.cohorte != mes]

    def categoria(nombre: str) -> List[FilaUbicada]:
        return [u for u in filas if u.categoria == nombre]

    return GruposMes(
        mes=mes,
        todas=agregar(filas),
        pedidos=agregar(de_pedido),
        cohorte_mes=agregar(del_mes),
        cola=agregar(de_cola),
        colas=_por_llave(de_cola, _cohorte),
        cargos_periodo=_por_llave(categoria(CATEGORIA_CARGO_PERIODO), _tipo),
        publicidad=agregar(categoria(CATEGORIA_PUBLICIDAD)),
        transferencias=agregar(categoria(CATEGORIA_TRANSFERENCIA)),
        sin_clasificar=_por_llave(categoria(CATEGORIA_SIN_CLASIFICAR), _tipo),
    )
