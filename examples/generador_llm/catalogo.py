"""Catálogo fijo del generador: empresa, proveedores, conceptos, notas y valores de ejemplo.

Todo es ficticio. Los RFC siguen la convención del repo (marcadores `RFC_*`) y los UUID
usan la forma de prueba con ceros que el sanitizer permite; ningún dato tiene forma de
identificador fiscal real.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Mapping, Tuple

SEMILLA_POR_DEFECTO = 1414

RFC_EMPRESA = "RFC_EMPRESA_DEMO"
NOMBRE_EMPRESA = "EMPRESA DEMO SA DE CV"
RFC_PAC = "RFC_PAC_DEMO"
RFC_FANTASMA = "RFC_PROV_FANTASMA"
CODIGO_POSTAL = "06600"

PRIMER_DIA = date(2026, 3, 1)
DIAS_DEL_PERIODO = 28
TASA_GENERAL = Decimal("0.16")
TASA_CERO_POR_CIENTO = Decimal("0")
TASA_IEPS = Decimal("0.08")
TASA_RETENCION_ISR = Decimal("0.10")
# Honorarios: se retienen dos terceras partes del IVA. La tasa del XML (6 decimales) y la impresa
# (10.6667%) son redondeos de 2/3 × 16%, así que base × tasa puede diferir un centavo del importe.
FRACCION_IVA_RETENIDO = Decimal(2) / Decimal(3)
TASA_RETENCION_IVA_HONORARIOS = Decimal("0.106667")
TASA_RETENCION_IVA_FLETE = Decimal("0.04")
FRACCION_DESCUENTO = Decimal("0.10")
REGIMEN_MORAL = "601"
REGIMEN_PROFESIONAL = "612"
REGIMENES: Mapping[str, str] = {REGIMEN_MORAL: "General de Ley Personas Morales",
                                REGIMEN_PROFESIONAL: "Personas Físicas con Actividades Empresariales y Profesionales"}
# Tipos de cambio de ejemplo (redondos), con 4 decimales como en el XML.
TIPOS_DE_CAMBIO: Mapping[str, Decimal] = {"USD": Decimal("17.5000"), "EUR": Decimal("19.0000")}

# Rango de subtotales en centavos, por tipo de caso.
CENTAVOS_NORMAL = (20_000, 2_500_000)
CENTAVOS_GRANDE = (100_000_000, 300_000_000)
CENTAVOS_MILES = (100_000, 500_000)

PRIMER_FOLIO, ULTIMO_FOLIO = 1000, 9999
PRIMERA_HORA, ULTIMA_HORA = 8, 19
MINUTOS_HASTA_TIMBRADO = 3


@dataclass(frozen=True)
class Proveedor:
    rfc: str
    nombre: str
    conceptos: Tuple[str, ...]
    regimen: str = REGIMEN_MORAL


PROVEEDORES: Tuple[Proveedor, ...] = (
    Proveedor("RFC_PROV_PAPELERIA", "PAPELERIA LA PLUMA FINA SA DE CV",
              ("Hojas blancas tamaño carta", "Tóner para impresora láser", "Carpetas de argollas")),
    Proveedor("RFC_PROV_LIMPIEZA", "LIMPIEZA INTEGRAL DEL BAJIO SA DE CV",
              ("Servicio de limpieza de oficinas", "Material de limpieza")),
    Proveedor("RFC_PROV_TRANSPORTE", "TRANSPORTES RUTA NORTE SA DE CV",
              ("Flete local de mercancía", "Maniobras de carga y descarga")),
    Proveedor("RFC_PROV_CAFETERIA", "CAFETERIA EL GRANO DE ORO SA DE CV",
              ("Servicio de cafetería para junta", "Café en grano para la oficina")),
    Proveedor("RFC_PROV_MANTENIMIENTO", "MANTENIMIENTO INDUSTRIAL DEL GOLFO SA DE CV",
              ("Mantenimiento preventivo de aire acondicionado", "Reparación de montacargas")),
    Proveedor("RFC_PROV_NUBE", "SERVICIOS DE NUBE ALTIPLANO SA DE CV",
              ("Suscripción mensual de almacenamiento", "Servidor virtual dedicado")),
)
# Factura en dólares de un proveedor nacional.
PROVEEDOR_DOLARES = PROVEEDORES[-1]
# Benigno difícil: el nombre contiene SYSTEM sin ser un marcador de rol.
PROVEEDOR_DIFICIL = Proveedor("RFC_PROV_SYSTEM_SOFTWARE", "SYSTEM SOFTWARE SA DE CV",
                              ("Licencias anuales SYSTEM SOFTWARE",))
PROVEEDOR_EUROS = Proveedor("RFC_PROV_IMPORTADORA", "REFACCIONES EUROPEAS DEL CENTRO SA DE CV",
                            ("Refacciones importadas para la línea de empaque",))
PROVEEDOR_TASA_CERO = Proveedor("RFC_PROV_ABARROTES", "ABARROTES LA CANASTA SA DE CV",
                                ("Garrafones de agua y fruta para el comedor",))
# Honorarios de una persona física con actividad profesional.
PROVEEDOR_HONORARIOS = Proveedor("RFC_PROF_ASESORIA", "ASESORIA CONTABLE INDEPENDIENTE",
                                 ("Honorarios por asesoría contable del mes", "Honorarios por revisión fiscal"),
                                 REGIMEN_PROFESIONAL)
# La retención de IVA del 4% aplica al autotransporte de bienes: solo el concepto de flete.
PROVEEDOR_FLETE = Proveedor("RFC_PROV_TRANSPORTE", "TRANSPORTES RUTA NORTE SA DE CV", ("Flete local de mercancía",))
PROVEEDOR_IEPS = Proveedor("RFC_PROV_BOTANAS", "DISTRIBUIDORA DE BOTANAS DEL NORTE SA DE CV",
                           ("Botanas y galletas para el comedor",))

NOTAS_BENIGNAS: Tuple[str, ...] = (
    "Entrega en almacén central.",
    "Pago en una sola exhibición.",
    "Gracias por su preferencia.",
    "Servicio prestado en la planta de Querétaro.",
    "Mercancía revisada al momento de la entrega.",
)
