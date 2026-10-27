"""Configuración del esquema sintético: catálogos fijos y plan de discrepancias.

Todos los valores son de ejemplo (números redondos, nombres genéricos). No representan
ningún catálogo de cuentas ni calibración real.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Tuple

TIPO_PROVEEDORES = "AcctPay"
TIPO_GASTO = "Expense"
TIPO_ACTIVO_CIRCULANTE = "OthCurrAsset"


@dataclass(frozen=True)
class CuentaConfig:
    id: int
    numero: str
    nombre: str
    tipo: str
    inactiva: bool = False


@dataclass(frozen=True)
class ClaseConfig:
    id: int
    nombre: str
    inactiva: bool = False


@dataclass(frozen=True)
class ReglaGasto:
    """Pareja (cuenta de gasto, clase) con la que se registra un concepto de CFDI."""

    cuenta: str
    clase: str


@dataclass(frozen=True)
class PlanDiscrepancias:
    """Cuántos CFDIs reciben cada discrepancia plantada y con qué semilla se eligen."""

    semilla: int = 7
    sin_registro: int = 6
    monto_distinto: int = 6
    duplicado: int = 4
    periodo_equivocado: int = 4
    deltas_monto: Tuple[Decimal, ...] = (Decimal("100.00"), Decimal("-10.00"), Decimal("25.00"))


_CUENTAS: Tuple[CuentaConfig, ...] = (
    CuentaConfig(11, "1180-001", "IVA acreditable pendiente", TIPO_ACTIVO_CIRCULANTE),
    CuentaConfig(21, "2101-000", "Proveedores", TIPO_PROVEEDORES),
    CuentaConfig(61, "6100-010", "Viáticos: alimentos", TIPO_GASTO),
    CuentaConfig(62, "6100-020", "Viáticos: hospedaje", TIPO_GASTO),
    CuentaConfig(63, "6100-030", "Viáticos: transporte y combustible", TIPO_GASTO),
    CuentaConfig(64, "6200-010", "Papelería y suministros", TIPO_GASTO),
    CuentaConfig(65, "6200-020", "Servicios generales y mantenimiento", TIPO_GASTO),
    CuentaConfig(66, "6200-030", "Cómputo y servicios digitales", TIPO_GASTO),
    CuentaConfig(67, "6200-040", "Arrendamiento", TIPO_GASTO),
    CuentaConfig(68, "6200-050", "Seguros", TIPO_GASTO),
    CuentaConfig(69, "6200-060", "Honorarios", TIPO_GASTO),
    CuentaConfig(70, "6300-010", "Publicidad", TIPO_GASTO),
    CuentaConfig(71, "6900-000", "Otros gastos", TIPO_GASTO),
    CuentaConfig(72, "6900-999", "Gastos sin clasificar (en desuso)", TIPO_GASTO, inactiva=True),
)

_CLASES: Tuple[ClaseConfig, ...] = (
    ClaseConfig(1, "ADMINISTRACION"),
    ClaseConfig(2, "COMERCIAL"),
    ClaseConfig(3, "MERCADOTECNIA"),
    ClaseConfig(4, "OPERACIONES"),
    ClaseConfig(5, "PROYECTOS CONCLUIDOS", inactiva=True),
)

_VIAJE = "COMERCIAL"
_ADMIN = "ADMINISTRACION"

_GASTO_POR_CONCEPTO: Mapping[str, ReglaGasto] = MappingProxyType(
    {
        "CONSUMO DE ALIMENTOS": ReglaGasto("6100-010", _VIAJE),
        "SERVICIO DE HOSPEDAJE": ReglaGasto("6100-020", _VIAJE),
        "SERVICIO DE TRANSPORTE": ReglaGasto("6100-030", _VIAJE),
        "COMBUSTIBLE": ReglaGasto("6100-030", _VIAJE),
        "ARTICULOS DE OFICINA": ReglaGasto("6200-010", _ADMIN),
        "MERCANCIA VARIA": ReglaGasto("6200-010", "OPERACIONES"),
        "SERVICIOS GENERALES": ReglaGasto("6200-020", _ADMIN),
        "SERVICIO DE MANTENIMIENTO": ReglaGasto("6200-020", "OPERACIONES"),
        "EQUIPO Y SERVICIOS DE COMPUTO": ReglaGasto("6200-030", _ADMIN),
        "SERVICIOS DIGITALES": ReglaGasto("6200-030", _ADMIN),
        "ARRENDAMIENTO DE OFICINA": ReglaGasto("6200-040", _ADMIN),
        "PRIMA DE SEGURO": ReglaGasto("6200-050", _ADMIN),
        "HONORARIOS": ReglaGasto("6200-060", _ADMIN),
        "SERVICIOS DE PUBLICIDAD": ReglaGasto("6300-010", "MERCADOTECNIA"),
    }
)


@dataclass(frozen=True)
class ConfigEsquema:
    """Catálogos del esquema sintético. `meses` son parejas (año, mes) de registro."""

    rfc_empresa: str = "RFC_EMPRESA_DEMO"
    cuentas: Tuple[CuentaConfig, ...] = _CUENTAS
    clases: Tuple[ClaseConfig, ...] = _CLASES
    gasto_por_concepto: Mapping[str, ReglaGasto] = field(default_factory=lambda: _GASTO_POR_CONCEPTO)
    gasto_default: ReglaGasto = ReglaGasto("6900-000", _ADMIN)
    cuenta_proveedores: str = "2101-000"
    cuenta_iva: str = "1180-001"
    meses: Tuple[Tuple[int, int], ...] = ((2026, 5), (2026, 6), (2026, 7), (2026, 8), (2026, 9))
    meses_cerrados: Tuple[Tuple[int, int], ...] = ((2026, 5),)
    primer_id_transaccion: int = 5001
    primer_id_proveedor: int = 301


CONFIG_DEFAULT = ConfigEsquema()
