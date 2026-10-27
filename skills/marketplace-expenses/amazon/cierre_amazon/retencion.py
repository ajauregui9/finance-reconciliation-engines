"""Retención de plataforma contra la tasa y la banda de la config (spec, sección 8).

Base de cálculo, la misma que documentan la spec y el README:
  filas     todas las filas de pedido (venta y reembolso) liquidadas en el mes contable,
            de cualquier cohorte;
  base      suma de (venta de productos + descuento promocional) de esas filas, sin IVA;
  retenida  menos la suma de la retención de plataforma de esas mismas filas;
  esperada  q2(base * tasa);
  observada retenida / base, dentro de banda si |observada - tasa| <= banda.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional, Tuple

from .agregacion import Agregado
from .alertas import Alerta, alerta
from .config import Config
from .dinero import q2, texto_monto, texto_tasa


@dataclass(frozen=True)
class ResultadoRetencion:
    base: Decimal
    retenida: Decimal
    esperada: Decimal
    diferencia: Decimal
    tasa: Decimal
    banda: Decimal
    tasa_observada: Optional[Decimal]
    dentro_de_banda: Optional[bool]


def _alerta_fuera(mes: str, r: ResultadoRetencion, observada: Decimal) -> Alerta:
    return alerta(
        "retencion_fuera_de_banda", mes,
        f"La retención de plataforma es {texto_tasa(observada)} de la base y se esperaba "
        f"{texto_tasa(r.tasa)} ± {texto_tasa(r.banda)}; diferencia {texto_monto(r.diferencia)}.",
        base=texto_monto(r.base), retenida=texto_monto(r.retenida), esperada=texto_monto(r.esperada),
        diferencia=texto_monto(r.diferencia), tasa_observada=texto_tasa(observada),
        tasa=texto_tasa(r.tasa), banda=texto_tasa(r.banda))


def evaluar_retencion(mes: str, pedidos_liquidados: Agregado,
                      config: Config) -> Tuple[ResultadoRetencion, Tuple[Alerta, ...]]:
    """Compara la retención del mes contra la config; recibe el agregado de filas de pedido."""
    base = pedidos_liquidados.montos.venta_neta
    retenida = -pedidos_liquidados.montos.retencion
    esperada = q2(base * config.tasa_retencion)
    observada = None if base == 0 else retenida / base
    dentro = None if observada is None else abs(observada - config.tasa_retencion) <= config.banda_retencion
    resultado = ResultadoRetencion(
        base=base, retenida=retenida, esperada=esperada, diferencia=retenida - esperada,
        tasa=config.tasa_retencion, banda=config.banda_retencion,
        tasa_observada=observada, dentro_de_banda=dentro)
    if observada is not None and dentro is False:
        return resultado, (_alerta_fuera(mes, resultado, observada),)
    if observada is None and retenida != 0:
        aviso = alerta("retencion_sin_base", mes,
                       f"Hay retención de plataforma ({texto_monto(retenida)}) pero la base del mes es cero.",
                       retenida=texto_monto(retenida))
        return resultado, (aviso,)
    return resultado, ()
