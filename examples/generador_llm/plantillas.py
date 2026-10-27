"""Plantillas de los documentos: CFDI 4.0 en XML y dos representaciones impresas en texto.

Los `.txt` simulan el texto que un extractor de PDF obtendría de la representación
impresa (columnas con espacios, pie de página). La plantilla A usa comas de miles y fecha
ISO; la B no usa comas y escribe la fecha dd/mm/aaaa.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import List

from .catalogo import CODIGO_POSTAL, MINUTOS_HASTA_TIMBRADO, NOMBRE_EMPRESA, RFC_EMPRESA, RFC_PAC
from .fabricas import Comprobante, texto_monto

ESPACIO_CFDI = "http://www.sat.gob.mx/cfd/4"
ESPACIO_TIMBRE = "http://www.sat.gob.mx/TimbreFiscalDigital"
SELLO_FICTICIO = "SINTETICO"
CLAVE_PRODUCTO = "80141600"
CLAVE_UNIDAD = "E48"
IMPUESTO_IVA = "002"
MONEDA_LOCAL = "MXN"
CIEN = Decimal(100)
REGLA = "-" * 64
DOBLE_REGLA = "=" * 64


# Escape de un valor de atributo XML; `&` va primero para no escapar dos veces.
_ESCAPES_ATRIBUTO = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"), ('"', "&quot;"))


def _atributo(valor: str) -> str:
    for caracter, entidad in _ESCAPES_ATRIBUTO:
        valor = valor.replace(caracter, entidad)
    return valor


def _atributos(pares: List[List[str]]) -> str:
    return " ".join(f'{nombre}="{_atributo(valor)}"' for nombre, valor in pares)


def _tasa_xml(c: Comprobante) -> str:
    return f"{c.tasa:.6f}"


def _tasa_impresa(c: Comprobante) -> str:
    return f"{(c.tasa * CIEN).normalize():f}"


def _raiz(c: Comprobante) -> str:
    pares = [["xmlns:cfdi", ESPACIO_CFDI], ["xmlns:tfd", ESPACIO_TIMBRE], ["Version", "4.0"], ["Serie", c.serie],
             ["Folio", str(c.folio)], ["Fecha", c.emision.isoformat()], ["SubTotal", texto_monto(c.subtotal)],
             ["Moneda", c.moneda]]
    if c.tipo_cambio is not None:
        pares.append(["TipoCambio", f"{c.tipo_cambio:.4f}"])
    pares += [["Total", texto_monto(c.total)], ["TipoDeComprobante", "I"], ["Exportacion", "01"],
              ["MetodoPago", "PUE"], ["FormaPago", "03"], ["LugarExpedicion", CODIGO_POSTAL]]
    return f"<cfdi:Comprobante {_atributos(pares)}>"


def _traslado(c: Comprobante) -> str:
    return "<cfdi:Traslado " + _atributos([["Base", texto_monto(c.subtotal)], ["Impuesto", IMPUESTO_IVA],
                                           ["TipoFactor", "Tasa"], ["TasaOCuota", _tasa_xml(c)],
                                           ["Importe", texto_monto(c.iva)]]) + "/>"


def xml_cfdi(c: Comprobante) -> str:
    """Un CFDI 4.0 de ingreso con un concepto, IVA trasladado y timbre de prueba."""
    timbrado = (c.emision + timedelta(minutes=MINUTOS_HASTA_TIMBRADO)).isoformat()
    emisor = _atributos([["Rfc", c.emisor.rfc], ["Nombre", c.emisor.nombre], ["RegimenFiscal", "601"]])
    receptor = _atributos([["Rfc", RFC_EMPRESA], ["Nombre", NOMBRE_EMPRESA], ["DomicilioFiscalReceptor", CODIGO_POSTAL],
                           ["RegimenFiscalReceptor", "601"], ["UsoCFDI", "G03"]])
    concepto = _atributos([["ClaveProdServ", CLAVE_PRODUCTO], ["Cantidad", "1"], ["ClaveUnidad", CLAVE_UNIDAD],
                           ["Descripcion", c.concepto], ["ValorUnitario", texto_monto(c.subtotal)],
                           ["Importe", texto_monto(c.subtotal)], ["ObjetoImp", "02"]])
    timbre = _atributos([["Version", "1.1"], ["UUID", c.uuid], ["FechaTimbrado", timbrado], ["RfcProvCertif", RFC_PAC],
                         ["SelloCFD", SELLO_FICTICIO], ["NoCertificadoSAT", SELLO_FICTICIO],
                         ["SelloSAT", SELLO_FICTICIO]])
    lineas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        _raiz(c),
        f"  <cfdi:Emisor {emisor}/>",
        f"  <cfdi:Receptor {receptor}/>",
        "  <cfdi:Conceptos>",
        f"    <cfdi:Concepto {concepto}>",
        f"      <cfdi:Impuestos><cfdi:Traslados>{_traslado(c)}</cfdi:Traslados></cfdi:Impuestos>",
        "    </cfdi:Concepto>",
        "  </cfdi:Conceptos>",
        f'  <cfdi:Impuestos TotalImpuestosTrasladados="{texto_monto(c.iva)}">',
        f"    <cfdi:Traslados>{_traslado(c)}</cfdi:Traslados>",
        "  </cfdi:Impuestos>",
        f"  <cfdi:Complemento><tfd:TimbreFiscalDigital {timbre}/></cfdi:Complemento>",
        "</cfdi:Comprobante>",
    ]
    return "\n".join(lineas) + "\n"


def _con_comas(monto: Decimal) -> str:
    return f"{monto:,.2f}"


def _linea_moneda(c: Comprobante) -> str:
    if c.tipo_cambio is None:
        return f"Moneda:               {c.moneda}"
    return f"Moneda:               {c.moneda}    Tipo de cambio: {c.tipo_cambio:.4f}"


def texto_a(c: Comprobante) -> str:
    """Representación impresa amplia: comas de miles, fecha ISO con hora."""
    lineas = [
        "FACTURA ELECTRÓNICA · CFDI 4.0",
        "Representación impresa de un CFDI",
        DOBLE_REGLA,
        f"EMISOR     {c.emisor.nombre}",
        f"           RFC: {c.emisor.rfc}",
        "           Régimen fiscal: 601 General de Ley Personas Morales",
        f"RECEPTOR   {NOMBRE_EMPRESA}",
        f"           RFC: {RFC_EMPRESA}",
        "           Uso del CFDI: G03 Gastos en general",
        REGLA,
        f"Folio fiscal (UUID):  {c.uuid}",
        f"Serie y folio:        {c.serie}-{c.folio}",
        f"Fecha de emisión:     {c.emision.date().isoformat()} {c.emision.time().isoformat()}",
        _linea_moneda(c),
        REGLA,
        "Cant.  Unidad  Descripción",
        f"1      {CLAVE_UNIDAD}     {c.concepto}",
        f"{'Importe':>48}  {_con_comas(c.subtotal)}",
        REGLA,
        f"{'Subtotal':>48}  $ {_con_comas(c.subtotal)}",
        f"{'IVA trasladado ' + _tasa_impresa(c) + '%':>48}  $ {_con_comas(c.iva)}",
        f"{'Total':>48}  $ {_con_comas(c.total)} {c.moneda}",
        f"Observaciones: {c.nota}",
        "Página 1 de 1",
    ]
    return "\n".join(lineas) + "\n"


def texto_b(c: Comprobante) -> str:
    """Representación compacta: sin comas de miles, fecha dd/mm/aaaa."""
    fecha = c.emision.date().strftime("%d/%m/%Y")
    cambio = "" if c.tipo_cambio is None else f"   T.C. {c.tipo_cambio:.4f}"
    lineas = [
        f"{c.emisor.nombre} | RFC {c.emisor.rfc}",
        f"Factura {c.serie}{c.folio}    Fecha: {fecha}",
        f"Cliente: {NOMBRE_EMPRESA}    RFC cliente: {RFC_EMPRESA}",
        f"UUID {c.uuid}",
        f"Concepto: {c.concepto}",
        f"Importe sin IVA ........ {texto_monto(c.subtotal)} {c.moneda}{cambio}",
        f"IVA ({_tasa_impresa(c)} %) ......... {texto_monto(c.iva)}",
        f"TOTAL A PAGAR .......... {texto_monto(c.total)} {c.moneda}",
        f"Notas: {c.nota}",
    ]
    return "\n".join(lineas) + "\n"
