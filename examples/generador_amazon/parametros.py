"""Parámetros, catálogo y casos borde del generador. Todo valor es de ejemplo."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Mapping, Tuple

SEMILLA_POR_DEFECTO = 2026
MESES_POR_DEFECTO = ("2026-04", "2026-05", "2026-06", "2026-07")
# Cada archivo declara su huso; distintos a propósito para que el corte importe.
HUSOS_POR_DEFECTO = (
    ("2026-04", "UTC-07:00"), ("2026-05", "UTC-07:00"), ("2026-06", "UTC-08:00"), ("2026-07", "UTC+00:00"),
)
PEDIDOS_MIN, PEDIDOS_MAX = 5, 500


@dataclass(frozen=True)
class Producto:
    sku: str
    descripcion: str
    precio: Decimal
    tasa_comision: Decimal
    logistica_unidad: Decimal


CATALOGO: Tuple[Producto, ...] = (
    Producto("NOR-001", "Termo de acero 1 L", Decimal("450.00"), Decimal("0.15"), Decimal("55.00")),
    Producto("NOR-002", "Taza térmica", Decimal("280.00"), Decimal("0.15"), Decimal("40.00")),
    Producto("BRI-001", "Audífonos inalámbricos", Decimal("1250.00"), Decimal("0.10"), Decimal("70.00")),
    Producto("BRI-002", "Cargador rápido", Decimal("390.00"), Decimal("0.10"), Decimal("45.00")),
    Producto("CUM-001", "Mochila urbana", Decimal("899.00"), Decimal("0.15"), Decimal("80.00")),
    Producto("CUM-002", "Botella plegable", Decimal("199.00"), Decimal("0.15"), Decimal("35.00")),
)
CAMPANAS = ("BRI | Producto", "CUM | Marca", "Genérica | Descubrimiento", "NOR | Búsqueda")


@dataclass(frozen=True)
class CasoBorde:
    """Una venta colocada a mano cerca de un corte de mes, con su respuesta esperada."""

    periodo: str
    fecha_hora_local: str
    fecha_pedido_local: str
    sku: str
    mes_liquidacion: str
    mes_pedido: str
    nota: str


CASOS_BORDE: Tuple[CasoBorde, ...] = (
    CasoBorde("2026-04", "2026-04-30 22:40:00", "2026-04-28 15:00:00", "NOR-002", "2026-04", "2026-04",
              "UTC-07:00: 22:40 local son 23:40 en el huso de cierre; se queda en abril"),
    CasoBorde("2026-04", "2026-04-30 23:20:00", "2026-04-29 12:00:00", "CUM-002", "2026-05", "2026-04",
              "UTC-07:00: 23:20 local son 00:20 del 1 de mayo; entra como cola de abril en mayo"),
    CasoBorde("2026-05", "2026-05-31 23:30:00", "2026-05-30 10:00:00", "CUM-002", "2026-06", "2026-05",
              "UTC-07:00: 23:30 local son 00:30 del 1 de junio; cola de mayo en junio"),
    CasoBorde("2026-06", "2026-06-30 21:30:00", "2026-06-29 09:00:00", "NOR-001", "2026-06", "2026-06",
              "UTC-08:00: 21:30 local son 23:30; se queda en junio"),
    CasoBorde("2026-06", "2026-06-30 22:30:00", "2026-06-30 08:00:00", "BRI-002", "2026-07", "2026-06",
              "UTC-08:00: 22:30 local son 00:30 del 1 de julio; sumar una hora fija la dejaría en junio"),
    CasoBorde("2026-06", "2026-06-02 10:00:00", "2026-05-31 22:10:00", "NOR-002", "2026-06", "2026-06",
              "UTC-08:00: el pedido de las 22:10 del 31 de mayo es 1 de junio en el huso de cierre"),
    CasoBorde("2026-07", "2026-07-01 03:00:00", "2026-06-29 20:00:00", "BRI-001", "2026-06", "2026-06",
              "UTC+00:00: 03:00 local son 21:00 del 30 de junio; el archivo de julio trae una fila de junio"),
    CasoBorde("2026-07", "2026-07-01 07:00:00", "2026-07-01 05:30:00", "NOR-001", "2026-07", "2026-06",
              "UTC+00:00: el pedido de las 05:30 local es 30 de junio; cola de junio en julio"),
)


@dataclass(frozen=True)
class ParametrosGenerador:
    """Todo lo que controla una corrida del generador."""

    semilla: int = SEMILLA_POR_DEFECTO
    pedidos_por_mes: int = 36
    meses: Tuple[str, ...] = MESES_POR_DEFECTO
    husos: Tuple[Tuple[str, str], ...] = HUSOS_POR_DEFECTO
    huso_cierre: str = "UTC-06:00"
    tasa_iva: Decimal = Decimal("0.16")
    tasa_retencion: Decimal = Decimal("0.08")
    banda_retencion: Decimal = Decimal("0.01")
    mes_retencion_anomala: str = "2026-06"
    tasa_retencion_anomala: Decimal = Decimal("0.16")
    mes_cola_negativa: str = "2026-06"
    suscripcion: Decimal = Decimal("500.00")
    envio: Decimal = Decimal("49.00")
    otra_tarifa: Decimal = Decimal("5.00")
    descuento: Decimal = Decimal("0.10")
    comision_que_se_devuelve: Decimal = Decimal("0.80")
    casos_borde: Tuple[CasoBorde, ...] = field(default=CASOS_BORDE)

    def __post_init__(self) -> None:
        if self.semilla < 0:
            raise ValueError("la semilla debe ser >= 0")
        if not PEDIDOS_MIN <= self.pedidos_por_mes <= PEDIDOS_MAX:
            raise ValueError(f"pedidos_por_mes debe estar entre {PEDIDOS_MIN} y {PEDIDOS_MAX}")
        if [mes for mes, _ in self.husos] != list(self.meses):
            raise ValueError("husos debe declarar un huso por cada mes, en el mismo orden")

    @property
    def huso_de(self) -> Mapping[str, str]:
        return dict(self.husos)
