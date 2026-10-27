"""Resumen del pipeline e invariantes recalculados sobre las filas ensambladas.

Los invariantes no confían en ningún motor: vuelven a contar sobre las filas que se
van a publicar y comparan contra los totales de control del estado de cuenta y
contra el propio resumen publicado. Nombres y reglas en `specs/pipeline.md`.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .cruce_cfdi_modelo import EVIDENCIAS, MOTIVOS
from .cruce_libro_modelo import (
    CONFLICTO_ASIENTO,
    CONFLICTO_CON_CRUCE,
    CONFLICTO_SIN_CRUCE,
    MOTIVO_CUBETA,
    MOTIVO_ININTERPRETABLE,
    MOTIVO_NO_APLICA,
    MOTIVO_NOMBRE,
    MOTIVO_OCUPADO,
    MOTIVO_SIN_CANDIDATO,
    MOTIVO_VEREDICTO,
    ORIGEN_MOTOR,
    ORIGEN_VEREDICTO,
)
from .montos import texto_monto
from .pipeline_filas import FilaCargo
from .pipeline_modelo import ETAPA_CFDI, ETAPA_LIBRO, ETAPA_PIPELINE, SITUACION_EN_REVISION, SITUACIONES, Candado
from .pipeline_revision import ORIGEN_CARGO, ORIGEN_CFDI, Observacion

CERO = Decimal("0.00")
MAX_EJEMPLOS = 5
SIN_OBSERVACIONES = "sin observaciones"
MOTIVOS_LIBRO: Tuple[str, ...] = (MOTIVO_ININTERPRETABLE, MOTIVO_NO_APLICA, MOTIVO_SIN_CANDIDATO, MOTIVO_OCUPADO,
                                  MOTIVO_NOMBRE, MOTIVO_CUBETA, MOTIVO_VEREDICTO)
ORIGENES: Tuple[str, ...] = (ORIGEN_MOTOR, ORIGEN_VEREDICTO)
CONFLICTOS: Tuple[str, ...] = (CONFLICTO_ASIENTO, CONFLICTO_SIN_CRUCE, CONFLICTO_CON_CRUCE)

Bolsa = Dict[str, Any]


# --- resumen --------------------------------------------------------------------


def _bolsa(filas: Iterable[FilaCargo]) -> Bolsa:
    lista = list(filas)
    return {"cargos": len(lista), "monto": texto_monto(sum((f.monto for f in lista), CERO))}


def _agrupar(filas: Sequence[FilaCargo], clave: Callable[[FilaCargo], Optional[str]],
             catalogo: Sequence[str]) -> Dict[str, Bolsa]:
    """Una bolsa por valor del catálogo (aunque quede en cero) y por cualquier valor observado fuera de él."""
    valores = set(catalogo) | {v for v in map(clave, filas) if v is not None}
    return {valor: _bolsa(f for f in filas if clave(f) == valor) for valor in sorted(valores)}


def _contar(valores: Iterable[Optional[str]], catalogo: Sequence[str]) -> Dict[str, int]:
    conteo = Counter(v for v in valores if v is not None)
    return {valor: conteo.get(valor, 0) for valor in sorted(set(catalogo) | set(conteo))}


def _por_emisor(filas: Sequence[FilaCargo], control: Mapping[str, Decimal]) -> Dict[str, Bolsa]:
    emisores = sorted({f.emisor for f in filas} | set(control))
    return {e: {**_bolsa(f for f in filas if f.emisor == e),
                "total_neto_estado": texto_monto(control[e]) if e in control else None} for e in emisores}


def resumir(filas: Sequence[FilaCargo], control: Mapping[str, Decimal]) -> Dict[str, Any]:
    """Conteos y montos por situación, por tier y motivo de CFDI, por lado del libro y por emisor."""
    return {
        "total": _bolsa(filas),
        "por_emisor": _por_emisor(filas, control),
        "por_situacion": _agrupar(filas, lambda f: f.situacion, SITUACIONES),
        "cfdi": {
            "por_tier": _agrupar(filas, lambda f: f.cfdi.tier, EVIDENCIAS),
            "por_motivo": _agrupar(filas, lambda f: f.cfdi.motivo, MOTIVOS),
            "uuids_asignados": len({u for f in filas for u in f.cfdi.uuids}),
        },
        "libro_mayor": {
            "con_asiento": _bolsa(f for f in filas if f.libro.asiento_id is not None),
            "sin_asiento": _bolsa(f for f in filas if f.libro.asiento_id is None),
            "por_motivo": _agrupar(filas, lambda f: f.libro.motivo, MOTIVOS_LIBRO),
            "por_origen": _contar((f.libro.origen for f in filas), ORIGENES),
            "riesgo_cubeta": sum(1 for f in filas if f.libro.riesgo_cubeta),
            "conflictos": _contar((f.libro.conflicto for f in filas), CONFLICTOS),
        },
    }


# --- invariantes ----------------------------------------------------------------


def _candado(nombre: str, problemas: Sequence[str]) -> Candado:
    if not problemas:
        return Candado(ETAPA_PIPELINE, nombre, True, SIN_OBSERVACIONES)
    ejemplos = "; ".join(sorted(problemas)[:MAX_EJEMPLOS])
    return Candado(ETAPA_PIPELINE, nombre, False, f"{len(problemas)} casos: {ejemplos}")


def _repetidos(pares: Iterable[Tuple[str, str]]) -> List[str]:
    """Cada valor que aparece más de una vez en (valor, cargo_id), con los cargos que lo usan."""
    duenos: Dict[str, List[str]] = {}
    for valor, cargo_id in pares:
        duenos.setdefault(valor, []).append(cargo_id)
    return [f"{v}: {', '.join(sorted(c))}" for v, c in sorted(duenos.items()) if len(c) > 1]


def verificar_cobertura(universo: Sequence[str], cfdi: Sequence[str], libro: Sequence[str]) -> Candado:
    """Cada cargo del universo aparece exactamente una vez en cada cruce."""
    esperados = set(universo)
    problemas = [f"universo: {i} repetido" for i, n in sorted(Counter(universo).items()) if n > 1]
    for etapa, ids in ((ETAPA_CFDI, cfdi), (ETAPA_LIBRO, libro)):
        vistos = Counter(ids)
        problemas.extend(f"{etapa}: falta {i}" for i in sorted(esperados - set(vistos)))
        problemas.extend(f"{etapa}: sobra {i}" for i in sorted(set(vistos) - esperados))
        problemas.extend(f"{etapa}: {i} aparece {n} veces" for i, n in sorted(vistos.items()) if n > 1)
    return _candado("cobertura", problemas)


def _tier_o_motivo(fila: FilaCargo) -> bool:
    lado = fila.cfdi
    con_cruce = lado.tier is not None and bool(lado.uuids) and lado.motivo is None
    sin_cruce = lado.tier is None and not lado.uuids and lado.motivo is not None
    return con_cruce or sin_cruce


def _asiento_o_motivo(fila: FilaCargo) -> bool:
    return (fila.libro.asiento_id is None) != (fila.libro.motivo is None)


def _totales_control(filas: Sequence[FilaCargo], control: Mapping[str, Decimal]) -> List[str]:
    problemas = []
    for emisor in sorted({f.emisor for f in filas} | set(control)):
        suma = sum((f.monto for f in filas if f.emisor == emisor), CERO)
        if emisor not in control:
            problemas.append(f"{emisor}: filas sin total de control ({texto_monto(suma)})")
        elif suma != control[emisor]:
            problemas.append(f"{emisor}: filas suman {texto_monto(suma)}, el estado dice "
                             f"{texto_monto(control[emisor])}")
    return problemas


def _leer_bolsa(bolsa: Mapping[str, Any]) -> Tuple[int, Decimal]:
    return int(bolsa["cargos"]), Decimal(str(bolsa["monto"]))


def _sumar(bolsas: Iterable[Mapping[str, Any]]) -> Tuple[int, Decimal]:
    leidas = [_leer_bolsa(b) for b in bolsas]
    return sum(c for c, _ in leidas), sum((m for _, m in leidas), CERO)


def _totales_resumen(filas: Sequence[FilaCargo], resumen: Mapping[str, Any]) -> List[str]:
    """Cada partición publicada debe sumar el total, y el total debe ser el de las filas."""
    reales = (len(filas), sum((f.monto for f in filas), CERO))
    total = _leer_bolsa(resumen["total"])
    cfdi, libro = resumen["cfdi"], resumen["libro_mayor"]
    particiones = {
        "por_emisor": list(resumen["por_emisor"].values()),
        "por_situacion": list(resumen["por_situacion"].values()),
        "cfdi": list(cfdi["por_tier"].values()) + list(cfdi["por_motivo"].values()),
        "libro_mayor": [libro["con_asiento"], libro["sin_asiento"]],
    }
    problemas = [f"{nombre}: {c} cargos / {texto_monto(m)} contra {reales[0]} / {texto_monto(reales[1])}"
                 for nombre, bolsas in particiones.items() for c, m in [_sumar(bolsas)] if (c, m) != reales]
    if total != reales:
        problemas.append(f"total publicado {total[0]} / {texto_monto(total[1])} no es el de las filas")
    motivos, sin_asiento = _sumar(libro["por_motivo"].values()), _leer_bolsa(libro["sin_asiento"])
    if motivos != sin_asiento:
        problemas.append(f"libro_mayor.por_motivo suma {motivos[0]} / {texto_monto(motivos[1])} y sin_asiento "
                         f"es {sin_asiento[0]} / {texto_monto(sin_asiento[1])}")
    return problemas


def _cuarentena(filas: Sequence[FilaCargo]) -> List[str]:
    """Una fila con observaciones está en revisión humana, y solo esas lo están."""
    return [f"{f.cargo_id}: {len(f.revision)} observaciones y situación {f.situacion}" for f in filas
            if bool(f.revision) != (f.situacion == SITUACION_EN_REVISION)]


def _cola_completa(filas: Sequence[FilaCargo], cola: Sequence[Observacion]) -> List[str]:
    """Cada observación llega a la fila de su cargo o de su CFDI asignado; la de un CFDI libre solo va a la cola."""
    por_cargo = {f.cargo_id: f for f in filas}
    por_uuid = {u: f for f in filas for u in f.cfdi.uuids}
    problemas = []
    for observacion in cola:
        clave = "/".join(observacion.llave)
        if observacion.origen == ORIGEN_CARGO:
            fila = por_cargo.get(observacion.registro_id)
            if fila is None:
                problemas.append(f"{clave}: el cargo no está en las filas")
                continue
        elif observacion.origen == ORIGEN_CFDI and observacion.registro_id in por_uuid:
            fila = por_uuid[observacion.registro_id]
        else:
            continue
        if observacion not in fila.revision:
            problemas.append(f"{clave}: no aparece en la fila {fila.cargo_id}")
    return problemas


def invariantes_de_filas(filas: Sequence[FilaCargo], resumen: Mapping[str, Any], control: Mapping[str, Decimal],
                         cola: Sequence[Observacion] = ()) -> Tuple[Candado, ...]:
    """Los invariantes de la spec, salvo la cobertura (que se verifica antes de ensamblar)."""
    return (
        _candado("exclusividad_uuid", _repetidos((u, f.cargo_id) for f in filas for u in f.cfdi.uuids)),
        _candado("exclusividad_asiento", _repetidos((f.libro.asiento_id, f.cargo_id) for f in filas
                                                    if f.libro.asiento_id is not None)),
        _candado("tier_o_motivo_cfdi", [f"{f.cargo_id}: tier={f.cfdi.tier}, {len(f.cfdi.uuids)} UUIDs, "
                                        f"motivo={f.cfdi.motivo}" for f in filas if not _tier_o_motivo(f)]),
        _candado("asiento_o_motivo_libro", [f"{f.cargo_id}: asiento={f.libro.asiento_id}, motivo={f.libro.motivo}"
                                            for f in filas if not _asiento_o_motivo(f)]),
        _candado("totales_control", _totales_control(filas, control)),
        _candado("totales_resumen", _totales_resumen(filas, resumen)),
        _candado("cuarentena", _cuarentena(filas)),
        _candado("cola_completa", _cola_completa(filas, cola)),
    )
