"""Insumos mínimos compartidos por las pruebas del revisor de P&L.

No contiene pruebas. Cada función devuelve un diccionario nuevo, de modo que
ninguna prueba comparte estado con otra. Los datos están hechos para que la
corrida base no tenga bloqueos, tenga todas las métricas dentro de banda y no
tenga variaciones (todas las cuentas repiten el monto del mes anterior).
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
DIR_SKILL = ROOT / "skills" / "pl-review-methodology"
DIR_SCRIPTS = DIR_SKILL / "scripts"
RUTA_CONFIG_EJEMPLO = DIR_SKILL / "config" / "parametros.example.json"
RUTA_MUESTRA = ROOT / "examples" / "sample_data" / "pl_monthly_sample.json"
PERIODO_MUESTRA = "2026-09"
PERIODO_BASE = "2026-03"

if str(DIR_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(DIR_SCRIPTS))

_CONFIG_BASE: Dict[str, Any] = {
    "esquema": "auditoria_pl_config/v1",
    "rubros": {
        "ingreso": ["4"],
        "costo": ["5"],
        "gasto_venta": ["61"],
        "gasto_admin": ["62"],
        "bajo_ebitda": ["7"],
    },
    "cuentas_sin_polizas_manuales": ["4010"],
    "madurez": {
        "dias_minimos_tras_cierre": 3,
        "cuentas_nomina": ["6130", "6210"],
        "provisiones_obligatorias": ["2150"],
    },
    "bandas": {
        "margen_bruto": {"minimo_pct": "40", "maximo_pct": "60", "favorable": "alto"},
        "gasto_venta": {"minimo_pct": "15", "maximo_pct": "20", "favorable": "bajo"},
        "gasto_admin": {"minimo_pct": "10", "maximo_pct": "20", "favorable": "bajo"},
        "ebitda": {"minimo_pct": "10", "maximo_pct": "30", "favorable": "alto"},
    },
    "publicidad": {"cuenta": "6120", "objetivo_pct": "8", "alerta_pct": "12"},
    "materialidad": {
        "piso_monto": "20000",
        "piso_pct_ingreso": "1",
        "piso_mencion": "2000",
        "variacion_pct_minima": "20",
        "tope_materiales": 10,
    },
}


def _linea(cuenta: str, nombre: str, monto: str) -> Dict[str, str]:
    return {"cuenta": cuenta, "nombre": nombre, "anterior": monto, "actual": monto}


_EXPORTACION_BASE: Dict[str, Any] = {
    "esquema": "exportacion_pl/v1",
    "periodo": PERIODO_BASE,
    "fecha_extraccion": "2026-04-05",
    "cuentas": [
        _linea("4010", "Venta de producto", "1000000.00"),
        _linea("5010", "Costo de venta", "500000.00"),
        _linea("6120", "Publicidad digital", "50000.00"),
        _linea("6130", "Sueldos de venta", "120000.00"),
        _linea("6210", "Sueldos administrativos", "150000.00"),
    ],
    "marcas": [{"marca": "Marca Uno", "venta": "1000000.00", "publicidad": "50000.00"}],
    "provisiones": [{"cuenta": "2150", "creado": "10000.00"}],
}


def config_base() -> Dict[str, Any]:
    return copy.deepcopy(_CONFIG_BASE)


def exportacion_base() -> Dict[str, Any]:
    return copy.deepcopy(_EXPORTACION_BASE)


def con_valor(documento: Dict[str, Any], ruta: str, valor: Any) -> Dict[str, Any]:
    """Copia `documento` y fija `valor` en la ruta con puntos (`madurez.cuentas_nomina`)."""
    nuevo = copy.deepcopy(documento)
    *padres, hoja = ruta.split(".")
    destino = nuevo
    for llave in padres:
        destino = destino[llave]
    destino[hoja] = valor
    return nuevo


def sin_llave(documento: Dict[str, Any], ruta: str) -> Dict[str, Any]:
    """Copia `documento` sin la llave de la ruta con puntos."""
    nuevo = copy.deepcopy(documento)
    *padres, hoja = ruta.split(".")
    destino = nuevo
    for llave in padres:
        destino = destino[llave]
    del destino[hoja]
    return nuevo


def con_cuenta(exportacion: Dict[str, Any], cuenta: str, **campos: Any) -> Dict[str, Any]:
    """Copia la exportación reemplazando (o agregando) la fila de `cuenta`."""
    nueva = copy.deepcopy(exportacion)
    filas: List[Dict[str, Any]] = nueva["cuentas"]
    for fila in filas:
        if fila["cuenta"] == cuenta:
            fila.update(campos)
            return nueva
    base = {"cuenta": cuenta, "nombre": f"Cuenta {cuenta}", "anterior": "0.00", "actual": "0.00"}
    base.update(campos)
    filas.append(base)
    return nueva


def sin_cuenta(exportacion: Dict[str, Any], cuenta: str) -> Dict[str, Any]:
    nueva = copy.deepcopy(exportacion)
    nueva["cuentas"] = [f for f in nueva["cuentas"] if f["cuenta"] != cuenta]
    return nueva
