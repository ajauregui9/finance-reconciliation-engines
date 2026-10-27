"""Construcción pura de las filas de cada tabla a partir del universo de CFDIs.

No toca SQLite: devuelve tuplas listas para insertar. Los montos salen como texto decimal
(`formatear`), nunca como `float`.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Dict, List, Mapping, Optional, Sequence, Tuple, Union

from netsuite_gl.cfdis import Cfdi
from netsuite_gl.config import TIPO_PROVEEDORES, ConfigEsquema, CuentaConfig, ReglaGasto
from netsuite_gl.discrepancias import Asignacion
from netsuite_gl.errores import ErrorPoblado
from netsuite_gl.montos import CERO, formatear
from netsuite_gl.periodos import Periodo, mes_siguiente, periodo_de_registro

Valor = Union[str, int, None]
Fila = Tuple[Valor, ...]

TIPO_FACTURA = "VendBill"
TIPO_NOTA_CREDITO = "VendCred"
MEMO_IVA = "IVA acreditable"


@dataclass(frozen=True)
class TransaccionArmada:
    id: int
    cfdi: Cfdi
    periodo: Periodo
    es_copia: bool


@dataclass(frozen=True)
class FilasEsquema:
    por_tabla: Mapping[str, Tuple[Fila, ...]]
    transacciones: Tuple[TransaccionArmada, ...]
    num_proveedores: int


@dataclass(frozen=True)
class _Partida:
    linea: int
    cuenta: CuentaConfig
    monto: Decimal
    al_debe: bool
    principal: bool
    impuesto: bool
    memo: str


def armar_filas(
    universo: Sequence[Cfdi], asignacion: Asignacion, config: ConfigEsquema, periodos: Sequence[Periodo]
) -> FilasEsquema:
    cuentas = {c.numero: c for c in config.cuentas}
    clases = {c.nombre: c.id for c in config.clases}
    _validar_config(config, cuentas, clases)
    proveedores = _proveedores(universo, config.primer_id_proveedor)
    transacciones = _transacciones(universo, asignacion, periodos, config.primer_id_transaccion)
    reglas = _reglas_por_uuid(universo, config)
    cabeceras: List[Fila] = []
    lineas: List[Fila] = []
    contables: List[Fila] = []
    for tx in transacciones:
        proveedor = proveedores[(tx.cfdi.rfc_emisor, tx.cfdi.nombre_emisor)][0]
        cabeceras.append(_cabecera(tx, proveedor))
        regla = reglas[tx.cfdi.uuid]
        delta = asignacion.monto_distinto.get(tx.cfdi.uuid, CERO)
        for partida in _partidas(tx.cfdi, delta, regla, cuentas, config):
            lineas.append(_fila_linea(tx.id, partida, clases[regla.clase], proveedor))
            contables.append(_fila_contable(tx.id, partida))
    por_tabla = {
        "account": tuple(_fila_cuenta(c) for c in config.cuentas),
        "accountingperiod": tuple(_fila_periodo(p) for p in periodos),
        "classification": tuple((c.id, c.nombre, c.nombre, _bandera(c.inactiva)) for c in config.clases),
        "vendor": tuple((i, eid, nombre, rfc, "F") for (rfc, nombre), (i, eid) in sorted(proveedores.items())),
        "transaction": tuple(cabeceras),
        "transactionline": tuple(lineas),
        "transactionaccountingline": tuple(contables),
        "customrecord_cfdi_recibido": tuple(_fila_registro(i, c) for i, c in enumerate(universo, start=1)),
    }
    return FilasEsquema(MappingProxyType(por_tabla), transacciones, len(proveedores))


def _validar_config(config: ConfigEsquema, cuentas: Mapping[str, CuentaConfig], clases: Mapping[str, int]) -> None:
    reglas = list(config.gasto_por_concepto.values()) + [config.gasto_default]
    faltantes = sorted({r.cuenta for r in reglas} - set(cuentas)) + sorted({r.clase for r in reglas} - set(clases))
    for numero in (config.cuenta_proveedores, config.cuenta_iva):
        if numero not in cuentas:
            faltantes.append(numero)
    if faltantes:
        raise ErrorPoblado(f"la config referencia cuentas o clases que no existen: {', '.join(faltantes)}")
    if cuentas[config.cuenta_proveedores].tipo != TIPO_PROVEEDORES:
        raise ErrorPoblado(f"la cuenta de proveedores {config.cuenta_proveedores} debe ser {TIPO_PROVEEDORES}")


def _proveedores(universo: Sequence[Cfdi], primer_id: int) -> Dict[Tuple[str, str], Tuple[int, str]]:
    pares = sorted({(c.rfc_emisor, c.nombre_emisor) for c in universo})
    return {par: (primer_id + i, f"PROV-{i + 1:04d}") for i, par in enumerate(pares)}


def _transacciones(
    universo: Sequence[Cfdi], asignacion: Asignacion, periodos: Sequence[Periodo], primer_id: int
) -> Tuple[TransaccionArmada, ...]:
    """Originales en orden (fecha, uuid) y, al final, las copias de los duplicados."""
    originales: List[TransaccionArmada] = []
    for cfdi in sorted(universo, key=lambda c: (c.fecha, c.uuid)):
        if cfdi.uuid in asignacion.sin_registro:
            continue
        periodo = _periodo_registrado(cfdi, cfdi.uuid in asignacion.periodo_equivocado, periodos)
        originales.append(TransaccionArmada(primer_id + len(originales), cfdi, periodo, False))
    siguiente = primer_id + len(originales)
    copias = [tx for tx in originales if tx.cfdi.uuid in asignacion.duplicado]
    return tuple(originales) + tuple(
        dataclasses.replace(tx, id=siguiente + i, es_copia=True) for i, tx in enumerate(copias)
    )


def _periodo_registrado(cfdi: Cfdi, equivocado: bool, periodos: Sequence[Periodo]) -> Periodo:
    correcto = periodo_de_registro(cfdi.fecha, periodos)
    if correcto is None:
        raise ErrorPoblado(f"no hay periodo de registro en la config para la fecha {cfdi.fecha} del CFDI {cfdi.uuid}")
    if not equivocado:
        return correcto
    siguiente = mes_siguiente(correcto, periodos)
    if siguiente is None:
        raise ErrorPoblado(
            f"el CFDI {cfdi.uuid} necesita el mes de registro siguiente a {correcto.nombre} y la config no lo tiene"
        )
    return siguiente


def _reglas_por_uuid(universo: Sequence[Cfdi], config: ConfigEsquema) -> Dict[str, ReglaGasto]:
    """Una nota de crédito usa el concepto de la factura que referencia, si está en el universo."""
    por_uuid = {c.uuid: c for c in universo}
    reglas: Dict[str, ReglaGasto] = {}
    for cfdi in universo:
        origen: Optional[Cfdi] = None
        if cfdi.tipo == "E" and cfdi.uuid_relacionado is not None:
            origen = por_uuid.get(cfdi.uuid_relacionado)
        concepto = (origen or cfdi).concepto
        reglas[cfdi.uuid] = config.gasto_por_concepto.get(concepto, config.gasto_default)
    return reglas


def _partidas(
    cfdi: Cfdi, delta: Decimal, regla: ReglaGasto, cuentas: Mapping[str, CuentaConfig], config: ConfigEsquema
) -> Tuple[_Partida, ...]:
    gasto = cfdi.subtotal_mxn + delta
    if gasto <= 0:
        raise ErrorPoblado(f"el delta {delta} deja el gasto del CFDI {cfdi.uuid} en {gasto}: debe quedar positivo")
    factura = cfdi.tipo == "I"
    partidas = [
        _Partida(0, cuentas[config.cuenta_proveedores], cfdi.total_mxn + delta, not factura, True, False,
                 cfdi.concepto),
        _Partida(1, cuentas[regla.cuenta], gasto, factura, False, False, cfdi.concepto),
    ]
    if cfdi.iva_mxn > 0:
        partidas.append(_Partida(2, cuentas[config.cuenta_iva], cfdi.iva_mxn, factura, False, True, MEMO_IVA))
    return tuple(partidas)


def _cabecera(tx: TransaccionArmada, proveedor: int) -> Fila:
    tipo = TIPO_FACTURA if tx.cfdi.tipo == "I" else TIPO_NOTA_CREDITO
    return (
        tx.id, tx.cfdi.referencia, tx.cfdi.fecha.isoformat(), tipo, tx.periodo.id, proveedor,
        tx.cfdi.concepto, "T", tx.cfdi.uuid,
    )


def _fila_linea(transaccion: int, partida: _Partida, clase: int, proveedor: int) -> Fila:
    return (
        transaccion, partida.linea, partida.linea, _bandera(partida.principal), _bandera(partida.impuesto),
        clase, proveedor if partida.principal else None, partida.memo,
    )


def _fila_contable(transaccion: int, partida: _Partida) -> Fila:
    texto = formatear(partida.monto)
    firmado = partida.monto if partida.al_debe else -partida.monto
    return (
        transaccion, partida.linea, partida.cuenta.id,
        texto if partida.al_debe else None, None if partida.al_debe else texto,
        formatear(firmado), "T",
    )


def _fila_cuenta(cuenta: CuentaConfig) -> Fila:
    return (cuenta.id, cuenta.numero, cuenta.nombre, cuenta.tipo, _bandera(cuenta.inactiva))


def _fila_periodo(p: Periodo) -> Fila:
    return (
        p.id, p.nombre, p.inicio.isoformat(), p.fin.isoformat(), _bandera(p.es_registro),
        _bandera(p.es_trimestre), _bandera(p.es_anual), _bandera(p.cerrado),
    )


def _fila_registro(id_registro: int, c: Cfdi) -> Fila:
    return (
        id_registro, c.uuid, c.uuid, c.fecha.isoformat(), c.tipo, c.rfc_emisor, c.nombre_emisor, c.serie,
        c.folio, c.concepto, formatear(c.subtotal_mxn), formatear(c.iva_mxn), formatear(c.total_mxn),
        c.uuid_relacionado,
    )


def _bandera(valor: bool) -> str:
    return "T" if valor else "F"
