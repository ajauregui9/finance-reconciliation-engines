"""Casos del lado cargo <-> CFDI, cada uno con su respuesta conocida.

Convenciones (documentadas en el README de la salida):
- delta = fecha_emision del CFDI - fecha del cargo, en días.
- Un CFDI es candidato si es recibido, de tipo I o E, con receptor = la empresa
  (RFC no genérico) y delta dentro de la ventana [ventana_min, ventana_max].
- Las notas de crédito (tipo E) restan: se comparan con signo.
"""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from itertools import combinations
from typing import Callable, List, Optional, Tuple

from .catalogo import (COMERCIOS, COMERCIOS_EXTRANJEROS, COMERCIOS_SIN_FACTURA, COMERCIOS_USD,
                       EMPLEADOS, TARJETAS)
from .config import RFC_EXTRANJERO, RFC_PUBLICO_GENERAL
from .contexto import Contexto, periodo_emisor
from .dinero import desde_centavos, q2, q4
from .fabricas import (Escenario, cargo_usd, cfdi_comercio, dias, esperar, nuevo_cargo,
                       nuevo_cfdi, tarjeta_al_azar)
from .modelo import Cfdi, Comercio, ExpectativaLibro
from .ruido import asiento_nomina, cfdi_nomina

CUOTAS = {
    "normal": 110, "monto_tolerancia": 8, "fuera_de_tolerancia": 3, "ventana": 2,
    "nota_credito_neta": 3, "rfc_generico_receptor_unico": 2,
    "rfc_generico_receptor_duplicado": 2, "rfc_generico_emisor_suma": 2,
    "nomina_distractor": 3, "usd_sin_cfdi": 6, "usd_moneda_original": 3, "sin_cfdi": 8,
}
# (número de CFDIs que suman el cargo, ¿lleva un CFDI distractor del mismo emisor?)
SUMAS = ((2, False), (2, False), (2, False), (2, False), (2, True), (2, True),
         (3, False), (3, False), (3, True), (3, True))
REEMBOLSOS_TOTALES = (True, False, False)
MAX_REINTENTOS = 200


def _grandes(minimo_alto: int) -> Tuple[Comercio, ...]:
    return tuple(c for c in COMERCIOS if c.rango[1] >= minimo_alto)


def _desvio(ctx: Contexto, minimo: Decimal, maximo: Decimal) -> Decimal:
    """Diferencia firmada al azar con |valor| en [minimo, maximo] (en pesos)."""
    valor = desde_centavos(ctx.entero(int(minimo * 100), int(maximo * 100)))
    return valor if ctx.probable(50) else -valor


def _uno_a_uno(ctx: Contexto, casos: Tuple[str, ...], total_de: Callable[[Decimal], Decimal],
               delta: int, *, esperado: bool = True, motivo: Optional[str] = None) -> Escenario:
    """Un cargo y un CFDI del mismo comercio; `total_de(monto)` fija el total del CFDI."""
    comercio = ctx.elegir(COMERCIOS)
    cargo = nuevo_cargo(ctx, comercio, ctx.monto(*comercio.rango))
    total = total_de(cargo.monto)
    cfdi = cfdi_comercio(ctx, comercio, total, cargo.fecha + dias(delta))
    evidencia = "monto_exacto" if total == cargo.monto else "monto_tolerancia"
    exp = (esperar(cargo, casos, (cfdi.uuid,), evidencia) if esperado
           else esperar(cargo, casos, prohibidos=(cfdi.uuid,), motivo=motivo))
    return Escenario(cargos=(cargo,), cfdis=(cfdi,), expectativas=(exp,))


def normales(ctx: Contexto) -> List[Escenario]:
    return [_uno_a_uno(ctx, ("normal",), lambda m: m, ctx.delta_en_ventana(-2, 6))
            for _ in range(CUOTAS["normal"])]


