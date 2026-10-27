"""Lectura estricta de la config `flujo_config/v1` y de la curva de cobranza.

El JSON se lee con números `Decimal` (ningún `float` llega a existir), se rechazan
llaves repetidas, faltantes o desconocidas, y cada ruta de insumo queda asociada a
exactamente una fuente.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from .contrato import FUENTES
from .errores import ErrorConfig

ESQUEMA_CONFIG = "flujo_config/v1"
LLAVES_CONFIG = frozenset({"esquema", "moneda", "insumos", "curva_cobranza"})
LLAVES_TRAMO = frozenset({"tramo", "dias_desde", "dias_hasta", "pesos"})
PATRON_MONEDA = re.compile(r"^[A-Z]{3}$")
UNO = Decimal(1)


@dataclass(frozen=True)
class TramoCurva:
    """Rango de antigüedad (días, ambos inclusive; `None` = sin límite) y sus pesos semanales."""

    tramo: str
    dias_desde: Optional[int]
    dias_hasta: Optional[int]
    pesos: Tuple[Decimal, ...]

    def contiene(self, antiguedad: int) -> bool:
        sobre_piso = self.dias_desde is None or antiguedad >= self.dias_desde
        bajo_techo = self.dias_hasta is None or antiguedad <= self.dias_hasta
        return sobre_piso and bajo_techo


@dataclass(frozen=True)
class CurvaCobranza:
    tramos: Tuple[TramoCurva, ...]


@dataclass(frozen=True)
class ConfigFlujo:
    moneda: str
    insumos: Tuple[Tuple[str, Path], ...]
    curva: CurvaCobranza

    def ruta(self, fuente: str) -> Path:
        for nombre, ruta in self.insumos:
            if nombre == fuente:
                return ruta
        raise ErrorConfig(f"la config no tiene ruta para la fuente '{fuente}'")


# --- utilidades de validación -----------------------------------------------------------


def _objeto(valor: object, contexto: str, llaves: FrozenSet[str]) -> Mapping[str, Any]:
    if not isinstance(valor, dict):
        raise ErrorConfig(f"{contexto} debe ser un objeto JSON")
    faltan = sorted(llaves - set(valor))
    if faltan:
        raise ErrorConfig(f"{contexto}: faltan llaves {', '.join(faltan)}")
    sobran = sorted(set(valor) - llaves)
    if sobran:
        raise ErrorConfig(f"{contexto}: llaves desconocidas {', '.join(sobran)}")
    return valor


def _sin_repetidas(pares: List[Tuple[str, Any]]) -> Dict[str, Any]:
    vistas: Dict[str, Any] = {}
    for llave, valor in pares:
        if llave in vistas:
            raise ErrorConfig(f"la llave '{llave}' aparece repetida en la config")
        vistas[llave] = valor
    return vistas


def _rechazar_constante(nombre: str) -> Any:
    raise ErrorConfig(f"la config contiene {nombre}, que no es un número válido")


def _entero_o_nulo(valor: object, contexto: str) -> Optional[int]:
    if valor is None:
        return None
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ErrorConfig(f"{contexto} debe ser un entero o null")
    return valor


def _fraccion(valor: object, contexto: str) -> Decimal:
    if isinstance(valor, float):
        raise ErrorConfig(f"{contexto}: el peso es float; escríbelo como texto decimal o número JSON")
    if isinstance(valor, bool) or not isinstance(valor, (str, int, Decimal)):
        raise ErrorConfig(f"{contexto}: el peso {valor!r} no es un decimal")
    try:
        peso = Decimal(valor.strip() if isinstance(valor, str) else valor)
    except InvalidOperation:
        raise ErrorConfig(f"{contexto}: el peso {valor!r} no es un decimal") from None
    if not peso.is_finite() or not 0 <= peso <= UNO:
        raise ErrorConfig(f"{contexto}: el peso {valor!r} debe estar entre 0 y 1")
    return peso


# --- curva de cobranza ------------------------------------------------------------------


def _tramo(crudo: object, indice: int) -> TramoCurva:
    contexto = f"curva_cobranza[{indice}]"
    datos = _objeto(crudo, contexto, LLAVES_TRAMO)
    nombre = datos["tramo"]
    if not isinstance(nombre, str) or not nombre.strip():
        raise ErrorConfig(f"{contexto}: 'tramo' debe ser un nombre no vacío")
    desde = _entero_o_nulo(datos["dias_desde"], f"{contexto}.dias_desde")
    hasta = _entero_o_nulo(datos["dias_hasta"], f"{contexto}.dias_hasta")
    if desde is not None and hasta is not None and desde > hasta:
        raise ErrorConfig(f"{contexto}: dias_desde mayor que dias_hasta ({desde} > {hasta})")
    crudos = datos["pesos"]
    if not isinstance(crudos, list) or not crudos:
        raise ErrorConfig(f"{contexto}: 'pesos' debe ser una lista con al menos un peso")
    pesos = tuple(_fraccion(p, f"{contexto}.pesos[{k}]") for k, p in enumerate(crudos))
    if sum(pesos) > UNO:
        raise ErrorConfig(f"{contexto}: los pesos suman más de 1 ({sum(pesos)})")
    return TramoCurva(tramo=nombre.strip(), dias_desde=desde, dias_hasta=hasta, pesos=pesos)


def _exigir_cobertura(tramos: Sequence[TramoCurva]) -> None:
    if tramos[0].dias_desde is not None:
        raise ErrorConfig("curva_cobranza: el primer tramo debe abrir con dias_desde null")
    if tramos[-1].dias_hasta is not None:
        raise ErrorConfig("curva_cobranza: el último tramo debe cerrar con dias_hasta null")
    for previo, actual in zip(tramos, tramos[1:]):
        contiguo = (
            previo.dias_hasta is not None
            and actual.dias_desde is not None
            and actual.dias_desde == previo.dias_hasta + 1
        )
        if not contiguo:
            raise ErrorConfig(f"curva_cobranza: hueco o traslape entre '{previo.tramo}' y '{actual.tramo}'")


def validar_curva(crudo: object) -> CurvaCobranza:
    """Valida la lista de tramos: cobertura total de antigüedades, sin huecos ni traslapes."""
    if not isinstance(crudo, list):
        raise ErrorConfig("curva_cobranza debe ser una lista de tramos")
    if not crudo:
        raise ErrorConfig("curva_cobranza necesita al menos un tramo")
    tramos = tuple(_tramo(t, i) for i, t in enumerate(crudo))
    nombres = [t.tramo for t in tramos]
    repetidos = sorted({n for n in nombres if nombres.count(n) > 1})
    if repetidos:
        raise ErrorConfig(f"curva_cobranza: tramo repetido {', '.join(repetidos)}")
    _exigir_cobertura(tramos)
    return CurvaCobranza(tramos=tramos)


# --- config completa --------------------------------------------------------------------


def _ruta_insumo(fuente: str, valor: object, base: Path) -> Path:
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorConfig(f"insumos.{fuente} debe ser una ruta no vacía")
    ruta = Path(valor.strip())
    return ruta if ruta.is_absolute() else base / ruta


def _insumos(crudo: object, base: Path) -> Tuple[Tuple[str, Path], ...]:
    datos = _objeto(crudo, "insumos", frozenset(FUENTES))
    return tuple((fuente, _ruta_insumo(fuente, datos[fuente], base)) for fuente in FUENTES)


def config_desde_dict(crudo: object, base: Path) -> ConfigFlujo:
    """Valida una config ya parseada; las rutas relativas se resuelven contra `base`."""
    datos = _objeto(crudo, "la config", LLAVES_CONFIG)
    if datos["esquema"] != ESQUEMA_CONFIG:
        raise ErrorConfig(f"esquema de config {datos['esquema']!r} no soportado (se espera '{ESQUEMA_CONFIG}')")
    moneda = datos["moneda"]
    if not isinstance(moneda, str) or not PATRON_MONEDA.match(moneda):
        raise ErrorConfig(f"moneda {moneda!r} inválida: se esperan tres letras mayúsculas")
    return ConfigFlujo(
        moneda=moneda,
        insumos=_insumos(datos["insumos"], base),
        curva=validar_curva(datos["curva_cobranza"]),
    )


def cargar_config(ruta: Path) -> ConfigFlujo:
    try:
        texto = ruta.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ErrorConfig(f"no se pudo leer la config {ruta}: {exc}") from exc
    try:
        crudo = json.loads(
            texto,
            parse_float=Decimal,
            parse_constant=_rechazar_constante,
            object_pairs_hook=_sin_repetidas,
        )
    except json.JSONDecodeError as exc:
        raise ErrorConfig(f"la config {ruta.name} no es JSON válido: {exc}") from exc
    return config_desde_dict(crudo, ruta.parent)
