"""Reporte de evaluación (`evaluacion_extraccion_llm/v2`) en JSON y en markdown.

El markdown se deriva del mismo diccionario que el JSON. Todo valor que viene del modelo o
de un documento es texto de un tercero: en las tablas se escapa (barras, comillas
invertidas, `<`, `>`, caracteres invisibles) y se recorta, para que no rompa la tabla ni se
interprete como marcado. Sin marcas de tiempo ni rutas: misma corrida, mismos bytes.
"""
from __future__ import annotations

import json
import unicodedata
from decimal import Decimal
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .config import Config, Precios, config_a_dict
from .costo import Consumo, usd_estimado
from .evaluacion import Evaluacion, ResumenGuardia
from .grabadas import ORIGEN_SINTETICO
from .modelo import CAMPOS, DECISIONES
from .pipeline import Corrida, ResultadoDocumento

ESQUEMA_REPORTE = "evaluacion_extraccion_llm/v2"
MODO_VIVO = "vivo"
SANGRIA = 2
LARGO_CELDA = 80
CATEGORIAS_INVISIBLES = frozenset({"Cc", "Cf"})
_ESCAPES = {"\\": "\\\\", "|": "\\|", "`": "'", "&": "&amp;", "<": "&lt;", ">": "&gt;"}

ADVERTENCIA_SINTETICA = (
    "Las respuestas grabadas son fixtures sintéticos escritos por el generador, no respuestas de Claude: "
    "estas métricas validan el pipeline de evaluación, no la exactitud de Claude. Las métricas reales "
    "salen del modo vivo (--modo vivo)."
)
ADVERTENCIA_REGRABADA = (
    "Respuestas grabadas de una corrida en vivo: el reporte reproduce esa corrida. Para medir el modelo "
    "actual hay que volver a correr en vivo."
)
ADVERTENCIA_VIVO = (
    "Corrida en vivo sobre documentos sintéticos con verdad conocida: mide la extracción del modelo en este "
    "conjunto, no en documentos reales."
)
ADVERTENCIA_SIN_ENVIOS = "Ningún documento llegó al modelo: no hay métricas de extracción."


def advertencia(modo: str, origenes: Sequence[str]) -> str:
    if ORIGEN_SINTETICO in origenes:
        return ADVERTENCIA_SINTETICA
    if not origenes:
        return ADVERTENCIA_SIN_ENVIOS
    return ADVERTENCIA_VIVO if modo == MODO_VIVO else ADVERTENCIA_REGRABADA


def _tasa(valor: Optional[Decimal]) -> Optional[str]:
    return None if valor is None else str(valor)


def _decisiones(corrida: Corrida) -> Dict[str, Any]:
    conteo: Dict[str, Any] = {d: sum(1 for r in corrida.resultados if r.decision == d) for d in DECISIONES}
    motivos: Dict[str, int] = {}
    for resultado in corrida.resultados:
        for codigo in sorted({o.codigo for o in resultado.observaciones}):
            motivos[codigo] = motivos.get(codigo, 0) + 1
    conteo["por_motivo"] = motivos
    return conteo


def _guardia(guardia: ResumenGuardia) -> Dict[str, Any]:
    return {
        "documentos_con_inyeccion": guardia.con_inyeccion,
        "detectados": guardia.detectados,
        "tasa_deteccion": _tasa(guardia.tasa_deteccion),
        "documentos_sin_inyeccion": guardia.sin_inyeccion,
        "falsos_positivos": guardia.falsos_positivos,
        "tasa_falsos_positivos": _tasa(guardia.tasa_falsos_positivos),
        "por_documento": [{"documento_id": d.documento_id, "tecnica": d.tecnica, "familias": list(d.familias)}
                          for d in guardia.por_documento],
    }


def _consumo(consumo: Consumo, precios: Precios) -> Dict[str, Any]:
    return {
        "documentos_enviados": len(consumo.por_documento),
        "tokens_entrada": consumo.tokens_entrada,
        "tokens_salida": consumo.tokens_salida,
        "tokens_totales": consumo.tokens_totales,
        "usd_estimado": str(usd_estimado(consumo, precios)),
        "por_documento": [{"documento_id": d, "tokens_entrada": u.tokens_entrada, "tokens_salida": u.tokens_salida}
                          for d, u in consumo.por_documento],
    }