def _fuera_de_tolerancia(ctx: Contexto) -> Escenario:
    """Cargo y CFDI casi iguales, pero a más de una separación: nunca caen en la tolerancia."""
    minimo, maximo = ctx.config.banda_fuera_de_tolerancia
    for _ in range(MAX_REINTENTOS):
        comercio = ctx.elegir(COMERCIOS)
        monto = desde_centavos(ctx.entero(comercio.rango[0] * 100, comercio.rango[1] * 100))
        total = monto + _desvio(ctx, minimo, maximo)
        if ctx.libre(monto) and ctx.libre(total):
            break
    else:
        raise RuntimeError("No se encontró un par cargo/CFDI fuera de tolerancia.")
    cargo = nuevo_cargo(ctx, comercio, ctx.reservar(monto))
    cfdi = cfdi_comercio(ctx, comercio, ctx.reservar(total), cargo.fecha + dias(ctx.delta_en_ventana(0, 4)))
    exp = esperar(cargo, ("fuera_de_tolerancia",), prohibidos=(cfdi.uuid,), motivo="fuera_de_tolerancia")
    return Escenario(cargos=(cargo,), cfdis=(cfdi,), expectativas=(exp,))


def tolerancias(ctx: Contexto) -> List[Escenario]:
    tol = ctx.config.tolerancia_monto
    dentro = [_uno_a_uno(ctx, ("monto_tolerancia",),
                         lambda m: m + _desvio(ctx, Decimal("0.05"), tol - Decimal("0.05")),
                         ctx.delta_en_ventana(0, 4))
              for _ in range(CUOTAS["monto_tolerancia"])]
    fuera = [_fuera_de_tolerancia(ctx) for _ in range(CUOTAS["fuera_de_tolerancia"])]
    return dentro + fuera


def ventanas(ctx: Contexto) -> List[Escenario]:
    """CFDIs justo en cada borde de la ventana y un día afuera de cada borde."""
    vmin, vmax = ctx.config.ventana_min, ctx.config.ventana_max
    casos = (("ventana_borde_inferior", vmin, True), ("ventana_borde_superior", vmax, True),
             ("fuera_ventana_inferior", vmin - 1, False), ("fuera_ventana_superior", vmax + 1, False))
    return [_uno_a_uno(ctx, (caso,), lambda m: m, delta, esperado=dentro, motivo="fuera_de_ventana")
            for caso, delta, dentro in casos for _ in range(CUOTAS["ventana"])]


def _partes(ctx: Contexto, total: Decimal, n: int) -> Tuple[Decimal, ...]:
    """Parte `total` en `n` montos libres, cada uno >= 15% del total."""
    for _ in range(MAX_REINTENTOS):
        cortes = sorted(ctx.entero(15, 85) for _ in range(n - 1))
        pcts = [b - a for a, b in zip([0] + cortes, cortes + [100])]
        if min(pcts) < 15:
            continue
        partes = [q2(total * p / 100) for p in pcts[:-1]]
        partes.append(total - sum(partes))
        if all(ctx.libre(p) for p in partes):
            return tuple(ctx.reservar(p) for p in partes)
    raise RuntimeError(f"No se pudo partir {total} en {n} montos libres.")


def _distractor(ctx: Contexto, comercio: Comercio, total: Decimal, partes: Tuple[Decimal, ...]) -> Decimal:
    """Monto de un CFDI extra que no completa la suma con ningún subconjunto de las partes."""
    faltantes = [total - sum(c) for k in range(1, len(partes)) for c in combinations(partes, k)]
    margen = 2 * ctx.config.tolerancia_monto
    for _ in range(MAX_REINTENTOS):
        valor = desde_centavos(ctx.entero(comercio.rango[0] * 100, comercio.rango[1] * 100))
        if ctx.libre(valor) and all(abs(valor - f) > margen for f in faltantes):
            return ctx.reservar(valor)
    raise RuntimeError("No se encontró un monto distractor seguro.")


