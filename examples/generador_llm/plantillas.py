"""Plantillas de los documentos: CFDI 4.0 en XML y dos representaciones impresas en texto.

Los `.txt` simulan el texto que un extractor de PDF obtendría de la representación
impresa (columnas con espacios, pie de página). La plantilla A usa comas de miles y fecha
ISO; la B no usa comas y escribe la fecha dd/mm/aaaa. El descuento, el IEPS y las
retenciones solo se imprimen (y solo aparecen en el XML) cuando el comprobante los trae.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import List

from .catalogo import CODIGO_POSTAL, MINUTOS_HASTA_TIMBRADO, NOMBRE_EMPRESA, REGIMENES, RFC_EMPRESA, RFC_PAC
from .fabricas import Comprobante, texto_monto

ESPACIO_CFDI = "http://www.sat.gob.mx/cfd/4"
ESPACIO_TIMBRE = "http://www.sat.gob.mx/TimbreFiscalDigital"
SELLO_FICTICIO = "SINTETICO"
CLAVE_PRODUCTO = "80141600"
CLAVE_UNIDAD = "E48"
IMPUESTO_ISR = "001"
IMPUESTO_IVA = "002"
IMPUESTO_IEPS = "003"
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


def _tasa_xml(tasa: Decimal) -> str:
    return f"{tasa:.6f}"


def _tasa_impresa(tasa: Decimal) -> str:
    return f"{(tasa * CIEN).normalize():f}"


def _raiz(c: Comprobante) -> str:
    pares = [["xmlns:cfdi", ESPACIO_CFDI], ["xmlns:tfd", ESPACIO_TIMBRE], ["Version", "4.0"], ["Serie", c.serie],
             ["Folio", str(c.folio)], ["Fecha", c.emision.isoformat()], ["SubTotal", texto_monto(c.subtotal)]]
    if c.desglose.descuento:
        pares.append(["Descuento", texto_monto(c.desglose.descuento)])
    pares.append(["Moneda", c.moneda])
    if c.tipo_cambio is not None:
        pares.append(["TipoCambio", f"{c.tipo_cambio:.4f}"])
    pares += [["Total", texto_monto(c.total)], ["TipoDeComprobante", "I"], ["Exportacion", "01"],
              ["MetodoPago", "PUE"], ["FormaPago", "03"], ["LugarExpedicion", CODIGO_POSTAL]]
    return f"<cfdi:Comprobante {_atributos(pares)}>"


def _nodo(elemento: str, base: Decimal, impuesto: str, tasa: Decimal, importe: Decimal) -> str:
    return f"<cfdi:{elemento} " + _atributos([["Base", texto_monto(base)], ["Impuesto", impuesto],
                                               ["TipoFactor", "Tasa"], ["TasaOCuota", _tasa_xml(tasa)],
                                               ["Importe", texto_monto(importe)]]) + "/>"


def _traslados(c: Comprobante) -> str:
    """El IVA (sobre la base más el IEPS) y, si aplica, el IEPS (sobre la base)."""
    nodos = _nodo("Traslado", c.base_iva, IMPUESTO_IVA, c.tasa, c.iva)
    if c.desglose.ieps:
        nodos += _nodo("Traslado", c.base, IMPUESTO_IEPS, c.desglose.tasa_ieps, c.desglose.ieps)
    return f"<cfdi:Traslados>{nodos}</cfdi:Traslados>"


def _retenciones_concepto(c: Comprobante) -> str:
    d = c.desglose
    nodos = ""
    if d.isr_retenido:
        nodos += _nodo("Retencion", c.base, IMPUESTO_ISR, d.tasa_isr_retenido, d.isr_retenido)
    if d.iva_retenido:
        nodos += _nodo("Retencion", c.base, IMPUESTO_IVA, d.tasa_iva_retenido, d.iva_retenido)
    return f"<cfdi:Retenciones>{nodos}</cfdi:Retenciones>" if nodos else ""


def _retenciones_comprobante(c: Comprobante) -> str:
    """A nivel comprobante, cada retención lleva solo Impuesto e Importe."""
    d = c.desglose
    pares = [(IMPUESTO_ISR, d.isr_retenido), (IMPUESTO_IVA, d.iva_retenido)]
    nodos = "".join(f"<cfdi:Retencion {_atributos([['Impuesto', i], ['Importe', texto_monto(m)]])}/>"
                    for i, m in pares if m)
    return f"<cfdi:Retenciones>{nodos}</cfdi:Retenciones>" if nodos else ""


def _impuestos_comprobante(c: Comprobante) -> List[str]:
    totales = []
    if c.desglose.retenidos:
        totales.append(f'TotalImpuestosRetenidos="{texto_monto(c.desglose.retenidos)}"')
    totales.append(f'TotalImpuestosTrasladados="{texto_monto(c.trasladados)}"')
    lineas = [f"  <cfdi:Impuestos {' '.join(totales)}>"]
    retenciones = _retenciones_comprobante(c)
    if retenciones:
        lineas.append(f"    {retenciones}")
    return lineas + [f"    {_traslados(c)}", "  </cfdi:Impuestos>"]


def xml_cfdi(c: Comprobante) -> str:
    """Un CFDI 4.0 de ingreso con un concepto, su desglose fiscal y timbre de prueba."""
    timbrado = (c.emision + timedelta(minutes=MINUTOS_HASTA_TIMBRADO)).isoformat()
    emisor = _atributos([["Rfc", c.emisor.rfc], ["Nombre", c.emisor.nombre], ["RegimenFiscal", c.emisor.regimen]])
    receptor = _atributos([["Rfc", RFC_EMPRESA], ["Nombre", NOMBRE_EMPRESA], ["DomicilioFiscalReceptor", CODIGO_POSTAL],
                           ["RegimenFiscalReceptor", "601"], ["UsoCFDI", "G03"]])
    pares_concepto = [["ClaveProdServ", CLAVE_PRODUCTO], ["Cantidad", "1"], ["ClaveUnidad", CLAVE_UNIDAD],
                      ["Descripcion", c.concepto], ["ValorUnitario", texto_monto(c.subtotal)],
                      ["Importe", texto_monto(c.subtotal)]]
    if c.desglose.descuento:
        pares_concepto.append(["Descuento", texto_monto(c.desglose.descuento)])
    concepto = _atributos(pares_concepto + [["ObjetoImp", "02"]])
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
        f"      <cfdi:Impuestos>{_traslados(c)}{_retenciones_concepto(c)}</cfdi:Impuestos>",
        "    </cfdi:Concepto>",
        "  </cfdi:Conceptos>",
        *_impuestos_comprobante(c),
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


def _renglones_a(c: Comprobante) -> List[str]:
    """Los renglones de montos de la plantilla A, del subtotal al total."""
    d = c.desglose
    renglones = [("Subtotal", c.subtotal)]
    if d.descuento:
        renglones.append(("Descuento", d.descuento))
    if d.ieps:
        renglones.append((f"IEPS trasladado {_tasa_impresa(d.tasa_ieps)}%", d.ieps))
    renglones.append((f"IVA trasladado {_tasa_impresa(c.tasa)}%", c.iva))
    if d.isr_retenido:
        renglones.append((f"ISR retenido {_tasa_impresa(d.tasa_isr_retenido)}%", d.isr_retenido))
    if d.iva_retenido:
        renglones.append((f"IVA retenido {_tasa_impresa(d.tasa_iva_retenido)}%", d.iva_retenido))
    return [f"{etiqueta:>48}  $ {_con_comas(monto)}" for etiqueta, monto in renglones]


def texto_a(c: Comprobante) -> str:
    """Representación impresa amplia: comas de miles, fecha ISO con hora."""
    lineas = [
        "FACTURA ELECTRÓNICA · CFDI 4.0",
        "Representación impresa de un CFDI",
        DOBLE_REGLA,
        f"EMISOR     {c.emisor.nombre}",
        f"           RFC: {c.emisor.rfc}",
        f"           Régimen fiscal: {c.emisor.regimen} {REGIMENES[c.emisor.regimen]}",
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
        *_renglones_a(c),
        f"{'Total':>48}  $ {_con_comas(c.total)} {c.moneda}",
        f"Observaciones: {c.nota}",
        "Página 1 de 1",
    ]
    return "\n".join(lineas) + "\n"


def _antes_del_iva_b(c: Comprobante) -> List[str]:
    """Descuento e IEPS de la plantilla B (solo los que aplican): van antes del IVA."""
    d = c.desglose
    renglones = []
    if d.descuento:
        renglones.append(f"Descuento .............. {texto_monto(d.descuento)}")
    if d.ieps:
        renglones.append(f"IEPS ({_tasa_impresa(d.tasa_ieps)} %) ........ {texto_monto(d.ieps)}")
    return renglones


def _retenciones_b(c: Comprobante) -> List[str]:
    d = c.desglose
    renglones = []
    if d.isr_retenido:
        renglones.append(f"Ret. ISR ({_tasa_impresa(d.tasa_isr_retenido)} %) .... {texto_monto(d.isr_retenido)}")
    if d.iva_retenido:
        renglones.append(f"Ret. IVA ({_tasa_impresa(d.tasa_iva_retenido)} %) .... {texto_monto(d.iva_retenido)}")
    return renglones


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
        *_antes_del_iva_b(c),
        f"IVA ({_tasa_impresa(c.tasa)} %) ......... {texto_monto(c.iva)}",
        *_retenciones_b(c),
        f"TOTAL A PAGAR .......... {texto_monto(c.total)} {c.moneda}",
        f"Notas: {c.nota}",
    ]
    return "\n".join(lineas) + "\n"
