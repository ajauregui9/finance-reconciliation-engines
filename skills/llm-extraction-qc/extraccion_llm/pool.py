"""Pool de CFDIs conocidos: la lectura determinista ("motor") contra la que se cruza al modelo.

Los XML se leen solo con el lector del motor de cruce cargo ↔ CFDI
(`conciliacion.cruce_cfdi_xml`: `defusedxml`, DTD prohibida, sin lector alternativo). Ese
módulo es el único punto del repo que parsea XML, así que este skill no abre los XML por su
cuenta. `cargar_cfdis_xml_con_montos` da los doce campos: UUID, fecha, RFCs, moneda, total,
`SubTotal`, `Descuento`, el IVA y el IEPS trasladados y el ISR y el IVA retenidos del
comprobante, todos en la moneda del comprobante. Un monto opcional en cero se guarda como
None ("el comprobante no lo trae"), igual que lo reportaría el modelo.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple

from conciliacion.cruce_cfdi_modelo import InsumoInvalido as InsumoDelMotor
from conciliacion.cruce_cfdi_xml import CfdiConMontos, DependenciaFaltante, cargar_cfdis_xml_con_montos
from conciliacion.cruce_cfdi_xml import huella_directorio

from .errores import InsumoInvalido
from .modelo import CAMPOS, Campos, texto_monto

# Los campos que el lector del motor lee del XML y que, por lo tanto, se cruzan: los doce.
CAMPOS_DEL_MOTOR: Tuple[str, ...] = CAMPOS


@dataclass(frozen=True)
class Pool:
    cfdis: Mapping[str, Campos]
    sha256: str


def _opcional(monto: Decimal) -> Optional[str]:
    return None if monto == 0 else texto_monto(monto)


def campos_del_motor(leido: CfdiConMontos) -> Campos:
    """Lo que leyó el motor, en la misma forma que la propuesta del modelo."""
    cfdi = leido.cfdi
    return Campos(rfc_emisor=cfdi.rfc_emisor, rfc_receptor=cfdi.rfc_receptor, uuid=cfdi.uuid,
                  fecha=cfdi.fecha_emision.isoformat(), subtotal=texto_monto(leido.subtotal),
                  descuento=_opcional(leido.descuento), iva=texto_monto(leido.iva_trasladado),
                  ieps=_opcional(leido.ieps_trasladado), isr_retenido=_opcional(leido.isr_retenido),
                  iva_retenido=_opcional(leido.iva_retenido), total=texto_monto(cfdi.total), moneda=cfdi.moneda)


def cargar_pool(directorio: Path, rfc_empresa: str) -> Pool:
    """Todos los CFDIs del directorio como `Campos`, con llave el UUID en mayúsculas."""
    try:
        leidos_xml = cargar_cfdis_xml_con_montos(directorio, rfc_empresa)
        huella = huella_directorio(directorio)
    except (InsumoDelMotor, DependenciaFaltante) as exc:
        raise InsumoInvalido(f"pool de CFDIs: {exc}") from None
    leidos = {x.cfdi.uuid.upper(): campos_del_motor(x) for x in leidos_xml}
    return Pool(MappingProxyType(leidos), huella)