def sumas(ctx: Contexto) -> List[Escenario]:
    """Un cargo respaldado por 2 o 3 CFDIs del mismo emisor que suman exacto."""
    salida: List[Escenario] = []
    for n, con_distractor in SUMAS:
        comercio = ctx.elegir(_grandes(2500))
        cargo = nuevo_cargo(ctx, comercio, ctx.monto(max(comercio.rango[0], 600), comercio.rango[1]))
        cfdis = tuple(cfdi_comercio(ctx, comercio, p, cargo.fecha + dias(ctx.delta_en_ventana(0, 5)))
                      for p in _partes(ctx, cargo.monto, n))
        extra: Tuple[Cfdi, ...] = ()
        if con_distractor:
            monto = _distractor(ctx, comercio, cargo.monto, tuple(c.total for c in cfdis))
            extra = (cfdi_comercio(ctx, comercio, monto, cargo.fecha + dias(ctx.delta_en_ventana(0, 5))),)
        casos = (f"suma_{n}",) + (("suma_con_distractor",) if con_distractor else ())
        exp = esperar(cargo, casos, tuple(c.uuid for c in cfdis), "suma", tuple(c.uuid for c in extra))
        salida.append(Escenario(cargos=(cargo,), cfdis=cfdis + extra, expectativas=(exp,)))
    return salida


def _bruto_y_descuento(ctx: Contexto, monto: Decimal) -> Tuple[Decimal, Decimal]:
    for _ in range(MAX_REINTENTOS):
        descuento = desde_centavos(int(monto * ctx.entero(5, 15)))
        bruto = monto + descuento
        if ctx.libre(descuento) and ctx.libre(bruto):
            return ctx.reservar(bruto), ctx.reservar(descuento)
    raise RuntimeError(f"No se encontró un descuento libre para {monto}.")


def notas_credito_netas(ctx: Contexto) -> List[Escenario]:
    """Cargo X respaldado por una factura (X + d) y una nota de crédito d del mismo emisor."""
    salida = []
    for _ in range(CUOTAS["nota_credito_neta"]):
        comercio = ctx.elegir(_grandes(2000))
        cargo = nuevo_cargo(ctx, comercio, ctx.monto(max(comercio.rango[0], 500), comercio.rango[1]))
        bruto, descuento = _bruto_y_descuento(ctx, cargo.monto)
        factura = cfdi_comercio(ctx, comercio, bruto, cargo.fecha + dias(ctx.delta_en_ventana(0, 2)))
        nota = cfdi_comercio(ctx, comercio, descuento, cargo.fecha + dias(ctx.delta_en_ventana(3, 8)),
                             tipo="E", relacionado=factura.uuid)
        exp = esperar(cargo, ("nota_credito_neta",), (factura.uuid, nota.uuid), "suma")
        salida.append(Escenario(cargos=(cargo,), cfdis=(factura, nota), expectativas=(exp,)))
    return salida


def reembolsos(ctx: Contexto) -> List[Escenario]:
    """Compra con su factura y, días después, un abono respaldado por una nota de crédito."""
    salida = []
    for total in REEMBOLSOS_TOTALES:
        comercio = ctx.elegir(_grandes(1500))
        tarjeta = tarjeta_al_azar(ctx)
        inicio, fin = periodo_emisor(ctx.config, tarjeta.emisor)
        compra = nuevo_cargo(ctx, comercio, ctx.monto(*comercio.rango), tarjeta=tarjeta,
                             fecha=ctx.fecha_entre(inicio, fin - dias(12)))
        monto = compra.monto if total else ctx.porcion(compra.monto, 20, 60)
        abono = nuevo_cargo(ctx, comercio, -monto, tarjeta=tarjeta, tipo="abono",
                            fecha=compra.fecha + dias(ctx.entero(3, 10)))
        factura = cfdi_comercio(ctx, comercio, compra.monto, compra.fecha + dias(ctx.delta_en_ventana(0, 2)))
        nota = cfdi_comercio(ctx, comercio, monto, abono.fecha + dias(ctx.delta_en_ventana(0, 3)),
                             tipo="E", relacionado=factura.uuid)
        casos = ("nota_credito_reembolso",) + (("reembolso_total",) if total else ())
        salida.append(Escenario(
            cargos=(compra, abono), cfdis=(factura, nota),
            expectativas=(esperar(compra, ("compra_con_reembolso",), (factura.uuid,), "monto_exacto"),
                          esperar(abono, casos, (nota.uuid,), "monto_exacto"))))
    return salida


