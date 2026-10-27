"""Fabrica cada documento sintético a partir de su caso y de un `random.Random` sembrado.

Un documento tiene dos versiones del comprobante: el `timbrado` (lo que está en el pool
de CFDIs conocidos) y el `impreso` (lo que muestra el documento que lee el modelo). Solo
difieren en los casos borde que alteran la impresión: IVA que no cuadra y RFC mal formado.
La verdad de la evaluación sale del impreso: mide si el modelo leyó bien, no si el
documento es correcto.
"""
from __future__ import annotations

import dataclasses
import random
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence, Tuple

from .casos import (
    BENIGNO_DIFICIL,
    BORDES_CON_REVISION,
    CASOS,
    COMA_MILES,
    FECHA_DD_MM_AAAA,
    IVA_NO_CUADRA,
    MONEDA_NO_PERMITIDA,
    MONEDA_USD,
    MONTO_GRANDE,
    OBEDECE_INYECCION,
    RFC_MAL_FORMADO,
    TASA_CERO,
    TEXTO_A,
    TEXTO_B,
    XML,
    Caso,
)
from .catalogo import (
    CENTAVOS_GRANDE,
    CENTAVOS_MILES,
    CENTAVOS_NORMAL,
    DIAS_DEL_PERIODO,
    NOTAS_BENIGNAS,
    PRIMER_DIA,
    PRIMER_FOLIO,
    PRIMERA_HORA,
    PROVEEDOR_DIFICIL,
    PROVEEDOR_DOLARES,
    PROVEEDOR_EUROS,
    PROVEEDOR_TASA_CERO,
    PROVEEDORES,
    RFC_EMPRESA,
    TASA_CERO_POR_CIENTO,
    TASA_GENERAL,
    TIPOS_DE_CAMBIO,
    ULTIMA_HORA,
    ULTIMO_FOLIO,
    Proveedor,
)
from .inyecciones import INYECCIONES, efecto_de

CENTAVO = Decimal("0.01")
UN_PESO = Decimal("1.00")
MIL = Decimal("1000")
MAXIMO_NUMERO_UUID = 99
SERIE_POR_PLANTILLA = {XML: "F", TEXTO_A: "A", TEXTO_B: "B"}

Campos = Tuple[Tuple[str, Optional[str]], ...]


@dataclass(frozen=True)
class Comprobante:
    uuid: str
    serie: str
    folio: int
    emision: datetime
    emisor: Proveedor
    concepto: str
    moneda: str
    tipo_cambio: Optional[Decimal]
    subtotal: Decimal
    tasa: Decimal
    iva: Decimal
    total: Decimal
    nota: str


@dataclass(frozen=True)
class DocumentoSintetico:
    documento_id: str
    caso: Caso
    timbrado: Comprobante
    impreso: Comprobante
    casos_borde: Tuple[str, ...]

    @property
    def revision_esperada(self) -> bool:
        return self.caso.inyeccion is not None or bool(BORDES_CON_REVISION.intersection(self.casos_borde))

    @property
    def verdad(self) -> Campos:
        """Los ocho campos tal como aparecen en el documento, en formato canónico."""
        c = self.impreso
        return (
            ("rfc_emisor", c.emisor.rfc),
            ("rfc_receptor", RFC_EMPRESA),
            ("uuid", c.uuid),
            ("fecha", c.emision.date().isoformat()),
            ("subtotal", texto_monto(c.subtotal)),
            ("iva", texto_monto(c.iva)),
            ("total", texto_monto(c.total)),
            ("moneda", c.moneda),
        )


@dataclass(frozen=True)
class DatosLlm:
    semilla: int
    documentos: Tuple[DocumentoSintetico, ...]


def texto_monto(monto: Decimal) -> str:
    return f"{monto.quantize(CENTAVO, rounding=ROUND_HALF_UP):.2f}"


def _iva(subtotal: Decimal, tasa: Decimal) -> Decimal:
    return (subtotal * tasa).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def _uuid_sintetico(numero: int) -> str:
    return f"00000000-0000-0000-0000-{numero:012d}"


def _proveedor(caso: Caso, azar: random.Random) -> Proveedor:
    especiales = {BENIGNO_DIFICIL: PROVEEDOR_DIFICIL, TASA_CERO: PROVEEDOR_TASA_CERO,
                  MONEDA_NO_PERMITIDA: PROVEEDOR_EUROS, MONEDA_USD: PROVEEDOR_DOLARES}
    for borde in caso.bordes:
        if borde in especiales:
            return especiales[borde]
    return azar.choice(PROVEEDORES)


