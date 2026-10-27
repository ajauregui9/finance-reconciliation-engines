"""Pool de CFDIs conocidos: la lectura determinista ("motor") contra la que se cruza al modelo.

Los XML se leen solo con el lector del motor de cruce cargo ↔ CFDI
(`conciliacion.cruce_cfdi_xml`: `defusedxml`, DTD prohibida, sin lector alternativo). Ese
módulo es el único punto del repo que parsea XML, así que este skill no abre los XML por su
cuenta. `cargar_cfdis_xml_con_montos` da los ocho campos: UUID, fecha, RFCs, moneda, total,
`SubTotal` y el IVA trasladado del comprobante, todos en la moneda del comprobante.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Tuple

from conciliacion.cruce_cfdi_modelo import InsumoInvalido as InsumoDelMotor
from conciliacion.cruce_cfdi_xml import DependenciaFaltante, cargar_cfdis_xml_con_montos, huella_directorio

from .errores import InsumoInvalido
from .modelo import CAMPOS, Campos, texto_monto

# Los campos que el lector del motor lee del XML y que, por lo tanto, se cruzan: los ocho.
CAMPOS_DEL_MOTOR: Tuple[str, ...] = CAMPOS


@dataclass(frozen=True)
class Pool:
    cfdis: Mapping[str, Campos]
    sha256: str


def cargar_pool(directorio: Path, rfc_empresa: str) -> Pool:
    """Todos los CFDIs del directorio como `Campos`, con llave el UUID en mayúsculas."""
    try:
        leidos_xml = cargar_cfdis_xml_con_montos(directorio, rfc_empresa)
        huella = huella_directorio(directorio)
    except (InsumoDelMotor, DependenciaFaltante) as exc:
        raise InsumoInvalido(f"pool de CFDIs: {exc}") from None
    leidos = {
        x.cfdi.uuid.upper(): Campos(rfc_emisor=x.cfdi.rfc_emisor, rfc_receptor=x.cfdi.rfc_receptor, uuid=x.cfdi.uuid,
                                    fecha=x.cfdi.fecha_emision.isoformat(), subtotal=texto_monto(x.subtotal),
                                    iva=texto_monto(x.iva_trasladado), total=texto_monto(x.cfdi.total),
                                    moneda=x.cfdi.moneda)
        for x in leidos_xml
    }
    return Pool(MappingProxyType(leidos), huella)