def _receptor_generico(ctx: Contexto, duplicado: bool) -> Escenario:
    """CFDI facturado a público en general: no prueba que el gasto sea de la empresa."""
    comercio = ctx.elegir(COMERCIOS)
    cargo = nuevo_cargo(ctx, comercio, ctx.monto(*comercio.rango))
    publico = cfdi_comercio(ctx, comercio, cargo.monto, cargo.fecha,
                            rfc_receptor=RFC_PUBLICO_GENERAL, nombre_receptor="PUBLICO EN GENERAL")
    if not duplicado:
        exp = esperar(cargo, ("rfc_generico_receptor_unico",), prohibidos=(publico.uuid,),
                      motivo="solo_rfc_generico")
        return Escenario(cargos=(cargo,), cfdis=(publico,), expectativas=(exp,))
    # El válido llega días después y más lejos en fecha: gana solo si se descarta el genérico.
    valido = cfdi_comercio(ctx, comercio, cargo.monto, cargo.fecha + dias(ctx.delta_en_ventana(3, 3)))
    exp = esperar(cargo, ("rfc_generico_receptor_duplicado",), (valido.uuid,), "monto_exacto",
                  (publico.uuid,))
    return Escenario(cargos=(cargo,), cfdis=(publico, valido), expectativas=(exp,))


def _emisor_generico_suma(ctx: Contexto) -> Escenario:
    """Dos comprobantes con RFC genérico de extranjero que suman el cargo pero son de emisores distintos."""
    comercio, otro = ctx.barajar(COMERCIOS_EXTRANJEROS)[:2]
    cargo = cargo_usd(ctx, comercio)
    parte, resto = _partes(ctx, cargo.monto, 2)
    cfdis = tuple(
        nuevo_cfdi(ctx, rfc_emisor=RFC_EXTRANJERO, nombre_emisor=nombre, serie="EXT", total=monto,
                   fecha=cargo.fecha + dias(ctx.delta_en_ventana(0, 5)), concepto="SERVICIOS DIGITALES",
                   con_iva=False, forma_pago="04")
        for nombre, monto in ((comercio.razon_social, parte), (otro.razon_social, resto)))
    exp = esperar(cargo, ("rfc_generico_emisor_suma",), prohibidos=tuple(c.uuid for c in cfdis),
                  motivo="solo_rfc_generico")
    return Escenario(cargos=(cargo,), cfdis=cfdis, expectativas=(exp,))


def rfc_genericos(ctx: Contexto) -> List[Escenario]:
    return ([_receptor_generico(ctx, False) for _ in range(CUOTAS["rfc_generico_receptor_unico"])]
            + [_receptor_generico(ctx, True) for _ in range(CUOTAS["rfc_generico_receptor_duplicado"])]
            + [_emisor_generico_suma(ctx) for _ in range(CUOTAS["rfc_generico_emisor_suma"])])


def _usd_moneda_original(ctx: Contexto) -> Escenario:
    """Factura en USD con su propio tipo de cambio: cuadra en dólares, no en pesos."""
    comercio = ctx.elegir(COMERCIOS_USD)
    cargo = cargo_usd(ctx, comercio)
    if cargo.tipo_cambio is None:
        raise ValueError(f"El cargo en USD {cargo.clave} no tiene tipo de cambio.")
    for _ in range(MAX_REINTENTOS):
        tc = q4(cargo.tipo_cambio + _desvio(ctx, Decimal("0.15"), Decimal("0.60")))
        if ctx.libre(q2(cargo.monto_original * tc)):
            break
    else:
        raise RuntimeError("No se encontró un tipo de cambio de factura con monto libre.")
    cfdi = cfdi_comercio(ctx, comercio, cargo.monto_original, cargo.fecha + dias(ctx.delta_en_ventana(0, 3)),
                         moneda="USD", tipo_cambio=tc)
    ctx.reservar(cfdi.total_mxn)
    exp = esperar(cargo, ("usd_moneda_original",), (cfdi.uuid,), "moneda_original")
    return Escenario(cargos=(cargo,), cfdis=(cfdi,), expectativas=(exp,))


def dolares(ctx: Contexto) -> List[Escenario]:
    sin_factura = []
    for _ in range(CUOTAS["usd_sin_cfdi"]):
        cargo = cargo_usd(ctx, ctx.elegir(COMERCIOS_EXTRANJEROS))
        sin_factura.append(Escenario(cargos=(cargo,), expectativas=(
            esperar(cargo, ("usd_sin_cfdi",), motivo="sin_candidato"),)))
    return sin_factura + [_usd_moneda_original(ctx) for _ in range(CUOTAS["usd_moneda_original"])]


