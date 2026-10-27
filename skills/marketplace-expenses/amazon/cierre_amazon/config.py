"""Config del cierre (spec, sección 3): lectura, validación y valores inmutables."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .dinero import a_tasa
from .errores import ErrorConfig
from .huso import interpretar_huso

ESQUEMA_CONFIG = "config_cierre_amazon/v1"

CATEGORIA_VENTA = "venta"
CATEGORIA_REEMBOLSO = "reembolso"
CATEGORIA_CARGO_PERIODO = "cargo_periodo"
CATEGORIA_PUBLICIDAD = "publicidad"
CATEGORIA_TRANSFERENCIA = "transferencia"
CATEGORIA_SIN_CLASIFICAR = "sin_clasificar"
CATEGORIAS_CONFIGURABLES = frozenset({
    CATEGORIA_VENTA, CATEGORIA_REEMBOLSO, CATEGORIA_CARGO_PERIODO,
    CATEGORIA_PUBLICIDAD, CATEGORIA_TRANSFERENCIA,
})
CATEGORIAS_DE_PEDIDO = frozenset({CATEGORIA_VENTA, CATEGORIA_REEMBOLSO})

FUENTE_LIQUIDACION = "liquidacion"
FUENTE_CONSOLA = "consola"
FUENTE_FACTURA = "factura"
FUENTES_PUBLICIDAD = (FUENTE_LIQUIDACION, FUENTE_CONSOLA, FUENTE_FACTURA)

CONCEPTOS_TARIFA = ("comision", "logistica", "otras_tarifas")


@dataclass(frozen=True)
class RangoTasa:
    """Rango de referencia inclusivo para una tasa efectiva."""

    minimo: Decimal
    maximo: Decimal

    def contiene(self, tasa: Decimal) -> bool:
        return self.minimo <= tasa <= self.maximo


@dataclass(frozen=True)
class Config:
    """Parámetros del cierre. Se construye solo con `config_desde_dict`."""

    moneda: str
    huso_cierre_texto: str
    huso_cierre: timezone
    tasa_iva: Decimal
    tipos: Mapping[str, str]
    fuente_publicidad: str
    tolerancia_publicidad: Decimal
    tasa_retencion: Decimal
    banda_retencion: Decimal
    referencias: Mapping[str, RangoTasa]

    def categoria(self, tipo: str) -> str:
        """Categoría de un `Tipo` de liquidación; lo no mapeado queda sin clasificar."""
        return self.tipos.get(tipo, CATEGORIA_SIN_CLASIFICAR)


def _seccion(datos: Mapping[str, Any], clave: str) -> Mapping[str, Any]:
    valor = datos.get(clave)
    if not isinstance(valor, dict):
        raise ErrorConfig(f"falta la sección '{clave}' o no es un objeto")
    return valor


def _texto(datos: Mapping[str, Any], clave: str, nombre: str) -> str:
    valor = datos.get(clave)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorConfig(f"'{nombre}' debe ser un texto no vacío")
    return valor.strip()


def _tasa(datos: Mapping[str, Any], clave: str, nombre: str) -> Decimal:
    if clave not in datos:
        raise ErrorConfig(f"falta '{nombre}'")
    try:
        return a_tasa(datos[clave])
    except ValueError as exc:
        raise ErrorConfig(f"'{nombre}' inválido: {exc}") from exc


def _exigir(condicion: bool, mensaje: str) -> None:
    if not condicion:
        raise ErrorConfig(mensaje)


def _tipos(datos: Mapping[str, Any]) -> Mapping[str, str]:
    tipos = datos.get("tipos")
    if not isinstance(tipos, dict) or not tipos:
        raise ErrorConfig("'tipos' debe ser un objeto no vacío")
    for tipo, categoria in tipos.items():
        _exigir(categoria in CATEGORIAS_CONFIGURABLES,
                f"tipos['{tipo}']: categoría desconocida {categoria!r}; "
                f"válidas: {sorted(CATEGORIAS_CONFIGURABLES)}")
    return MappingProxyType(dict(sorted(tipos.items())))


def _referencias(datos: Mapping[str, Any]) -> Mapping[str, RangoTasa]:
    crudas = datos.get("referencias_tarifas", {})
    _exigir(isinstance(crudas, dict), "'referencias_tarifas' debe ser un objeto")
    rangos = {}
    for concepto in sorted(crudas):
        _exigir(concepto in CONCEPTOS_TARIFA,
                f"referencias_tarifas: concepto desconocido '{concepto}'; válidos: {list(CONCEPTOS_TARIFA)}")
        rango = _seccion(crudas, concepto)
        minimo = _tasa(rango, "min", f"referencias_tarifas.{concepto}.min")
        maximo = _tasa(rango, "max", f"referencias_tarifas.{concepto}.max")
        _exigir(minimo <= maximo, f"referencias_tarifas.{concepto}: min debe ser <= max")
        rangos[concepto] = RangoTasa(minimo, maximo)
    return MappingProxyType(rangos)


def config_desde_dict(datos: Mapping[str, Any]) -> Config:
    """Valida un dict con la forma de la spec y devuelve una `Config` inmutable."""
    _exigir(datos.get("esquema") == ESQUEMA_CONFIG, f"'esquema' debe ser {ESQUEMA_CONFIG!r}")
    huso_texto = _texto(datos, "huso_cierre", "huso_cierre")
    try:
        huso_cierre = interpretar_huso(huso_texto)
    except ValueError as exc:
        raise ErrorConfig(f"'huso_cierre' inválido: {exc}") from exc
    tasa_iva = _tasa(datos, "tasa_iva", "tasa_iva")
    _exigir(Decimal("0") <= tasa_iva < Decimal("1"), "'tasa_iva' debe estar en [0, 1)")

    publicidad = _seccion(datos, "publicidad")
    fuente = _texto(publicidad, "fuente_autoritativa", "publicidad.fuente_autoritativa")
    _exigir(fuente in FUENTES_PUBLICIDAD,
            f"publicidad.fuente_autoritativa debe ser una de {list(FUENTES_PUBLICIDAD)}")
    tolerancia = _tasa(publicidad, "tolerancia", "publicidad.tolerancia")
    _exigir(tolerancia >= 0, "'publicidad.tolerancia' debe ser >= 0")

    retencion = _seccion(datos, "retencion")
    tasa_retencion = _tasa(retencion, "tasa", "retencion.tasa")
    _exigir(Decimal("0") < tasa_retencion < Decimal("1"), "'retencion.tasa' debe estar en (0, 1)")
    banda = _tasa(retencion, "banda", "retencion.banda")
    _exigir(banda >= 0, "'retencion.banda' debe ser >= 0")

    return Config(
        moneda=_texto(datos, "moneda", "moneda"),
        huso_cierre_texto=huso_texto,
        huso_cierre=huso_cierre,
        tasa_iva=tasa_iva,
        tipos=_tipos(datos),
        fuente_publicidad=fuente,
        tolerancia_publicidad=tolerancia,
        tasa_retencion=tasa_retencion,
        banda_retencion=banda,
        referencias=_referencias(datos),
    )


def cargar_config(ruta: Path) -> Config:
    """Lee y valida un archivo de config JSON."""
    if not ruta.is_file():
        raise ErrorConfig(f"el archivo de config no existe: {ruta.name}")
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ErrorConfig(f"{ruta.name}: no es un JSON legible ({exc})") from exc
    if not isinstance(datos, dict):
        raise ErrorConfig(f"{ruta.name}: la config debe ser un objeto JSON")
    return config_desde_dict(datos)


def con_fuente_publicidad(config: Config, fuente: str) -> Config:
    """Copia de la config con otra fuente autoritativa de publicidad."""
    if fuente not in FUENTES_PUBLICIDAD:
        raise ErrorConfig(f"fuente de publicidad desconocida {fuente!r}; válidas: {list(FUENTES_PUBLICIDAD)}")
    return replace(config, fuente_publicidad=fuente)
