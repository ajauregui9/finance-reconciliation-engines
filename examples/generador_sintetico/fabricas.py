"""Fábricas de cargos, CFDIs y asientos, y el contenedor `Escenario`."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable, Optional, Tuple

from .catalogo import (CONCEPTOS, CUENTA_IVA, CUENTAS_GASTO, EMISORES, PROVEEDOR_CUBETA,
                       TARJETAS)
from .config import NOMBRE_EMPRESA, RFC_EMPRESA
from .contexto import Contexto, periodo_emisor
from .dinero import CERO, q2, separar_iva
from .modelo import (Asiento, Cargo, Cfdi, Comercio, Expectativa, ExpectativaCfdi,
                     ExpectativaLibro, GrupoEmpate, LineaMayor, Tarjeta)

DIAS_MARGEN_FIN = 2


@dataclass(frozen=True)
class Escenario:
    """Un caso (o lote de casos) con todos sus artefactos y respuestas conocidas."""

    cargos: Tuple[Cargo, ...] = ()
    cfdis: Tuple[Cfdi, ...] = ()
    asientos: Tuple[Asiento, ...] = ()
    expectativas: Tuple[Expectativa, ...] = ()
    grupos: Tuple[GrupoEmpate, ...] = ()


def unir(escenarios: Iterable[Escenario]) -> Escenario:
    lista = tuple(escenarios)
    return Escenario(
        cargos=tuple(c for e in lista for c in e.cargos),
        cfdis=tuple(c for e in lista for c in e.cfdis),
        asientos=tuple(a for e in lista for a in e.asientos),
        expectativas=tuple(x for e in lista for x in e.expectativas),
        grupos=tuple(g for e in lista for g in e.grupos),
    )


def dias(n: int) -> timedelta:
    return timedelta(days=n)


def esperar(cargo: Cargo, casos: Tuple[str, ...], esperados: Tuple[str, ...] = (),
            evidencia: Optional[str] = None, prohibidos: Tuple[str, ...] = (),
            motivo: Optional[str] = None, libro: Optional[ExpectativaLibro] = None,
            grupo: Optional[str] = None) -> Expectativa:
    """Atajo para declarar la respuesta conocida de un cargo."""
    return Expectativa(cargo.clave, casos, ExpectativaCfdi(esperados, evidencia, prohibidos, motivo),
                       libro, grupo)


# ------------------------------------------------------------------- cargos
def tarjeta_al_azar(ctx: Contexto, emisor: Optional[str] = None) -> Tarjeta:
    opciones = [t for t in TARJETAS if emisor is None or t.emisor == emisor]
    return ctx.elegir(opciones)


def fecha_cargo(ctx: Contexto, tarjeta: Tarjeta, margen_fin: int = DIAS_MARGEN_FIN) -> date:
    inicio, fin = periodo_emisor(ctx.config, tarjeta.emisor)
    return ctx.fecha_entre(inicio, fin - dias(margen_fin))


def nuevo_cargo(ctx: Contexto, comercio: Optional[Comercio], monto: Decimal, *,
                tarjeta: Optional[Tarjeta] = None, fecha: Optional[date] = None,
                tipo: str = "cargo", moneda_original: str = "MXN",
                monto_original: Optional[Decimal] = None,
                tipo_cambio: Optional[Decimal] = None) -> Cargo:
    """Crea una fila del estado de cuenta; `monto` va firmado (abonos negativos)."""
    tarjeta = tarjeta or tarjeta_al_azar(ctx)
    fecha = fecha or fecha_cargo(ctx, tarjeta)
    _, fin = periodo_emisor(ctx.config, tarjeta.emisor)
    aplicacion = min(fecha + dias(ctx.entero(0, DIAS_MARGEN_FIN)), fin)
    return Cargo(
        clave=ctx.clave("K"), tarjeta=tarjeta, fecha=fecha, fecha_aplicacion=aplicacion,
        descriptor=comercio.descriptor if comercio else "", ciudad=comercio.ciudad if comercio else "",
        monto=monto, monto_original=monto if monto_original is None else monto_original,
        moneda_original=moneda_original, tipo_cambio=tipo_cambio, tipo_movimiento=tipo,
        comercio=comercio,
    )


def cargo_usd(ctx: Contexto, comercio: Comercio, *, tarjeta: Optional[Tarjeta] = None) -> Cargo:
    """Cargo cobrado en USD: monto en pesos = USD x tipo de cambio de la tarjeta."""
    for _ in range(500):
        usd = ctx.monto(*comercio.rango, moneda="USD")
        tc = ctx.tipo_cambio()
        mxn = q2(usd * tc)
        if ctx.libre(mxn):
            ctx.reservar(mxn)
            return nuevo_cargo(ctx, comercio, mxn, tarjeta=tarjeta, moneda_original="USD",
                               monto_original=usd, tipo_cambio=tc)
    raise RuntimeError("No fue posible sortear un cargo en USD con monto libre.")


# -------------------------------------------------------------------- CFDIs
def forma_pago_tarjeta(ctx: Contexto) -> str:
    """Casi siempre 04 (tarjeta de crédito); a veces mal capturada, como en la vida real."""
    tirada = ctx.entero(1, 100)
    return "04" if tirada <= 85 else ("99" if tirada <= 95 else "03")


def nuevo_cfdi(ctx: Contexto, *, rfc_emisor: str, nombre_emisor: str, serie: str, total: Decimal,
               fecha: date, concepto: str, tipo: str = "I", direccion: str = "recibido",
               rfc_receptor: str = RFC_EMPRESA, nombre_receptor: str = NOMBRE_EMPRESA,
               moneda: str = "MXN", tipo_cambio: Optional[Decimal] = None,
               con_iva: bool = True, forma_pago: str = "04",
               relacionado: Optional[str] = None) -> Cfdi:
    subtotal, iva = separar_iva(total) if con_iva else (total, CERO)
    total_mxn = q2(total * tipo_cambio) if tipo_cambio is not None else total
    uso = {"I": "G03", "E": "G02", "N": "CN01"}[tipo]
    return Cfdi(
        uuid=ctx.uuid(), fecha_emision=fecha, tipo_comprobante=tipo, direccion=direccion,
        rfc_emisor=rfc_emisor, nombre_emisor=nombre_emisor, rfc_receptor=rfc_receptor,
        nombre_receptor=nombre_receptor, moneda=moneda, tipo_cambio=tipo_cambio,
        subtotal=subtotal, iva=iva, total=total, total_mxn=total_mxn, forma_pago=forma_pago,
        uso_cfdi=uso, concepto=concepto, serie=serie, uuid_relacionado=relacionado,
    )


def cfdi_comercio(ctx: Contexto, comercio: Comercio, total: Decimal, fecha: date, *,
                  tipo: str = "I", relacionado: Optional[str] = None,
                  rfc_receptor: str = RFC_EMPRESA, nombre_receptor: str = NOMBRE_EMPRESA,
                  moneda: str = "MXN", tipo_cambio: Optional[Decimal] = None) -> Cfdi:
    """CFDI emitido por un comercio de tarjeta (por omisión, a la empresa)."""
    concepto = CONCEPTOS[comercio.categoria] if tipo == "I" else "DEVOLUCION O BONIFICACION"
    return nuevo_cfdi(ctx, rfc_emisor=comercio.rfc, nombre_emisor=comercio.razon_social,
                      serie=comercio.serie, total=total, fecha=fecha, concepto=concepto, tipo=tipo,
                      rfc_receptor=rfc_receptor, nombre_receptor=nombre_receptor, moneda=moneda,
                      tipo_cambio=tipo_cambio, forma_pago=forma_pago_tarjeta(ctx),
                      relacionado=relacionado)


# ------------------------------------------------------------------ asientos
def lineas_gasto(gasto: Tuple[str, str], total: Decimal, con_iva: bool,
            cuenta_contra: Tuple[str, str]) -> Tuple[LineaMayor, ...]:
    """Cargo a gasto (+ IVA) y abono a la cuenta contraria; siempre cuadra."""
    subtotal, iva = separar_iva(total) if con_iva else (total, CERO)
    lineas = [LineaMayor(gasto[0], gasto[1], subtotal, CERO)]
    if iva:
        lineas.append(LineaMayor(CUENTA_IVA[0], CUENTA_IVA[1], iva, CERO))
    lineas.append(LineaMayor(cuenta_contra[0], cuenta_contra[1], CERO, total))
    return tuple(lineas)


def _invertir(lineas: Tuple[LineaMayor, ...]) -> Tuple[LineaMayor, ...]:
    return tuple(LineaMayor(x.cuenta, x.nombre_cuenta, x.haber, x.debe) for x in lineas)


def periodo_de(fecha: date) -> str:
    return f"{fecha.year:04d}-{fecha.month:02d}"


def asiento_tarjeta(ctx: Contexto, cargo: Cargo, fecha: date, *, cubeta: bool = False,
                    periodo_estado: Optional[str] = None) -> Asiento:
    """Registro de un cargo (o abono) de tarjeta; la referencia apunta a su estado de cuenta."""
    comercio = cargo.comercio_requerido()
    emisor = EMISORES[cargo.emisor]
    if cubeta:
        proveedor = PROVEEDOR_CUBETA
        gasto, con_iva = CUENTAS_GASTO["varios"], False
    else:
        proveedor = (comercio.proveedor_id, comercio.nombre_proveedor, comercio.rfc)
        gasto = CUENTAS_GASTO[comercio.categoria]
        con_iva = comercio.factura and not comercio.extranjero
    lineas = lineas_gasto(gasto, abs(cargo.monto), con_iva, (emisor.cuenta, emisor.nombre_cuenta))
    concepto = CONCEPTOS[comercio.categoria]
    if cargo.tipo_movimiento == "abono":
        lineas, concepto = _invertir(lineas), f"DEVOLUCION {concepto}"
    return Asiento(clave=ctx.clave("A"), fecha=fecha, origen="TARJETA", proveedor_id=proveedor[0],
                   proveedor_nombre=proveedor[1], proveedor_rfc=proveedor[2],
                   referencia=f"EDC {cargo.emisor} {periodo_estado or ctx.config.periodo}", memo=concepto,
                   lineas=lineas)


def asiento_simple(ctx: Contexto, *, fecha: date, origen: str, proveedor: Tuple[str, str, str],
                   memo: str, lineas: Tuple[LineaMayor, ...]) -> Asiento:
    return Asiento(clave=ctx.clave("A"), fecha=fecha, origen=origen, proveedor_id=proveedor[0],
                   proveedor_nombre=proveedor[1], proveedor_rfc=proveedor[2],
                   referencia=f"{origen} {periodo_de(fecha)}", memo=memo, lineas=lineas)

