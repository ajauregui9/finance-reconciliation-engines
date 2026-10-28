"""Contrato de la frontera de entrada del cruce cargo ↔ CFDI (JSONL, XML y config).

Montos: texto o número JSON, hasta dos decimales, dígitos ASCII, sin separador de miles.
Un float pasa solo por su `repr`; uno ambiguo (`0.1 + 0.2`) es error. Nada se redondea.
"""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from conciliacion import cruce_cfdi
from conciliacion.cruce_cfdi_config import config_desde_dict
from conciliacion.cruce_cfdi_insumos import a_monto, cargo_desde_dict, cfdi_desde_dict
from conciliacion.cruce_cfdi_modelo import ConfigInvalida, InsumoInvalido
from conciliacion.cruce_cfdi_xml import cargar_cfdis_xml, cargar_cfdis_xml_con_montos

ROOT = Path(__file__).resolve().parents[1]
CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"
EMPRESA = "RFC_EMPRESA_DEMO"
FUERA_DE_CONTRATO = ["١٠٠.٠٠", "100.005", "1 000.00", "1,000.00", "1,00.00", "1e2", "", 0.1 + 0.2, 100.005,
                     True, None]


def _cargo(**cambios: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {"cargo_id": "ALFA-0001", "fecha": "2026-07-10", "descripcion": "CAFE LUNA AZUL",
                            "monto": "100.00", "moneda_original": "MXN", "monto_original": "100.00",
                            "tipo_movimiento": "cargo", "estado": "ok"}
    return {**base, **cambios}


def _cfdi(**cambios: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {"uuid": "U-1", "fecha_emision": "2026-07-10", "tipo_comprobante": "I",
                            "direccion": "recibido", "rfc_emisor": "RFC_COM_01", "nombre_emisor": "CAFETERIA",
                            "rfc_receptor": EMPRESA, "moneda": "MXN", "total": "100.00", "total_mxn": "100.00",
                            "uuid_relacionado": None}
    return {**base, **cambios}


def _xml(total: str = "116.00", subtotal: str = "100.00", fecha: str = "2026-07-12T10:15:00",
         moneda: str = "MXN", tipo_cambio: Optional[str] = None, importe: str = "16.00") -> str:
    tc = f' TipoCambio="{tipo_cambio}"' if tipo_cambio is not None else ""
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" '
            'xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" Version="4.0" '
            f'Fecha="{fecha}" TipoDeComprobante="I" Moneda="{moneda}" SubTotal="{subtotal}" Total="{total}"{tc}>'
            '<cfdi:Emisor Rfc="RFC_COM_01" Nombre="CAFETERIA"/><cfdi:Receptor Rfc="RFC_EMPRESA_DEMO"/>'
            f'<cfdi:Impuestos TotalImpuestosTrasladados="{importe}"><cfdi:Traslados>'
            f'<cfdi:Traslado Impuesto="002" TipoFactor="Tasa" Importe="{importe}"/></cfdi:Traslados>'
            '</cfdi:Impuestos><cfdi:Complemento><tfd:TimbreFiscalDigital '
            'UUID="00000000-0000-0000-0000-000000000001"/></cfdi:Complemento></cfdi:Comprobante>')


def _carpeta(tmp_path: Path, xml: str) -> Path:
    (tmp_path / "a.xml").write_text(xml, encoding="utf-8")
    return tmp_path


# ------------------------------------------------------------------- a_monto
@pytest.mark.parametrize("valor, esperado", [("100", "100.00"), (" -1234.5 ", "-1234.50"), (100, "100.00"),
                                             (100.5, "100.50"), (Decimal("2.5"), "2.50")])
def test_monto_valido(valor: object, esperado: str) -> None:
    assert str(a_monto(valor, "monto")) == esperado


@pytest.mark.parametrize("valor", FUERA_DE_CONTRATO)
def test_monto_fuera_de_contrato(valor: object) -> None:
    with pytest.raises(InsumoInvalido, match="monto"):
        a_monto(valor, "monto")


def test_float_ambiguo_dice_por_que() -> None:
    with pytest.raises(InsumoInvalido, match="decimales significativos"):
        a_monto(0.1 + 0.2, "monto")


# -------------------------------------------------------------------- JSONL
@pytest.mark.parametrize("campo", ["monto", "monto_original"])
def test_cargo_con_monto_fuera_de_contrato(campo: str) -> None:
    with pytest.raises(InsumoInvalido, match=campo):
        cargo_desde_dict(_cargo(**{campo: "100.005"}))


@pytest.mark.parametrize("fecha", ["٢٠٢٦-٠٧-١٠", "20260710", "2026-W28-5", "2026-07-10 12:30:00"])
def test_fechas_solo_iso_ascii(fecha: str) -> None:
    with pytest.raises(InsumoInvalido, match="fecha"):
        cargo_desde_dict(_cargo(fecha=fecha))
    with pytest.raises(InsumoInvalido, match="fecha_emision"):
        cfdi_desde_dict(_cfdi(fecha_emision=fecha))


def test_fecha_emision_con_hora() -> None:
    assert cfdi_desde_dict(_cfdi(fecha_emision="2026-07-10T23:59:59")).fecha_emision == date(2026, 7, 10)


@pytest.mark.parametrize("total", ["100.005", "١٠٠.٠٠", 0.1 + 0.2])
def test_cfdi_con_total_fuera_de_contrato(total: object) -> None:
    with pytest.raises(InsumoInvalido, match="total"):
        cfdi_desde_dict(_cfdi(total=total, total_mxn=total))


def test_config_con_tolerancia_de_tres_decimales() -> None:
    with pytest.raises(ConfigInvalida, match="uno_a_uno"):
        config_desde_dict({"tolerancias": {"uno_a_uno": "1.005"}})


# ---------------------------------------------------------------------- XML
@pytest.mark.parametrize("cambio, atributo", [
    ({"total": "116.005"}, "Total"), ({"total": "١١٦.٠٠"}, "Total"), ({"total": "1,116.00"}, "Total"),
    ({"subtotal": "100.005"}, "SubTotal"), ({"importe": "16.005"}, "Importe"),
])
def test_xml_con_monto_fuera_de_contrato(tmp_path: Path, cambio: Dict[str, str], atributo: str) -> None:
    with pytest.raises(InsumoInvalido, match=rf"a\.xml: .*{atributo}"):
        cargar_cfdis_xml_con_montos(_carpeta(tmp_path, _xml(**cambio)), EMPRESA)


@pytest.mark.parametrize("fecha", ["٢٠٢٦-٠٧-١٢T10:15:00", "2026-07-12", "2026-07-12 10:15:00", "20260712T101500",
                                   "2026-07-12T10:15:00Z"])
def test_xml_con_fecha_fuera_de_forma(tmp_path: Path, fecha: str) -> None:
    with pytest.raises(InsumoInvalido, match="Fecha"):
        cargar_cfdis_xml(_carpeta(tmp_path, _xml(fecha=fecha)), EMPRESA)


def test_xml_tipo_de_cambio_con_seis_decimales_sin_redondeo_previo(tmp_path: Path) -> None:
    # 1000.00 × 17.123449 = 17123.449 -> 17123.45; redondear antes el tipo de cambio a 17.1234 daría 17123.40.
    xml = _xml(total="1000.00", subtotal="862.07", moneda="USD", tipo_cambio="17.123449")
    (cfdi,) = cargar_cfdis_xml(_carpeta(tmp_path, xml), EMPRESA)
    assert cfdi.total_mxn == Decimal("17123.45")


@pytest.mark.parametrize("tipo_cambio", ["١٧.٥٠", "17.1234567", "-17.50", "0", "17,50"])
def test_xml_tipo_de_cambio_fuera_de_contrato(tmp_path: Path, tipo_cambio: str) -> None:
    with pytest.raises(InsumoInvalido, match="TipoCambio"):
        cargar_cfdis_xml(_carpeta(tmp_path, _xml(moneda="USD", tipo_cambio=tipo_cambio)), EMPRESA)


# ---------------------------------------------------------------------- CLI
def test_cli_sale_con_2_y_no_escribe(tmp_path: Path) -> None:
    universo = tmp_path / "universo.jsonl"
    universo.write_text(json.dumps(_cargo(monto="100.005")) + "\n", encoding="utf-8")
    salida = tmp_path / "salida.json"
    assert cruce_cfdi.main(["--universo", str(universo), "--cfdis", str(CFDIS), "--salida", str(salida)]) == 2
    assert not salida.exists()
