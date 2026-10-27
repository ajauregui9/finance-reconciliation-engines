"""Autoverificación: el oráculo es la única respuesta razonable con estos datos.

Reglas de candidatura que el oráculo supone (y documenta el README):
- CFDI candidato de un cargo: recibido, tipo I o E, receptor = la empresa y
  delta dentro de la ventana. Uno a uno: |valor firmado - monto| <= tolerancia,
  en pesos o, si ambos están en USD, en dólares.
- Suma: 2 o 3 CFDIs candidatos del emisor del comercio (RFC no genérico). Los
  tiers uno a uno con afinidad tienen precedencia: un cargo resuelto así no llega
  al tier de suma, y un CFDI reclamado así por otro cargo no entra en sumas.
- Afinidad: un cruce solo por monto también es un cruce (`monto_sin_afinidad`, por
  revisar) y se decide después de todos los cruces con afinidad. Por eso, para un
  cargo sin cruce esperado o con un cruce por revisar, también cuenta la suma de
  cualquier otro emisor no genérico hecha con CFDIs que ningún cruce anterior
  reclama; y un CFDI que se supone sin afinidad no comparte ninguna inicial de
  palabra con la descripción del cargo.
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
from typing import Dict, FrozenSet, Iterable, List, Mapping, Set, Tuple

from .afinidad import CASO_EMPATE, EVIDENCIA_SIN_AFINIDAD, nombres_ajenos
from .catalogo import EMISORES
from .config import LIBRO_DESFASE_MAX, LIBRO_DESFASE_MIN, RFC_EMPRESA, RFCS_GENERICOS, ConfigGenerador
from .estado_cuenta import descripcion_cruda
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


def _sumas(cargo: Cargo, candidatos: List[Cfdi], tol: Decimal, *, ajenas: bool = False) -> Set[FrozenSet[str]]:
    """Grupos de 2 o 3 CFDIs de un mismo RFC no genérico que suman el monto: del emisor del comercio o,
    con `ajenas`, de cualquier otro emisor (una suma sin afinidad también es un cruce)."""
    rfc = cargo.comercio.rfc if cargo.comercio else None
    grupos: Dict[str, List[Cfdi]] = {}
    for u in candidatos:
        if u.rfc_emisor not in RFCS_GENERICOS and (u.rfc_emisor != rfc) == ajenas:
            grupos.setdefault(u.rfc_emisor, []).append(u)
    return {frozenset(u.uuid for u in combo) for propios in grupos.values() for k in (2, 3)
            for combo in combinations(propios, k)
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
    """UUID -> cargo que lo reclama en un tier uno a uno con afinidad (la primera fase del motor)."""
    return {u: e.clave_cargo for e in expectativas if e.cfdi.evidencia in EVIDENCIAS_UNO_A_UNO
            for u in e.cfdi.esperados}


def _reclamados_antes_de_sumas_ajenas(expectativas: Iterable[Expectativa]) -> Dict[str, str]:
    """UUID -> cargo que lo reclama en una fase anterior a las sumas sin afinidad (todas salvo esas sumas)."""
    return {u: e.clave_cargo for e in expectativas if e.cfdi.evidencia is not None
            and not (e.cfdi.evidencia == EVIDENCIA_SIN_AFINIDAD and len(e.cfdi.esperados) > 1)
            for u in e.cfdi.esperados}


def _sumas_posibles(cargo: Cargo, exp: Expectativa, candidatos: List[Cfdi], reclamados: Tuple[Dict[str, str], ...],
                    tol: Decimal) -> Set[FrozenSet[str]]:
    """Sumas que el motor podría formar para el cargo, según la fase en que competirían."""
    if exp.cfdi.evidencia in EVIDENCIAS_UNO_A_UNO:
        return set()
    cid, (afines, previos) = cargo.cargo_id, reclamados
    sumas = _sumas(cargo, [u for u in candidatos if afines.get(u.uuid, cid) == cid], tol)
    if exp.cfdi.evidencia in (None, EVIDENCIA_SIN_AFINIDAD):
        sumas |= _sumas(cargo, [u for u in candidatos if previos.get(u.uuid, cid) == cid], tol, ajenas=True)
    return sumas


def _verificar_cfdi(cargo: Cargo, exp: Expectativa, cfdis: Tuple[Cfdi, ...], grupo: Set[str],
                    reclamados: Tuple[Dict[str, str], ...], config: ConfigGenerador) -> List[str]:
    cid, tol = cargo.cargo_id, config.tolerancia_monto
    candidatos = candidatos_cfdi(cargo, cfdis, config.ventana_min, config.ventana_max)
    permitidos = set(exp.cfdi.esperados) | set(exp.cfdi.prohibidos) | grupo
    violaciones = [f"{cid}: candidato 1 a 1 no previsto {u}"
                   for u in sorted(_uno_a_uno(cargo, candidatos, tol) - permitidos)]
    sumas = _sumas_posibles(cargo, exp, candidatos, reclamados, tol)
    es_suma = exp.cfdi.evidencia == "suma" or (exp.cfdi.evidencia == EVIDENCIA_SIN_AFINIDAD
                                               and len(exp.cfdi.esperados) > 1)
    esperada = {frozenset(exp.cfdi.esperados)} if es_suma else set()
    violaciones += [f"{cid}: suma no prevista {sorted(s)}" for s in sorted(sumas - esperada, key=sorted)]
    if esperada and not esperada <= sumas:
        violaciones.append(f"{cid}: la suma esperada no es candidata")
    fuera = set(exp.cfdi.esperados) - {u.uuid for u in candidatos}
    violaciones += [f"{cid}: CFDI esperado fuera de candidatura {u}" for u in sorted(fuera)]
    return violaciones


def _verificar_afinidad(cargo: Cargo, exp: Expectativa, por_uuid: Mapping[str, Cfdi]) -> List[str]:
    """Lo que se supone sin afinidad (lo esperado por revisar y el señuelo de un empate) lo es de verdad."""
    supuestos = list(exp.cfdi.esperados) if exp.cfdi.evidencia == EVIDENCIA_SIN_AFINIDAD else []
    if CASO_EMPATE in exp.casos:
        supuestos += list(exp.cfdi.prohibidos)
    descripcion = descripcion_cruda(cargo)
    return [f"{cargo.cargo_id}: el CFDI {u} se supone sin afinidad y su emisor comparte inicial con el cargo"
            for u in supuestos if u in por_uuid and not nombres_ajenos(descripcion, por_uuid[u].nombre_emisor)]


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
    por_uuid = {c.uuid: c for c in datos.cfdis}
    reclamados = (_reclamados_uno_a_uno(datos.expectativas), _reclamados_antes_de_sumas_ajenas(datos.expectativas))
    violaciones = _exclusividad(datos.expectativas)
    faltantes = {c.cargo_id for c in datos.cargos} ^ set(expectativas)
    violaciones += [f"{c}: cargo sin expectativa o expectativa sin cargo" for c in sorted(faltantes)]
    for cargo in datos.cargos:
        exp = expectativas.get(cargo.cargo_id)
        if exp is None or not cargo.interpretable or cargo.tipo_movimiento == "pago":
            continue
        violaciones += _verificar_cfdi(cargo, exp, datos.cfdis, grupo_cfdi.get(cargo.cargo_id, set()),
                                       reclamados, datos.config)
        violaciones += _verificar_afinidad(cargo, exp, por_uuid)
        violaciones += _verificar_libro(cargo, exp, datos.asientos, por_id,
                                        grupo_libro.get(cargo.cargo_id, set()), datos.config.tolerancia_monto)
    violaciones += verificar_veredictos(datos)
    violaciones += verificar_inyecciones(datos)
    return tuple(violaciones)
