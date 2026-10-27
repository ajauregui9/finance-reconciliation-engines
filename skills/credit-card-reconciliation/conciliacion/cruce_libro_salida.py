"""Candados, resumen y serialización determinista del cruce con libro mayor.

La salida no lleva marcas de tiempo ni rutas: dos corridas con los mismos insumos dan
los mismos bytes. Los importes viajan como texto con dos decimales.
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from fractions import Fraction
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

from .cruce_libro_config import config_a_dict
from .cruce_libro_modelo import (
    CERO,
    ESQUEMA_SALIDA,
    VEREDICTO_REGISTRADO,
    Candidato,
    Cargo,
    ConfigCruceLibro,
    Cruce,
    EvaluacionCargo,
    LineaLibro,
    Veredicto,
)
from .cruce_libro_veredictos import Conciliacion, ResultadoFinal
from .nombres import a_decimal4

Objeto = Dict[str, object]


def _monto(valor: Decimal) -> str:
    return f"{valor:.2f}"


def _similitud(valor: Optional[Fraction]) -> Optional[str]:
    return None if valor is None else str(a_decimal4(valor))


# ----------------------------------------------------------------- por cargo
def _propuesta(cruce: Cruce) -> Objeto:
    c = cruce.candidato
    return {"asiento_id": cruce.asiento_id, "linea": c.linea.linea if c else None,
            "evidencia": c.evidencia if c else None, "riesgo_cubeta": cruce.riesgo_cubeta,
            "similitud": _similitud(c.similitud) if c else None, "delta_dias": c.delta_dias if c else None,
            "diferencia_monto": _monto(c.diferencia) if c else None, "motivo_sin_cruce": cruce.motivo}


def _candidato(c: Candidato, cargo: Cargo, ocupante: Optional[str]) -> Objeto:
    importe = c.linea.haber if cargo.monto > 0 else c.linea.debe
    return {"asiento_id": c.linea.asiento_id, "linea": c.linea.linea, "fecha": c.linea.fecha.isoformat(),
            "delta_dias": c.delta_dias, "proveedor_id": c.linea.proveedor_id,
            "proveedor_nombre": c.linea.proveedor_nombre, "importe": _monto(importe),
            "diferencia_monto": _monto(c.diferencia), "es_cubeta": c.es_cubeta,
            "similitud": _similitud(c.similitud), "evaluacion": c.evaluacion,
            "ocupado_por": ocupante if ocupante != cargo.cargo_id else None}


def _final(f: ResultadoFinal) -> Objeto:
    return {"asiento_id": f.asiento_id, "origen": f.origen, "riesgo_cubeta": f.riesgo_cubeta,
            "motivo_sin_cruce": f.motivo, "reasignado_por_veredicto": f.reasignado}


def _veredicto(v: Optional[Veredicto]) -> Optional[Objeto]:
    return None if v is None else {"veredicto": v.veredicto, "asiento_id": v.asiento_id, "nota": v.nota}


def _cargo(ev: EvaluacionCargo, conc: Conciliacion, ocupantes: Mapping[str, str], maximo: int) -> Objeto:
    cargo = ev.cargo
    muestra = [_candidato(c, cargo, ocupantes.get(c.linea.asiento_id)) for c in ev.candidatos[:maximo]]
    return {
        "cargo_id": cargo.cargo_id, "emisor": cargo.emisor, "estado": cargo.estado,
        "fecha": cargo.fecha.isoformat() if cargo.fecha else None, "descripcion": cargo.descripcion,
        "monto": _monto(cargo.monto), "tipo_movimiento": cargo.tipo_movimiento,
        "propuesta": _propuesta(conc.propuesta[cargo.cargo_id]),
        "veredicto": _veredicto(conc.veredictos.get(cargo.cargo_id)),
        "conflicto": conc.conflictos.get(cargo.cargo_id),
        "final": _final(conc.final[cargo.cargo_id]),
        "candidatos": {**ev.conteos(), "muestra": muestra},
    }


def _conflictos(conc: Conciliacion) -> List[Objeto]:
    salida: List[Objeto] = []
    for cargo_id, tipo in sorted(conc.conflictos.items()):
        propuesta = conc.propuesta[cargo_id]
        salida.append({"cargo_id": cargo_id, "tipo": tipo, "veredicto": _veredicto(conc.veredictos[cargo_id]),
                       "propuesta": {"asiento_id": propuesta.asiento_id, "motivo_sin_cruce": propuesta.motivo,
                                     "riesgo_cubeta": propuesta.riesgo_cubeta}})
    return salida


# ------------------------------------------------------------------- candados
def _usos_finales(final: Mapping[str, ResultadoFinal]) -> Dict[str, List[str]]:
    usos: Dict[str, List[str]] = {}
    for cargo_id in sorted(final):
        asiento = final[cargo_id].asiento_id
        if asiento is not None:
            usos.setdefault(asiento, []).append(cargo_id)
    return usos


def _candado_exclusividad(final: Mapping[str, ResultadoFinal]) -> Objeto:
    repetidos = {a: cs for a, cs in sorted(_usos_finales(final).items()) if len(cs) > 1}
    return {"ok": not repetidos, "detalle": {"asientos_con_varios_cargos": repetidos}}


def _sumas_por_estado(cargos: Sequence[Cargo], final: Mapping[str, ResultadoFinal]) -> Tuple[Decimal, Decimal]:
    con = sum((c.monto for c in cargos if final[c.cargo_id].asiento_id is not None), CERO)
    sin = sum((c.monto for c in cargos if final[c.cargo_id].asiento_id is None), CERO)
    return con, sin


def _candado_cobertura(cargos: Sequence[Cargo], final: Mapping[str, ResultadoFinal]) -> Objeto:
    ids_universo = sorted(c.cargo_id for c in cargos)
    ids_salida = sorted(final)
    total = sum((c.monto for c in cargos), CERO)
    con, sin = _sumas_por_estado(cargos, final) if ids_universo == ids_salida else (CERO, CERO)
    ok = ids_universo == ids_salida and con + sin == total
    return {"ok": ok, "detalle": {"cargos_universo": len(ids_universo), "cargos_salida": len(ids_salida),
                                  "monto_universo": _monto(total), "monto_con_cruce": _monto(con),
                                  "monto_sin_cruce": _monto(sin)}}


def _candado_partida_doble(lineas: Sequence[LineaLibro]) -> Objeto:
    sumas: Dict[str, Tuple[Decimal, Decimal]] = {}
    for x in lineas:
        debe, haber = sumas.get(x.asiento_id, (CERO, CERO))
        sumas[x.asiento_id] = (debe + x.debe, haber + x.haber)
    descuadrados = {a: {"debe": _monto(d), "haber": _monto(h)} for a, (d, h) in sorted(sumas.items()) if d != h}
    return {"ok": not descuadrados, "detalle": {"asientos": len(sumas), "asientos_descuadrados": descuadrados}}


def candados(conc: Conciliacion, cargos: Sequence[Cargo], lineas: Sequence[LineaLibro]) -> Dict[str, Objeto]:
    return {"exclusividad": _candado_exclusividad(conc.final), "cobertura": _candado_cobertura(cargos, conc.final),
            "partida_doble": _candado_partida_doble(lineas)}


def candados_fallidos(reporte: Mapping[str, object]) -> List[str]:
    tabla = reporte["candados"]
    assert isinstance(tabla, dict)
    return sorted(nombre for nombre, candado in tabla.items() if not candado["ok"])


# -------------------------------------------------------------------- resumen
def _conteo(valores: Sequence[Optional[str]]) -> Dict[str, int]:
    return dict(sorted(Counter(v for v in valores if v is not None).items()))


def _resumen(conc: Conciliacion, cargos: Sequence[Cargo]) -> Objeto:
    propuesta, final = list(conc.propuesta.values()), list(conc.final.values())
    veredictos = list(conc.veredictos.values())
    con, sin = _sumas_por_estado(cargos, conc.final)
    return {
        "cargos": len(cargos),
        "propuesta": {"con_cruce": sum(1 for p in propuesta if p.asiento_id),
                      "riesgo_cubeta": sum(1 for p in propuesta if p.riesgo_cubeta),
                      "por_motivo": _conteo([p.motivo for p in propuesta])},
        "final": {"con_cruce": sum(1 for f in final if f.asiento_id),
                  "riesgo_cubeta": sum(1 for f in final if f.riesgo_cubeta),
                  "por_origen": _conteo([f.origen for f in final]),
                  "por_motivo": _conteo([f.motivo for f in final]),
                  "reasignados_por_veredicto": sum(1 for f in final if f.reasignado)},
        "veredictos": {"total": len(veredictos),
                       "registrado": sum(1 for v in veredictos if v.veredicto == VEREDICTO_REGISTRADO),
                       "no_registrado": sum(1 for v in veredictos if v.veredicto != VEREDICTO_REGISTRADO),
                       "conflictos": _conteo(list(conc.conflictos.values()))},
        "montos": {"universo": _monto(con + sin), "final_con_cruce": _monto(con), "final_sin_cruce": _monto(sin)},
    }


def construir_reporte(conc: Conciliacion, cargos: Sequence[Cargo], lineas: Sequence[LineaLibro],
                      config: ConfigCruceLibro, insumos: Mapping[str, object]) -> Objeto:
    """Documento completo de salida (ver la sección "Salida" de la spec)."""
    ocupantes = {a: cs[0] for a, cs in _usos_finales(conc.final).items()}
    return {
        "esquema": ESQUEMA_SALIDA,
        "parametros": config_a_dict(config),
        "insumos": dict(insumos),
        "candados": candados(conc, cargos, lineas),
        "resumen": _resumen(conc, cargos),
        "conflictos": _conflictos(conc),
        "cargos": [_cargo(ev, conc, ocupantes, config.max_candidatos_reporte) for ev in conc.evaluaciones],
    }


def a_json(reporte: Mapping[str, object]) -> str:
    return json.dumps(reporte, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
