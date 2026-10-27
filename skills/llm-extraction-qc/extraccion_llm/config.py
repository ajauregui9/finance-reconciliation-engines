"""Config de la corrida (`config_extraccion_llm/v1`): modelo, límites de costo, precios y reglas.

La validación es estricta: una llave desconocida o faltante, un tipo equivocado o un valor
fuera de rango es `InsumoInvalido`. Los precios van como texto y se leen a `Decimal`; un
número JSON se rechaza para no pasar por float.
"""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, FrozenSet, Mapping, Optional, Tuple

from .errores import InsumoInvalido

ESQUEMA_CONFIG = "config_extraccion_llm/v1"
LLAVE_COMENTARIO = "_comentario"
LLAVES: FrozenSet[str] = frozenset({"esquema", "modelo", "max_tokens_salida", "temperatura", "herramienta_estricta",
                                    "rfc_empresa", "aceptar_rfc_marcador", "monedas_permitidas", "limites",
                                    "precios_usd_por_millon"})
LLAVES_LIMITES: FrozenSet[str] = frozenset({"max_documentos", "max_tokens"})
LLAVES_PRECIOS: FrozenSet[str] = frozenset({"entrada", "salida"})
TEMPERATURA_MAXIMA = 1
_FORMA_MONEDA = re.compile(r"[A-Z]{3}")
_FORMA_PRECIO = re.compile(r"[0-9]+(?:\.[0-9]+)?")


@dataclass(frozen=True)
class Limites:
    max_documentos: int
    max_tokens: int


@dataclass(frozen=True)
class Precios:
    entrada_por_millon: Decimal
    salida_por_millon: Decimal


@dataclass(frozen=True)
class Config:
    modelo: str
    max_tokens_salida: int
    temperatura: Optional[float]
    herramienta_estricta: bool
    rfc_empresa: str
    aceptar_rfc_marcador: bool
    monedas_permitidas: Tuple[str, ...]
    limites: Limites
    precios: Precios


def _llaves_exactas(datos: Mapping[str, Any], esperadas: FrozenSet[str], contexto: str) -> None:
    presentes = set(datos) - {LLAVE_COMENTARIO}
    desconocidas, faltantes = sorted(presentes - esperadas), sorted(esperadas - presentes)
    if desconocidas:
        raise InsumoInvalido(f"{contexto}: llaves desconocidas {desconocidas}")
    if faltantes:
        raise InsumoInvalido(f"{contexto}: faltan las llaves {faltantes}")


def _objeto(valor: Any, contexto: str) -> Mapping[str, Any]:
    if not isinstance(valor, dict):
        raise InsumoInvalido(f"{contexto}: se esperaba un objeto JSON")
    return valor


def _texto(valor: Any, campo: str) -> str:
    if not isinstance(valor, str) or not valor.strip() or valor != valor.strip() or " " in valor:
        raise InsumoInvalido(f"config: {campo} debe ser texto no vacío y sin espacios; llegó {valor!r}")
    return valor


def _entero_positivo(valor: Any, campo: str) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int) or valor < 1:
        raise InsumoInvalido(f"config: {campo} debe ser un entero mayor que cero; llegó {valor!r}")
    return int(valor)


def _booleano(valor: Any, campo: str) -> bool:
    if not isinstance(valor, bool):
        raise InsumoInvalido(f"config: {campo} debe ser true o false; llegó {valor!r}")
    return valor


def _temperatura(valor: Any) -> Optional[float]:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not 0 <= valor <= TEMPERATURA_MAXIMA:
        raise InsumoInvalido(f"config: temperatura debe ser null o un número entre 0 y {TEMPERATURA_MAXIMA}; "
                             f"llegó {valor!r}")
    return float(valor)


def _monedas(valor: Any) -> Tuple[str, ...]:
    es_lista = isinstance(valor, list) and bool(valor)
    valido = es_lista and all(isinstance(m, str) and _FORMA_MONEDA.fullmatch(m) for m in valor)
    if not valido or len(set(valor)) != len(valor):
        raise InsumoInvalido(f"config: monedas_permitidas debe ser una lista no vacía de códigos de tres letras "
                             f"mayúsculas sin repetir; llegó {valor!r}")
    return tuple(valor)