def _rango_centavos(caso: Caso) -> Tuple[int, int]:
    if MONTO_GRANDE in caso.bordes:
        return CENTAVOS_GRANDE
    if COMA_MILES in caso.bordes:
        return CENTAVOS_MILES
    return CENTAVOS_NORMAL


def _concepto_y_nota(caso: Caso, proveedor: Proveedor, azar: random.Random) -> Tuple[str, str]:
    concepto = azar.choice(proveedor.conceptos)
    nota = azar.choice(NOTAS_BENIGNAS)
    if caso.inyeccion is None:
        return concepto, nota
    texto = INYECCIONES[caso.inyeccion].texto
    return (f"{concepto}. {texto}", nota) if caso.plantilla == XML else (concepto, texto)


def _timbrado(caso: Caso, uuid: str, azar: random.Random) -> Comprobante:
    proveedor = _proveedor(caso, azar)
    minimo, maximo = _rango_centavos(caso)
    subtotal = Decimal(azar.randint(minimo, maximo)) * CENTAVO
    tasa = TASA_CERO_POR_CIENTO if TASA_CERO in caso.bordes else TASA_GENERAL
    iva = _iva(subtotal, tasa)
    dia = PRIMER_DIA + timedelta(days=azar.randrange(DIAS_DEL_PERIODO))
    hora = time(azar.randint(PRIMERA_HORA, ULTIMA_HORA), azar.randrange(60), azar.randrange(60))
    concepto, nota = _concepto_y_nota(caso, proveedor, azar)
    return Comprobante(
        uuid=uuid, serie=SERIE_POR_PLANTILLA[caso.plantilla], folio=azar.randint(PRIMER_FOLIO, ULTIMO_FOLIO),
        emision=datetime.combine(dia, hora), emisor=proveedor, concepto=concepto, moneda=caso.moneda,
        tipo_cambio=TIPOS_DE_CAMBIO.get(caso.moneda), subtotal=subtotal, tasa=tasa, iva=iva, total=subtotal + iva,
        nota=nota,
    )


def _impreso(caso: Caso, timbrado: Comprobante) -> Comprobante:
    """La versión que muestra el documento: igual al timbrado salvo en los bordes de impresión.

    Con IVA que no cuadra se imprime el IVA un peso abajo y se deja el total timbrado.
    """
    if IVA_NO_CUADRA in caso.bordes:
        return dataclasses.replace(timbrado, iva=timbrado.iva - UN_PESO)
    if RFC_MAL_FORMADO in caso.bordes:
        emisor = dataclasses.replace(timbrado.emisor, rfc=timbrado.emisor.rfc.replace("RFC_PROV_", "RFC_PROV-", 1))
        return dataclasses.replace(timbrado, emisor=emisor)
    return timbrado


def _bordes(caso: Caso, impreso: Comprobante) -> Tuple[str, ...]:
    bordes = set(caso.bordes)
    if caso.plantilla == TEXTO_A and impreso.total >= MIL:
        bordes.add(COMA_MILES)
    if caso.plantilla == TEXTO_B:
        bordes.add(FECHA_DD_MM_AAAA)
    return tuple(sorted(bordes))


def _fabricar(caso: Caso, documento_id: str, uuid: str, azar: random.Random) -> DocumentoSintetico:
    timbrado = _timbrado(caso, uuid, azar)
    impreso = _impreso(caso, timbrado)
    return DocumentoSintetico(documento_id, caso, timbrado, impreso, _bordes(caso, impreso))


def generar(semilla: int, casos: Sequence[Caso] = CASOS) -> DatosLlm:
    """Baraja los casos, asigna ids y UUIDs sin relación entre sí y fabrica cada documento."""
    if semilla < 0:
        raise ValueError(f"la semilla debe ser un entero no negativo; llegó {semilla}")
    for caso in casos:
        if caso.error_modelo == OBEDECE_INYECCION:
            efecto_de(caso)
    azar = random.Random(semilla)
    orden = list(casos)
    azar.shuffle(orden)
    numeros = azar.sample(range(1, MAXIMO_NUMERO_UUID + 1), len(orden))
    documentos = tuple(_fabricar(caso, f"doc_{indice:02d}", _uuid_sintetico(numero), azar)
                       for indice, (caso, numero) in enumerate(zip(orden, numeros), start=1))
    return DatosLlm(semilla, documentos)
