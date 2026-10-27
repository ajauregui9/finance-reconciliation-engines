"""Catálogo de layouts de estado de cuenta e interpretación de sus filas.

Un layout se reconoce solo por su encabezado completo, comparado sin ninguna
tolerancia. Cada layout trae su propia función que convierte las celdas de una
fila (ya emparejadas con los nombres de columna) en una `Lectura`: los campos
canónicos que se pudieron leer y la lista de problemas encontrados. Ninguna
función de este módulo descarta filas ni decide si un estado cuadra; eso lo
hace `conciliacion.universo`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Callable, Dict, Mapping, Optional, Pattern, Sequence, Tuple

from .montos import leer_importe, leer_tipo_cambio


class ErrorInsumo(Exception):
    """Un insumo no se puede usar; la corrida se detiene sin escribir nada."""


class EncabezadoDesconocido(ErrorInsumo):
    """El encabezado de un archivo no coincide con ningún layout del catálogo."""


# Motivos por los que una fila queda ininterpretable, en orden de reporte.
FILA_VACIA = "fila_vacia"
COLUMNAS_INCOMPLETAS = "columnas_incompletas"
FECHA_INVALIDA = "fecha_invalida"
FECHA_APLICACION_INVALIDA = "fecha_aplicacion_invalida"
DESCRIPCION_VACIA = "descripcion_vacia"
TITULAR_VACIO = "titular_vacio"
TARJETA_INVALIDA = "tarjeta_invalida"
MONTO_INVALIDO = "monto_invalido"
MONTO_AMBIGUO = "monto_ambiguo"
MONTO_CERO = "monto_cero"
MONEDA_ORIGINAL_INVALIDA = "moneda_original_invalida"
ORDEN_MOTIVOS: Tuple[str, ...] = (
    FILA_VACIA, COLUMNAS_INCOMPLETAS, FECHA_INVALIDA, FECHA_APLICACION_INVALIDA,
    DESCRIPCION_VACIA, TITULAR_VACIO, TARJETA_INVALIDA, MONTO_INVALIDO, MONTO_AMBIGUO,
    MONTO_CERO, MONEDA_ORIGINAL_INVALIDA,
)

TIPO_CARGO = "cargo"
TIPO_PAGO = "pago"
TIPO_ABONO = "abono"

ORDEN_DIA_MES = "DMA"
ORDEN_MES_DIA = "MDA"
_PATRON_FECHA = re.compile(r"([0-9]{2})/([0-9]{2})/([0-9]{4})")
_PATRON_CODIGO_MONEDA = re.compile(r"[A-Z]{3}")
_MONEDA_NACIONAL = "MXN"


@dataclass(frozen=True)
class Lectura:
    """Campos canónicos de una fila; `None` significa que no se pudo leer."""

    fecha: Optional[date]
    fecha_aplicacion: Optional[date]
    descripcion: Optional[str]
    titular: Optional[str]
    tarjeta_ultimos4: Optional[str]
    monto: Optional[Decimal]
    monto_original: Optional[Decimal]
    moneda_original: Optional[str]
    tipo_cambio: Optional[Decimal]
    problemas: Tuple[str, ...]


@dataclass(frozen=True)
class Layout:
    nombre: str
    encabezado: Tuple[str, ...]
    moneda: str  # moneda de facturación: la del importe que cobra el emisor
    marca_pago: str  # prefijo de la descripción de un pago a la tarjeta
    interpretar: Callable[[Mapping[str, str]], Lectura]


@dataclass(frozen=True)
class _Origen:
    moneda: str
    monto: Optional[Decimal]
    tipo_cambio: Optional[Decimal]


@dataclass(frozen=True)
class _Importes:
    monto: Optional[Decimal]
    origen: Optional[_Origen]  # None: datos de moneda de origen inválidos
    problemas: Tuple[str, ...]


@dataclass(frozen=True)
class _Columnas:
    """Nombres de las columnas comunes a todo layout."""

    fecha: str
    aplicacion: str
    descripcion: str
    titular: str
    tarjeta: str


# --- piezas comunes -----------------------------------------------------------


def leer_fecha(texto: str, orden: str) -> Optional[date]:
    """Lee `NN/NN/AAAA` en el orden indicado; `None` si no existe esa fecha."""
    if orden not in (ORDEN_DIA_MES, ORDEN_MES_DIA):
        raise ValueError(f"orden de fecha desconocido: {orden!r}")
    partes = _PATRON_FECHA.fullmatch(texto.strip())
    if partes is None:
        return None
    primero, segundo, anio = (int(p) for p in partes.groups())
    dia, mes = (primero, segundo) if orden == ORDEN_DIA_MES else (segundo, primero)
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None  # 30 de febrero, mes 13: la fila se marca, no se corrige


def clasificar_movimiento(
    monto: Optional[Decimal], descripcion: Optional[str], marca_pago: str
) -> Optional[str]:
    """Cargo si es positivo; pago o abono si es negativo; `None` si no aplica."""
    if monto is None or monto == 0:
        return None
    if monto > 0:
        return TIPO_CARGO
    es_pago = descripcion is not None and descripcion.upper().startswith(marca_pago.upper())
    return TIPO_PAGO if es_pago else TIPO_ABONO


def _texto_libre(crudo: str) -> Optional[str]:
    compacto = " ".join(crudo.split())
    return compacto if compacto else None


def _tarjeta(crudo: str, patron: Pattern[str]) -> Optional[str]:
    hallado = patron.fullmatch(crudo.strip())
    return hallado.group(1) if hallado else None


def _problema_de_monto(monto: Optional[Decimal]) -> Tuple[str, ...]:
    if monto is None:
        return (MONTO_INVALIDO,)
    return (MONTO_CERO,) if monto == 0 else ()


def _armar_lectura(
    celdas: Mapping[str, str], columnas: _Columnas, orden: str,
    patron_tarjeta: Pattern[str], importes: _Importes,
) -> Lectura:
    fecha = leer_fecha(celdas[columnas.fecha], orden)
    aplicacion = leer_fecha(celdas[columnas.aplicacion], orden)
    descripcion = _texto_libre(celdas[columnas.descripcion])
    titular = _texto_libre(celdas[columnas.titular])
    tarjeta = _tarjeta(celdas[columnas.tarjeta], patron_tarjeta)
    ausentes = {
        FECHA_INVALIDA: fecha is None,
        FECHA_APLICACION_INVALIDA: aplicacion is None,
        DESCRIPCION_VACIA: descripcion is None,
        TITULAR_VACIO: titular is None,
        TARJETA_INVALIDA: tarjeta is None,
        MONEDA_ORIGINAL_INVALIDA: importes.origen is None,
    }
    encontrados = {m for m, falta in ausentes.items() if falta} | set(importes.problemas)
    origen = importes.origen
    return Lectura(
        fecha=fecha, fecha_aplicacion=aplicacion, descripcion=descripcion, titular=titular,
        tarjeta_ultimos4=tarjeta, monto=importes.monto,
        monto_original=origen.monto if origen else None,
        moneda_original=origen.moneda if origen else None,
        tipo_cambio=origen.tipo_cambio if origen else None,
        problemas=tuple(m for m in ORDEN_MOTIVOS if m in encontrados),
    )


def _lectura_sin_campos(motivo: str) -> Lectura:
    return Lectura(None, None, None, None, None, None, None, None, None, (motivo,))


def _codigo_extranjero(texto: str) -> Optional[str]:
    codigo = texto.strip()
    if _PATRON_CODIGO_MONEDA.fullmatch(codigo) and codigo != _MONEDA_NACIONAL:
        return codigo
    return None


def _mismo_signo(a: Decimal, b: Decimal) -> bool:
    return (a > 0) == (b > 0)


# --- ALFA_V1: importe único firmado, fechas día/mes ------------------------------

_ALFA = _Columnas("Fecha de operación", "Fecha de aplicación", "Descripción", "Titular",
                  "Tarjeta")
_ALFA_MONEDA, _ALFA_IMPORTE_ORIGEN = "Moneda origen", "Importe origen"
_ALFA_TIPO_CAMBIO, _ALFA_IMPORTE = "Tipo de cambio", "Importe MXN"
_ALFA_TARJETA = re.compile(r"\*+([0-9]{4})")


def _origen_alfa(celdas: Mapping[str, str], monto: Optional[Decimal]) -> Optional[_Origen]:
    importe = leer_importe(celdas[_ALFA_IMPORTE_ORIGEN], con_signo=True, con_miles=True)
    texto_tc = celdas[_ALFA_TIPO_CAMBIO].strip()
    codigo = celdas[_ALFA_MONEDA].strip()
    if importe is None:
        return None
    if codigo == _MONEDA_NACIONAL:
        coincide = monto is None or importe == monto
        return _Origen(codigo, importe, None) if coincide and not texto_tc else None
    extranjera = _codigo_extranjero(codigo)
    tipo_cambio = leer_tipo_cambio(texto_tc)
    if extranjera is None or tipo_cambio is None or importe == 0:
        return None
    if monto is not None and not _mismo_signo(importe, monto):
        return None
    return _Origen(extranjera, importe, tipo_cambio)


def _interpretar_alfa(celdas: Mapping[str, str]) -> Lectura:
    monto = leer_importe(celdas[_ALFA_IMPORTE], con_signo=True, con_miles=True)
    importes = _Importes(monto, _origen_alfa(celdas, monto), _problema_de_monto(monto))
    return _armar_lectura(celdas, _ALFA, ORDEN_DIA_MES, _ALFA_TARJETA, importes)


# --- BETA_V1: columnas de cargo y crédito sin signo, fechas mes/día ---------------

_BETA = _Columnas("Transaction Date", "Post Date", "Description", "Card Member",
                  "Account Ending")
_BETA_EXTRANJERO, _BETA_DIVISA = "Foreign Spend Amount", "Foreign Currency"
_BETA_TIPO_CAMBIO, _BETA_CARGO, _BETA_CREDITO = "Exchange Rate", "Charges", "Credits"
_BETA_TARJETA = re.compile(r"([0-9]{4})")


def _monto_beta(celdas: Mapping[str, str]) -> Tuple[Optional[Decimal], Tuple[str, ...]]:
    cargo = celdas[_BETA_CARGO].strip()
    credito = celdas[_BETA_CREDITO].strip()
    if bool(cargo) == bool(credito):
        return None, (MONTO_AMBIGUO,)
    valor = leer_importe(cargo or credito, con_signo=False, con_miles=False)
    if valor is None:
        return None, (MONTO_INVALIDO,)
    monto = valor if cargo else Decimal(0) - valor
    return monto, _problema_de_monto(monto)


def _origen_beta(celdas: Mapping[str, str], monto: Optional[Decimal]) -> Optional[_Origen]:
    textos = tuple(celdas[c].strip() for c in (_BETA_EXTRANJERO, _BETA_DIVISA, _BETA_TIPO_CAMBIO))
    if not any(textos):
        return _Origen(_MONEDA_NACIONAL, monto, None)
    if not all(textos):
        return None
    importe = leer_importe(textos[0], con_signo=False, con_miles=False)
    codigo = _codigo_extranjero(textos[1])
    tipo_cambio = leer_tipo_cambio(textos[2])
    if importe is None or importe == 0 or codigo is None or tipo_cambio is None:
        return None
    # El importe extranjero no trae signo: toma el del importe cobrado, si se conoce.
    firmado = None if monto is None else (importe if monto >= 0 else Decimal(0) - importe)
    return _Origen(codigo, firmado, tipo_cambio)


def _interpretar_beta(celdas: Mapping[str, str]) -> Lectura:
    monto, problemas = _monto_beta(celdas)
    importes = _Importes(monto, _origen_beta(celdas, monto), problemas)
    return _armar_lectura(celdas, _BETA, ORDEN_MES_DIA, _BETA_TARJETA, importes)


# --- catálogo -------------------------------------------------------------------


def armar_catalogo(layouts: Sequence[Layout]) -> Mapping[str, Layout]:
    """Catálogo inmutable por nombre; rechaza nombres o encabezados repetidos."""
    por_nombre: Dict[str, Layout] = {}
    vistos: Dict[Tuple[str, ...], str] = {}
    for layout in layouts:
        if layout.nombre in por_nombre:
            raise ValueError(f"layout repetido en el catálogo: {layout.nombre}")
        if layout.encabezado in vistos:
            raise ValueError(
                f"{layout.nombre} repite el encabezado de {vistos[layout.encabezado]}")
        por_nombre[layout.nombre] = layout
        vistos[layout.encabezado] = layout.nombre
    return MappingProxyType(por_nombre)


def _encabezado(columnas: _Columnas, *resto: str) -> Tuple[str, ...]:
    return (columnas.fecha, columnas.aplicacion, columnas.descripcion, columnas.titular,
            columnas.tarjeta) + resto


LAYOUTS: Mapping[str, Layout] = armar_catalogo((
    Layout(
        nombre="ALFA_V1",
        encabezado=_encabezado(_ALFA, _ALFA_MONEDA, _ALFA_IMPORTE_ORIGEN, _ALFA_TIPO_CAMBIO,
                               _ALFA_IMPORTE),
        moneda=_MONEDA_NACIONAL, marca_pago="PAGO RECIBIDO", interpretar=_interpretar_alfa),
    Layout(
        nombre="BETA_V1",
        encabezado=_encabezado(_BETA, _BETA_EXTRANJERO, _BETA_DIVISA, _BETA_TIPO_CAMBIO,
                               _BETA_CARGO, _BETA_CREDITO),
        moneda=_MONEDA_NACIONAL, marca_pago="PAYMENT RECEIVED", interpretar=_interpretar_beta),
))


def detectar_layout(encabezado: Sequence[str], origen: str) -> Layout:
    """Devuelve el layout cuyo encabezado es idéntico al leído; nunca adivina."""
    leido = tuple(encabezado)
    for layout in LAYOUTS.values():
        if layout.encabezado == leido:
            return layout
    conocidos = ", ".join(sorted(LAYOUTS))
    raise EncabezadoDesconocido(
        f"{origen}: encabezado desconocido {list(leido)!r}. Debe coincidir exactamente "
        f"con uno de los layouts conocidos ({conocidos}); el layout no se adivina.")


def interpretar_fila(layout: Layout, celdas: Sequence[str]) -> Lectura:
    """Interpreta una fila de datos; las filas vacías o desalineadas se marcan."""
    if all(not celda.strip() for celda in celdas):
        return _lectura_sin_campos(FILA_VACIA)
    if len(celdas) != len(layout.encabezado):
        return _lectura_sin_campos(COLUMNAS_INCOMPLETAS)
    return layout.interpretar(dict(zip(layout.encabezado, celdas)))
