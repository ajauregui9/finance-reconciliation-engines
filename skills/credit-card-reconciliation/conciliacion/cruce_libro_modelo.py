"""Tipos inmutables y vocabulario del cruce cargo ↔ libro mayor (ver `specs/cruce_libro.md`)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from fractions import Fraction
from typing import Dict, Optional, Tuple

from .nombres import ReglasNombres

CENTAVO = Decimal("0.01")
CERO = Decimal("0.00")
ESQUEMA_CONFIG = "cruce_libro_config/v1"
ESQUEMA_SALIDA = "cruce_libro/v1"

# Motivos de no-cruce.
MOTIVO_ININTERPRETABLE = "fila_ininterpretable"
MOTIVO_NO_APLICA = "no_aplica"
MOTIVO_SIN_CANDIDATO = "sin_candidato"
MOTIVO_OCUPADO = "candidato_ocupado"
MOTIVO_NOMBRE = "descartado_por_nombre"
MOTIVO_CUBETA = "cubeta_evidencia_insuficiente"
MOTIVO_VEREDICTO = "veredicto_no_registrado"

# Evaluación de cada candidato.
EVAL_ELEGIBLE = "elegible"
EVAL_NOMBRE = "nombre_insuficiente"
EVAL_CUBETA_FECHA = "cubeta_fuera_de_fecha"

EVIDENCIA_NOMBRE = "monto_y_nombre"
EVIDENCIA_CUBETA = "monto_y_fecha_cubeta"

VEREDICTO_REGISTRADO = "registrado"
VEREDICTO_NO_REGISTRADO = "no_registrado"
VEREDICTOS_VALIDOS = (VEREDICTO_REGISTRADO, VEREDICTO_NO_REGISTRADO)

CONFLICTO_ASIENTO = "asiento_distinto"
CONFLICTO_SIN_CRUCE = "motor_sin_cruce"
CONFLICTO_CON_CRUCE = "motor_con_cruce"

ORIGEN_MOTOR = "motor"
ORIGEN_VEREDICTO = "veredicto_humano"

TIPOS_BUSCABLES = ("cargo", "abono")
TIPO_PAGO = "pago"
TIPOS_MOVIMIENTO = TIPOS_BUSCABLES + (TIPO_PAGO,)
ESTADO_OK = "ok"


@dataclass(frozen=True)
class VentanaDias:
    """Rango de días, ambos extremos inclusive."""

    minimo: int
    maximo: int

    def __post_init__(self) -> None:
        if self.minimo > self.maximo:
            raise ValueError(f"Ventana inválida: min {self.minimo} > max {self.maximo}.")

    def contiene(self, dias: int) -> bool:
        return self.minimo <= dias <= self.maximo

    def incluye(self, otra: VentanaDias) -> bool:
        return self.minimo <= otra.minimo and otra.maximo <= self.maximo


@dataclass(frozen=True)
class ConfigCruceLibro:
    """Parámetros del motor. Los valores por omisión son los del ejemplo versionado."""

    cuentas_tarjeta: Tuple[Tuple[str, str], ...] = (("ALFA", "2105-001"), ("BETA", "2105-002"))
    proveedores_cubeta: frozenset[str] = frozenset({"PRV-0999"})
    tolerancia_monto: Decimal = Decimal("1.00")
    ventana_busqueda: VentanaDias = field(default=VentanaDias(-30, 30))
    ventana_cubeta: VentanaDias = field(default=VentanaDias(0, 5))
    umbral_similitud: Decimal = Decimal("0.50")
    nombres: ReglasNombres = field(default=ReglasNombres())
    max_candidatos_reporte: int = 5
    moneda_libro: str = "MXN"

    def __post_init__(self) -> None:
        if self.tolerancia_monto < 0:
            raise ValueError("La tolerancia de monto no puede ser negativa.")
        if not Decimal(0) <= self.umbral_similitud <= Decimal(1):
            raise ValueError("El umbral de similitud debe estar entre 0 y 1.")
        if not self.ventana_busqueda.incluye(self.ventana_cubeta):
            raise ValueError("La ventana de cubeta debe caber dentro de la ventana de búsqueda.")
        if self.max_candidatos_reporte < 0:
            raise ValueError("max_candidatos_reporte no puede ser negativo.")
        emisores = [e for e, _ in self.cuentas_tarjeta]
        if len(set(emisores)) != len(emisores):
            raise ValueError("Un emisor aparece dos veces en cuentas_tarjeta.")

    @property
    def cuenta_por_emisor(self) -> Dict[str, str]:
        return dict(self.cuentas_tarjeta)

    @property
    def umbral_fraccion(self) -> Fraction:
        return Fraction(self.umbral_similitud)


@dataclass(frozen=True)
class Cargo:
    """Lado izquierdo: un cargo del universo normalizado."""

    cargo_id: str
    emisor: str
    estado: str
    fecha: Optional[date]
    descripcion: str
    monto: Decimal
    tipo_movimiento: str

    @property
    def buscable(self) -> bool:
        return self.estado == ESTADO_OK and self.tipo_movimiento in TIPOS_BUSCABLES


@dataclass(frozen=True)
class LineaLibro:
    """Lado derecho: una línea de póliza del libro mayor."""

    asiento_id: str
    linea: int
    fecha: date
    cuenta: str
    proveedor_id: str
    proveedor_nombre: str
    debe: Decimal
    haber: Decimal


@dataclass(frozen=True)
class Veredicto:
    """Lo que una persona decidió sobre un cargo; el motor nunca lo cambia."""

    cargo_id: str
    veredicto: str
    asiento_id: Optional[str]
    nota: str


@dataclass(frozen=True)
class Candidato:
    """Una línea candidata para un cargo, con su evaluación."""

    linea: LineaLibro
    delta_dias: int
    diferencia: Decimal
    es_cubeta: bool
    similitud: Optional[Fraction]
    evaluacion: str

    @property
    def elegible(self) -> bool:
        return self.evaluacion == EVAL_ELEGIBLE

    @property
    def evidencia(self) -> str:
        return EVIDENCIA_CUBETA if self.es_cubeta else EVIDENCIA_NOMBRE

    def prioridad(self) -> Tuple[int, Decimal, Fraction, int, int, str, int]:
        """Llave de la spec sin el cargo: evidencia, importe, nombre, fecha, ids."""
        return (int(self.es_cubeta), self.diferencia, -(self.similitud or Fraction(0)),
                abs(self.delta_dias), self.delta_dias, self.linea.asiento_id, self.linea.linea)


@dataclass(frozen=True)
class EvaluacionCargo:
    """Un cargo con todos sus candidatos, ya evaluados y ordenados por prioridad."""

    cargo: Cargo
    candidatos: Tuple[Candidato, ...]
    motivo_previo: Optional[str]

    def conteos(self) -> Dict[str, int]:
        evaluaciones = [c.evaluacion for c in self.candidatos]
        return {"total": len(evaluaciones), "elegibles": evaluaciones.count(EVAL_ELEGIBLE),
                "descartados_por_nombre": evaluaciones.count(EVAL_NOMBRE),
                "cubeta_fuera_de_fecha": evaluaciones.count(EVAL_CUBETA_FECHA)}


@dataclass(frozen=True)
class Cruce:
    """Resultado de una corrida del motor para un cargo."""

    cargo_id: str
    candidato: Optional[Candidato]
    motivo: Optional[str]

    @property
    def asiento_id(self) -> Optional[str]:
        return self.candidato.linea.asiento_id if self.candidato else None

    @property
    def riesgo_cubeta(self) -> bool:
        return bool(self.candidato and self.candidato.es_cubeta)
