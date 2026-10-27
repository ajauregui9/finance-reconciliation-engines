"""Catálogo ficticio: emisores de tarjeta, titulares, comercios, proveedores y cuentas.

Todos los nombres son inventados y genéricos (estilo de comercio público, sin
marcas reales). Los RFC son marcadores `RFC_*` o los genéricos del SAT.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from .config import RFC_EXTRANJERO, RFC_PUBLICO_GENERAL
from .modelo import Comercio, Tarjeta


@dataclass(frozen=True)
class EmisorTarjeta:
    clave: str
    nombre: str
    layout: str
    archivo: str
    cuenta: str
    nombre_cuenta: str
    marca_pago: str


EMISORES: Dict[str, EmisorTarjeta] = {
    "ALFA": EmisorTarjeta("ALFA", "BANCO FICTICIO ALFA", "ALFA_V1", "estado_cuenta_alfa.csv",
                          "2105-001", "TARJETA CORPORATIVA ALFA", "PAGO RECIBIDO GRACIAS"),
    "BETA": EmisorTarjeta("BETA", "BANCO FICTICIO BETA", "BETA_V1", "estado_cuenta_beta.csv",
                          "2105-002", "TARJETA CORPORATIVA BETA", "PAYMENT RECEIVED - THANK YOU"),
}

TARJETAS: Tuple[Tarjeta, ...] = (
    Tarjeta("ALFA", "ANA DEMO", "1001"),
    Tarjeta("ALFA", "BRUNO DEMO", "1002"),
    Tarjeta("BETA", "CARLA DEMO", "2001"),
    Tarjeta("BETA", "DIEGO DEMO", "2002"),
)

# Cuentas contables: (cuenta, nombre).
CUENTA_BANCO = ("1102-001", "BANCO CUENTA CONCENTRADORA")
CUENTA_IVA = ("1180-001", "IVA ACREDITABLE PAGADO")
CUENTA_PROVEEDORES = ("2101-001", "PROVEEDORES NACIONALES")
CUENTA_ISR_NOMINA = ("2160-001", "ISR RETENIDO POR SALARIOS")
CUENTA_SUELDOS = ("6101-001", "SUELDOS Y SALARIOS")

CUENTAS_GASTO: Dict[str, Tuple[str, str]] = {
    "alimentos": ("6201-001", "ALIMENTOS Y CONSUMOS"),
    "combustible": ("6202-001", "COMBUSTIBLES Y LUBRICANTES"),
    "hospedaje": ("6203-001", "HOSPEDAJE"),
    "transporte": ("6204-001", "PASAJES Y TRANSPORTE"),
    "oficina": ("6205-001", "PAPELERIA Y ARTICULOS DE OFICINA"),
    "tecnologia": ("6206-001", "SOFTWARE Y SERVICIOS DE COMPUTO"),
    "estacionamiento": ("6207-001", "ESTACIONAMIENTOS Y PEAJES"),
    "mantenimiento": ("6208-001", "MANTENIMIENTO Y REPARACIONES"),
    "servicios": ("6209-001", "SERVICIOS GENERALES"),
    "renta": ("6210-001", "ARRENDAMIENTO DE INMUEBLES"),
    "honorarios": ("6211-001", "HONORARIOS PROFESIONALES"),
    "publicidad": ("6212-001", "PUBLICIDAD Y PROPAGANDA"),
    "seguros": ("6213-001", "SEGUROS Y FIANZAS"),
    "energia": ("6214-001", "ENERGIA ELECTRICA"),
    "varios": ("6299-001", "GASTOS VARIOS"),
}

CONCEPTOS: Dict[str, str] = {
    "alimentos": "CONSUMO DE ALIMENTOS",
    "combustible": "COMBUSTIBLE",
    "hospedaje": "SERVICIO DE HOSPEDAJE",
    "transporte": "SERVICIO DE TRANSPORTE",
    "oficina": "ARTICULOS DE OFICINA",
    "tecnologia": "EQUIPO Y SERVICIOS DE COMPUTO",
    "estacionamiento": "ESTACIONAMIENTO Y PEAJE",
    "mantenimiento": "SERVICIO DE MANTENIMIENTO",
    "servicios": "SERVICIOS GENERALES",
    "renta": "ARRENDAMIENTO DE OFICINA",
    "honorarios": "HONORARIOS",
    "publicidad": "SERVICIOS DE PUBLICIDAD",
    "seguros": "PRIMA DE SEGURO",
    "energia": "SUMINISTRO DE ENERGIA",
    "varios": "MERCANCIA VARIA",
}

PROVEEDOR_CUBETA = ("PRV-0999", "GASTOS VARIOS TARJETA", RFC_PUBLICO_GENERAL)


def _com(n: int, categoria: str, descriptor: str, ciudad: str, razon: str, proveedor: str,
         rango: Tuple[int, int], serie: str) -> Comercio:
    """Comercio nacional que sí factura."""
    return Comercio(f"COM{n:02d}", categoria, descriptor, ciudad, razon, proveedor,
                    f"PRV-{n:04d}", f"RFC_COM_{n:02d}", True, False, serie, rango)


def _sin_factura(n: int, categoria: str, descriptor: str, ciudad: str, proveedor: str,
                 rango: Tuple[int, int]) -> Comercio:
    """Comercio nacional que no emite CFDI; en el ERP lleva RFC genérico."""
    return Comercio(f"SFA{n:02d}", categoria, descriptor, ciudad, proveedor, proveedor,
                    f"PRV-{100 + n:04d}", RFC_PUBLICO_GENERAL, False, False, "", rango)


def _extranjero(n: int, descriptor: str, ciudad: str, razon: str, rango_usd: Tuple[int, int]) -> Comercio:
    """Comercio extranjero que cobra en USD y no emite CFDI."""
    return Comercio(f"EXT{n:02d}", "tecnologia", descriptor, ciudad, razon, razon,
                    f"PRV-{200 + n:04d}", RFC_EXTRANJERO, False, True, "EXT", rango_usd)


# Comercios nacionales que facturan en pesos (rango en pesos).
COMERCIOS: Tuple[Comercio, ...] = (
    _com(1, "alimentos", "CAFE LUNA AZUL 0231", "CDMX", "CAFETERIA LUNA AZUL SA DE CV",
         "CAFETERIA LUNA AZUL", (80, 900), "CLA"),
    _com(2, "alimentos", "TAQ EL FOGONCITO", "GDL", "TAQUERIA EL FOGONCITO SA DE CV",
         "TAQUERIA EL FOGONCITO", (150, 1800), "TEF"),
    _com(3, "alimentos", "REST TERRAZA DEL VALLE", "MTY",
         "RESTAURANTE LA TERRAZA DEL VALLE S DE RL DE CV", "RESTAURANTE TERRAZA DEL VALLE",
         (400, 4500), "RTV"),
    _com(4, "alimentos", "PAN TRIGO DORADO 12", "QRO", "PANADERIA TRIGO DORADO SA DE CV",
         "PANADERIA TRIGO DORADO", (60, 700), "PTD"),
    _com(5, "alimentos", "MARISCOS PUERTO VIEJO", "VER", "MARISCOS PUERTO VIEJO SA DE CV",
         "MARISCOS PUERTO VIEJO", (300, 3500), "MPV"),
    _com(6, "combustible", "GAS RUTA NORTE 5521", "MTY", "GASOLINERA RUTA NORTE SA DE CV",
         "GASOLINERA RUTA NORTE", (400, 2500), "GRN"),
    _com(7, "combustible", "ES EL CRUCERO 0874", "PUE", "ESTACION DE SERVICIO EL CRUCERO SA DE CV",
         "ESTACION DE SERVICIO EL CRUCERO", (350, 2200), "EEC"),
    _com(8, "combustible", "COMBUST DEL BAJIO", "LEON", "COMBUSTIBLES DEL BAJIO DEMO SA DE CV",
         "COMBUSTIBLES DEL BAJIO DEMO", (300, 2000), "CBD"),
    _com(9, "hospedaje", "HTL PLAZA CENTRAL", "CDMX", "HOTEL PLAZA CENTRAL DEMO SA DE CV",
         "HOTEL PLAZA CENTRAL DEMO", (1500, 9000), "HPC"),
    _com(10, "hospedaje", "HOTEL MIRADOR DEL LAGO", "MICH",
         "OPERADORA HOTEL MIRADOR DEL LAGO SA DE CV", "HOTEL MIRADOR DEL LAGO", (1800, 8000), "HML"),
    _com(11, "hospedaje", "POSADA LOS ARCOS", "OAX", "POSADA LOS ARCOS DE ANTEQUERA SA DE CV",
         "POSADA LOS ARCOS", (900, 5000), "PLA"),
    _com(12, "transporte", "AUTOBUSES RUTA DEMO", "CDMX", "AUTOBUSES RUTA DEMO SA DE CV",
         "AUTOBUSES RUTA DEMO", (250, 1800), "ARD"),
    _com(13, "transporte", "TAXI SEGURO EJEMPLO", "GDL", "TAXI SEGURO EJEMPLO SC",
         "TAXI SEGURO EJEMPLO", (80, 650), "TSE"),
    _com(14, "transporte", "AERODEMO NAL 0012", "CDMX", "AEROLINEA DEMO NACIONAL SA DE CV",
         "AEROLINEA DEMO NACIONAL", (1800, 9500), "ADN"),
    _com(15, "oficina", "PAPELERIA PLUMA FINA", "CDMX", "PAPELERIA LA PLUMA FINA SA DE CV",
         "PAPELERIA LA PLUMA FINA", (50, 1500), "PPF"),
    _com(16, "oficina", "SUMINISTROS OFI EJEMPLO", "MTY", "SUMINISTROS DE OFICINA EJEMPLO SA DE CV",
         "SUMINISTROS DE OFICINA EJEMPLO", (200, 4000), "SOE"),
    _com(17, "mantenimiento", "FERRET EL TORNILLO", "QRO", "FERRETERIA EL TORNILLO FELIZ SA DE CV",
         "FERRETERIA EL TORNILLO FELIZ", (100, 3000), "FTF"),
    _com(18, "tecnologia", "COMPUTO Y REDES MUESTRA", "GDL", "COMPUTO Y REDES MUESTRA SA DE CV",
         "COMPUTO Y REDES MUESTRA", (800, 12000), "CRM"),
    _com(19, "tecnologia", "SW NUBE DEMO MX", "CDMX", "SOFTWARE NUBE DEMO MEXICO SA DE CV",
         "SOFTWARE NUBE DEMO MEXICO", (300, 5000), "SND"),
    _com(20, "servicios", "TEL MOVIL EJEMPLO", "CDMX", "TELEFONIA MOVIL EJEMPLO SA DE CV",
         "TELEFONIA MOVIL EJEMPLO", (300, 2000), "TME"),
    _com(21, "mantenimiento", "TALLER EL PISTON", "PUE", "TALLER MECANICO EL PISTON SA DE CV",
         "TALLER MECANICO EL PISTON", (500, 7000), "TEP"),
    _com(22, "servicios", "LAVANDERIA BURBUJAS", "MTY", "LAVANDERIA BURBUJAS DEMO SA DE CV",
         "LAVANDERIA BURBUJAS DEMO", (90, 900), "LBD"),
    _com(23, "varios", "FARMACIA SALUD EJEMPLO", "CDMX", "FARMACIA SALUD EJEMPLO SA DE CV",
         "FARMACIA SALUD EJEMPLO", (60, 1500), "FSE"),
    _com(24, "varios", "FLORERIA JARDIN DEMO", "GDL", "FLORERIA JARDIN DEMO SA DE CV",
         "FLORERIA JARDIN DEMO", (300, 2500), "FJD"),
    _com(25, "servicios", "MENSAJ RAPIDA MUESTRA", "CDMX", "MENSAJERIA RAPIDA MUESTRA SA DE CV",
         "MENSAJERIA RAPIDA MUESTRA", (120, 1600), "MRM"),
    _com(26, "oficina", "LIBRERIA PAGINA DEMO", "QRO", "LIBRERIA PAGINA DEMO SA DE CV",
         "LIBRERIA PAGINA DEMO", (150, 2500), "LPD"),
    _com(27, "oficina", "IMPRENTA TINTA EJEMPLO", "PUE", "IMPRENTA TINTA EJEMPLO SA DE CV",
         "IMPRENTA TINTA EJEMPLO", (400, 6000), "ITE"),
    _com(28, "alimentos", "COCINA LA OLLA DEMO", "CDMX", "COCINA ECONOMICA LA OLLA DEMO SA DE CV",
         "COCINA ECONOMICA LA OLLA DEMO", (70, 600), "COD"),
)

# Comercios nacionales que cobran en USD y facturan en USD (rango en dólares).
COMERCIOS_USD: Tuple[Comercio, ...] = (
    _com(29, "hospedaje", "HOTEL PLAYA DEMO", "QROO", "HOTEL PLAYA DEMO SA DE CV",
         "HOTEL PLAYA DEMO", (120, 600), "HPD"),
    _com(30, "transporte", "RENTA AUTOS EJEMPLO", "QROO", "RENTA DE AUTOS EJEMPLO SA DE CV",
         "RENTA DE AUTOS EJEMPLO", (60, 400), "RAE"),
)

COMERCIOS_SIN_FACTURA: Tuple[Comercio, ...] = (
    _sin_factura(1, "estacionamiento", "ESTACIONAMIENTO PLAZA", "CDMX",
                 "ESTACIONAMIENTO PLAZA DEMO", (30, 400)),
    _sin_factura(2, "estacionamiento", "CASETA AUTOPISTA DEMO", "MEX", "CASETAS AUTOPISTA DEMO", (60, 900)),
    _sin_factura(3, "varios", "TIENDITA LA ESQUINA", "GDL", "TIENDITA LA ESQUINA", (25, 600)),
    _sin_factura(4, "estacionamiento", "PARQUIMETRO MUNICIPAL", "QRO",
                 "PARQUIMETROS MUNICIPALES DEMO", (20, 300)),
    _sin_factura(5, "alimentos", "JUGOS EL OASIS", "PUE", "JUGOS EL OASIS", (30, 400)),
    _sin_factura(6, "servicios", "LAVA AUTOS EL BRILLO", "MTY", "AUTOLAVADO EL BRILLO", (80, 700)),
)

COMERCIOS_EXTRANJEROS: Tuple[Comercio, ...] = (
    _extranjero(1, "DEMOCLOUD TOOLS", "US", "DEMO CLOUD TOOLS LLC", (10, 300)),
    _extranjero(2, "SAMPLE DESIGN SUITE", "US", "SAMPLE DESIGN SUITE INC", (15, 250)),
    _extranjero(3, "EXAMPLE VIDEO MEET", "US", "EXAMPLE VIDEO MEETINGS INC", (12, 150)),
    _extranjero(4, "TESTDATA STORAGE", "IE", "TEST DATA STORAGE LTD", (5, 120)),
    _extranjero(5, "MOCKUP STOCK IMAGES", "US", "MOCKUP STOCK IMAGES LLC", (20, 200)),
)


@dataclass(frozen=True)
class ProveedorRuido:
    """Proveedor que se paga por transferencia: sus CFDIs nunca respaldan cargos."""

    proveedor_id: str
    nombre: str
    rfc: str
    categoria: str
    serie: str
    rango: Tuple[int, int]


PROVEEDORES_RUIDO: Tuple[ProveedorRuido, ...] = tuple(
    ProveedorRuido(f"PRV-{300 + n:04d}", nombre, f"RFC_PRV_{n:02d}", categoria, serie, rango)
    for n, (nombre, categoria, serie, rango) in enumerate((
        ("INMOBILIARIA DEMO NORTE SA DE CV", "renta", "IDN", (15000, 45000)),
        ("SERVICIOS DE LIMPIEZA EJEMPLO SA DE CV", "servicios", "SLE", (3000, 12000)),
        ("DESPACHO CONTABLE MUESTRA SC", "honorarios", "DCM", (8000, 30000)),
        ("ENERGIA DEMO DEL CENTRO SA DE CV", "energia", "EDM", (2000, 9000)),
        ("AGENCIA DE PUBLICIDAD MUESTRA SA DE CV", "publicidad", "APM", (5000, 40000)),
        ("SEGUROS FICTICIOS DEL VALLE SA DE CV", "seguros", "SFV", (4000, 20000)),
        ("VIGILANCIA Y SEGURIDAD EJEMPLO SA DE CV", "servicios", "VSE", (6000, 18000)),
        ("MANTENIMIENTO INDUSTRIAL DEMO SA DE CV", "mantenimiento", "MID", (1500, 15000)),
        ("AGUA PURIFICADA MUESTRA SA DE CV", "servicios", "APU", (300, 2500)),
        ("SOPORTE TECNICO EJEMPLO SC", "tecnologia", "STE", (2500, 14000)),
    ), 1)
)

EMPLEADOS: Tuple[Tuple[str, str, str], ...] = tuple(
    (f"EMP-{n:02d}", f"EMPLEADO SINTETICO {n:02d}", f"RFC_EMPLEADO_{n:02d}") for n in range(1, 10)
)
