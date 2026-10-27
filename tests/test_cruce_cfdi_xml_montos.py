"""Lectura de SubTotal e IVA trasladado del CFDI en XML (`cargar_cfdis_xml_con_montos`).

El lector de siempre (`cargar_cfdis_xml`) no cambia: estas pruebas fijan la función nueva
y verifican que la vieja sigue aceptando lo mismo que antes.
"""
from __future__ import annotations

import dataclasses
import sys
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion.cruce_cfdi_modelo import InsumoInvalido  # noqa: E402
from conciliacion.cruce_cfdi_xml import (  # noqa: E402
    CfdiConMontos,
    DependenciaFaltante,
    cargar_cfdis_xml,
    cargar_cfdis_xml_con_montos,
)

EMPRESA = "RFC_EMPRESA_DEMO"
UUID_A = "00000000-0000-0000-0000-000000000001"
UUID_B = "00000000-0000-0000-0000-000000000002"
SIN_NODO = None


def traslado(importe: Optional[str], impuesto: str = "002", factor: str = "Tasa") -> str:
    importe_xml = "" if importe is None else f' Importe="{importe}"'
    return f'<cfdi:Traslado Impuesto="{impuesto}" TipoFactor="{factor}"{importe_xml}/>'


def nodo_impuestos(declarado: Optional[str], *traslados: str, retenido: Optional[str] = None) -> str:
    atributos = "" if declarado is None else f' TotalImpuestosTrasladados="{declarado}"'
    retenciones = ""
    if retenido is not None:
        atributos += f' TotalImpuestosRetenidos="{retenido}"'
        retenciones = f'<cfdi:Retenciones><cfdi:Retencion Impuesto="001" Importe="{retenido}"/></cfdi:Retenciones>'
    lista = f"<cfdi:Traslados>{''.join(traslados)}</cfdi:Traslados>" if traslados else ""
    return f"<cfdi:Impuestos{atributos}>{lista}{retenciones}</cfdi:Impuestos>"


IMPUESTOS_BASE = nodo_impuestos("160.00", traslado("160.00"))
# Un traslado a nivel concepto: nunca cuenta, solo el nodo Impuestos del comprobante.
CONCEPTO_CON_IVA = ('<cfdi:Conceptos><cfdi:Concepto Importe="1000.00"><cfdi:Impuestos><cfdi:Traslados>'
                    + traslado("999.00") + "</cfdi:Traslados></cfdi:Impuestos></cfdi:Concepto></cfdi:Conceptos>")


def comprobante(
    subtotal: Optional[str] = "1000.00",
    total: str = "1160.00",
    impuestos: Optional[str] = IMPUESTOS_BASE,
    uuid: str = UUID_A,
    moneda: str = "MXN",
    tipo_cambio: Optional[str] = None,
) -> str:
    atributos = ['Version="4.0"', 'Fecha="2026-03-10T09:30:00"', 'TipoDeComprobante="I"', f'Moneda="{moneda}"',
                 f'Total="{total}"']
    if subtotal is not None:
        atributos.append(f'SubTotal="{subtotal}"')
    if tipo_cambio is not None:
        atributos.append(f'TipoCambio="{tipo_cambio}"')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
        'xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" ' + " ".join(atributos) + ">"
        '<cfdi:Emisor Rfc="RFC_PROV_PAPELERIA" Nombre="PAPELERIA LA PLUMA FINA"/>'
        f'<cfdi:Receptor Rfc="{EMPRESA}" Nombre="EMPRESA DEMO"/>'
        + CONCEPTO_CON_IVA
        + (impuestos or "")
        + f'<cfdi:Complemento><tfd:TimbreFiscalDigital UUID="{uuid}"/></cfdi:Complemento>'
        "</cfdi:Comprobante>"
    )


def carpeta(tmp_path: Path, **archivos: str) -> Path:
    for nombre, contenido in archivos.items():
        (tmp_path / f"{nombre}.xml").write_text(contenido, encoding="utf-8")
    return tmp_path


def leer_uno(tmp_path: Path, xml: str) -> CfdiConMontos:
    (leido,) = cargar_cfdis_xml_con_montos(carpeta(tmp_path, a=xml), EMPRESA)
    return leido


# ----------------------------------------------------------------- lectura

def test_lee_subtotal_e_iva_como_decimal_junto_al_cfdi_de_siempre(tmp_path: Path) -> None:
    leido = leer_uno(tmp_path, comprobante())
    assert (leido.subtotal, leido.iva_trasladado) == (Decimal("1000.00"), Decimal("160.00"))
    assert isinstance(leido.subtotal, Decimal) and isinstance(leido.iva_trasladado, Decimal)
    assert leido.cfdi == cargar_cfdis_xml(tmp_path, EMPRESA)[0]


def test_el_atributo_total_trasladados_manda_sobre_los_traslados(tmp_path: Path) -> None:
    impuestos = nodo_impuestos("160.00", traslado("150.00"))
    assert leer_uno(tmp_path, comprobante(impuestos=impuestos)).iva_trasladado == Decimal("160.00")


def test_sin_atributo_suma_solo_los_traslados_de_iva_del_comprobante(tmp_path: Path) -> None:
    impuestos = nodo_impuestos(None, traslado("100.00"), traslado("60.00"), traslado("80.00", impuesto="003"))
    assert leer_uno(tmp_path, comprobante(impuestos=impuestos)).iva_trasladado == Decimal("160.00")


def test_traslado_exento_sin_importe_cuenta_cero(tmp_path: Path) -> None:
    impuestos = nodo_impuestos(None, traslado(None, factor="Exento"), traslado("16.00"))
    assert leer_uno(tmp_path, comprobante(total="116.00", impuestos=impuestos)).iva_trasladado == Decimal("16.00")


