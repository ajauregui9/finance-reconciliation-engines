"""Orquesta el cierre de todos los meses declarados, en orden (spec, secciones 4 a 10)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .agregacion import Agregado, GruposMes, agregar, agrupar_mes
from .alertas import Alerta, Candado, alerta
from .config import Config
from .dinero import texto_monto
from .gasto import GastoDevengado, armar_gasto
from .huso import mes_anterior
from .modelo import ArchivoLiquidacion, Insumos
from .publicidad import ResultadoPublicidad, resolver_publicidad
from .retencion import ResultadoRetencion, evaluar_retencion
from .tarifas import Tarifas, alertas_referencia, provision, tasas_efectivas
from .ubicacion import FilaUbicada, ubicar
from .validacion import evaluar_candados


@dataclass(frozen=True)
class CierreMes:
    """Resultado completo de un mes contable."""

    mes: str
    grupos: GruposMes
    tasas: Optional[Mapping[str, Decimal]]
    venta_erp: Optional[Decimal]
    venta_pendiente: Optional[Decimal]
    provision: Optional[Tarifas]
    provision_anterior: Optional[Tarifas]
    gasto: GastoDevengado
    publicidad: ResultadoPublicidad
    retencion: ResultadoRetencion
    alertas: Tuple[Alerta, ...]
    candados: Tuple[Candado, ...]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.candados)


@dataclass(frozen=True)
class ResultadoCorrida:
    """Todos los meses cerrados más lo que quedó fuera de ellos."""

    config: Config
    archivos: Tuple[ArchivoLiquidacion, ...]
    meses: Tuple[CierreMes, ...]
    fuera_de_meses: Mapping[str, Agregado]
    alertas: Tuple[Alerta, ...]

    @property
    def ok(self) -> bool:
        return all(c.ok for c in self.meses)


@dataclass(frozen=True)
class _Devengo:
    """Paso intermedio: tasas, venta pendiente y provisiones de un mes."""

    tasas: Optional[Mapping[str, Decimal]]
    venta_erp: Optional[Decimal]
    venta_pendiente: Optional[Decimal]
    provision: Optional[Tarifas]
    provision_anterior: Optional[Tarifas]
    alertas: Tuple[Alerta, ...]


def _devengo(grupos: GruposMes, insumos: Insumos, previo: Optional[CierreMes], config: Config) -> _Devengo:
    mes = grupos.mes
    alertas: List[Alerta] = []
    tasas = tasas_efectivas(grupos.cohorte_mes)
    if tasas is None:
        alertas.append(alerta("sin_tasa_efectiva", mes,
                              "La cohorte del mes no tiene venta neta: no hay tasa efectiva ni provisión."))
    else:
        alertas.extend(alertas_referencia(mes, tasas, config.referencias))
    venta_erp = None if insumos.venta_erp is None else insumos.venta_erp.get(mes)
    if venta_erp is None:
        alertas.append(alerta("sin_venta_erp", mes, "No hay venta del ERP para el mes: no se calcula provisión."))
    pendiente = None if venta_erp is None else venta_erp - grupos.cohorte_mes.venta_neta
    nueva = None if pendiente is None else provision(pendiente, grupos.cohorte_mes)
    anterior = None if previo is None else previo.provision
    if grupos.cola.filas and anterior is None:
        alertas.append(alerta(
            "cola_sin_provision_previa", mes,
            f"La cola ({grupos.cola.filas} filas, venta neta {texto_monto(grupos.cola.venta_neta)}) se reconoce "
            "completa porque el mes anterior no tiene provisión en esta corrida.",
            filas=str(grupos.cola.filas), venta_neta=texto_monto(grupos.cola.venta_neta)))
    return _Devengo(tasas=tasas, venta_erp=venta_erp, venta_pendiente=pendiente, provision=nueva,
                    provision_anterior=anterior, alertas=tuple(alertas))


def _cerrar_mes(mes: str, filas: Sequence[FilaUbicada], previo: Optional[CierreMes], insumos: Insumos,
                config: Config) -> CierreMes:
    grupos = agrupar_mes(mes, filas)
    devengo = _devengo(grupos, insumos, previo, config)
    publicidad, alertas_publicidad = resolver_publicidad(mes, grupos.publicidad, insumos.consola, insumos.facturas,
                                                         config)
    retencion, alertas_retencion = evaluar_retencion(mes, grupos.pedidos, config)
    gasto = armar_gasto(grupos, devengo.provision, devengo.provision_anterior, publicidad.monto)
    return CierreMes(
        mes=mes, grupos=grupos, tasas=devengo.tasas, venta_erp=devengo.venta_erp,
        venta_pendiente=devengo.venta_pendiente, provision=devengo.provision,
        provision_anterior=devengo.provision_anterior, gasto=gasto, publicidad=publicidad, retencion=retencion,
        alertas=devengo.alertas + alertas_publicidad + alertas_retencion,
        candados=evaluar_candados(filas, grupos, gasto, publicidad),
    )


def _fuera_de_meses(por_mes: Mapping[str, Sequence[FilaUbicada]],
                    meses: Sequence[str]) -> Tuple[Mapping[str, Agregado], Tuple[Alerta, ...]]:
    fuera = {mes: agregar(filas) for mes, filas in sorted(por_mes.items()) if mes not in meses}
    alertas = tuple(
        alerta("filas_fuera_de_meses", mes,
               f"{agregado.filas} filas caen en {mes} con el corte del huso de cierre y ese mes no se cierra "
               f"en esta corrida (total {texto_monto(agregado.total)}).",
               filas=str(agregado.filas), total=texto_monto(agregado.total))
        for mes, agregado in fuera.items())
    return MappingProxyType(fuera), alertas


def cerrar(insumos: Insumos, config: Config) -> ResultadoCorrida:
    """Cierra todos los periodos declarados, en orden, para encadenar provisiones."""
    meses = sorted({archivo.periodo for archivo in insumos.archivos})
    por_mes: Dict[str, List[FilaUbicada]] = {}
    for ubicada in ubicar(insumos.archivos, config):
        por_mes.setdefault(ubicada.mes, []).append(ubicada)
    cierres: List[CierreMes] = []
    for mes in meses:
        anterior = cierres[-1] if cierres and cierres[-1].mes == mes_anterior(mes) else None
        cierres.append(_cerrar_mes(mes, por_mes.get(mes, []), anterior, insumos, config))
    fuera, alertas = _fuera_de_meses(por_mes, meses)
    return ResultadoCorrida(config=config, archivos=insumos.archivos, meses=tuple(cierres),
                            fuera_de_meses=fuera, alertas=alertas)
