"""Lector de CFDI 3.3/4.0 en XML para el cruce cargo ↔ CFDI.

El XML se parsea únicamente con `defusedxml` (sin DTD, sin entidades, sin
referencias externas). Si la biblioteca no está instalada, la lectura falla con
`DependenciaFaltante`: no existe un lector alternativo. Cada comprobante se
traduce al mismo registro que `cfdis.jsonl` y pasa por la misma validación.

`cargar_cfdis_xml_con_montos` lee además `SubTotal` y el IVA trasladado del comprobante
(montos que el cruce cargo ↔ CFDI no usa), sin validar que cuadren con `Total`.
"""
from __future__ import annotations

import hashlib
import importlib
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Dict, Optional, Tuple, Type, TypeVar, cast

from .cruce_cfdi_insumos import a_monto, cfdi_desde_dict, verificar_unicos
from .cruce_cfdi_modelo import MONEDA_LOCAL, Cfdi, InsumoInvalido

ESPACIOS_CFDI = ("http://www.sat.gob.mx/cfd/4", "http://www.sat.gob.mx/cfd/3")
ESPACIO_TIMBRE = "http://www.sat.gob.mx/TimbreFiscalDigital"
MONEDA_SIN_VALOR = "XXX"
DIEZMILESIMO = Decimal("0.0001")
CENTAVO = Decimal("0.01")
SIN_IVA = Decimal("0.00")
IMPUESTO_IVA = "002"
FACTOR_EXENTO = "Exento"

T = TypeVar("T")


class DependenciaFaltante(RuntimeError):
    """Falta una biblioteca obligatoria para leer el insumo."""


@dataclass(frozen=True)
class CfdiConMontos:
    """Un CFDI con su `SubTotal` y su IVA trasladado, en la moneda del comprobante."""

    cfdi: Cfdi
    subtotal: Decimal
    iva_trasladado: Decimal


_Errores = Tuple[Type[BaseException], ...]


def _parser_seguro() -> Tuple[ModuleType, _Errores]:
    try:
        arbol = importlib.import_module("defusedxml.ElementTree")
        base = importlib.import_module("defusedxml")
    except ImportError:
        raise DependenciaFaltante(
            "leer CFDI en XML requiere defusedxml (pip install defusedxml); no hay lector alternativo"
        ) from None
    errores = (cast(Type[BaseException], arbol.ParseError), cast(Type[BaseException], base.DefusedXmlException))
    return arbol, errores


def _atributo(nodo: Any, nombre: str, archivo: str, obligatorio: bool = True) -> Optional[str]:
    valor = nodo.get(nombre)
    if valor is None and obligatorio:
        raise InsumoInvalido(f"{archivo}: falta el atributo {nombre} en {_etiqueta(nodo)}")
    return None if valor is None else str(valor)


def _etiqueta(nodo: Any) -> str:
    return str(nodo.tag).rsplit("}", 1)[-1]


def _hijo(raiz: Any, espacio: str, nombre: str, archivo: str) -> Any:
    nodo = raiz.find(f"{{{espacio}}}{nombre}")
    if nodo is None:
        raise InsumoInvalido(f"{archivo}: falta el nodo {nombre}")
    return nodo


def _total_en_pesos(total: Decimal, moneda: str, tipo_cambio: Optional[str], archivo: str) -> Decimal:
    if moneda in (MONEDA_LOCAL, MONEDA_SIN_VALOR):
        return total
    if tipo_cambio is None:
        raise InsumoInvalido(f"{archivo}: falta TipoCambio para un comprobante en {moneda}")
    try:
        tasa = Decimal(tipo_cambio).quantize(DIEZMILESIMO, rounding=ROUND_HALF_UP)
    except ArithmeticError:
        raise InsumoInvalido(f"{archivo}: TipoCambio ilegible {tipo_cambio!r}") from None
    return (total * tasa).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _espacio(raiz: Any) -> str:
    return str(raiz.tag)[1:].split("}", 1)[0] if str(raiz.tag).startswith("{") else ""


def _registro(raiz: Any, archivo: str, rfc_empresa: str) -> Dict[str, Any]:
    espacio = _espacio(raiz)
    if espacio not in ESPACIOS_CFDI or _etiqueta(raiz) != "Comprobante":
        raise InsumoInvalido(f"{archivo}: la raíz no es un cfdi:Comprobante 3.3/4.0")
    emisor = _hijo(raiz, espacio, "Emisor", archivo)
    receptor = _hijo(raiz, espacio, "Receptor", archivo)
    timbre = raiz.find(f".//{{{ESPACIO_TIMBRE}}}TimbreFiscalDigital")
    if timbre is None:
        raise InsumoInvalido(f"{archivo}: falta el TimbreFiscalDigital (sin UUID)")
    relacionado = raiz.find(f"{{{espacio}}}CfdiRelacionados/{{{espacio}}}CfdiRelacionado")
    moneda = _atributo(raiz, "Moneda", archivo) or ""
    total = a_monto(_atributo(raiz, "Total", archivo), f"{archivo}: Total")
    rfc_emisor = _atributo(emisor, "Rfc", archivo)
    fecha = _atributo(raiz, "Fecha", archivo) or ""
    try:
        emision = datetime.fromisoformat(fecha).date().isoformat()
    except ValueError:
        raise InsumoInvalido(f"{archivo}: Fecha ilegible {fecha!r}") from None
    return {
        "uuid": _atributo(timbre, "UUID", archivo),
        "fecha_emision": emision,
        "tipo_comprobante": _atributo(raiz, "TipoDeComprobante", archivo),
        "direccion": "emitido" if rfc_emisor == rfc_empresa else "recibido",
        "rfc_emisor": rfc_emisor,
        "nombre_emisor": _atributo(emisor, "Nombre", archivo, obligatorio=False) or "",
        "rfc_receptor": _atributo(receptor, "Rfc", archivo),
        "moneda": moneda,
        "total": str(total),
        "total_mxn": str(_total_en_pesos(total, moneda, _atributo(raiz, "TipoCambio", archivo, False), archivo)),
        "uuid_relacionado": None if relacionado is None else _atributo(relacionado, "UUID", archivo),
    }


