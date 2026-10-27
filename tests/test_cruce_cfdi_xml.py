"""Pruebas del lector de CFDI en XML: solo defusedxml, sin fallback."""
from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion import cruce_cfdi  # noqa: E402
from conciliacion.cruce_cfdi_modelo import InsumoInvalido  # noqa: E402
from conciliacion.cruce_cfdi_xml import DependenciaFaltante, cargar_cfdis_xml  # noqa: E402

EMPRESA = "RFC_EMPRESA_DEMO"
UUID_1 = "00000000-0000-0000-0000-000000000001"
UUID_2 = "00000000-0000-0000-0000-000000000002"


def comprobante(
    uuid: Optional[str] = UUID_1,
    tipo: str = "I",
    total: Optional[str] = "116.00",
    moneda: str = "MXN",
    tipo_cambio: Optional[str] = None,
    emisor: str = "RFC_COM_01",
    receptor: str = EMPRESA,
    relacionado: Optional[str] = None,
    version: str = "4",
) -> str:
    atributos = [f'Version="{version}.0"', 'Fecha="2026-07-12T10:15:00"', f'TipoDeComprobante="{tipo}"',
                 f'Moneda="{moneda}"', 'SubTotal="100.00"']
    if total is not None:
        atributos.append(f'Total="{total}"')
    if tipo_cambio is not None:
        atributos.append(f'TipoCambio="{tipo_cambio}"')
    relacion = (f'<cfdi:CfdiRelacionados TipoRelacion="01"><cfdi:CfdiRelacionado UUID="{relacionado}"/>'
                "</cfdi:CfdiRelacionados>") if relacionado else ""
    timbre = (f'<cfdi:Complemento><tfd:TimbreFiscalDigital UUID="{uuid}"/></cfdi:Complemento>'
              if uuid else "")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/{version}" '
        'xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital" ' + " ".join(atributos) + ">"
        + relacion
        + f'<cfdi:Emisor Rfc="{emisor}" Nombre="CAFETERÍA LUNA AZUL"/>'
        + f'<cfdi:Receptor Rfc="{receptor}" Nombre="EMPRESA DEMO"/>'
        + timbre + "</cfdi:Comprobante>"
    )


def carpeta(tmp_path: Path, **archivos: str) -> Path:
    for nombre, contenido in archivos.items():
        (tmp_path / f"{nombre}.xml").write_text(contenido, encoding="utf-8")
    return tmp_path


class TestSinDefusedxml:
    def test_falla_sin_fallback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(sys.modules, "defusedxml", None)
        monkeypatch.setitem(sys.modules, "defusedxml.ElementTree", None)
        with pytest.raises(DependenciaFaltante, match="defusedxml"):
            cargar_cfdis_xml(carpeta(tmp_path, a=comprobante()), EMPRESA)


class TestConDefusedxml:
    @pytest.fixture(autouse=True)
    def _requiere_defusedxml(self) -> None:
        pytest.importorskip("defusedxml")

    def test_factura_recibida(self, tmp_path: Path) -> None:
        (f,) = cargar_cfdis_xml(carpeta(tmp_path, a=comprobante()), EMPRESA)
        assert (f.uuid, f.fecha_emision, f.tipo_comprobante, f.direccion) == (
            UUID_1, date(2026, 7, 12), "I", "recibido")
        assert (f.rfc_emisor, f.nombre_emisor, f.rfc_receptor) == ("RFC_COM_01", "CAFETERÍA LUNA AZUL", EMPRESA)
        assert (f.total, f.total_mxn, f.uuid_relacionado) == (Decimal("116.00"), Decimal("116.00"), None)

    def test_usd_convierte_con_su_tipo_de_cambio(self, tmp_path: Path) -> None:
        xml = comprobante(moneda="USD", total="10.05", tipo_cambio="18.4567")
        (f,) = cargar_cfdis_xml(carpeta(tmp_path, a=xml), EMPRESA)
        assert (f.moneda, f.total, f.total_mxn) == ("USD", Decimal("10.05"), Decimal("185.49"))

    def test_nota_de_credito_relacionada_y_version_3(self, tmp_path: Path) -> None:
        xml = comprobante(uuid=UUID_2, tipo="E", relacionado=UUID_1, version="3")
        (f,) = cargar_cfdis_xml(carpeta(tmp_path, a=xml), EMPRESA)
        assert (f.tipo_comprobante, f.uuid_relacionado, f.valor_mxn) == ("E", UUID_1, Decimal("-116.00"))

    def test_emitido_por_la_empresa(self, tmp_path: Path) -> None:
        xml = comprobante(tipo="N", emisor=EMPRESA, receptor="RFC_EMPLEADO_01")
        (f,) = cargar_cfdis_xml(carpeta(tmp_path, a=xml), EMPRESA)
        assert f.direccion == "emitido"

    def test_orden_por_uuid(self, tmp_path: Path) -> None:
        cfdis = cargar_cfdis_xml(carpeta(tmp_path, z=comprobante(uuid=UUID_1), a=comprobante(uuid=UUID_2)), EMPRESA)
        assert [f.uuid for f in cfdis] == [UUID_1, UUID_2]

    def test_entidades_prohibidas(self, tmp_path: Path) -> None:
        bomba = ('<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]>'
                 "<r>&b;</r>")
        with pytest.raises(InsumoInvalido, match="bomba.xml"):
            cargar_cfdis_xml(carpeta(tmp_path, bomba=bomba), EMPRESA)

    def test_xml_mal_formado(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="roto.xml"):
            cargar_cfdis_xml(carpeta(tmp_path, roto="<cfdi:Comprobante"), EMPRESA)

    def test_raiz_que_no_es_comprobante(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="Comprobante"):
            cargar_cfdis_xml(carpeta(tmp_path, a="<otro/>"), EMPRESA)

    def test_sin_timbre(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="TimbreFiscalDigital"):
            cargar_cfdis_xml(carpeta(tmp_path, a=comprobante(uuid=None)), EMPRESA)

    def test_sin_total(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="Total"):
            cargar_cfdis_xml(carpeta(tmp_path, a=comprobante(total=None)), EMPRESA)

    def test_moneda_extranjera_sin_tipo_de_cambio(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="TipoCambio"):
            cargar_cfdis_xml(carpeta(tmp_path, a=comprobante(moneda="USD")), EMPRESA)

    def test_uuid_repetido(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match="duplicado"):
            cargar_cfdis_xml(carpeta(tmp_path, a=comprobante(), b=comprobante()), EMPRESA)

    def test_carpeta_vacia_o_inexistente(self, tmp_path: Path) -> None:
        with pytest.raises(InsumoInvalido, match=r"\.xml"):
            cargar_cfdis_xml(tmp_path, EMPRESA)
        with pytest.raises(InsumoInvalido, match="no es un directorio"):
            cargar_cfdis_xml(tmp_path / "falta", EMPRESA)

    def test_cli_con_xml(self, tmp_path: Path) -> None:
        xmls = tmp_path / "x"
        xmls.mkdir()
        carpeta(xmls, a=comprobante())
        salida = tmp_path / "s.json"
        universo = RAIZ / "examples" / "synthetic" / "universo_cargos_esperado.jsonl"
        argumentos = ["--universo", str(universo), "--cfdis-xml", str(xmls), "--salida", str(salida)]
        assert cruce_cfdi.main(argumentos) == 0
        assert salida.exists()
