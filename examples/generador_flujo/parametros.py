"""Parámetros del generador de insumos de flujo (`parametros_generador_flujo/v1`).

Todos los montos y conteos de ejemplo viven en `parametros.json`; aquí solo se
valida su forma. Los montos se escriben como texto decimal, nunca como float.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, FrozenSet, Mapping, Optional, Tuple

ESQUEMA_PARAMETROS = "parametros_generador_flujo/v1"
CENTAVO = Decimal("0.01")
DIA_MAXIMO_FIJO = 28
PATRON_FECHA = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PATRON_MONEDA = re.compile(r"^[A-Z]{3}$")
LLAVES_RAIZ = frozenset({"esquema", "semilla", "corte", "moneda", "dias_programacion", "saldos_bancarios",
                         "cxc_antiguedad", "cxp_programadas", "nomina", "impuestos"})
LLAVES_RANGO = frozenset({"monto_min", "monto_max"})


class ErrorParametros(ValueError):
    """Los parámetros del generador no cumplen su esquema."""


@dataclass(frozen=True)
class RangoMonto:
    minimo: Decimal
    maximo: Decimal


@dataclass(frozen=True)
class Cuenta:
    cuenta: str
    banco: str


@dataclass(frozen=True)
class ParamSaldos:
    cuentas: Tuple[Cuenta, ...]
    rango: RangoMonto


@dataclass(frozen=True)
class ParamAcreedores:
    """Registros de CxC con saldo acreedor; el rango es del valor absoluto del saldo."""

    registros: int
    rango: RangoMonto


@dataclass(frozen=True)
class ParamCxc:
    clientes: int
    facturas: int
    plazos_dias: Tuple[int, ...]
    emision_dias_atras_max: int
    rango: RangoMonto
    antiguedades_borde: Tuple[int, ...]
    saldos_acreedores: ParamAcreedores
    saldos_cero: int


@dataclass(frozen=True)
class ParamCxp:
    proveedores: int
    facturas: int
    rango: RangoMonto
    dias_borde: Tuple[int, ...]
    dias_vencidos: Tuple[int, ...]


@dataclass(frozen=True)
class ParamNomina:
    dia_quincena: int
    descripcion: str
    rango: RangoMonto


@dataclass(frozen=True)
class ConceptoImpuesto:
    impuesto: str
    rango: RangoMonto


@dataclass(frozen=True)
class ParamImpuestos:
    dia_limite: int
    conceptos: Tuple[ConceptoImpuesto, ...]


@dataclass(frozen=True)
class Parametros:
    semilla: int
    corte: date
    moneda: str
    dias_programacion: int
    saldos: ParamSaldos
    cxc: ParamCxc
    cxp: ParamCxp
    nomina: ParamNomina
    impuestos: ParamImpuestos


# --- validadores elementales ------------------------------------------------------------


def _objeto(valor: object, contexto: str, llaves: FrozenSet[str]) -> Mapping[str, Any]:
    if not isinstance(valor, dict):
        raise ErrorParametros(f"{contexto} debe ser un objeto JSON")
    faltan = sorted(llaves - set(valor))
    if faltan:
        raise ErrorParametros(f"{contexto}: faltan llaves {', '.join(faltan)}")
    sobran = sorted(set(valor) - llaves)
    if sobran:
        raise ErrorParametros(f"{contexto}: llaves desconocidas {', '.join(sobran)}")
    return valor


def _entero(valor: object, contexto: str, minimo: Optional[int] = None) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorParametros(f"{contexto} debe ser un entero")
    if minimo is not None and valor < minimo:
        raise ErrorParametros(f"{contexto} debe ser al menos {minimo}")
    return valor


def _conteo(valor: object, contexto: str) -> int:
    numero = _entero(valor, contexto)
    if numero <= 0:
        raise ErrorParametros(f"{contexto} debe ser un entero mayor que cero")
    return numero


def _dia_fijo(valor: object, contexto: str) -> int:
    dia = _entero(valor, contexto, minimo=1)
    if dia > DIA_MAXIMO_FIJO:
        raise ErrorParametros(f"{contexto} debe estar entre 1 y {DIA_MAXIMO_FIJO} para existir en todo mes")
    return dia


def _enteros(valor: object, contexto: str) -> Tuple[int, ...]:
    if not isinstance(valor, list):
        raise ErrorParametros(f"{contexto} debe ser una lista de enteros")
    return tuple(_entero(v, f"{contexto}[{i}]") for i, v in enumerate(valor))


def _texto(valor: object, contexto: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorParametros(f"{contexto} debe ser texto no vacío")
    return valor.strip()


def _monto(valor: object, contexto: str) -> Decimal:
    if not isinstance(valor, str):
        raise ErrorParametros(f"{contexto} debe ser texto decimal como \"1000.00\"")
    try:
        numero = Decimal(valor)
    except InvalidOperation:
        raise ErrorParametros(f"{contexto}: '{valor}' no es texto decimal") from None
    if not numero.is_finite():
        raise ErrorParametros(f"{contexto}: '{valor}' no es un monto finito")
    return numero.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _rango(datos: Mapping[str, Any], contexto: str, positivo: bool = True) -> RangoMonto:
    minimo = _monto(datos["monto_min"], f"{contexto}.monto_min")
    maximo = _monto(datos["monto_max"], f"{contexto}.monto_max")
    if minimo > maximo:
        raise ErrorParametros(f"{contexto}: monto_min no puede ser mayor que monto_max")
    if positivo and minimo <= 0:
        raise ErrorParametros(f"{contexto}: monto_min debe ser mayor que cero")
    return RangoMonto(minimo=minimo, maximo=maximo)


# --- secciones --------------------------------------------------------------------------


def _cuenta(crudo: object, indice: int) -> Cuenta:
    contexto = f"saldos_bancarios.cuentas[{indice}]"
    datos = _objeto(crudo, contexto, frozenset({"cuenta", "banco"}))
    return Cuenta(
        cuenta=_texto(datos["cuenta"], f"{contexto}.cuenta"), banco=_texto(datos["banco"], f"{contexto}.banco"),
    )


def _saldos(crudo: object) -> ParamSaldos:
    datos = _objeto(crudo, "saldos_bancarios", LLAVES_RANGO | {"cuentas"})
    cuentas_crudas = datos["cuentas"]
    if not isinstance(cuentas_crudas, list) or not cuentas_crudas:
        raise ErrorParametros("saldos_bancarios.cuentas: se necesita al menos una cuenta")
    cuentas = tuple(_cuenta(c, i) for i, c in enumerate(cuentas_crudas))
    if len({c.cuenta for c in cuentas}) != len(cuentas):
        raise ErrorParametros("saldos_bancarios.cuentas: hay cuentas repetidas")
    return ParamSaldos(cuentas=cuentas, rango=_rango(datos, "saldos_bancarios", positivo=False))


def _acreedores(crudo: object) -> ParamAcreedores:
    contexto = "cxc_antiguedad.saldos_acreedores"
    datos = _objeto(crudo, contexto, LLAVES_RANGO | {"registros"})
    return ParamAcreedores(registros=_entero(datos["registros"], f"{contexto}.registros", minimo=0),
                           rango=_rango(datos, contexto))


def _cxc(crudo: object) -> ParamCxc:
    llaves = LLAVES_RANGO | {"clientes", "facturas", "plazos_dias", "emision_dias_atras_max", "antiguedades_borde",
                             "saldos_acreedores", "saldos_cero"}
    datos = _objeto(crudo, "cxc_antiguedad", llaves)
    plazos = tuple(_conteo(p, f"cxc_antiguedad.plazos_dias[{i}]") for i, p in enumerate(_enteros(
        datos["plazos_dias"], "cxc_antiguedad.plazos_dias")))
    if not plazos:
        raise ErrorParametros("cxc_antiguedad.plazos_dias necesita al menos un plazo")
    borde = _enteros(datos["antiguedades_borde"], "cxc_antiguedad.antiguedades_borde")
    for antiguedad in borde:
        if antiguedad < 0 and max(plazos) < -antiguedad:
            raise ErrorParametros(
                f"cxc_antiguedad: ningún plazo de plazos_dias alcanza la antigüedad {antiguedad} "
                "sin emitir la factura después del corte"
            )
    facturas = _conteo(datos["facturas"], "cxc_antiguedad.facturas")
    if facturas < len(borde):
        raise ErrorParametros("cxc_antiguedad.facturas debe ser al menos el número de antiguedades_borde")
    return ParamCxc(
        clientes=_conteo(datos["clientes"], "cxc_antiguedad.clientes"), facturas=facturas, plazos_dias=plazos,
        emision_dias_atras_max=_entero(datos["emision_dias_atras_max"], "cxc_antiguedad.emision_dias_atras_max", 0),
        rango=_rango(datos, "cxc_antiguedad"), antiguedades_borde=borde,
        saldos_acreedores=_acreedores(datos["saldos_acreedores"]),
        saldos_cero=_entero(datos["saldos_cero"], "cxc_antiguedad.saldos_cero", minimo=0),
    )


def _dias_vencidos(valor: object) -> Tuple[int, ...]:
    dias = _enteros(valor, "cxp_programadas.dias_vencidos")
    if any(d >= 0 for d in dias):
        raise ErrorParametros("cxp_programadas.dias_vencidos solo admite días negativos (antes del corte)")
    if len(set(dias)) != len(dias):
        raise ErrorParametros("cxp_programadas.dias_vencidos tiene días repetidos")
    return dias


def _cxp(crudo: object, dias_programacion: int) -> ParamCxp:
    llaves = LLAVES_RANGO | {"proveedores", "facturas", "dias_borde", "dias_vencidos"}
    datos = _objeto(crudo, "cxp_programadas", llaves)
    borde = _enteros(datos["dias_borde"], "cxp_programadas.dias_borde")
    if any(not 0 <= d <= dias_programacion for d in borde):
        raise ErrorParametros("cxp_programadas.dias_borde debe caer entre 0 y dias_programacion")
    facturas = _conteo(datos["facturas"], "cxp_programadas.facturas")
    if facturas < len(borde):
        raise ErrorParametros("cxp_programadas.facturas debe ser al menos el número de dias_borde")
    return ParamCxp(proveedores=_conteo(datos["proveedores"], "cxp_programadas.proveedores"), facturas=facturas,
                    rango=_rango(datos, "cxp_programadas"), dias_borde=borde,
                    dias_vencidos=_dias_vencidos(datos["dias_vencidos"]))


def _nomina(crudo: object) -> ParamNomina:
    datos = _objeto(crudo, "nomina", LLAVES_RANGO | {"dia_quincena", "descripcion"})
    return ParamNomina(dia_quincena=_dia_fijo(datos["dia_quincena"], "nomina.dia_quincena"),
                       descripcion=_texto(datos["descripcion"], "nomina.descripcion"), rango=_rango(datos, "nomina"))


def _impuestos(crudo: object) -> ParamImpuestos:
    datos = _objeto(crudo, "impuestos", frozenset({"dia_limite", "conceptos"}))
    crudos = datos["conceptos"]
    if not isinstance(crudos, list) or not crudos:
        raise ErrorParametros("impuestos.conceptos necesita al menos un impuesto")
    conceptos = tuple(_concepto(c, i) for i, c in enumerate(crudos))
    if len({c.impuesto for c in conceptos}) != len(conceptos):
        raise ErrorParametros("impuestos.conceptos: hay impuestos repetidos")
    return ParamImpuestos(dia_limite=_dia_fijo(datos["dia_limite"], "impuestos.dia_limite"), conceptos=conceptos)


def _concepto(crudo: object, indice: int) -> ConceptoImpuesto:
    contexto = f"impuestos.conceptos[{indice}]"
    datos = _objeto(crudo, contexto, LLAVES_RANGO | {"impuesto"})
    return ConceptoImpuesto(impuesto=_texto(datos["impuesto"], f"{contexto}.impuesto"), rango=_rango(datos, contexto))


def _corte(valor: object) -> date:
    if not isinstance(valor, str) or not PATRON_FECHA.match(valor):
        raise ErrorParametros("corte debe ser una fecha AAAA-MM-DD")
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErrorParametros(f"corte '{valor}' no es una fecha válida") from None


def parametros_desde_dict(crudo: object) -> Parametros:
    datos = _objeto(crudo, "los parámetros", LLAVES_RAIZ)
    if datos["esquema"] != ESQUEMA_PARAMETROS:
        raise ErrorParametros(f"esquema {datos['esquema']!r} no soportado (se espera '{ESQUEMA_PARAMETROS}')")
    moneda = datos["moneda"]
    if not isinstance(moneda, str) or not PATRON_MONEDA.match(moneda):
        raise ErrorParametros("moneda debe ser un código de tres letras mayúsculas")
    dias = _conteo(datos["dias_programacion"], "dias_programacion")
    return Parametros(
        semilla=_entero(datos["semilla"], "semilla"), corte=_corte(datos["corte"]), moneda=moneda,
        dias_programacion=dias, saldos=_saldos(datos["saldos_bancarios"]), cxc=_cxc(datos["cxc_antiguedad"]),
        cxp=_cxp(datos["cxp_programadas"], dias), nomina=_nomina(datos["nomina"]),
        impuestos=_impuestos(datos["impuestos"]),
    )


def cargar_parametros(ruta: Path) -> Parametros:
    try:
        crudo = json.loads(ruta.read_text(encoding="utf-8"), parse_float=Decimal)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorParametros(f"no se pudieron leer los parámetros {ruta}: {exc}") from exc
    return parametros_desde_dict(crudo)
