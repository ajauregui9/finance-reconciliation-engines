"""Publicidad contada una sola vez aunque venga de varias fuentes (spec, sección 7).

Las filas de publicidad de la liquidación ya llegan separadas de las tarifas y de los
cargos del periodo (categoría propia). Aquí solo se decide qué monto entra al gasto: el de
la fuente autoritativa de la config. Las demás fuentes sirven para cuadrar.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .agregacion import Agregado
from .alertas import Alerta, alerta
from .config import FUENTE_CONSOLA, FUENTE_FACTURA, FUENTE_LIQUIDACION, Config
from .dinero import CERO, q2, texto_monto
from .errores import ErrorInsumo
from .modelo import FacturaPublicidad, GastoConsola


@dataclass(frozen=True)
class ResultadoPublicidad:
    """Montos sin IVA por fuente y la línea que entra al gasto devengado."""

    fuente_autoritativa: str
    monto: Decimal
    liquidacion_con_iva: Decimal
    liquidacion_sin_iva: Decimal
    filas_liquidacion: int
    consola: Optional[Decimal]
    filas_consola: int
    factura: Optional[FacturaPublicidad]
    diferencias: Mapping[str, Decimal]


def _factura_del_mes(mes: str, facturas: Optional[Sequence[FacturaPublicidad]]) -> Optional[FacturaPublicidad]:
    if facturas is None:
        return None
    return next((f for f in facturas if f.mes == mes), None)


def _alertas_factura(mes: str, factura: FacturaPublicidad, config: Config) -> List[Alerta]:
    iva_esperado = q2(factura.subtotal * config.tasa_iva)
    if factura.subtotal + factura.iva == factura.total and factura.iva == iva_esperado:
        return []
    return [alerta(
        "factura_iva_inconsistente", mes,
        f"La factura de publicidad {factura.folio} no cuadra: subtotal {texto_monto(factura.subtotal)}, "
        f"IVA {texto_monto(factura.iva)} (esperado {texto_monto(iva_esperado)}), total {texto_monto(factura.total)}.",
        folio=factura.folio, iva=texto_monto(factura.iva), iva_esperado=texto_monto(iva_esperado))]


def _alertas_diferencia(mes: str, fuente: str, diferencias: Mapping[str, Decimal],
                        tolerancia: Decimal) -> List[Alerta]:
    return [
        alerta("publicidad_fuentes_difieren", mes,
               f"La publicidad según {otra} difiere {texto_monto(diferencia)} de la fuente autoritativa ({fuente}).",
               fuente=otra, autoritativa=fuente, diferencia=texto_monto(diferencia),
               tolerancia=texto_monto(tolerancia))
        for otra, diferencia in diferencias.items()
        if abs(diferencia) > tolerancia
    ]


def resolver_publicidad(mes: str, en_liquidacion: Agregado, consola: Optional[Sequence[GastoConsola]],
                        facturas: Optional[Sequence[FacturaPublicidad]],
                        config: Config) -> Tuple[ResultadoPublicidad, Tuple[Alerta, ...]]:
    """Elige el monto de la fuente autoritativa y compara las demás contra él.

    Raises:
        ErrorInsumo: si la fuente autoritativa no está disponible para el mes.
    """
    con_iva = -en_liquidacion.total
    sin_iva = q2(con_iva / (1 + config.tasa_iva))
    consola_mes = None if consola is None else [g for g in consola if g.mes == mes]
    monto_consola = None if consola_mes is None else sum((g.gasto for g in consola_mes), CERO)
    factura = _factura_del_mes(mes, facturas)
    por_fuente: Dict[str, Optional[Decimal]] = {
        FUENTE_LIQUIDACION: sin_iva,
        FUENTE_CONSOLA: monto_consola,
        FUENTE_FACTURA: None if factura is None else factura.subtotal,
    }
    fuente = config.fuente_publicidad
    autoritativo = por_fuente[fuente]
    if autoritativo is None:
        raise ErrorInsumo(
            f"{mes}: la fuente autoritativa de publicidad '{fuente}' no está disponible; "
            "agrega el archivo o elige otra fuente en la config")
    diferencias = MappingProxyType({
        otra: monto - autoritativo
        for otra, monto in sorted(por_fuente.items())
        if monto is not None and otra != fuente
    })
    alertas = _alertas_diferencia(mes, fuente, diferencias, config.tolerancia_publicidad)
    if factura is not None:
        alertas.extend(_alertas_factura(mes, factura, config))
    resultado = ResultadoPublicidad(
        fuente_autoritativa=fuente, monto=autoritativo, liquidacion_con_iva=con_iva, liquidacion_sin_iva=sin_iva,
        filas_liquidacion=en_liquidacion.filas, consola=monto_consola,
        filas_consola=0 if consola_mes is None else len(consola_mes), factura=factura, diferencias=diferencias)
    return resultado, tuple(alertas)
