"""Carga, validación y eco de la config del cruce con libro mayor.

Formato en `specs/cruce_libro.md` ("Config"). Llaves desconocidas, floats y enteros
booleanos se rechazan; lo que no viene en el archivo toma el valor por omisión.
"""
from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, Mapping, Optional

from .cruce_libro_insumos import ErrorInsumo, a_decimal_exacto, a_monto, leer_texto
from .cruce_libro_modelo import ESQUEMA_CONFIG, ConfigCruceLibro, VentanaDias
from .nombres import ReglasNombres

LLAVES_NOMBRES = ("largo_max_abreviatura", "largo_min_pieza", "largo_min_prefijo", "largo_min_raiz",
                  "min_nombres_stopword", "stopwords_fijas")


def _entero(valor: object, llave: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorInsumo(f"config: {llave} debe ser un entero ({valor!r}).")
    return valor


def _texto_no_vacio(valor: object, llave: str) -> str:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorInsumo(f"config: {llave} debe ser texto no vacío ({valor!r}).")
    return valor.strip()


def _lista_textos(valor: object, llave: str) -> frozenset[str]:
    if not isinstance(valor, list):
        raise ErrorInsumo(f"config: {llave} debe ser una lista de textos.")
    return frozenset(_texto_no_vacio(x, llave) for x in valor)


def _importe(valor: object, llave: str) -> Decimal:
    """Importe de config: solo texto (nunca float), cuantizado a centavos."""
    return a_monto(str(a_decimal_exacto(valor, f"config: {llave}")), f"config: {llave}")


def _ventana(valor: object, llave: str) -> VentanaDias:
    if not isinstance(valor, dict) or set(valor) != {"min", "max"}:
        raise ErrorInsumo(f"config: {llave} debe ser un objeto con exactamente min y max.")
    return VentanaDias(_entero(valor["min"], f"{llave}.min"), _entero(valor["max"], f"{llave}.max"))


def _cuentas(valor: object, llave: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(valor, dict) or not valor:
        raise ErrorInsumo(f"config: {llave} debe ser un objeto emisor -> cuenta.")
    return tuple(sorted((_texto_no_vacio(e, llave), _texto_no_vacio(c, llave)) for e, c in valor.items()))


def _reglas_nombres(valor: object, llave: str) -> ReglasNombres:
    if not isinstance(valor, dict):
        raise ErrorInsumo(f"config: {llave} debe ser un objeto.")
    desconocidas = sorted(set(valor) - set(LLAVES_NOMBRES))
    if desconocidas:
        raise ErrorInsumo(f"config: llaves desconocidas en {llave}: {', '.join(desconocidas)}.")
    cambios: Dict[str, object] = {
        k: _entero(v, f"{llave}.{k}") for k, v in valor.items() if k != "stopwords_fijas"}
    if "stopwords_fijas" in valor:
        cambios["stopwords_fijas"] = frozenset(
            t.upper() for t in _lista_textos(valor["stopwords_fijas"], f"{llave}.stopwords_fijas"))
    return replace(ReglasNombres(), **cambios)  # type: ignore[arg-type]


_LECTORES: Dict[str, tuple[str, Callable[[object, str], object]]] = {
    "cuentas_tarjeta": ("cuentas_tarjeta", _cuentas),
    "proveedores_cubeta": ("proveedores_cubeta", _lista_textos),
    "tolerancia_monto": ("tolerancia_monto", lambda v, k: _importe(v, k)),
    "ventana_busqueda_dias": ("ventana_busqueda", _ventana),
    "ventana_cubeta_dias": ("ventana_cubeta", _ventana),
    "umbral_similitud": ("umbral_similitud", lambda v, k: a_decimal_exacto(v, f"config: {k}")),
    "nombres": ("nombres", _reglas_nombres),
    "max_candidatos_reporte": ("max_candidatos_reporte", _entero),
    "moneda_libro": ("moneda_libro", _texto_no_vacio),
}


def config_desde_dict(datos: Mapping[str, object]) -> ConfigCruceLibro:
    """Valida un objeto de config ya decodificado y lo combina con los valores por omisión."""
    desconocidas = sorted(set(datos) - set(_LECTORES) - {"esquema"})
    if desconocidas:
        raise ErrorInsumo(f"config: llaves desconocidas: {', '.join(desconocidas)}.")
    if datos.get("esquema") != ESQUEMA_CONFIG:
        raise ErrorInsumo(f"config: esquema debe ser {ESQUEMA_CONFIG!r} ({datos.get('esquema')!r}).")
    cambios = {campo: lector(datos[llave], llave) for llave, (campo, lector) in _LECTORES.items() if llave in datos}
    try:
        return replace(ConfigCruceLibro(), **cambios)  # type: ignore[arg-type]
    except ValueError as exc:
        raise ErrorInsumo(f"config: {exc}") from exc


def cargar_config(ruta: Optional[Path]) -> ConfigCruceLibro:
    """Lee la config JSON; sin ruta devuelve los valores por omisión."""
    if ruta is None:
        return ConfigCruceLibro()
    try:
        datos = json.loads(leer_texto(ruta))
    except json.JSONDecodeError as exc:
        raise ErrorInsumo(f"{ruta.name}: JSON inválido ({exc.msg}).") from exc
    if not isinstance(datos, dict):
        raise ErrorInsumo(f"{ruta.name}: la config debe ser un objeto JSON.")
    return config_desde_dict(datos)


def config_a_dict(config: ConfigCruceLibro) -> Dict[str, object]:
    """Eco serializable de la config efectiva, con la misma forma que el archivo de ejemplo."""
    reglas = config.nombres
    return {
        "esquema": ESQUEMA_CONFIG,
        "cuentas_tarjeta": dict(config.cuentas_tarjeta),
        "proveedores_cubeta": sorted(config.proveedores_cubeta),
        "tolerancia_monto": str(config.tolerancia_monto),
        "ventana_busqueda_dias": {"min": config.ventana_busqueda.minimo, "max": config.ventana_busqueda.maximo},
        "ventana_cubeta_dias": {"min": config.ventana_cubeta.minimo, "max": config.ventana_cubeta.maximo},
        "umbral_similitud": str(config.umbral_similitud),
        "nombres": {
            "largo_max_abreviatura": reglas.largo_max_abreviatura, "largo_min_pieza": reglas.largo_min_pieza,
            "largo_min_prefijo": reglas.largo_min_prefijo, "largo_min_raiz": reglas.largo_min_raiz,
            "min_nombres_stopword": reglas.min_nombres_stopword,
            "stopwords_fijas": sorted(reglas.stopwords_fijas),
        },
        "max_candidatos_reporte": config.max_candidatos_reporte,
        "moneda_libro": config.moneda_libro,
    }
