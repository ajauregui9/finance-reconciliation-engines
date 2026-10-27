"""Salida JSON determinista (spec, sección 11): llaves ordenadas, montos como texto."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .agregacion import Agregado
from .alertas import Alerta
from .cierre import CierreMes, ResultadoCorrida
from .config import CONCEPTOS_TARIFA, Config
from .dinero import texto_monto, texto_tasa
from .modelo import COLUMNAS_MONTO
from .tarifas import Tarifas

ESQUEMA_SALIDA = "cierre_amazon/v1"


def _monto(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else texto_monto(valor)


def _agregado(agregado: Agregado) -> Dict[str, Any]:
    return {
        "filas": agregado.filas,
        "pedidos": agregado.pedidos,
        "venta_neta": texto_monto(agregado.venta_neta),
        "total": texto_monto(agregado.total),
        "montos": {c: texto_monto(getattr(agregado.montos, c)) for c in COLUMNAS_MONTO},
    }


def _agregados(grupos: Mapping[str, Agregado]) -> Dict[str, Any]:
    return {clave: _agregado(valor) for clave, valor in grupos.items()}


def _tarifas(tarifas: Optional[Tarifas]) -> Optional[Dict[str, str]]:
    if tarifas is None:
        return None
    return {c: texto_monto(tarifas.concepto(c)) for c in CONCEPTOS_TARIFA}


def _alerta(a: Alerta) -> Dict[str, Any]:
    return {"codigo": a.codigo, "mes": a.mes, "mensaje": a.mensaje, "datos": dict(a.datos)}


def _parametros(config: Config) -> Dict[str, Any]:
    return {
        "moneda": config.moneda,
        "huso_cierre": config.huso_cierre_texto,
        "tasa_iva": texto_tasa(config.tasa_iva),
        "fuente_publicidad": config.fuente_publicidad,
        "tolerancia_publicidad": texto_monto(config.tolerancia_publicidad),
        "retencion": {"tasa": texto_tasa(config.tasa_retencion), "banda": texto_tasa(config.banda_retencion)},
        "referencias_tarifas": {c: {"min": texto_tasa(r.minimo), "max": texto_tasa(r.maximo)}
                                for c, r in config.referencias.items()},
        "tipos": dict(config.tipos),
    }


def _liquidado(cierre: CierreMes) -> Dict[str, Any]:
    g = cierre.grupos
    return {
        "filas": g.todas.filas, "total": texto_monto(g.todas.total), "pedidos": _agregado(g.pedidos),
        "cohorte_mes": _agregado(g.cohorte_mes), "colas": _agregados(g.colas),
        "cargos_periodo": _agregados(g.cargos_periodo), "publicidad": _agregado(g.publicidad),
        "transferencias": _agregado(g.transferencias), "sin_clasificar": _agregados(g.sin_clasificar),
    }


def _devengo(cierre: CierreMes) -> Dict[str, Any]:
    tasas = None if cierre.tasas is None else {c: texto_tasa(t) for c, t in cierre.tasas.items()}
    return {
        "tasas_efectivas": tasas,
        "venta_neta_cohorte_mes": texto_monto(cierre.grupos.cohorte_mes.venta_neta),
        "venta_erp": _monto(cierre.venta_erp),
        "venta_pendiente": _monto(cierre.venta_pendiente),
        "provision": _tarifas(cierre.provision),
        "provision_anterior": _tarifas(cierre.provision_anterior),
    }


def _gasto(cierre: CierreMes) -> Dict[str, Any]:
    gasto = cierre.gasto
    lineas = {
        c: {"cohorte_mes": texto_monto(linea.cohorte_mes), "provision": texto_monto(linea.provision),
            "cola_real": texto_monto(linea.cola_real), "reverso": texto_monto(linea.reverso),
            "total": texto_monto(linea.total)}
        for c, linea in gasto.tarifas.items()
    }
    return {"tarifas": lineas, "cargos_periodo": {t: texto_monto(m) for t, m in gasto.cargos_periodo.items()},
            "publicidad": texto_monto(gasto.publicidad), "total": texto_monto(gasto.total)}


def _publicidad(cierre: CierreMes) -> Dict[str, Any]:
    p = cierre.publicidad
    factura = None if p.factura is None else {
        "folio": p.factura.folio, "subtotal": texto_monto(p.factura.subtotal), "iva": texto_monto(p.factura.iva),
        "total": texto_monto(p.factura.total)}
    return {
        "fuente_autoritativa": p.fuente_autoritativa,
        "monto": texto_monto(p.monto),
        "liquidacion": {"con_iva": texto_monto(p.liquidacion_con_iva), "sin_iva": texto_monto(p.liquidacion_sin_iva),
                        "filas": p.filas_liquidacion},
        "consola": None if p.consola is None else {"sin_iva": texto_monto(p.consola), "filas": p.filas_consola},
        "factura": factura,
        "diferencias": {f: texto_monto(d) for f, d in p.diferencias.items()},
    }


def _retencion(cierre: CierreMes) -> Dict[str, Any]:
    r = cierre.retencion
    return {
        "base": texto_monto(r.base), "retenida": texto_monto(r.retenida), "esperada": texto_monto(r.esperada),
        "diferencia": texto_monto(r.diferencia), "tasa": texto_tasa(r.tasa), "banda": texto_tasa(r.banda),
        "tasa_observada": None if r.tasa_observada is None else texto_tasa(r.tasa_observada),
        "dentro_de_banda": r.dentro_de_banda,
    }


def _mes(cierre: CierreMes) -> Dict[str, Any]:
    return {
        "mes": cierre.mes, "ok": cierre.ok, "liquidado": _liquidado(cierre), "devengo": _devengo(cierre),
        "gasto_devengado": _gasto(cierre), "publicidad": _publicidad(cierre), "retencion": _retencion(cierre),
        "alertas": [_alerta(a) for a in cierre.alertas],
        "candados": [{"nombre": c.nombre, "ok": c.ok, "detalle": c.detalle} for c in cierre.candados],
    }


def seleccionar_meses(resultado: ResultadoCorrida, meses: Optional[Sequence[str]]) -> List[CierreMes]:
    """Los cierres pedidos, en orden; un mes que no se cerró es un `ValueError`."""
    if not meses:
        return list(resultado.meses)
    cerrados = {c.mes for c in resultado.meses}
    faltantes = sorted(set(meses) - cerrados)
    if faltantes:
        raise ValueError(f"meses no cerrados en esta corrida: {', '.join(faltantes)}; disponibles: "
                         f"{', '.join(sorted(cerrados))}")
    return [c for c in resultado.meses if c.mes in set(meses)]


def a_dict(resultado: ResultadoCorrida, meses: Optional[Sequence[str]] = None) -> Dict[str, Any]:
    """Documento completo; `meses` filtra solo la lista de meses."""
    return {
        "esquema": ESQUEMA_SALIDA,
        "ok": resultado.ok,
        "parametros": _parametros(resultado.config),
        "archivos": [{"archivo": a.nombre, "periodo": a.periodo, "huso": a.huso_texto, "filas": len(a.filas),
                      "total": texto_monto(a.total)} for a in resultado.archivos],
        "filas_fuera_de_meses": _agregados(resultado.fuera_de_meses),
        "alertas": [_alerta(a) for a in resultado.alertas],
        "meses": [_mes(c) for c in seleccionar_meses(resultado, meses)],
    }


def a_json(resultado: ResultadoCorrida, meses: Optional[Sequence[str]] = None) -> str:
    """Texto JSON canónico: UTF-8, llaves ordenadas, sangría de 2 y salto de línea final."""
    return json.dumps(a_dict(resultado, meses), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