def _monto_no_negativo(texto: Optional[str], campo: str) -> Decimal:
    monto = a_monto(texto, campo)
    if monto < 0:
        raise InsumoInvalido(f"{campo}: no puede ser negativo; llegó {monto}")
    return monto


def _importe_iva(traslado: Any, archivo: str) -> Decimal:
    """Un traslado exento no lleva `Importe` y aporta cero; cualquier otro lo exige."""
    if traslado.get("TipoFactor") == FACTOR_EXENTO and traslado.get("Importe") is None:
        return SIN_IVA
    return _monto_no_negativo(_atributo(traslado, "Importe", archivo), f"{archivo}: Importe del Traslado de IVA")


def _iva_trasladado(raiz: Any, archivo: str) -> Decimal:
    """`TotalImpuestosTrasladados` del nodo Impuestos del comprobante o, si falta, sus traslados 002."""
    espacio = _espacio(raiz)
    impuestos = raiz.find(f"{{{espacio}}}Impuestos")
    if impuestos is None:
        return SIN_IVA
    declarado = _atributo(impuestos, "TotalImpuestosTrasladados", archivo, obligatorio=False)
    if declarado is not None:
        return _monto_no_negativo(declarado, f"{archivo}: TotalImpuestosTrasladados")
    traslados = impuestos.findall(f"{{{espacio}}}Traslados/{{{espacio}}}Traslado")
    return sum((_importe_iva(t, archivo) for t in traslados if t.get("Impuesto") == IMPUESTO_IVA), SIN_IVA)


def _leer_uno(ruta: Path, arbol: ModuleType, errores: _Errores, armar: Callable[[Any, str], T]) -> T:
    try:
        raiz = arbol.fromstring(ruta.read_bytes(), forbid_dtd=True)
    except OSError as exc:
        raise InsumoInvalido(f"no se puede leer {ruta}: {exc.strerror or exc}") from None
    except errores as exc:
        raise InsumoInvalido(f"{ruta.name}: XML rechazado ({type(exc).__name__}: {exc})") from None
    try:
        return armar(raiz, ruta.name)
    except InsumoInvalido as exc:
        mensaje = str(exc)
        raise InsumoInvalido(mensaje if mensaje.startswith(ruta.name) else f"{ruta.name}: {mensaje}") from None


def archivos_xml(directorio: Path) -> Tuple[Path, ...]:
    if not directorio.is_dir():
        raise InsumoInvalido(f"{directorio} no es un directorio")
    archivos = tuple(sorted(p for p in directorio.iterdir() if p.is_file() and p.suffix.lower() == ".xml"))
    if not archivos:
        raise InsumoInvalido(f"{directorio}: no contiene archivos .xml")
    return archivos


def _cargar(directorio: Path, armar: Callable[[Any, str], T], uuid_de: Callable[[T], str]) -> Tuple[T, ...]:
    arbol, errores = _parser_seguro()
    leidos = [(ruta.name, _leer_uno(ruta, arbol, errores, armar)) for ruta in archivos_xml(directorio)]
    verificar_unicos(((uuid_de(leido), nombre) for nombre, leido in leidos), "uuid")
    return tuple(sorted((leido for _, leido in leidos), key=uuid_de))


def cargar_cfdis_xml(directorio: Path, rfc_empresa: str) -> Tuple[Cfdi, ...]:
    """Todos los `.xml` del directorio, ordenados por uuid; un UUID repetido es un error."""

    def armar(raiz: Any, archivo: str) -> Cfdi:
        return cfdi_desde_dict(_registro(raiz, archivo, rfc_empresa))

    return _cargar(directorio, armar, lambda cfdi: cfdi.uuid)


def cargar_cfdis_xml_con_montos(directorio: Path, rfc_empresa: str) -> Tuple[CfdiConMontos, ...]:
    """Como `cargar_cfdis_xml`, más `SubTotal` (obligatorio) y el IVA trasladado de cada comprobante."""

    def armar(raiz: Any, archivo: str) -> CfdiConMontos:
        cfdi = cfdi_desde_dict(_registro(raiz, archivo, rfc_empresa))
        subtotal = _monto_no_negativo(_atributo(raiz, "SubTotal", archivo), f"{archivo}: SubTotal")
        return CfdiConMontos(cfdi, subtotal, _iva_trasladado(raiz, archivo))

    return _cargar(directorio, armar, lambda leido: leido.cfdi.uuid)


def huella_directorio(directorio: Path) -> str:
    """SHA-256 estable del conjunto de XML: nombre y huella de cada archivo, en orden."""
    resumen = hashlib.sha256()
    for ruta in archivos_xml(directorio):
        resumen.update(f"{ruta.name}\0{hashlib.sha256(ruta.read_bytes()).hexdigest()}\n".encode("utf-8"))
    return resumen.hexdigest()
