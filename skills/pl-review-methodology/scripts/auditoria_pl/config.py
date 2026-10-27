"""Configuración del revisor (`auditoria_pl_config/v1`), leída en modo estricto.

Cada llave que este módulo acepta la usa alguna regla. Una llave que sobra o
falta detiene la lectura, de modo que la config no puede prometer algo que el
código no hace.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Any, List, Mapping, Optional, Tuple

from .dinero import CERO
from .validacion import (
    ErrorEntrada,
    exigir_llaves,
    exigir_objeto,
    leer_codigo,
    leer_codigos,
    leer_entero,
    leer_monto,
    leer_porcentaje,
    leer_texto,
)

ESQUEMA_CONFIG = "auditoria_pl_config/v1"
RUBROS: Tuple[str, ...] = ("ingreso", "costo", "gasto_venta", "gasto_admin", "bajo_ebitda")
RUBRO_INGRESO = "ingreso"
# Orden de presentación de las métricas: el de un estado de resultados.
METRICAS: Tuple[str, ...] = ("margen_bruto", "gasto_venta", "gasto_admin", "ebitda")
LADOS: Tuple[str, ...] = ("alto", "bajo")


@dataclass(frozen=True)
class CatalogoRubros:
    """Pares (prefijo, rubro). Ningún prefijo es prefijo de otro."""

    pares: Tuple[Tuple[str, str], ...]

    def rubro_de(self, cuenta: str) -> Optional[str]:
        for prefijo, rubro in self.pares:
            if cuenta.startswith(prefijo):
                return rubro
        return None


@dataclass(frozen=True)
class Banda:
    minimo_pct: Decimal
    maximo_pct: Decimal
    favorable: str


@dataclass(frozen=True)
class ReglasMadurez:
    dias_minimos_tras_cierre: int
    cuentas_nomina: Tuple[str, ...]
    provisiones_obligatorias: Tuple[str, ...]


@dataclass(frozen=True)
class ReglasPublicidad:
    cuenta: str
    objetivo_pct: Decimal
    alerta_pct: Decimal


@dataclass(frozen=True)
class ReglasMaterialidad:
    piso_monto: Decimal
    piso_pct_ingreso: Decimal
    piso_mencion: Decimal
    variacion_pct_minima: Decimal
    tope_materiales: int


@dataclass(frozen=True)
class ConfigAuditoria:
    rubros: CatalogoRubros
    cuentas_sin_polizas_manuales: Tuple[str, ...]
    madurez: ReglasMadurez
    bandas: Mapping[str, Banda]
    publicidad: ReglasPublicidad
    materialidad: ReglasMaterialidad


def _leer_rubros(crudo: Any) -> CatalogoRubros:
    objeto = exigir_objeto(crudo, "rubros")
    exigir_llaves(objeto, "rubros", RUBROS)
    pares: List[Tuple[str, str]] = []
    for rubro in RUBROS:
        prefijos = leer_codigos(objeto[rubro], f"rubros.{rubro}")
        if rubro == RUBRO_INGRESO and not prefijos:
            raise ErrorEntrada("rubros.ingreso: no puede ir vacío (sin ingreso no hay base)")
        pares.extend((prefijo, rubro) for prefijo in prefijos)
    for i, (uno, rubro_uno) in enumerate(pares):
        for otro, rubro_otro in pares[i + 1 :]:
            if uno.startswith(otro) or otro.startswith(uno):
                raise ErrorEntrada(f"rubros: el prefijo {uno!r} ({rubro_uno}) se traslapa con {otro!r} ({rubro_otro})")
    return CatalogoRubros(pares=tuple(pares))


def _leer_cuentas_sin_polizas(crudo: Any, rubros: CatalogoRubros) -> Tuple[str, ...]:
    cuentas = leer_codigos(crudo, "cuentas_sin_polizas_manuales")
    for cuenta in cuentas:
        if rubros.rubro_de(cuenta) != RUBRO_INGRESO:
            raise ErrorEntrada(
                f"cuentas_sin_polizas_manuales: la cuenta {cuenta!r} no cae en ningún prefijo de rubros.ingreso"
            )
    return tuple(sorted(cuentas))


def _leer_madurez(crudo: Any) -> ReglasMadurez:
    objeto = exigir_objeto(crudo, "madurez")
    exigir_llaves(objeto, "madurez", ("dias_minimos_tras_cierre", "cuentas_nomina", "provisiones_obligatorias"))
    return ReglasMadurez(
        dias_minimos_tras_cierre=leer_entero(objeto["dias_minimos_tras_cierre"], "madurez.dias_minimos_tras_cierre", 0),
        cuentas_nomina=tuple(sorted(leer_codigos(objeto["cuentas_nomina"], "madurez.cuentas_nomina"))),
        provisiones_obligatorias=tuple(
            sorted(leer_codigos(objeto["provisiones_obligatorias"], "madurez.provisiones_obligatorias"))
        ),
    )


def _leer_banda(crudo: Any, ruta: str) -> Banda:
    objeto = exigir_objeto(crudo, ruta)
    exigir_llaves(objeto, ruta, ("minimo_pct", "maximo_pct", "favorable"))
    minimo = leer_monto(objeto["minimo_pct"], f"{ruta}.minimo_pct")
    maximo = leer_monto(objeto["maximo_pct"], f"{ruta}.maximo_pct")
    if minimo > maximo:
        raise ErrorEntrada(f"{ruta}: minimo_pct ({minimo}) es mayor que maximo_pct ({maximo})")
    favorable = leer_texto(objeto["favorable"], f"{ruta}.favorable")
    if favorable not in LADOS:
        raise ErrorEntrada(f"{ruta}.favorable: debe ser 'alto' o 'bajo', llegó {favorable!r}")
    return Banda(minimo_pct=minimo, maximo_pct=maximo, favorable=favorable)


def _leer_bandas(crudo: Any) -> Mapping[str, Banda]:
    objeto = exigir_objeto(crudo, "bandas")
    exigir_llaves(objeto, "bandas", (), opcionales=METRICAS)
    return MappingProxyType({m: _leer_banda(objeto[m], f"bandas.{m}") for m in METRICAS if m in objeto})


def _leer_publicidad(crudo: Any) -> ReglasPublicidad:
    objeto = exigir_objeto(crudo, "publicidad")
    exigir_llaves(objeto, "publicidad", ("cuenta", "objetivo_pct", "alerta_pct"))
    objetivo = leer_porcentaje(objeto["objetivo_pct"], "publicidad.objetivo_pct")
    alerta = leer_porcentaje(objeto["alerta_pct"], "publicidad.alerta_pct")
    if objetivo > alerta:
        raise ErrorEntrada(f"publicidad: objetivo_pct ({objetivo}) no puede superar alerta_pct ({alerta})")
    return ReglasPublicidad(
        cuenta=leer_codigo(objeto["cuenta"], "publicidad.cuenta"), objetivo_pct=objetivo, alerta_pct=alerta
    )


def _leer_materialidad(crudo: Any) -> ReglasMaterialidad:
    ruta = "materialidad"
    objeto = exigir_objeto(crudo, ruta)
    llaves = ("piso_monto", "piso_pct_ingreso", "piso_mencion", "variacion_pct_minima", "tope_materiales")
    exigir_llaves(objeto, ruta, llaves)
    piso_monto = leer_monto(objeto["piso_monto"], f"{ruta}.piso_monto")
    piso_mencion = leer_monto(objeto["piso_mencion"], f"{ruta}.piso_mencion")
    if not CERO < piso_mencion <= piso_monto:
        raise ErrorEntrada(
            f"{ruta}: se requiere 0 < piso_mencion <= piso_monto; llegó piso_mencion={piso_mencion}, "
            f"piso_monto={piso_monto}"
        )
    return ReglasMaterialidad(
        piso_monto=piso_monto,
        piso_pct_ingreso=leer_porcentaje(objeto["piso_pct_ingreso"], f"{ruta}.piso_pct_ingreso"),
        piso_mencion=piso_mencion,
        variacion_pct_minima=leer_porcentaje(objeto["variacion_pct_minima"], f"{ruta}.variacion_pct_minima"),
        tope_materiales=leer_entero(objeto["tope_materiales"], f"{ruta}.tope_materiales", 1),
    )


def leer_config(crudo: Any) -> ConfigAuditoria:
    """Valida el JSON decodificado de la config y devuelve su forma tipada e inmutable."""
    objeto = exigir_objeto(crudo, "")
    exigir_llaves(
        objeto,
        "",
        ("esquema", "rubros", "cuentas_sin_polizas_manuales", "madurez", "bandas", "publicidad", "materialidad"),
    )
    if objeto["esquema"] != ESQUEMA_CONFIG:
        raise ErrorEntrada(f"esquema: se esperaba {ESQUEMA_CONFIG!r}, llegó {objeto['esquema']!r}")
    rubros = _leer_rubros(objeto["rubros"])
    return ConfigAuditoria(
        rubros=rubros,
        cuentas_sin_polizas_manuales=_leer_cuentas_sin_polizas(objeto["cuentas_sin_polizas_manuales"], rubros),
        madurez=_leer_madurez(objeto["madurez"]),
        bandas=_leer_bandas(objeto["bandas"]),
        publicidad=_leer_publicidad(objeto["publicidad"]),
        materialidad=_leer_materialidad(objeto["materialidad"]),
    )
