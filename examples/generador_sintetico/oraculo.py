"""Construye el oráculo: la respuesta esperada por cargo para el universo, los cruces y el pipeline."""
from __future__ import annotations

from collections import Counter
from typing import Dict, Optional, Sequence

from .catalogo import EMISORES, PROVEEDOR_CUBETA
from .config import (CUBETA_LEJANA_MAX, CUBETA_LEJANA_MIN, LIBRO_DESFASE_MAX, LIBRO_DESFASE_MIN,
                     NOMBRE_EMPRESA, RFC_EMPRESA, RFCS_GENERICOS)
from .dinero import texto
from .modelo import Datos, Expectativa, InyeccionSembrada, VeredictoHumano
from .veredictos import ARCHIVO_VEREDICTOS

ESQUEMA = "oraculo_conciliacion/v1"


def _veredicto(v: Optional[VeredictoHumano]) -> Optional[Dict[str, object]]:
    return None if v is None else {"veredicto": v.veredicto, "asiento_id": v.asiento_id}


def _cargo(e: Expectativa, v: Optional[VeredictoHumano]) -> Dict[str, object]:
    libro = e.libro_requerido()
    return {
        "cargo_id": e.clave_cargo,
        "casos": sorted(e.casos),
        "grupo_empate": e.grupo_empate,
        "cfdi": {"esperados": sorted(e.cfdi.esperados), "evidencia": e.cfdi.evidencia,
                 "prohibidos": sorted(e.cfdi.prohibidos), "motivo_sin_cruce": e.cfdi.motivo},
        "libro_mayor": {"esperado": libro.esperado, "riesgo_cubeta": libro.riesgo_cubeta,
                        "prohibidos": sorted(libro.prohibidos), "motivo_sin_cruce": libro.motivo,
                        "veredicto": _veredicto(v), "conflicto": v.conflicto if v else None},
    }


def _revision_texto_libre(inyecciones: Sequence[InyeccionSembrada]) -> Dict[str, object]:
    """Lo que un guard correcto debe mandar a revisión humana y los cargos que deben quedar en revisión."""
    return {
        "marcados": [{"origen": "cfdi", "registro_id": s.uuid, "campo": "concepto", "familia": s.familia,
                      "cargo_id": s.cargo_id, "plantilla": s.plantilla} for s in inyecciones],
        "cargos_en_revision": sorted(s.cargo_id for s in inyecciones if s.cargo_id is not None),
    }


def construir_oraculo(datos: Datos) -> Dict[str, object]:
    config = datos.config
    casos = Counter(caso for e in datos.expectativas for caso in e.casos)
    veredictos = {v.cargo_id: v for v in datos.veredictos}
    conflictos = Counter(v.conflicto for v in datos.veredictos if v.conflicto)
    return {
        "esquema": ESQUEMA,
        "parametros": {
            "semilla": config.semilla, "intento": datos.intento, "periodo": config.periodo,
            "ventana_dias": {"min": config.ventana_min, "max": config.ventana_max},
            "tolerancia_monto": texto(config.tolerancia_monto),
            "banda_fuera_de_tolerancia": {"min": texto(config.banda_fuera_de_tolerancia[0]),
                                          "max": texto(config.banda_fuera_de_tolerancia[1])},
            "empresa": {"rfc": RFC_EMPRESA, "nombre": NOMBRE_EMPRESA},
            "rfcs_genericos": list(RFCS_GENERICOS),
            "cuentas_tarjeta": {k: e.cuenta for k, e in sorted(EMISORES.items())},
            "proveedor_cubeta": {"id": PROVEEDOR_CUBETA[0], "nombre": PROVEEDOR_CUBETA[1]},
            "libro_desfase_dias": {"min": LIBRO_DESFASE_MIN, "max": LIBRO_DESFASE_MAX},
            "cubeta_lejana_dias": {"min": CUBETA_LEJANA_MIN, "max": CUBETA_LEJANA_MAX},
        },
        "resumen": {
            "cargos": len(datos.cargos), "cfdis": len(datos.cfdis), "asientos": len(datos.asientos),
            "lineas_libro": sum(len(a.lineas) for a in datos.asientos),
            "casos": dict(sorted(casos.items())),
        },
        "grupos_empate": [{"grupo": g.grupo, "cargos": list(g.cargos), "cfdis": list(g.cfdis),
                           "asientos": list(g.asientos)}
                          for g in sorted(datos.grupos, key=lambda g: g.grupo)],
        "cargos": [_cargo(e, veredictos.get(e.clave_cargo)) for e in datos.expectativas],
        "veredictos_libro": {"archivo": ARCHIVO_VEREDICTOS, "filas": len(datos.veredictos),
                             "conflictos": dict(sorted(conflictos.items())),
                             "sin_conflicto": sum(1 for v in datos.veredictos if v.conflicto is None)},
        "revision_texto_libre": _revision_texto_libre(datos.inyecciones),
    }