def sin_cfdi(ctx: Contexto) -> List[Escenario]:
    salida = []
    for _ in range(CUOTAS["sin_cfdi"]):
        comercio = ctx.elegir(COMERCIOS_SIN_FACTURA)
        cargo = nuevo_cargo(ctx, comercio, ctx.monto(*comercio.rango))
        salida.append(Escenario(cargos=(cargo,), expectativas=(
            esperar(cargo, ("sin_cfdi",), motivo="sin_candidato"),)))
    return salida


def nomina_distractores(ctx: Contexto) -> List[Escenario]:
    """Cargo sin factura cuyo monto coincide con un CFDI de nómina y con su asiento."""
    salida = []
    for n in range(CUOTAS["nomina_distractor"]):
        comercio = ctx.elegir(_grandes(3000))
        cargo = nuevo_cargo(ctx, comercio, ctx.monto(max(comercio.rango[0], 1000), comercio.rango[1]))
        empleado = EMPLEADOS[-(n + 1)]
        fecha = cargo.fecha + dias(ctx.delta_en_ventana(1, 1))
        cfdi = cfdi_nomina(ctx, empleado, cargo.monto, fecha, "PAGO EXTRAORDINARIO DE NOMINA")
        asiento = asiento_nomina(ctx, empleado, cargo.monto, fecha)
        libro = ExpectativaLibro(prohibidos=(asiento.clave,), motivo="sin_candidato")
        exp = esperar(cargo, ("nomina_distractor", "libro_nomina_distractor"), prohibidos=(cfdi.uuid,),
                      motivo="sin_candidato", libro=libro)
        salida.append(Escenario(cargos=(cargo,), cfdis=(cfdi,), asientos=(asiento,), expectativas=(exp,)))
    return salida


def filas_ininterpretables(ctx: Contexto) -> List[Escenario]:
    """Una fila por emisor con fecha imposible; su monto sí cuenta en los totales."""
    crudas = {"ALFA": f"30/02/{ctx.config.anio}", "BETA": f"04/31/{ctx.config.anio}"}
    salida = []
    for emisor, cruda in crudas.items():
        comercio = ctx.elegir(COMERCIOS_SIN_FACTURA)
        base = nuevo_cargo(ctx, comercio, ctx.monto(*comercio.rango), tarjeta=tarjeta_al_azar(ctx, emisor))
        cargo = replace(base, fecha=base.fecha_aplicacion, fecha_cruda_invalida=cruda)
        libro = ExpectativaLibro(motivo="fila_ininterpretable")
        salida.append(Escenario(cargos=(cargo,), expectativas=(
            esperar(cargo, ("fila_ininterpretable",), motivo="fila_ininterpretable", libro=libro),)))
    return salida


def pagos(ctx: Contexto) -> List[Escenario]:
    """Pago del saldo anterior: no es un gasto; no aplica cruce con CFDI ni con libro."""
    salida = []
    for emisor in ("ALFA", "BETA"):
        tarjeta = next(t for t in TARJETAS if t.emisor == emisor)
        inicio, _ = periodo_emisor(ctx.config, emisor)
        cargo = nuevo_cargo(ctx, None, -ctx.monto(25000, 90000), tarjeta=tarjeta, tipo="pago",
                            fecha=inicio + dias(4))
        libro = ExpectativaLibro(motivo="no_aplica")
        salida.append(Escenario(cargos=(cargo,), expectativas=(
            esperar(cargo, ("pago_tarjeta",), motivo="no_aplica", libro=libro),)))
    return salida


def todos(ctx: Contexto) -> List[Escenario]:
    """Todos los casos del lado CFDI en un orden fijo (el orden determina el azar)."""
    return (normales(ctx) + tolerancias(ctx) + ventanas(ctx) + sumas(ctx)
            + notas_credito_netas(ctx) + reembolsos(ctx) + rfc_genericos(ctx) + dolares(ctx)
            + sin_cfdi(ctx) + nomina_distractores(ctx) + filas_ininterpretables(ctx) + pagos(ctx))
