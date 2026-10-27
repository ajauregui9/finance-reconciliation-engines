"""Ubica cada fila en su mes contable, su categoría y su cohorte (spec, secciones 4 y 5)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from .config import CATEGORIAS_DE_PEDIDO, Config
from .errores import ErrorInsumo
from .huso import mes_en_huso
from .modelo import ArchivoLiquidacion, FilaLiquidacion


@dataclass(frozen=True)
class FilaUbicada:
    """Una fila con el mes contable de su liquidación y, si es de pedido, su cohorte."""

    fila: FilaLiquidacion
    mes: str
    categoria: str
    cohorte: Optional[str]

    @property
    def es_de_pedido(self) -> bool:
        return self.categoria in CATEGORIAS_DE_PEDIDO


def _ubicar_fila(fila: FilaLiquidacion, config: Config) -> FilaUbicada:
    categoria = config.categoria(fila.tipo)
    cohorte = None
    if categoria in CATEGORIAS_DE_PEDIDO:
        lugar = f"{fila.archivo}, fila {fila.numero} (tipo '{fila.tipo}')"
        if not fila.pedido:
            raise ErrorInsumo(f"{lugar}: una fila de pedido necesita 'Pedido'")
        if fila.instante_pedido is None:
            raise ErrorInsumo(f"{lugar}: una fila de pedido necesita 'Fecha del pedido'")
        cohorte = mes_en_huso(fila.instante_pedido, config.huso_cierre)
    return FilaUbicada(fila=fila, mes=mes_en_huso(fila.instante, config.huso_cierre),
                       categoria=categoria, cohorte=cohorte)


def ubicar(archivos: Iterable[ArchivoLiquidacion], config: Config) -> Tuple[FilaUbicada, ...]:
    """Todas las filas de todos los archivos, en el orden en que se leyeron."""
    return tuple(_ubicar_fila(fila, config) for archivo in archivos for fila in archivo.filas)
