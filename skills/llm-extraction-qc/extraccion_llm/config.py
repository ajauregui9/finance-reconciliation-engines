"""Config de la corrida (`config_extraccion_llm/v2`): modelo, límites de costo, precios, reglas y reintentos.

La validación es estricta: una llave desconocida o faltante, un tipo equivocado o un valor
fuera de rango es `InsumoInvalido`. Los precios y la tolerancia del cuadre van como texto y
se leen a `Decimal`; un número JSON se rechaza para no pasar por float. Las esperas de los
reintentos son segundos (números JSON): no son montos.
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

ESQUEMA_CONFIG = "config_extraccion_llm/v2"
LLAVE_COMENTARIO = "_comentario"
LLAVES: FrozenSet[str] = frozenset({"esquema", "modelo", "max_tokens_salida", "temperatura", "herramienta_estricta",
                                    "rfc_empresa", "aceptar_rfc_marcador", "monedas_permitidas",
                                    "tolerancia_cuadre", "limites", "precios_usd_por_millon", "reintentos"})
LLAVES_LIMITES: FrozenSet[str] = frozenset({"max_documentos", "max_tokens"})
LLAVES_PRECIOS: FrozenSet[str] = frozenset({"entrada", "salida"})
LLAVES_REINTENTOS: FrozenSet[str] = frozenset({"max_reintentos", "espera_inicial_s", "espera_maxima_s"})
TEMPERATURA_MAXIMA = 1
# La tolerancia del cuadre es para redondeo, no para errores: se acota a unos centavos.
TOLERANCIA_CUADRE_MAXIMA = Decimal("0.10")
MAX_REINTENTOS_PERMITIDOS = 10
ESPERA_MAXIMA_PERMITIDA_S = 300
_FORMA_MONEDA = re.compile(r"[A-Z]{3}")
_FORMA_PRECIO = re.compile(r"[0-9]+(?:\.[0-9]+)?")
_FORMA_CENTAVOS = re.compile(r"[0-9]+(?:\.[0-9]{1,2})?")


@dataclass(frozen=True)
class Limites:
    max_documentos: int
    max_tokens: int


@dataclass(frozen=True)
class Precios:
    entrada_por_millon: Decimal
    salida_por_millon: Decimal


@dataclass(frozen=True)
class Reintentos:
    """Reintentos de la API ante errores transitorios: cuántos y cuánto esperar entre ellos (segundos)."""

    max_reintentos: int
    espera_inicial_s: float
    espera_maxima_s: float


@dataclass(frozen=True)
class Config:
    modelo: str
    max_tokens_salida: int
    temperatura: Optional[float]
    herramienta_estricta: bool
    rfc_empresa: str
    aceptar_rfc_marcador: bool
    monedas_permitidas: Tuple[str, ...]
    tolerancia_cuadre: Decimal
    limites: Limites
    precios: Precios
    reintentos: Reintentos


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


def _tolerancia(valor: Any) -> Decimal:
    if not isinstance(valor, str) or not _FORMA_CENTAVOS.fullmatch(valor) or Decimal(valor) > TOLERANCIA_CUADRE_MAXIMA:
        raise InsumoInvalido(f"config: tolerancia_cuadre debe ser un monto en texto entre \"0.00\" y "
                             f"\"{TOLERANCIA_CUADRE_MAXIMA}\" con hasta dos decimales; llegó {valor!r}")
    return Decimal(valor)


def _segundos(valor: Any, campo: str, minimo: float) -> float:
    es_numero = isinstance(valor, (int, float)) and not isinstance(valor, bool)
    if not es_numero or not minimo <= valor <= ESPERA_MAXIMA_PERMITIDA_S or valor <= 0:
        raise InsumoInvalido(f"config: reintentos.{campo} debe ser un número de segundos mayor que cero, entre "
                             f"{minimo} y {ESPERA_MAXIMA_PERMITIDA_S}; llegó {valor!r}")
    return float(valor)


def _reintentos(valor: Any) -> Reintentos:
    datos = _objeto(valor, "config: reintentos")
    _llaves_exactas(datos, LLAVES_REINTENTOS, "config: reintentos")
    maximo = datos["max_reintentos"]
    if isinstance(maximo, bool) or not isinstance(maximo, int) or not 0 <= maximo <= MAX_REINTENTOS_PERMITIDOS:
        raise InsumoInvalido(f"config: reintentos.max_reintentos debe ser un entero entre 0 y "
                             f"{MAX_REINTENTOS_PERMITIDOS}; llegó {maximo!r}")
    inicial = _segundos(datos["espera_inicial_s"], "espera_inicial_s", 0)
    return Reintentos(maximo, inicial, _segundos(datos["espera_maxima_s"], "espera_maxima_s", inicial))


def config_desde_dict(datos: Any) -> Config:
    raiz = _objeto(datos, "config")
    if raiz.get("esquema") != ESQUEMA_CONFIG:
        raise InsumoInvalido(f"config: esquema {raiz.get('esquema')!r}; se esperaba {ESQUEMA_CONFIG!r}")
    _llaves_exactas(raiz, LLAVES, "config")
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
        tolerancia_cuadre=_tolerancia(raiz["tolerancia_cuadre"]),
        limites=Limites(_entero_positivo(limites["max_documentos"], "limites.max_documentos"),
                        _entero_positivo(limites["max_tokens"], "limites.max_tokens")),
        precios=Precios(_precio(precios["entrada"], "entrada"), _precio(precios["salida"], "salida")),
        reintentos=_reintentos(raiz["reintentos"]),
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
        "tolerancia_cuadre": str(config.tolerancia_cuadre),
        "limites": {"max_documentos": config.limites.max_documentos, "max_tokens": config.limites.max_tokens},
        "precios_usd_por_millon": {"entrada": str(config.precios.entrada_por_millon),
                                   "salida": str(config.precios.salida_por_millon)},
        "reintentos": {"max_reintentos": config.reintentos.max_reintentos,
                       "espera_inicial_s": config.reintentos.espera_inicial_s,
                       "espera_maxima_s": config.reintentos.espera_maxima_s},
    }
