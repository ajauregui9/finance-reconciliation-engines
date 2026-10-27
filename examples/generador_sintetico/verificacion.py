"""Autoverificación: el oráculo es la única respuesta razonable con estos datos.

Reglas de candidatura que el oráculo supone (y documenta el README):
- CFDI candidato de un cargo: recibido, tipo I o E, receptor = la empresa y
  delta dentro de la ventana. Uno a uno: |valor firmado - monto| <= tolerancia,
  en pesos o, si ambos están en USD, en dólares.
- Suma: 2 o 3 CFDIs candidatos del emisor del comercio (RFC no genérico). Los
  tiers uno a uno tienen precedencia: un cargo resuelto uno a uno no llega al
  tier de suma, y un CFDI reclamado uno a uno por otro cargo no entra en sumas.
- Asiento candidato: línea en una cuenta de tarjeta (2105-*) del lado correcto,
  con |importe - |monto|| <= tolerancia y a no más de 30 días del cargo.
Cualquier candidato fuera de lo esperado, lo prohibido o el grupo de empate es
una violación. También se valida exclusividad y coherencia de lo esperado, y que
cada veredicto humano plantado traiga el conflicto que implica el oráculo y que cada
inyección sembrada esté en su CFDI y respalde al cargo que dice.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations
from decimal import Decimal
from typing import Dict, FrozenSet, Iterable, List, Set, Tuple

from .catalogo import EMISORES
from .config import LIBRO_DESFASE_MAX, LIBRO_DESFASE_MIN, RFC_EMPRESA, RFCS_GENERICOS, ConfigGenerador
from .modelo import Asiento, Cargo, Cfdi, Datos, Expectativa, LineaMayor
from .inyecciones import verificar_inyecciones
from .veredictos import verificar_veredictos

DIAS_CANDIDATO_LIBRO = 30
PREFIJO_CUENTA_TARJETA = "2105-"
EVIDENCIAS_UNO_A_UNO = ("monto_exacto", "monto_tolerancia", "moneda_original")


def _delta(cfdi: Cfdi, cargo: Cargo) -> int:
    return (cfdi.fecha_emision - cargo.fecha).days


def candidatos_cfdi(cargo: Cargo, cfdis: Iterable[Cfdi], vmin: int, vmax: int) -> List[Cfdi]:
    return [u for u in cfdis
            if u.direccion == "recibido" and u.tipo_comprobante in ("I", "E")
            and u.rfc_receptor == RFC_EMPRESA and vmin <= _delta(u, cargo) <= vmax]


def _uno_a_uno(cargo: Cargo, candidatos: List[Cfdi], tol: Decimal) -> Set[str]:
    salida = {u.uuid for u in candidatos if abs(u.valor_firmado_mxn - cargo.monto) <= tol}
    if cargo.moneda_original == "USD":
        salida |= {u.uuid for u in candidatos if u.moneda == "USD"
                   and abs(u.valor_firmado_original - cargo.monto_original) <= tol}
    return salida


def _sumas(cargo: Cargo, candidatos: List[Cfdi], tol: Decimal) -> Set[FrozenSet[str]]:
    rfc = cargo.comercio.rfc if cargo.comercio else None
    if rfc is None or rfc in RFCS_GENERICOS:
        return set()
    propios = [u for u in candidatos if u.rfc_emisor == rfc]
    return {frozenset(u.uuid for u in combo) for k in (2, 3) for combo in combinations(propios, k)
            if abs(sum(u.valor_firmado_mxn for u in combo) - cargo.monto) <= tol}


def _lado_tarjeta(asiento: Asiento) -> List[LineaMayor]:
    return [x for x in asiento.lineas if x.cuenta.startswith(PREFIJO_CUENTA_TARJETA)]


def _candidatos_libro(cargo: Cargo, asientos: Iterable[Asiento], tol: Decimal) -> Set[str]:
    salida: Set[str] = set()
    for a in asientos:
        if abs((a.fecha - cargo.fecha).days) > DIAS_CANDIDATO_LIBRO:
            continue
        for x in _lado_tarjeta(a):
            importe = x.haber if cargo.monto > 0 else x.debe
            if importe > 0 and abs(importe - abs(cargo.monto)) <= tol:
                salida.add(a.asiento_id)
    return salida


def _exclusividad(expectativas: Tuple[Expectativa, ...]) -> List[str]:
    uuids = Counter(u for e in expectativas for u in e.cfdi.esperados)
    asientos = Counter(e.libro.esperado for e in expectativas if e.libro and e.libro.esperado)
    return ([f"CFDI {u} esperado por {n} cargos" for u, n in uuids.items() if n > 1]
            + [f"asiento {a} esperado por {n} cargos" for a, n in asientos.items() if n > 1])


def _reclamados_uno_a_uno(expectativas: Iterable[Expectativa]) -> Dict[str, str]:
    """UUID -> cargo que lo reclama en un tier uno a uno."""
    return {u: e.clave_cargo for e in expectativas if e.cfdi.evidencia in EVIDENCIAS_UNO_A_UNO
            for u in e.cfdi.esperados}


def _verificar_cfdi(cargo: Cargo, exp: Expectativa, cfdis: Tuple[Cfdi, ...], grupo: Set[str],
                    reclamados: Dict[str, str], config: ConfigGenerador) -> List[str]:
    cid, tol = cargo.cargo_id, config.tolerancia_monto
    candidatos = candidatos_cfdi(cargo, cfdis, config.ventana_min, config.ventana_max)
    permitidos = set(exp.cfdi.esperados) | set(exp.cfdi.prohibidos) | grupo
    violaciones = [f"{cid}: candidato 1 a 1 no previsto {u}"
                   for u in sorted(_uno_a_uno(cargo, candidatos, tol) - permitidos)]
    libres = [u for u in candidatos if reclamados.get(u.uuid, cid) == cid]
    sumas = set() if exp.cfdi.evidencia in EVIDENCIAS_UNO_A_UNO else _sumas(cargo, libres, tol)
    esperada = {frozenset(exp.cfdi.esperados)} if exp.cfdi.evidencia == "suma" else set()
    violaciones += [f"{cid}: suma no prevista {sorted(s)}" for s in sorted(sumas - esperada, key=sorted)]
    if esperada and not esperada <= sumas:
        violaciones.append(f"{cid}: la suma esperada no es candidata")
    fuera = set(exp.cfdi.esperados) - {u.uuid for u in candidatos}
    violaciones += [f"{cid}: CFDI esperado fuera de candidatura {u}" for u in sorted(fuera)]
    return violaciones


def _verificar_libro(cargo: Cargo, exp: Expectativa, asientos: Tuple[Asiento, ...],
                     por_id: Dict[str, Asiento], grupo: Set[str], tol: Decimal) -> List[str]:
    cid, libro = cargo.cargo_id, exp.libro_requerido()
    permitidos = set(libro.prohibidos) | grupo | ({libro.esperado} if libro.esperado else set())
    violaciones = [f"{cid}: asiento candidato no previsto {a}"
                   for a in sorted(_candidatos_libro(cargo, asientos, tol) - permitidos)]
    if libro.esperado:
        asiento = por_id[libro.esperado]
        desfase = (asiento.fecha - cargo.fecha).days
        cuentas = {x.cuenta for x in _lado_tarjeta(asiento)}
        fecha_ok = LIBRO_DESFASE_MIN <= desfase <= LIBRO_DESFASE_MAX
        if not fecha_ok or cuentas != {EMISORES[cargo.emisor].cuenta}:
            violaciones.append(f"{cid}: asiento esperado {libro.esperado} con fecha o cuenta incoherente")
    return violaciones


def verificar(datos: Datos) -> Tuple[str, ...]:
    """Devuelve las violaciones encontradas (tupla vacía si el conjunto es válido)."""
    expectativas = {e.clave_cargo: e for e in datos.expectativas}
    grupo_cfdi = {c: set(g.cfdis) for g in datos.grupos for c in g.cargos}
    grupo_libro = {c: set(g.asientos) for g in datos.grupos for c in g.cargos}
    por_id = {a.asiento_id: a for a in datos.asientos}
    reclamados = _reclamados_uno_a_uno(datos.expectativas)
    violaciones = _exclusividad(datos.expectativas)
    faltantes = {c.cargo_id for c in datos.cargos} ^ set(expectativas)
    violaciones += [f"{c}: cargo sin expectativa o expectativa sin cargo" for c in sorted(faltantes)]
    for cargo in datos.cargos:
        exp = expectativas.get(cargo.cargo_id)
        if exp is None or not cargo.interpretable or cargo.tipo_movimiento == "pago":
            continue
        violaciones += _verificar_cfdi(cargo, exp, datos.cfdis, grupo_cfdi.get(cargo.cargo_id, set()),
                                       reclamados, datos.config)
        violaciones += _verificar_libro(cargo, exp, datos.asientos, por_id,
                                        grupo_libro.get(cargo.cargo_id, set()), datos.config.tolerancia_monto)
    violaciones += verificar_veredictos(datos)
    violaciones += verificar_inyecciones(datos)
    return tuple(violaciones)
