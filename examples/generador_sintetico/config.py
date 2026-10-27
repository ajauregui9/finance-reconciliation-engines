"""Parámetros del generador sintético y constantes compartidas.

Todos los valores son de ejemplo, redondos y documentados; no representan la
calibración de ningún proceso real.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Tuple

SEMILLA_POR_DEFECTO = 4242
MAX_INTENTOS = 25
# Primer folio de cada serie de CFDI (por emisor y serie).
FOLIO_INICIAL = 1001

RFC_PUBLICO_GENERAL = "XAXX010101000"
RFC_EXTRANJERO = "XEXX010101000"
RFCS_GENERICOS = (RFC_PUBLICO_GENERAL, RFC_EXTRANJERO)

RFC_EMPRESA = "RFC_EMPRESA_DEMO"
NOMBRE_EMPRESA = "EMPRESA DEMO SA DE CV"

# Holgura que se suma a 2 x tolerancia para separar montos sorteados al azar:
# así ningún monto cae por accidente dentro de la tolerancia de otro.
HOLGURA_SEPARACION = Decimal("0.50")
# Ancho de la banda de casi cruces "fuera de tolerancia": |CFDI - cargo| va de la
# separación mínima a la separación más este ancho.
ANCHO_CASI_CRUCE = Decimal("2.00")

# Desfase (en días) entre la fecha del cargo y su registro en el libro mayor.
LIBRO_DESFASE_MIN = 0
LIBRO_DESFASE_MAX = 3
# Desfase de un asiento de proveedor-cubeta que pertenece a otro periodo.
CUBETA_LEJANA_MIN = 20
CUBETA_LEJANA_MAX = 30

TOLERANCIA_MINIMA = Decimal("0.10")
TOLERANCIA_MAXIMA = Decimal("2.00")


@dataclass(frozen=True)
class ConfigGenerador:
    """Configuración inmutable de una corrida.

    `ventana_min`/`ventana_max`: ventana de fechas asimétrica, en días, de
    `fecha_emision del CFDI - fecha del cargo` (ambos extremos inclusive).
    `tolerancia_monto`: diferencia máxima, en pesos, para el tier con tolerancia.
    """

    semilla: int = SEMILLA_POR_DEFECTO
    anio: int = 2026
    mes: int = 7
    ventana_min: int = -3
    ventana_max: int = 10
    tolerancia_monto: Decimal = Decimal("1.00")

    def __post_init__(self) -> None:
        if not isinstance(self.semilla, int) or self.semilla < 0:
            raise ValueError("La semilla debe ser un entero no negativo.")
        if not 1 <= self.mes <= 12:
            raise ValueError("El mes debe estar entre 1 y 12.")
        if not self.ventana_min <= 0 <= self.ventana_max:
            raise ValueError("La ventana de fechas debe cumplir ventana_min <= 0 <= ventana_max.")
        if not isinstance(self.tolerancia_monto, Decimal):
            raise TypeError("La tolerancia de monto debe ser Decimal, nunca float.")
        if not TOLERANCIA_MINIMA <= self.tolerancia_monto <= TOLERANCIA_MAXIMA:
            raise ValueError(
                f"La tolerancia debe estar entre {TOLERANCIA_MINIMA} y {TOLERANCIA_MAXIMA} "
                "(abajo no caben casos con tolerancia; arriba los montos chicos se amontonan)."
            )

    @property
    def separacion_montos(self) -> Decimal:
        """Distancia mínima entre dos montos sorteados al azar."""
        return 2 * self.tolerancia_monto + HOLGURA_SEPARACION

    @property
    def banda_fuera_de_tolerancia(self) -> Tuple[Decimal, Decimal]:
        """Rango (min, max) de |CFDI - cargo| en los casi cruces plantados fuera de tolerancia."""
        return self.separacion_montos, self.separacion_montos + ANCHO_CASI_CRUCE

    @property
    def periodo(self) -> str:
        return f"{self.anio:04d}-{self.mes:02d}"
