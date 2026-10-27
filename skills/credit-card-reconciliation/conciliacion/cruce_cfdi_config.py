"""Parámetros del cruce cargo ↔ CFDI: valores de ejemplo, lectura desde JSON y validación de rangos.

Los valores por defecto son de ejemplo (redondos) y coinciden con los parámetros
del conjunto sintético; no son una calibración. `config/cruce_cfdi.example.json`
es la misma config escrita como archivo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple

from .cruce_cfdi_insumos import a_monto
from .cruce_cfdi_modelo import ConfigInvalida

ESQUEMA_CONFIG = "cruce_cfdi_config/v1"
# Techos duros de la búsqueda de sumas: acotan Σ C(N, k) por par (cargo, emisor).
TECHO_CFDIS_POR_SUMA = 4
TECHO_CANDIDATOS_POR_EMISOR = 20
PISO_CFDIS_POR_SUMA = 2

# Llave JSON -> campo del dataclass, agrupadas por sección (None = llave de primer nivel).
_SECCIONES: Dict[Any, Dict[str, str]] = {
    None: {"rfc_empresa": "rfc_empresa", "rfcs_genericos": "rfcs_genericos", "afinidad_minima": "afinidad_minima"},
    "ventana_dias": {"min": "ventana_min", "max": "ventana_max"},
    "tolerancias": {
        "uno_a_uno": "tolerancia_uno_a_uno",
        "moneda_original": "tolerancia_moneda_original",
        "suma": "tolerancia_suma",
    },
    "suma": {
        "min_cfdis": "suma_min_cfdis",
        "max_cfdis": "suma_max_cfdis",
        "max_candidatos_por_emisor": "suma_max_candidatos",
    },
    "diagnostico": {
        "banda_fuera_de_tolerancia": "banda_fuera_de_tolerancia",
        "margen_fuera_de_ventana_dias": "margen_fuera_de_ventana_dias",
    },
}


@dataclass(frozen=True)
class ConfigCruce:
    rfc_empresa: str = "RFC_EMPRESA_DEMO"
    rfcs_genericos: Tuple[str, ...] = ("XAXX010101000", "XEXX010101000")
    ventana_min: int = -3
    ventana_max: int = 10
    tolerancia_uno_a_uno: Decimal = Decimal("1.00")
    tolerancia_moneda_original: Decimal = Decimal("1.00")
    tolerancia_suma: Decimal = Decimal("1.00")
    suma_min_cfdis: int = 2
    suma_max_cfdis: int = 3
    suma_max_candidatos: int = 10
    afinidad_minima: Decimal = Decimal("0.50")
    banda_fuera_de_tolerancia: Decimal = Decimal("5.00")
    margen_fuera_de_ventana_dias: int = 10

    def __post_init__(self) -> None:
        problemas = _problemas(self)
        if problemas:
            raise ConfigInvalida("; ".join(problemas))


def _problemas(c: ConfigCruce) -> Tuple[str, ...]:
    reglas = (
        (bool(c.rfc_empresa.strip()), "rfc_empresa no puede estar vacío"),
        (all(r.strip() for r in c.rfcs_genericos), "rfcs_genericos no admite cadenas vacías"),
        (c.ventana_min <= c.ventana_max,
         f"ventana_dias: min ({c.ventana_min}) no puede ser mayor que max ({c.ventana_max})"),
        (c.tolerancia_uno_a_uno >= 0, "tolerancias.uno_a_uno no puede ser negativa"),
        (c.tolerancia_moneda_original >= 0, "tolerancias.moneda_original no puede ser negativa"),
        (c.tolerancia_suma >= 0, "tolerancias.suma no puede ser negativa"),
        (PISO_CFDIS_POR_SUMA <= c.suma_min_cfdis <= TECHO_CFDIS_POR_SUMA,
         f"suma.min_cfdis debe estar entre {PISO_CFDIS_POR_SUMA} y {TECHO_CFDIS_POR_SUMA}"),
        (PISO_CFDIS_POR_SUMA <= c.suma_max_cfdis <= TECHO_CFDIS_POR_SUMA,
         f"suma.max_cfdis debe estar entre {PISO_CFDIS_POR_SUMA} y {TECHO_CFDIS_POR_SUMA}"),
        (c.suma_min_cfdis <= c.suma_max_cfdis,
         f"suma.min_cfdis ({c.suma_min_cfdis}) no puede ser mayor que suma.max_cfdis ({c.suma_max_cfdis})"),
        (c.suma_max_cfdis <= c.suma_max_candidatos <= TECHO_CANDIDATOS_POR_EMISOR,
         f"suma.max_candidatos_por_emisor debe estar entre suma.max_cfdis y {TECHO_CANDIDATOS_POR_EMISOR}"),
        (0 <= c.afinidad_minima <= 1, "afinidad_minima debe estar entre 0 y 1"),
        (c.banda_fuera_de_tolerancia >= c.tolerancia_uno_a_uno,
         f"diagnostico.banda_fuera_de_tolerancia ({c.banda_fuera_de_tolerancia}) no puede ser menor que "
         f"tolerancias.uno_a_uno ({c.tolerancia_uno_a_uno})"),
        (c.margen_fuera_de_ventana_dias >= 0, "diagnostico.margen_fuera_de_ventana_dias no puede ser negativo"),
    )
    return tuple(mensaje for cumple, mensaje in reglas if not cumple)


_POR_DEFECTO = ConfigCruce()


def _convertir(campo: str, nombre_json: str, valor: Any) -> Any:
    """Valida el tipo JSON contra el del valor por defecto del campo y lo convierte."""
    referencia = getattr(_POR_DEFECTO, campo)
    if isinstance(referencia, int):
        if isinstance(valor, bool) or not isinstance(valor, int):
            raise ConfigInvalida(f"{nombre_json} debe ser un entero; llegó {valor!r}")
        return valor
    if isinstance(referencia, Decimal):
        return a_monto(valor, nombre_json, ConfigInvalida)
    if isinstance(referencia, str):
        if not isinstance(valor, str):
            raise ConfigInvalida(f"{nombre_json} debe ser texto; llegó {valor!r}")
        return valor
    if not isinstance(valor, list) or not all(isinstance(x, str) for x in valor):
        raise ConfigInvalida(f"{nombre_json} debe ser una lista de textos; llegó {valor!r}")
    return tuple(valor)


def _seccion(datos: Mapping[str, Any], seccion: str) -> Mapping[str, Any]:
    contenido = datos.get(seccion, {})
    if not isinstance(contenido, dict):
        raise ConfigInvalida(f"{seccion} debe ser un objeto")
    return contenido


def config_desde_dict(datos: Any) -> ConfigCruce:
    """Arma la config a partir de un objeto JSON; las llaves ausentes toman el valor de ejemplo."""
    if not isinstance(datos, dict):
        raise ConfigInvalida("la config debe ser un objeto JSON")
    esquema = datos.get("esquema", ESQUEMA_CONFIG)
    if esquema != ESQUEMA_CONFIG:
        raise ConfigInvalida(f"esquema de config no soportado: {esquema!r}")
    primer_nivel = set(_SECCIONES[None]) | {s for s in _SECCIONES if s is not None} | {"esquema"}
    desconocidas = sorted(set(datos) - primer_nivel)
    if desconocidas:
        raise ConfigInvalida(f"llaves desconocidas en la config: {', '.join(desconocidas)}")
    valores: Dict[str, Any] = {}
    for seccion, mapa in _SECCIONES.items():
        contenido = datos if seccion is None else _seccion(datos, seccion)
        if seccion is not None:
            sobrantes = sorted(set(contenido) - set(mapa))
            if sobrantes:
                raise ConfigInvalida(f"llaves desconocidas en {seccion}: {', '.join(sobrantes)}")
        for llave, campo in mapa.items():
            if llave in contenido:
                nombre_json = llave if seccion is None else f"{seccion}.{llave}"
                valores[campo] = _convertir(campo, nombre_json, contenido[llave])
    return ConfigCruce(**valores)


def _a_json(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, tuple):
        return list(valor)
    return valor


def config_a_dict(config: ConfigCruce) -> Dict[str, Any]:
    """La config efectiva con la forma del archivo de ejemplo (montos como cadenas)."""
    salida: Dict[str, Any] = {"esquema": ESQUEMA_CONFIG}
    for seccion, mapa in _SECCIONES.items():
        destino = salida if seccion is None else salida.setdefault(seccion, {})
        for llave, campo in mapa.items():
            destino[llave] = _a_json(getattr(config, campo))
    return salida


def cargar_config(ruta: Path) -> ConfigCruce:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigInvalida(f"no se puede leer la config {ruta}: {exc}") from None
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise ConfigInvalida(f"la config {ruta.name} no es JSON válido ({exc.msg})") from None
    return config_desde_dict(datos)
