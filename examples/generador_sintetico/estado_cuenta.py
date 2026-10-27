"""Estado de cuenta crudo (dos layouts), universo esperado y resumen con totales de control.

ALFA_V1: encabezados en español, fechas DD/MM/AAAA, importe único firmado con
separador de miles, descriptor de ancho fijo (24) seguido de la ciudad.
BETA_V1: encabezados en inglés, fechas MM/DD/AAAA (estilo EUA: ambiguas frente a
ALFA en los días 1-12, por eso el layout se detecta por encabezado exacto),
columnas Charges/Credits sin signo ni separador de miles, descriptor y ciudad
separados por un espacio.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .catalogo import EMISORES
from .config import ConfigGenerador
from .contexto import periodo_emisor
from .dinero import CERO, texto, texto_miles, texto_tc
from .modelo import Cargo

ENCABEZADOS: Dict[str, Tuple[str, ...]] = {
    "ALFA_V1": ("Fecha de operación", "Fecha de aplicación", "Descripción", "Titular", "Tarjeta",
                "Moneda origen", "Importe origen", "Tipo de cambio", "Importe MXN"),
    "BETA_V1": ("Transaction Date", "Post Date", "Description", "Card Member", "Account Ending",
                "Foreign Spend Amount", "Foreign Currency", "Exchange Rate", "Charges", "Credits"),
}
ANCHO_DESCRIPTOR_ALFA = 24


def _fecha_alfa(cargo: Cargo, campo: str) -> str:
    valor = getattr(cargo, campo)
    return f"{valor.day:02d}/{valor.month:02d}/{valor.year:04d}"


def _fecha_beta(cargo: Cargo, campo: str) -> str:
    valor = getattr(cargo, campo)
    return f"{valor.month:02d}/{valor.day:02d}/{valor.year:04d}"


def descripcion_cruda(cargo: Cargo) -> str:
    if cargo.tipo_movimiento == "pago":
        return EMISORES[cargo.emisor].marca_pago
    nombre = cargo.descriptor[:ANCHO_DESCRIPTOR_ALFA - 1]
    if cargo.emisor == "ALFA":
        return f"{nombre:<{ANCHO_DESCRIPTOR_ALFA}}{cargo.ciudad}"
    return f"{nombre} {cargo.ciudad}"


def _tc(cargo: Cargo) -> str:
    return texto_tc(cargo.tipo_cambio) if cargo.tipo_cambio is not None else ""


def fila_cruda(cargo: Cargo) -> Tuple[str, ...]:
    """Celdas de la fila tal como las exporta el emisor."""
    if cargo.emisor == "ALFA":
        fecha = cargo.fecha_cruda_invalida or _fecha_alfa(cargo, "fecha")
        return (fecha, _fecha_alfa(cargo, "fecha_aplicacion"), descripcion_cruda(cargo),
                cargo.tarjeta.titular, f"****{cargo.tarjeta.ultimos4}", cargo.moneda_original,
                texto_miles(cargo.monto_original), _tc(cargo), texto_miles(cargo.monto))
    extranjera = cargo.moneda_original != "MXN"
    fecha = cargo.fecha_cruda_invalida or _fecha_beta(cargo, "fecha")
    return (fecha, _fecha_beta(cargo, "fecha_aplicacion"), descripcion_cruda(cargo),
            cargo.tarjeta.titular, cargo.tarjeta.ultimos4,
            texto(abs(cargo.monto_original)) if extranjera else "",
            cargo.moneda_original if extranjera else "", _tc(cargo),
            texto(cargo.monto) if cargo.monto > 0 else "",
            texto(-cargo.monto) if cargo.monto < 0 else "")


def registro_universo(cargo: Cargo, config: ConfigGenerador) -> Dict[str, Optional[object]]:
    """Cargo normalizado esperado: lo que el normalizador del universo debe producir de la fila cruda."""
    emisor = EMISORES[cargo.emisor]
    _, corte = periodo_emisor(config, cargo.emisor)
    return {
        "cargo_id": cargo.cargo_id, "emisor": cargo.emisor, "layout": emisor.layout,
        "archivo": emisor.archivo, "fila": cargo.fila, "corte": corte.isoformat(),
        "fecha": cargo.fecha.isoformat() if cargo.interpretable else None,
        "fecha_aplicacion": cargo.fecha_aplicacion.isoformat(),
        "descripcion": " ".join(descripcion_cruda(cargo).split()),
        "titular": cargo.tarjeta.titular, "tarjeta_ultimos4": cargo.tarjeta.ultimos4,
        "monto": texto(cargo.monto), "moneda": "MXN",
        "monto_original": texto(cargo.monto_original), "moneda_original": cargo.moneda_original,
        "tipo_cambio": texto_tc(cargo.tipo_cambio) if cargo.tipo_cambio is not None else None,
        "tipo_movimiento": cargo.tipo_movimiento,
        "estado": "ok" if cargo.interpretable else "ininterpretable",
        "motivo": None if cargo.interpretable else "fecha_invalida",
    }


def resumen_estado(emisor_clave: str, cargos: List[Cargo], config: ConfigGenerador) -> Dict[str, object]:
    """Totales de control del estado de cuenta (el saldo anterior se pagó completo)."""
    emisor = EMISORES[emisor_clave]
    inicio, fin = periodo_emisor(config, emisor_clave)
    montos = [c.monto for c in cargos]
    neto = sum(montos, CERO)
    saldo_anterior = -sum((c.monto for c in cargos if c.tipo_movimiento == "pago"), CERO)
    return {
        "archivo": emisor.archivo, "emisor": emisor.clave, "nombre_emisor": emisor.nombre,
        "layout": emisor.layout, "moneda": "MXN", "periodo_inicio": inicio.isoformat(),
        "periodo_fin": fin.isoformat(), "corte": fin.isoformat(), "num_movimientos": len(cargos),
        "total_cargos": texto(sum((m for m in montos if m > 0), CERO)),
        "total_abonos": texto(sum((m for m in montos if m < 0), CERO)),
        "total_neto": texto(neto), "saldo_anterior": texto(saldo_anterior),
        "saldo_al_corte": texto(saldo_anterior + neto),
    }
