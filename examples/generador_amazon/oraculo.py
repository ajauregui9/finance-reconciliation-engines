"""Respuesta esperada por mes contable, calculada desde el modelo de eventos del generador."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Sequence

from .filas import Fila
from .montos import CERO, q2, texto
from .parametros import ParametrosGenerador
from .pedidos import Venta
from .tiempo import FORMATO, huso, mes_de

TARIFAS = ("comision", "logistica", "otras_tarifas")


def _suma(filas: Sequence[Fila], columna: str) -> Decimal:
    return sum((f.monto(columna) for f in filas), CERO)


def _venta_neta(filas: Sequence[Fila]) -> Decimal:
    return _suma(filas, "venta_productos") + _suma(filas, "descuento_promocional")


def _gasto(filas: Sequence[Fila]) -> Dict[str, str]:
    return {c: texto(-_suma(filas, c)) for c in TARIFAS}


def _mes(mes: str, filas: Sequence[Fila], consola: Decimal, p: ParametrosGenerador,
         cierre: timezone) -> Dict[str, Any]:
    de_pedido = [f for f in filas if f.es_de_pedido]
    cohorte = [f for f in de_pedido if _cohorte(f, cierre) == mes]
    cola = [f for f in de_pedido if _cohorte(f, cierre) != mes]
    origenes = sorted({_cohorte(f, cierre) for f in cola})
    anuncios = [f for f in filas if f.tipo == "Publicidad"]
    con_iva = -sum((f.total for f in anuncios), CERO)
    cargos = sorted({f.tipo for f in filas if f.tipo in ("Almacenaje", "Suscripción", "Ajuste")})
    return {
        "filas": len(filas),
        "total_liquidado": texto(sum((f.total for f in filas), CERO)),
        "venta_neta_cohorte_mes": texto(_venta_neta(cohorte)),
        "venta_neta_cola": {o: texto(_venta_neta([f for f in cola if _cohorte(f, cierre) == o])) for o in origenes},
        "tarifas_cohorte_mes": _gasto(cohorte),
        "tarifas_cola": _gasto(cola),
        "cargos_periodo": {t: texto(-sum((f.total for f in filas if f.tipo == t), CERO)) for t in cargos},
        "publicidad_sin_iva": {"consola": texto(consola), "factura": texto(consola),
                               "liquidacion": texto(q2(con_iva / (1 + p.tasa_iva)))},
        "filas_publicidad_liquidacion": len(anuncios),
        "retencion": {"base": texto(_venta_neta(de_pedido)), "retenida": texto(-_suma(de_pedido, "retencion"))},
    }


def _cohorte(fila: Fila, cierre: timezone) -> str:
    if fila.pedido_en is None:
        raise ValueError(f"la fila {fila.tipo} {fila.pedido!r} no tiene fecha de pedido")
    return mes_de(fila.pedido_en, cierre)


def _caso(fila: Fila, indice: int, numero: int, p: ParametrosGenerador, cierre: timezone) -> Dict[str, Any]:
    caso = p.casos_borde[indice]
    pedido_en = fila.pedido_en
    if pedido_en is None:
        raise ValueError(f"el caso borde {fila.pedido} no tiene fecha de pedido")
    zona = huso(p.huso_de[fila.periodo])
    ingenuo = (datetime.strptime(caso.fecha_hora_local, FORMATO) + timedelta(hours=1)).strftime("%Y-%m")
    return {
        "archivo": f"liquidacion_{fila.periodo}.csv", "fila": numero, "pedido": fila.pedido,
        "huso": p.huso_de[fila.periodo], "fecha_hora_local": fila.instante.astimezone(zona).strftime(FORMATO),
        "fecha_pedido_local": pedido_en.astimezone(zona).strftime(FORMATO),
        "mes_liquidacion": mes_de(fila.instante, cierre), "mes_pedido": mes_de(pedido_en, cierre),
        "esperado": {"mes_liquidacion": caso.mes_liquidacion, "mes_pedido": caso.mes_pedido},
        "desfase_fijo_de_una_hora_falla": ingenuo != mes_de(fila.instante, cierre), "nota": caso.nota,
    }


def _verificar(oraculo: Mapping[str, Any], p: ParametrosGenerador) -> None:
    """El generador se detiene si los escenarios diseñados no quedaron como se pidió."""
    problemas: List[str] = []
    if oraculo["meses_retencion_fuera_de_banda"] != [p.mes_retencion_anomala]:
        problemas.append(f"retención fuera de banda en {oraculo['meses_retencion_fuera_de_banda']}")
    if oraculo["meses_cola_negativa"] != [p.mes_cola_negativa]:
        problemas.append(f"cola negativa en {oraculo['meses_cola_negativa']}")
    if oraculo["filas_fuera_de_meses"]:
        problemas.append(f"filas fuera de los meses: {oraculo['filas_fuera_de_meses']}")
    for caso in oraculo["casos_borde"]:
        obtenido = {"mes_liquidacion": caso["mes_liquidacion"], "mes_pedido": caso["mes_pedido"]}
        if obtenido != caso["esperado"]:
            problemas.append(f"caso borde {caso['pedido']} quedó en {obtenido}, se diseñó {caso['esperado']}")
    if len(oraculo["casos_borde"]) != len(p.casos_borde):
        problemas.append("no todos los casos borde llegaron a un archivo")
    if problemas:
        raise RuntimeError("autoverificación del generador: " + "; ".join(problemas))


def armar_oraculo(filas_por_archivo: Mapping[str, Sequence[Fila]], ventas: Sequence[Venta],
                  consola: Mapping[str, Decimal], venta_erp: Mapping[str, Decimal],
                  p: ParametrosGenerador) -> Dict[str, Any]:
    cierre = huso(p.huso_cierre)
    todas = [f for periodo in sorted(filas_por_archivo) for f in filas_por_archivo[periodo]]
    meses = {mes: _mes(mes, [f for f in todas if mes_de(f.instante, cierre) == mes], consola[mes], p, cierre)
             for mes in p.meses}
    casos = [_caso(f, f.caso_borde, numero, p, cierre) for periodo in sorted(filas_por_archivo)
             for numero, f in enumerate(filas_por_archivo[periodo], start=1) if f.caso_borde is not None]
    fuera = sorted({mes_de(f.instante, cierre) for f in todas} - set(p.meses))
    fuera_de_banda = []
    for mes, datos in meses.items():
        base, retenida = Decimal(datos["retencion"]["base"]), Decimal(datos["retencion"]["retenida"])
        if base != 0 and abs(retenida / base - p.tasa_retencion) > p.banda_retencion:
            fuera_de_banda.append(mes)
    oraculo: Dict[str, Any] = {
        "esquema": "oraculo_cierre_amazon/v1",
        "parametros": {
            "semilla": p.semilla, "pedidos_por_mes": p.pedidos_por_mes, "meses": list(p.meses),
            "husos_archivo": dict(p.husos), "huso_cierre": p.huso_cierre, "tasa_iva": str(p.tasa_iva),
            "tasa_retencion": str(p.tasa_retencion), "banda_retencion": str(p.banda_retencion),
            "tasa_retencion_anomala": str(p.tasa_retencion_anomala),
        },
        "meses": meses,
        "venta_erp": {m: texto(v) for m, v in venta_erp.items()},
        "ventas_pendientes": len([v for v in ventas if v.liquidada_en is None]),
        "casos_borde": sorted(casos, key=lambda c: c["pedido"]),
        "filas_fuera_de_meses": fuera,
        "meses_retencion_fuera_de_banda": fuera_de_banda,
        "meses_cola_negativa": [m for m, d in meses.items()
                                if d["venta_neta_cola"] and sum(Decimal(v) for v in d["venta_neta_cola"].values()) < 0],
    }
    _verificar(oraculo, p)
    return oraculo