def _documento(resultado: ResultadoDocumento) -> Dict[str, Any]:
    uso = resultado.uso
    return {
        "documento_id": resultado.documento_id,
        "formato": resultado.formato,
        "enviado": resultado.enviado,
        "decision": resultado.decision,
        "motivos": sorted({o.codigo for o in resultado.observaciones}),
        "hallazgos": [{"familia": h.familia, "fragmento": h.fragmento} for h in resultado.hallazgos],
        "observaciones": [{"codigo": o.codigo, "campo": o.campo, "detalle": o.detalle}
                          for o in resultado.observaciones],
        "propuesta": None if resultado.propuesta is None else resultado.propuesta.como_dict(),
        "tokens_entrada": None if uso is None else uso.tokens_entrada,
        "tokens_salida": None if uso is None else uso.tokens_salida,
        "origen_respuesta": resultado.origen_respuesta,
        "modelo_respuesta": resultado.modelo_respuesta,
    }


def armar_reporte(*, modo: str, config: Config, corrida: Corrida, evaluacion: Evaluacion,
                  insumos: Mapping[str, Any], grabadas_sin_usar: Sequence[str]) -> Dict[str, Any]:
    origenes = sorted({r.origen_respuesta for r in corrida.resultados if r.origen_respuesta is not None})
    modelos = sorted({r.modelo_respuesta for r in corrida.resultados if r.modelo_respuesta is not None})
    return {
        "esquema": ESQUEMA_REPORTE,
        "advertencia": advertencia(modo, origenes),
        "modo": modo,
        "modelo": config.modelo,
        "modelos_respuesta": modelos,
        "origenes_respuesta": origenes,
        "parametros": config_a_dict(config),
        "insumos": dict(insumos),
        "decisiones": _decisiones(corrida),
        "guardia": _guardia(evaluacion.guardia),
        "metricas": {c: {"vp": m.vp, "fp": m.fp, "fn": m.fn, "precision": _tasa(m.precision),
                         "recall": _tasa(m.recall)} for c, m in evaluacion.metricas.items()},
        "seguridad": {"concordantes_con_error": list(evaluacion.concordantes_con_error),
                      "revision_esperada_sin_revision": list(evaluacion.revision_esperada_sin_revision)},
        "consumo": _consumo(corrida.consumo, config.precios),
        "discrepancias_motor": [{"documento_id": d.documento_id, "campo": d.campo, "propuesta": d.propuesta,
                                 "motor": d.motor} for d in evaluacion.discrepancias_motor],
        "discrepancias_extraccion": [{"documento_id": d.documento_id, "campo": d.campo, "propuesta": d.propuesta,
                                      "verdad": d.verdad} for d in evaluacion.discrepancias_extraccion],
        "documentos": [_documento(r) for r in corrida.resultados],
        "grabadas_sin_usar": list(grabadas_sin_usar),
    }


def texto_json(reporte: Mapping[str, Any]) -> str:
    return json.dumps(reporte, ensure_ascii=False, sort_keys=True, indent=SANGRIA) + "\n"


# ----------------------------------------------------------------- markdown

def celda(valor: object) -> str:
    """Un valor listo para una celda de tabla: recortado, escapado y sin invisibles."""
    if valor is None:
        return "—"
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    texto = str(valor)
    if len(texto) > LARGO_CELDA:
        texto = texto[:LARGO_CELDA - 3] + "..."
    piezas = (f"\\u{ord(c):04x}" if unicodedata.category(c) in CATEGORIAS_INVISIBLES else _ESCAPES.get(c, c)
              for c in texto)
    return "".join(piezas)


def _tabla(encabezados: Sequence[str], filas: Sequence[Sequence[object]]) -> List[str]:
    if not filas:
        return ["Ninguna.", ""]
    lineas = ["| " + " | ".join(encabezados) + " |", "|" + "---|" * len(encabezados)]
    lineas += ["| " + " | ".join(celda(v) for v in fila) + " |" for fila in filas]
    return lineas + [""]


def _lista(valores: Sequence[str]) -> str:
    return ", ".join(f"`{celda(v)}`" for v in valores) if valores else "ninguno"


def _md_encabezado(r: Mapping[str, Any]) -> List[str]:
    return ["# Evaluación de extracción de CFDI con LLM", "", f"> **Advertencia:** {r['advertencia']}", "",
            f"- Esquema: `{r['esquema']}`", f"- Modo: `{r['modo']}`", f"- Modelo configurado: `{celda(r['modelo'])}`",
            f"- Modelos en las respuestas: {_lista(r['modelos_respuesta'])}",
            f"- Origen de las respuestas: {_lista(r['origenes_respuesta'])}", ""]