def _precio(valor: Any, campo: str) -> Decimal:
    if not isinstance(valor, str) or not _FORMA_PRECIO.fullmatch(valor):
        raise InsumoInvalido(f"config: precios_usd_por_millon.{campo} debe ser un monto no negativo en texto "
                             f"(\"5.00\"); llegó {valor!r}")
    return Decimal(valor)


def config_desde_dict(datos: Any) -> Config:
    raiz = _objeto(datos, "config")
    _llaves_exactas(raiz, LLAVES, "config")
    if raiz["esquema"] != ESQUEMA_CONFIG:
        raise InsumoInvalido(f"config: esquema {raiz['esquema']!r}; se esperaba {ESQUEMA_CONFIG!r}")
    limites = _objeto(raiz["limites"], "config: limites")
    _llaves_exactas(limites, LLAVES_LIMITES, "config: limites")
    precios = _objeto(raiz["precios_usd_por_millon"], "config: precios_usd_por_millon")
    _llaves_exactas(precios, LLAVES_PRECIOS, "config: precios_usd_por_millon")
    return Config(
        modelo=_texto(raiz["modelo"], "modelo"),
        max_tokens_salida=_entero_positivo(raiz["max_tokens_salida"], "max_tokens_salida"),
        temperatura=_temperatura(raiz["temperatura"]),
        herramienta_estricta=_booleano(raiz["herramienta_estricta"], "herramienta_estricta"),
        rfc_empresa=_texto(raiz["rfc_empresa"], "rfc_empresa"),
        aceptar_rfc_marcador=_booleano(raiz["aceptar_rfc_marcador"], "aceptar_rfc_marcador"),
        monedas_permitidas=_monedas(raiz["monedas_permitidas"]),
        limites=Limites(_entero_positivo(limites["max_documentos"], "limites.max_documentos"),
                        _entero_positivo(limites["max_tokens"], "limites.max_tokens")),
        precios=Precios(_precio(precios["entrada"], "entrada"), _precio(precios["salida"], "salida")),
    )


def cargar_config(ruta: Path) -> Config:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise InsumoInvalido(f"no se puede leer la config {ruta}: {exc}") from None
    try:
        datos = json.loads(texto)
    except json.JSONDecodeError as exc:
        raise InsumoInvalido(f"{ruta.name}: JSON inválido ({exc.msg})") from None
    try:
        return config_desde_dict(datos)
    except InsumoInvalido as exc:
        raise InsumoInvalido(f"{ruta.name}: {exc}") from None


def con_ajustes(config: Config, modelo: Optional[str] = None, max_documentos: Optional[int] = None,
                max_tokens: Optional[int] = None) -> Config:
    """La config con lo que se haya pedido por línea de comandos, validado igual que el archivo."""
    nuevo_modelo = config.modelo if modelo is None else _texto(modelo, "modelo")
    documentos = config.limites.max_documentos
    tokens = config.limites.max_tokens
    if max_documentos is not None:
        documentos = _entero_positivo(max_documentos, "limites.max_documentos (--max-documentos)")
    if max_tokens is not None:
        tokens = _entero_positivo(max_tokens, "limites.max_tokens (--max-tokens)")
    limites = Limites(documentos, tokens)
    return dataclasses.replace(config, modelo=nuevo_modelo, limites=limites)


def config_a_dict(config: Config) -> Dict[str, Any]:
    """La config efectiva en el mismo formato del archivo (precios como texto)."""
    return {
        "esquema": ESQUEMA_CONFIG,
        "modelo": config.modelo,
        "max_tokens_salida": config.max_tokens_salida,
        "temperatura": config.temperatura,
        "herramienta_estricta": config.herramienta_estricta,
        "rfc_empresa": config.rfc_empresa,
        "aceptar_rfc_marcador": config.aceptar_rfc_marcador,
        "monedas_permitidas": list(config.monedas_permitidas),
        "limites": {"max_documentos": config.limites.max_documentos, "max_tokens": config.limites.max_tokens},
        "precios_usd_por_millon": {"entrada": str(config.precios.entrada_por_millon),
                                   "salida": str(config.precios.salida_por_millon)},
    }
