"""Salidas JSON deterministas: el resumen de 13 semanas y las filas contrato (JSONL).

Llaves ordenadas, montos como texto con dos decimales, UTF-8 y LF, sin marcas de
tiempo ni rutas absolutas: dos corridas iguales producen los mismos bytes.
"""
from __future__ import annotations

import json
from typing import Dict, List

from .avisos import avisos
from .calendario import fin_horizonte
from .contrato import CONCEPTO_DE_FUENTE, CONCEPTOS_ENTRADA, CONCEPTOS_SALIDA, FilaContrato, ResultadoFuente
from .dinero import texto_monto
from .ensamblador import Flujo, SemanaFlujo

ESQUEMA_SALIDA = "flujo_13_semanas/v1"
SANGRIA = 2

Documento = Dict[str, object]


def _semana(semana: SemanaFlujo) -> Documento:
    montos = dict(semana.montos)
    return {
        "semana": semana.numero,
        "inicio": semana.inicio.isoformat(),
        "fin": semana.fin.isoformat(),
        "saldo_inicial": texto_monto(semana.saldo_inicial),
        "entradas": {c: texto_monto(montos[c]) for c in CONCEPTOS_ENTRADA},
        "salidas": {c: texto_monto(montos[c]) for c in CONCEPTOS_SALIDA},
        "total_entradas": texto_monto(semana.entradas),
        "total_salidas": texto_monto(semana.salidas),
        "flujo_neto": texto_monto(semana.flujo_neto),
        "saldo_final": texto_monto(semana.saldo_final),
    }


def _fuente(resultado: ResultadoFuente) -> Documento:
    return {
        "fuente": resultado.fuente,
        "concepto": CONCEPTO_DE_FUENTE[resultado.fuente],
        "archivo": resultado.archivo,
        "sha256": resultado.sha256,
        "registros": resultado.registros,
        "registros_en_cero": resultado.registros_en_cero,
        "filas_contrato": len(resultado.filas),
        "total_insumo": texto_monto(resultado.total_insumo),
        "en_horizonte": texto_monto(resultado.en_horizonte),
        "fuera_horizonte": texto_monto(resultado.fuera_horizonte),
        "no_cobrable": texto_monto(resultado.no_cobrable),
    }


def fila_a_documento(fila: FilaContrato) -> Documento:
    return {
        "fuente": fila.fuente,
        "concepto": fila.concepto,
        "semana": fila.semana,
        "fecha": fila.fecha.isoformat(),
        "referencia": fila.referencia,
        "contraparte": fila.contraparte,
        "monto": texto_monto(fila.monto),
        "marca": fila.marca,
    }


def documento_avisos(flujo: Flujo) -> Documento:
    """Clave del aviso -> registros y monto (texto) de las filas o registros que cuenta."""
    return {a.clave: {"registros": a.registros, "monto": texto_monto(a.monto)} for a in avisos(flujo)}


def documento(flujo: Flujo) -> Documento:
    primera, ultima = flujo.semanas[0], flujo.semanas[-1]
    semanas: List[Documento] = [_semana(s) for s in flujo.semanas]
    return {
        "esquema": ESQUEMA_SALIDA,
        "corte": flujo.corte.isoformat(),
        "moneda": flujo.moneda,
        "horizonte": {
            "inicio": flujo.corte.isoformat(),
            "fin": fin_horizonte(flujo.corte).isoformat(),
            "semanas": len(flujo.semanas),
        },
        "semanas": semanas,
        "fuentes": [_fuente(r) for r in flujo.fuentes],
        "avisos": documento_avisos(flujo),
        "totales": {
            "saldo_inicial": texto_monto(primera.saldo_inicial),
            "total_entradas": texto_monto(flujo.total_entradas),
            "total_salidas": texto_monto(flujo.total_salidas),
            "flujo_neto": texto_monto(ultima.saldo_final - primera.saldo_inicial),
            "saldo_final": texto_monto(ultima.saldo_final),
        },
    }


def contenido_json(flujo: Flujo) -> str:
    return json.dumps(documento(flujo), ensure_ascii=False, sort_keys=True, indent=SANGRIA) + "\n"


def contenido_jsonl(flujo: Flujo) -> str:
    return "".join(
        json.dumps(fila_a_documento(f), ensure_ascii=False, sort_keys=True) + "\n" for f in flujo.filas
    )