def test_sin_nodo_impuestos_del_comprobante_el_iva_es_cero(tmp_path: Path) -> None:
    leido = leer_uno(tmp_path, comprobante(total="1000.00", impuestos=SIN_NODO))
    assert leido.iva_trasladado == Decimal("0.00")


def test_solo_retenciones_el_iva_trasladado_es_cero(tmp_path: Path) -> None:
    impuestos = nodo_impuestos(None, retenido="100.00")
    assert leer_uno(tmp_path, comprobante(total="900.00", impuestos=impuestos)).iva_trasladado == Decimal("0.00")


def test_montos_en_la_moneda_del_comprobante_sin_convertir(tmp_path: Path) -> None:
    xml = comprobante(subtotal="100.00", total="116.00", impuestos=nodo_impuestos("16.00", traslado("16.00")),
                      moneda="USD", tipo_cambio="17.5000")
    leido = leer_uno(tmp_path, xml)
    assert (leido.subtotal, leido.iva_trasladado) == (Decimal("100.00"), Decimal("16.00"))
    assert leido.cfdi.total_mxn == Decimal("2030.00")


def test_redondea_a_centavos_half_up(tmp_path: Path) -> None:
    xml = comprobante(subtotal="1000.005", impuestos=nodo_impuestos("160.125"))
    leido = leer_uno(tmp_path, xml)
    assert (leido.subtotal, leido.iva_trasladado) == (Decimal("1000.01"), Decimal("160.13"))


def test_no_valida_el_cuadre_con_el_total(tmp_path: Path) -> None:
    # SubTotal + IVA − retención = Total: un CFDI válido que no cumple SubTotal + IVA = Total.
    impuestos = nodo_impuestos("160.00", traslado("160.00"), retenido="100.00")
    leido = leer_uno(tmp_path, comprobante(total="1060.00", impuestos=impuestos))
    assert (leido.subtotal, leido.iva_trasladado, leido.cfdi.total) == (
        Decimal("1000.00"), Decimal("160.00"), Decimal("1060.00"))


def test_el_resultado_es_inmutable(tmp_path: Path) -> None:
    leido = leer_uno(tmp_path, comprobante())
    with pytest.raises(dataclasses.FrozenInstanceError):
        leido.subtotal = Decimal("1.00")  # type: ignore[misc]


def test_orden_por_uuid(tmp_path: Path) -> None:
    leidos = cargar_cfdis_xml_con_montos(carpeta(tmp_path, z=comprobante(uuid=UUID_A),
                                                 a=comprobante(uuid=UUID_B)), EMPRESA)
    assert [x.cfdi.uuid for x in leidos] == [UUID_A, UUID_B]


# ----------------------------------------------------------------- errores

def test_sin_subtotal_es_error_que_nombra_el_archivo(tmp_path: Path) -> None:
    with pytest.raises(InsumoInvalido, match=r"^a\.xml: .*SubTotal"):
        leer_uno(tmp_path, comprobante(subtotal=None))


@pytest.mark.parametrize("subtotal", ["abc", "-1.00", "NaN"])
def test_subtotal_ilegible_negativo_o_no_finito(tmp_path: Path, subtotal: str) -> None:
    with pytest.raises(InsumoInvalido, match="SubTotal"):
        leer_uno(tmp_path, comprobante(subtotal=subtotal))


@pytest.mark.parametrize("declarado", ["-1.00", "x"])
def test_total_trasladados_ilegible_o_negativo(tmp_path: Path, declarado: str) -> None:
    with pytest.raises(InsumoInvalido, match="TotalImpuestosTrasladados"):
        leer_uno(tmp_path, comprobante(impuestos=nodo_impuestos(declarado)))


@pytest.mark.parametrize("importe", [None, "-5.00", "x"])
def test_traslado_de_iva_sin_importe_valido_es_error(tmp_path: Path, importe: Optional[str]) -> None:
    with pytest.raises(InsumoInvalido, match="Importe"):
        leer_uno(tmp_path, comprobante(impuestos=nodo_impuestos(None, traslado(importe))))


def test_el_lector_de_siempre_no_exige_subtotal(tmp_path: Path) -> None:
    sin_subtotal = carpeta(tmp_path, a=comprobante(subtotal=None))
    (cfdi,) = cargar_cfdis_xml(sin_subtotal, EMPRESA)
    assert cfdi.total == Decimal("1160.00")
    with pytest.raises(InsumoInvalido, match="SubTotal"):
        cargar_cfdis_xml_con_montos(sin_subtotal, EMPRESA)


def test_uuid_repetido(tmp_path: Path) -> None:
    with pytest.raises(InsumoInvalido, match="duplicado"):
        cargar_cfdis_xml_con_montos(carpeta(tmp_path, a=comprobante(), b=comprobante()), EMPRESA)


def test_dtd_rechazada(tmp_path: Path) -> None:
    bomba = '<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa">]><r>&a;</r>'
    with pytest.raises(InsumoInvalido, match="bomba.xml: XML rechazado"):
        cargar_cfdis_xml_con_montos(carpeta(tmp_path, bomba=bomba), EMPRESA)


def test_sin_defusedxml_no_hay_lector_alternativo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "defusedxml", None)
    monkeypatch.setitem(sys.modules, "defusedxml.ElementTree", None)
    with pytest.raises(DependenciaFaltante, match="defusedxml"):
        cargar_cfdis_xml_con_montos(carpeta(tmp_path, a=comprobante()), EMPRESA)
