"""Documentos de salida del pipeline (`reporte.json`, `cargos.jsonl`, `bloqueo.json`) y su serialización.

Serialización determinista: UTF-8, llaves ordenadas, fin de línea LF, sin marcas de
tiempo ni rutas absolutas. La forma de cada documento está en `specs/pipeline.md`.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence

from .pipeline_etapas import EtapaCfdi, EtapaLibro, Insumos
from .pipeline_filas import FilaCargo, fila_a_dict
from .pipeline_modelo import ESQUEMA_BLOQUEO, ESQUEMA_REPORTE, SITUACION_EN_REVISION, Candado, MotivoProvisional
from .pipeline_revision import ORIGEN_CFDI, Revision, observacion_a_dict


def a_json(documento: Mapping[str, Any]) -> str:
    return json.dumps(documento, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def a_jsonl(filas: Sequence[FilaCargo]) -> str:
    return "".join(json.dumps(fila_a_dict(f), ensure_ascii=False, sort_keys=True) + "\n"
                   for f in sorted(filas, key=lambda f: f.cargo_id))


def candado_a_dict(candado: Candado) -> Dict[str, Any]:
    return {"etapa": candado.etapa, "nombre": candado.nombre, "cumple": candado.cumple, "detalle": candado.detalle}


def motivo_a_dict(motivo: MotivoProvisional) -> Dict[str, str]:
    return {"etapa": motivo.etapa, "motivo": motivo.motivo, "detalle": motivo.detalle}


def _motivos(motivos: Sequence[MotivoProvisional]) -> Dict[str, Any]:
    return {"provisional": bool(motivos), "motivos_provisional": [motivo_a_dict(m) for m in motivos]}


def armar_bloqueo(etapa: str, candados: Sequence[Candado], motivos: Sequence[MotivoProvisional],
                  insumos: Insumos) -> Dict[str, Any]:
    """Lo que se escribe con código 3: la etapa que bloqueó y todo lo evaluado hasta ahí."""
    return {
        "esquema": ESQUEMA_BLOQUEO,
        "etapa": etapa,
        "fallidos": [c.nombre for c in candados if not c.cumple],
        "candados": [candado_a_dict(c) for c in candados],
        "insumos": dict(insumos.huellas),
        **_motivos(motivos),
    }


def _etapas(insumos: Insumos, revision: Revision, cfdi: EtapaCfdi, libro: EtapaLibro) -> Dict[str, Any]:
    universo = insumos.universo
    return {
        "universo": {
            "num_cargos": len(universo.cargos),
            "filas_ininterpretables": sum(1 for c in universo.cargos if c.estado != "ok"),
            "estados_leidos": [c.emisor for c in universo.controles],
            "estados_omitidos": list(universo.estados_omitidos),
            "provisional": universo.es_provisional,
        },
        "revision_texto_libre": {"revisor": revision.revisor, "textos_revisados": len(revision.textos),
                                 "observaciones": len(revision.cola),
                                 "textos_marcados": len({o.llave for o in revision.cola})},
        "cruce_cfdi": {"resumen": cfdi.documento["resumen"]},
        "cruce_libro": {"resumen": libro.documento["resumen"], "veredictos_aplicados": len(insumos.veredictos),
                        "veredictos_en_espera": len(insumos.en_espera)},
    }


def _en_espera(insumos: Insumos) -> List[Dict[str, Any]]:
    return [{"cargo_id": v.cargo_id, "veredicto": v.veredicto, "asiento_id": v.asiento_id}
            for v in insumos.en_espera]


def cargos_en_revision(filas: Sequence[FilaCargo]) -> List[str]:
    return sorted(f.cargo_id for f in filas if f.situacion == SITUACION_EN_REVISION)


def revision_humana(revision: Revision, filas: Sequence[FilaCargo]) -> Dict[str, Any]:
    """La cola de revisión humana y cuántos textos, cargos y CFDIs sin cargo quedaron marcados."""
    asignados = {u for f in filas for u in f.cfdi.uuids}
    en_revision = cargos_en_revision(filas)
    libres = {o.registro_id for o in revision.cola if o.origen == ORIGEN_CFDI and o.registro_id not in asignados}
    return {
        "revisor": revision.revisor,
        "marcados": {"textos": len({o.llave for o in revision.cola}), "observaciones": len(revision.cola),
                     "cargos_en_revision": len(en_revision), "cfdis_sin_cargo": len(libres),
                     "por_familia": dict(sorted(Counter(o.familia for o in revision.cola).items()))},
        "cargos_en_revision": en_revision,
        "cola": [observacion_a_dict(o) for o in revision.cola],
    }


_CAMPOS_POR_REVISAR = ("uuids", "tier", "afinidad_nombre", "diferencia", "moneda_diferencia")


def cfdi_por_revisar(filas: Sequence[FilaCargo]) -> List[Dict[str, Any]]:
    """Cargos cuyo CFDI solo coincide por monto, con su afinidad de nombre, ordenados por `cargo_id`."""
    salida = []
    for fila in sorted(filas, key=lambda f: f.cargo_id):
        if fila.cfdi.por_revisar:
            cfdi = fila_a_dict(fila)["cfdi"]
            salida.append({"cargo_id": fila.cargo_id, "situacion": fila.situacion,
                           **{campo: cfdi[campo] for campo in _CAMPOS_POR_REVISAR}})
    return salida


def armar_reporte(*, insumos: Insumos, motivos: Sequence[MotivoProvisional], revision: Revision,
                  cfdi: EtapaCfdi, libro: EtapaLibro, candados: Sequence[Candado], resumen: Mapping[str, Any],
                  filas: Sequence[FilaCargo], artefactos: Mapping[str, str]) -> Dict[str, Any]:
    """El documento `pipeline_tarjetas/v1`; `artefactos` mapea cada archivo escrito a su SHA-256."""
    return {
        "esquema": ESQUEMA_REPORTE,
        **_motivos(motivos),
        "insumos": dict(insumos.huellas),
        "parametros": {"cruce_cfdi": cfdi.documento["parametros"], "cruce_libro": libro.documento["parametros"]},
        "etapas": _etapas(insumos, revision, cfdi, libro),
        "candados": [candado_a_dict(c) for c in candados],
        "resumen": dict(resumen),
        "revision_humana": revision_humana(revision, filas),
        "cfdi_por_revisar": cfdi_por_revisar(filas),
        "veredictos_en_espera": _en_espera(insumos),
        "artefactos": dict(sorted(artefactos.items())),
    }
