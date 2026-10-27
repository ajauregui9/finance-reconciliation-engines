"""Respuestas grabadas sintéticas: lo que "respondería" el modelo, con errores plantados.

No son respuestas de Claude. Las escribe este generador para que el modo grabado pueda
probar el pipeline de evaluación sin red ni llave. Parten de la verdad del documento y le
aplican, según el caso, un error verosímil. El uso de tokens es una aproximación fija
(~4 caracteres por token), no un conteo real.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Optional, Tuple

from .casos import (
    COMA_MILES_EN_RESPUESTA,
    DIGITO_TOTAL,
    FECHA_LITERAL,
    IEPS_EN_IVA,
    IVA_OMITIDO,
    IVA_SOBRE_TOTAL,
    OBEDECE_INYECCION,
    RETENCION_OMITIDA,
)
from .catalogo import TASA_GENERAL
from .fabricas import CENTAVO, DocumentoSintetico, texto_monto
from .inyecciones import INYECCIONES, efecto_de

ESQUEMA_GRABADA = "respuesta_grabada/v1"
ORIGEN_SINTETICO = "sintetico"
MODELO_FICTICIO = "fixture-sintetico"
NOMBRE_HERRAMIENTA = "registrar_cfdi"
CARACTERES_POR_TOKEN = 4
TOKENS_FIJOS_ENTRADA = 600  # instrucciones de sistema y definición de la herramienta
TOKENS_FIJOS_SALIDA = 40
MIL = Decimal("1000")
DESPLAZAMIENTO_DIGITO = 5
CAMPOS_MONTO = ("subtotal", "descuento", "iva", "ieps", "isr_retenido", "iva_retenido", "total")

Entrada = Dict[str, Optional[str]]


@dataclass(frozen=True)
class ErrorPlantado:
    documento_id: str
    tipo: str
    campos: Tuple[str, ...]
    contrafactual: bool


def _cambiar_digito(monto: str) -> str:
    """Cambia el dígito de las decenas de la parte entera (o el de las unidades si no hay)."""
    entero, decimales = monto.split(".")
    posicion = max(len(entero) - 2, 0)
    nuevo = str((int(entero[posicion]) + DESPLAZAMIENTO_DIGITO) % 10)
    return f"{entero[:posicion]}{nuevo}{entero[posicion + 1:]}.{decimales}"


def _fecha_impresa(iso: str) -> str:
    anio, mes, dia = iso.split("-")
    return f"{dia}/{mes}/{anio}"


def _con_comas(valor: Optional[str]) -> Optional[str]:
    if valor is None or Decimal(valor) < MIL:
        return valor
    return f"{Decimal(valor):,.2f}"


def _iva_sobre_total(entrada: Entrada) -> Entrada:
    """El error de aplicar la tasa al total: IVA y subtotal cambian, su suma no."""
    total = Decimal(str(entrada["total"]))
    iva = (total * TASA_GENERAL).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return {**entrada, "subtotal": texto_monto(total - iva), "iva": texto_monto(iva)}


def _ieps_en_iva(entrada: Entrada) -> Entrada:
    """El error de sumar el IEPS al IVA: el desglose cambia y la suma no."""
    iva = Decimal(str(entrada["iva"])) + Decimal(str(entrada["ieps"]))
    return {**entrada, "iva": texto_monto(iva), "ieps": None}


def _con_error(documento: DocumentoSintetico, entrada: Entrada) -> Entrada:
    tipo = documento.caso.error_modelo
    if tipo == DIGITO_TOTAL:
        return {**entrada, "total": _cambiar_digito(str(entrada["total"]))}
    if tipo == IVA_OMITIDO:
        return {**entrada, "iva": None}
    if tipo == FECHA_LITERAL:
        return {**entrada, "fecha": _fecha_impresa(str(entrada["fecha"]))}
    if tipo == IVA_SOBRE_TOTAL:
        return _iva_sobre_total(entrada)
    if tipo == COMA_MILES_EN_RESPUESTA:
        return {**entrada, **{c: _con_comas(entrada[c]) for c in CAMPOS_MONTO}}
    if tipo == RETENCION_OMITIDA:
        return {**entrada, "isr_retenido": None, "iva_retenido": None}
    if tipo == IEPS_EN_IVA:
        return _ieps_en_iva(entrada)
    if tipo == OBEDECE_INYECCION:
        campo, valor = efecto_de(documento.caso)
        return {**entrada, campo: valor}
    return entrada


def entrada_modelo(documento: DocumentoSintetico) -> Entrada:
    return _con_error(documento, dict(documento.verdad))


def error_plantado(documento: DocumentoSintetico) -> Optional[ErrorPlantado]:
    tipo = documento.caso.error_modelo
    if tipo is None:
        return None
    verdad = dict(documento.verdad)
    entrada = entrada_modelo(documento)
    campos = tuple(sorted(c for c in verdad if entrada[c] != verdad[c]))
    inyeccion = documento.caso.inyeccion
    contrafactual = inyeccion is not None and not INYECCIONES[inyeccion].pensada_para_evadir
    return ErrorPlantado(documento.documento_id, tipo, campos, contrafactual)


def _tokens(caracteres: int) -> int:
    return math.ceil(caracteres / CARACTERES_POR_TOKEN)


def respuesta_grabada(documento: DocumentoSintetico, texto: str) -> Dict[str, Any]:
    entrada = entrada_modelo(documento)
    caracteres_salida = sum(len(c) + len(v or "") for c, v in entrada.items())
    return {
        "esquema": ESQUEMA_GRABADA,
        "documento_id": documento.documento_id,
        "sha256_documento": hashlib.sha256(texto.encode("utf-8")).hexdigest(),
        "origen": ORIGEN_SINTETICO,
        "respuesta": {
            "model": MODELO_FICTICIO,
            "stop_reason": "tool_use",
            "usage": {"input_tokens": TOKENS_FIJOS_ENTRADA + _tokens(len(texto)),
                      "output_tokens": TOKENS_FIJOS_SALIDA + _tokens(caracteres_salida)},
            "content": [{"type": "tool_use", "name": NOMBRE_HERRAMIENTA, "input": entrada}],
        },
    }
