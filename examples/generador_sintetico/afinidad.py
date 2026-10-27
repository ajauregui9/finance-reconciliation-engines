"""Casos de afinidad de nombre, sembrados sobre el conjunto ya ensamblado.

Un cruce que solo coincide por monto no respalda al cargo: el motor lo publica como
`monto_sin_afinidad` (pendiente de revisión humana) y le deja ocupado el CFDI. Se
siembra un caso de cada tipo:

- `afinidad_emisor_ajeno`: a un cargo `sin_cfdi`, un CFDI de otro comercio con el
  monto exacto. Respuesta: ese CFDI, `monto_sin_afinidad`.
- `afinidad_suma_emisor_ajeno`: a un cargo `sin_cfdi`, dos CFDIs de otro comercio
  que suman el monto. Respuesta: ambos, `monto_sin_afinidad`.
- `empate_monto_afinidad`: a un cargo `normal`, un CFDI de otro comercio con el
  mismo monto y delta 0. Respuesta: el propio (`monto_exacto`); el ajeno, prohibido.
- `afinidad_descriptor_agregador`: un cargo `normal` sin asiento cuyo descriptor
  pasa a `PGDEMO *PEDIDO nnnn WEB`. Respuesta: su propio CFDI, `monto_sin_afinidad`.

"Ajeno" se garantiza sin reproducir la heurística del motor: ninguna palabra de la
razón social comparte inicial con una palabra de la descripción del cargo (palabras de
3 o más caracteres que no son solo dígitos). Toda regla de compatibilidad de palabras
del motor exige la misma inicial, así que la afinidad es 0.

Se siembran con su propia sub-semilla, después de veredictos e inyecciones: no consumen
el azar del resto de la corrida ni cambian ids, montos o fechas, y solo usan cargos sin
veredicto, sin inyección, fuera de grupos de empate y sin prohibidos. El cargo del
descriptor de pasarela es de un comercio con otros cargos, así que su descriptor original
sigue en el universo. Cada CFDI nuevo lleva el folio siguiente de su serie.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from .catalogo import COMERCIOS
from .config import FOLIO_INICIAL, ConfigGenerador
from .contexto import Contexto
from .escenarios_cfdi import partir_monto
from .estado_cuenta import descripcion_cruda
from .fabricas import cfdi_comercio, dias
from .modelo import Cargo, Cfdi, Comercio, Expectativa, ExpectativaCfdi, InyeccionSembrada, VeredictoHumano

SAL_AFINIDAD = 900_007
EVIDENCIA_SIN_AFINIDAD = "monto_sin_afinidad"
CASO_EMISOR_AJENO = "afinidad_emisor_ajeno"
CASO_SUMA_AJENA = "afinidad_suma_emisor_ajeno"
CASO_EMPATE = "empate_monto_afinidad"
CASO_AGREGADOR = "afinidad_descriptor_agregador"
CASOS_AFINIDAD: Tuple[str, ...] = (CASO_EMISOR_AJENO, CASO_SUMA_AJENA, CASO_EMPATE, CASO_AGREGADOR)
CASO_SIN_CFDI = "sin_cfdi"
CASO_NORMAL = "normal"

PASARELA = "PGDEMO *PEDIDO"
CIUDAD_PASARELA = "WEB"
PEDIDO_MIN, PEDIDO_MAX = 1000, 9999
MONTO_MINIMO_SUMA = Decimal("200.00")
LARGO_MINIMO_PALABRA = 3
_PALABRA = re.compile(r"[A-Z0-9]+")


def iniciales(texto: str) -> FrozenSet[str]:
    """Iniciales de las palabras de 3+ caracteres que no son solo dígitos."""
    return frozenset(p[0] for p in _PALABRA.findall(texto.upper())
                     if len(p) >= LARGO_MINIMO_PALABRA and not p.isdigit())


def nombres_ajenos(descripcion: str, razon_social: str) -> bool:
    """True si ninguna palabra de un nombre comparte inicial con una del otro (afinidad 0 en el motor)."""
    return not iniciales(descripcion) & iniciales(razon_social)


@dataclass(frozen=True)
class _Siembra:
    """Lo que un caso cambia: la expectativa del cargo, el cargo (si cambia) y los CFDIs nuevos."""

    expectativa: Expectativa
    cfdis: Tuple[Cfdi, ...] = ()
    cargo: Optional[Cargo] = None


@dataclass(frozen=True)
class _Base:
    """Lo que ya está ensamblado, indexado para elegir cargos limpios."""

    cargos: Mapping[str, Cargo]
    cfdis: Mapping[str, Cfdi]
    vetados: FrozenSet[str]

    def limpio(self, e: Expectativa) -> bool:
        cargo = self.cargos[e.clave_cargo]
        return (e.clave_cargo not in self.vetados and e.grupo_empate is None and not e.cfdi.prohibidos
                and not e.libro_requerido().prohibidos and cargo.interpretable and cargo.comercio is not None
                and cargo.tipo_movimiento == "cargo" and cargo.moneda_original == "MXN")


def _recaso(e: Expectativa, viejo: str, nuevo: str) -> Tuple[str, ...]:
    return tuple(nuevo if c == viejo else c for c in e.casos)


def _comercio_ajeno(ctx: Contexto, descripcion: str) -> Comercio:
    opciones = [c for c in COMERCIOS if nombres_ajenos(descripcion, c.razon_social)]
    if not opciones:
        raise RuntimeError(f"ningún comercio del catálogo es ajeno a {descripcion!r}")
    return ctx.elegir(opciones)


def _sin_cfdi(base: _Base, e: Expectativa) -> bool:
    return CASO_SIN_CFDI in e.casos and e.cfdi.evidencia is None and e.cfdi.motivo == "sin_candidato"


def _sin_cfdi_para_suma(base: _Base, e: Expectativa) -> bool:
    return _sin_cfdi(base, e) and base.cargos[e.clave_cargo].monto >= MONTO_MINIMO_SUMA


def _normal(e: Expectativa) -> bool:
    return CASO_NORMAL in e.casos and e.cfdi.evidencia == "monto_exacto" and len(e.cfdi.esperados) == 1


def _emisor_ajeno(ctx: Contexto, base: _Base, e: Expectativa) -> _Siembra:
    cargo = base.cargos[e.clave_cargo]
    comercio = _comercio_ajeno(ctx, descripcion_cruda(cargo))
    cfdi = cfdi_comercio(ctx, comercio, cargo.monto, cargo.fecha + dias(ctx.delta_en_ventana(0, 4)))
    return _Siembra(replace(e, casos=_recaso(e, CASO_SIN_CFDI, CASO_EMISOR_AJENO),
                            cfdi=ExpectativaCfdi((cfdi.uuid,), EVIDENCIA_SIN_AFINIDAD)), (cfdi,))


def _suma_ajena(ctx: Contexto, base: _Base, e: Expectativa) -> _Siembra:
    cargo = base.cargos[e.clave_cargo]
    comercio = _comercio_ajeno(ctx, descripcion_cruda(cargo))
    cfdis = tuple(cfdi_comercio(ctx, comercio, parte, cargo.fecha + dias(ctx.delta_en_ventana(0, 5)))
                  for parte in partir_monto(ctx, cargo.monto, 2))
    return _Siembra(replace(e, casos=_recaso(e, CASO_SIN_CFDI, CASO_SUMA_AJENA),
                            cfdi=ExpectativaCfdi(tuple(c.uuid for c in cfdis), EVIDENCIA_SIN_AFINIDAD)), cfdis)


def _empate(ctx: Contexto, base: _Base, e: Expectativa) -> _Siembra:
    """Un CFDI ajeno del mismo monto y más cercano en fecha: solo la afinidad decide."""
    cargo = base.cargos[e.clave_cargo]
    cfdi = cfdi_comercio(ctx, _comercio_ajeno(ctx, descripcion_cruda(cargo)), cargo.monto, cargo.fecha)
    return _Siembra(replace(e, casos=_recaso(e, CASO_NORMAL, CASO_EMPATE),
                            cfdi=replace(e.cfdi, prohibidos=(cfdi.uuid,))), (cfdi,))


def _agregador(ctx: Contexto, base: _Base, e: Expectativa) -> _Siembra:
    """El descriptor de una pasarela que no nombra al comercio: el CFDI propio queda por revisar."""
    cargo = base.cargos[e.clave_cargo]
    nuevo = replace(cargo, descriptor=f"{PASARELA} {ctx.entero(PEDIDO_MIN, PEDIDO_MAX)}", ciudad=CIUDAD_PASARELA)
    return _Siembra(replace(e, casos=_recaso(e, CASO_NORMAL, CASO_AGREGADOR),
                            cfdi=replace(e.cfdi, evidencia=EVIDENCIA_SIN_AFINIDAD)), cargo=nuevo)


def _empate_elegible(base: _Base, e: Expectativa) -> bool:
    return _normal(e) and base.cfdis[e.cfdi.esperados[0]].fecha_emision != base.cargos[e.clave_cargo].fecha


def _agregador_elegible(base: _Base, e: Expectativa) -> bool:
    cargo = base.cargos[e.clave_cargo]
    comercio = cargo.comercio_requerido()
    pasarela = f"{PASARELA} {PEDIDO_MIN} {CIUDAD_PASARELA}"
    original = descripcion_cruda(cargo)
    repetido = any(c.cargo_id != cargo.cargo_id and descripcion_cruda(c) == original for c in base.cargos.values())
    return (_normal(e) and e.libro_requerido().esperado is None and repetido
            and nombres_ajenos(pasarela, comercio.razon_social))


_Elegible = Callable[[_Base, Expectativa], bool]
_Sembrador = Callable[[Contexto, _Base, Expectativa], _Siembra]
PLANES: Tuple[Tuple[_Elegible, _Sembrador], ...] = (
    (_sin_cfdi, _emisor_ajeno),
    (_sin_cfdi_para_suma, _suma_ajena),
    (_empate_elegible, _empate),
    (_agregador_elegible, _agregador),
)


def _montos(cargos: Iterable[Cargo], cfdis: Iterable[Cfdi]) -> List[Tuple[Decimal, str]]:
    montos = [(c.monto, "MXN") for c in cargos]
    montos += [(c.monto_original, c.moneda_original) for c in cargos if c.moneda_original != "MXN"]
    montos += [(c.total_mxn, "MXN") for c in cfdis]
    montos += [(c.total, c.moneda) for c in cfdis if c.moneda != "MXN"]
    return montos


def _sembrar_uno(ctx: Contexto, base: _Base, elegibles: Sequence[Expectativa], sembrador: _Sembrador) -> _Siembra:
    """El primer cargo elegible (en orden barajado) que admite la siembra."""
    ultimo = "sin cargos elegibles"
    for e in ctx.barajar(elegibles):
        try:
            return sembrador(ctx, base, e)
        except RuntimeError as exc:
            ultimo = str(exc)
    raise RuntimeError(f"no se pudo sembrar un caso de afinidad ({ultimo})")


def _con_folios(existentes: Sequence[Cfdi], nuevos: Sequence[Cfdi]) -> Tuple[Cfdi, ...]:
    """Cada CFDI nuevo toma el folio siguiente al mayor de su emisor y serie."""
    ultimos: Dict[Tuple[str, str, str], int] = {}
    for c in existentes:
        llave = (c.rfc_emisor, c.nombre_emisor, c.serie)
        ultimos[llave] = max(ultimos.get(llave, FOLIO_INICIAL - 1), int(c.folio))
    salida = []
    for c in sorted(nuevos, key=lambda x: (x.fecha_emision, x.uuid)):
        llave = (c.rfc_emisor, c.nombre_emisor, c.serie)
        ultimos[llave] = ultimos.get(llave, FOLIO_INICIAL - 1) + 1
        salida.append(replace(c, folio=str(ultimos[llave])))
    return tuple(salida)


def _cargo_final(siembra: Optional[_Siembra], cargo: Cargo) -> Cargo:
    return siembra.cargo if siembra is not None and siembra.cargo is not None else cargo


def sembrar_afinidad(config: ConfigGenerador, intento: int, cargos: Tuple[Cargo, ...], cfdis: Tuple[Cfdi, ...],
                     expectativas: Tuple[Expectativa, ...], veredictos: Sequence[VeredictoHumano],
                     inyecciones: Sequence[InyeccionSembrada]
                     ) -> Tuple[Tuple[Cargo, ...], Tuple[Cfdi, ...], Tuple[Expectativa, ...]]:
    """Cargos, CFDIs (ordenados por UUID) y expectativas con los cuatro casos de afinidad sembrados."""
    ctx = Contexto(config, intento, SAL_AFINIDAD)
    ctx.ocupar(_montos(cargos, cfdis), (c.uuid for c in cfdis))
    vetados = frozenset(v.cargo_id for v in veredictos) | frozenset(s.cargo_id for s in inyecciones if s.cargo_id)
    base = _Base({c.cargo_id: c for c in cargos}, {c.uuid: c for c in cfdis}, vetados)
    siembras: Dict[str, _Siembra] = {}
    for elegible, sembrador in PLANES:
        candidatos = [e for e in expectativas if e.clave_cargo not in siembras and base.limpio(e) and elegible(base, e)]
        siembra = _sembrar_uno(ctx, base, candidatos, sembrador)
        siembras[siembra.expectativa.clave_cargo] = siembra
    nuevos = _con_folios(cfdis, [c for s in siembras.values() for c in s.cfdis])
    cargos_finales = tuple(_cargo_final(siembras.get(c.cargo_id), c) for c in cargos)
    expectativas_finales = tuple(siembras[e.clave_cargo].expectativa if e.clave_cargo in siembras else e
                                 for e in expectativas)
    return cargos_finales, tuple(sorted(cfdis + nuevos, key=lambda c: c.uuid)), expectativas_finales
