"""Estructuras inmutables que el generador produce y escribe."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional, Tuple

from .config import ConfigGenerador


@dataclass(frozen=True)
class Tarjeta:
    emisor: str
    titular: str
    ultimos4: str


@dataclass(frozen=True)
class Comercio:
    """Un comercio ficticio con sus tres nombres (estado de cuenta, CFDI, ERP)."""

    clave: str
    categoria: str
    descriptor: str
    ciudad: str
    razon_social: str
    nombre_proveedor: str
    proveedor_id: str
    rfc: str
    factura: bool
    extranjero: bool
    serie: str
    rango: Tuple[int, int]


@dataclass(frozen=True)
class Cargo:
    """Una fila del estado de cuenta; `clave` es interna hasta asignar el id final."""

    clave: str
    tarjeta: Tarjeta
    fecha: date
    fecha_aplicacion: date
    descriptor: str
    ciudad: str
    monto: Decimal
    monto_original: Decimal
    moneda_original: str
    tipo_cambio: Optional[Decimal]
    tipo_movimiento: str
    comercio: Optional[Comercio] = None
    fecha_cruda_invalida: Optional[str] = None
    cargo_id: str = ""
    fila: int = 0

    @property
    def emisor(self) -> str:
        return self.tarjeta.emisor

    @property
    def interpretable(self) -> bool:
        return self.fecha_cruda_invalida is None

    def comercio_requerido(self) -> Comercio:
        """El comercio del cargo; falla con un mensaje claro si el cargo no tiene uno."""
        if self.comercio is None:
            raise ValueError(f"El cargo {self.clave or self.cargo_id} no tiene comercio asociado.")
        return self.comercio


@dataclass(frozen=True)
class Cfdi:
    uuid: str
    fecha_emision: date
    tipo_comprobante: str
    direccion: str
    rfc_emisor: str
    nombre_emisor: str
    rfc_receptor: str
    nombre_receptor: str
    moneda: str
    tipo_cambio: Optional[Decimal]
    subtotal: Decimal
    iva: Decimal
    total: Decimal
    total_mxn: Decimal
    forma_pago: str
    uso_cfdi: str
    concepto: str
    serie: str
    uuid_relacionado: Optional[str] = None
    folio: str = ""

    @property
    def valor_firmado_mxn(self) -> Decimal:
        return -self.total_mxn if self.tipo_comprobante == "E" else self.total_mxn

    @property
    def valor_firmado_original(self) -> Decimal:
        return -self.total if self.tipo_comprobante == "E" else self.total


@dataclass(frozen=True)
class LineaMayor:
    cuenta: str
    nombre_cuenta: str
    debe: Decimal
    haber: Decimal


@dataclass(frozen=True)
class Asiento:
    clave: str
    fecha: date
    origen: str
    proveedor_id: str
    proveedor_nombre: str
    proveedor_rfc: str
    referencia: str
    memo: str
    lineas: Tuple[LineaMayor, ...]
    asiento_id: str = ""


@dataclass(frozen=True)
class ExpectativaCfdi:
    esperados: Tuple[str, ...] = ()
    evidencia: Optional[str] = None
    prohibidos: Tuple[str, ...] = ()
    motivo: Optional[str] = None


@dataclass(frozen=True)
class ExpectativaLibro:
    esperado: Optional[str] = None
    riesgo_cubeta: bool = False
    prohibidos: Tuple[str, ...] = ()
    motivo: Optional[str] = None


@dataclass(frozen=True)
class Expectativa:
    """Respuesta conocida para un cargo (claves internas hasta el ensamblado)."""

    clave_cargo: str
    casos: Tuple[str, ...]
    cfdi: ExpectativaCfdi
    libro: Optional[ExpectativaLibro] = None
    grupo_empate: Optional[str] = None

    def libro_requerido(self) -> ExpectativaLibro:
        """La expectativa de libro mayor; falla si el ensamblado aún no la completó."""
        if self.libro is None:
            raise ValueError(f"El cargo {self.clave_cargo} no tiene expectativa de libro mayor.")
        return self.libro


@dataclass(frozen=True)
class GrupoEmpate:
    grupo: str
    cargos: Tuple[str, ...]
    cfdis: Tuple[str, ...]
    asientos: Tuple[str, ...] = ()


@dataclass(frozen=True)
class VeredictoHumano:
    """Veredicto sintético de una persona sobre el registro de un cargo en el libro mayor.

    `conflicto` es el desacuerdo que un motor correcto debe reportar contra su propia
    propuesta (o None si coinciden).
    """

    cargo_id: str
    veredicto: str
    asiento_id: Optional[str]
    nota: str
    conflicto: Optional[str]


@dataclass(frozen=True)
class InyeccionSembrada:
    """Texto con instrucciones sembrado en el concepto de un CFDI.

    `familia` es la que un guard correcto debe reportar; `cargo_id` es el cargo que ese
    CFDI respalda (que debe quedar en revisión humana) o None si no respalda ninguno.
    """

    uuid: str
    familia: str
    cargo_id: Optional[str]
    plantilla: str


@dataclass(frozen=True)
class Datos:
    """Resultado completo de una corrida, ya con ids finales y ordenado."""

    config: ConfigGenerador
    intento: int
    cargos: Tuple[Cargo, ...]
    cfdis: Tuple[Cfdi, ...]
    asientos: Tuple[Asiento, ...]
    expectativas: Tuple[Expectativa, ...]
    grupos: Tuple[GrupoEmpate, ...]
    veredictos: Tuple[VeredictoHumano, ...] = ()
    inyecciones: Tuple[InyeccionSembrada, ...] = ()