def _md_decisiones(r: Mapping[str, Any]) -> List[str]:
    decisiones = r["decisiones"]
    lineas = ["## Decisiones", ""] + _tabla(["Decisión", "Documentos"], [[d, decisiones[d]] for d in DECISIONES])
    return lineas + _tabla(["Motivo", "Documentos"], sorted(decisiones["por_motivo"].items()))


def _md_guardia(r: Mapping[str, Any]) -> List[str]:
    g = r["guardia"]
    indicadores = [["Documentos con inyección plantada", g["documentos_con_inyeccion"]],
                   ["Detectados", g["detectados"]], ["Tasa de detección", g["tasa_deteccion"]],
                   ["Documentos sin inyección", g["documentos_sin_inyeccion"]],
                   ["Falsos positivos", g["falsos_positivos"]],
                   ["Tasa de falsos positivos", g["tasa_falsos_positivos"]]]
    detalle = [[d["documento_id"], d["tecnica"], ", ".join(d["familias"]) or None] for d in g["por_documento"]]
    return (["## Guard (prompt_guard, antes del modelo)", "", "Un documento marcado no se envía al modelo y va a "
             "revisión humana.", ""] + _tabla(["Indicador", "Valor"], indicadores)
            + _tabla(["Documento", "Técnica plantada", "Familias detectadas"], detalle))


def _md_metricas(r: Mapping[str, Any]) -> List[str]:
    filas = [[c, m["vp"], m["fp"], m["fn"], m["precision"], m["recall"]]
             for c, m in ((c, r["metricas"][c]) for c in CAMPOS)]
    return (["## Métricas por campo", "", "Población: documentos enviados al modelo.", ""]
            + _tabla(["Campo", "VP", "FP", "FN", "Precisión", "Recall"], filas))


def _md_seguridad(r: Mapping[str, Any]) -> List[str]:
    s = r["seguridad"]
    filas = [["Concordantes con algún campo distinto de la verdad", ", ".join(s["concordantes_con_error"]) or None],
             ["Revisión esperada que quedó concordante", ", ".join(s["revision_esperada_sin_revision"]) or None]]
    return ["## Seguridad del ruteo", ""] + _tabla(["Indicador", "Documentos"], filas)


def _md_consumo(r: Mapping[str, Any]) -> List[str]:
    c = r["consumo"]
    filas = [["Documentos enviados", c["documentos_enviados"]], ["Tokens de entrada", c["tokens_entrada"]],
             ["Tokens de salida", c["tokens_salida"]], ["Tokens totales", c["tokens_totales"]],
             ["USD estimado", c["usd_estimado"]]]
    return ["## Consumo", ""] + _tabla(["Indicador", "Valor"], filas)


def _md_discrepancias(r: Mapping[str, Any]) -> List[str]:
    motor = [[d["documento_id"], d["campo"], d["propuesta"], d["motor"]] for d in r["discrepancias_motor"]]
    verdad = [[d["documento_id"], d["campo"], d["propuesta"], d["verdad"]] for d in r["discrepancias_extraccion"]]
    return (["## Discrepancias modelo vs motor", ""] + _tabla(["Documento", "Campo", "Modelo", "Motor"], motor)
            + ["## Discrepancias modelo vs verdad", ""] + _tabla(["Documento", "Campo", "Modelo", "Verdad"], verdad))


def _md_documentos(r: Mapping[str, Any]) -> List[str]:
    filas = [[d["documento_id"], d["formato"], d["enviado"], d["decision"], ", ".join(d["motivos"]) or None,
              d["tokens_entrada"], d["tokens_salida"]] for d in r["documentos"]]
    insumos = [[nombre, datos["registros"], datos["sha256"]] for nombre, datos in sorted(r["insumos"].items())
               if datos is not None]
    sin_usar = ", ".join(r["grabadas_sin_usar"]) or "ninguna"
    return (["## Documentos", ""]
            + _tabla(["Documento", "Formato", "Enviado", "Decisión", "Motivos", "Tokens entrada", "Tokens salida"],
                     filas)
            + ["## Insumos", ""] + _tabla(["Insumo", "Registros", "SHA-256"], insumos)
            + [f"Respuestas grabadas sin usar: {celda(sin_usar)}"])


def texto_markdown(reporte: Mapping[str, Any]) -> str:
    secciones = (_md_encabezado, _md_decisiones, _md_guardia, _md_metricas, _md_seguridad, _md_consumo,
                 _md_discrepancias, _md_documentos)
    lineas: List[str] = []
    for seccion in secciones:
        lineas += seccion(reporte)
    return "\n".join(lineas).rstrip("\n") + "\n"
