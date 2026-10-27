"""Pruebas del CSV de carga con validación previa y de las propuestas."""
from __future__ import annotations

import csv
import dataclasses
import hashlib
import io
import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "netsuite-gl-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from netsuite_gl.carga_csv import CargaRechazada, generar_csv  # noqa: E402
from netsuite_gl.carga_modelo import (  # noqa: E402
    AsientoCarga,
    ErrorEntrada,
    LineaCarga,
    asientos_desde_json,
)
from netsuite_gl.carga_validacion import (  # noqa: E402
    FORMATO_JOURNAL,
    FORMATO_VENDOR_BILL,
    ErrorCarga,
    leer_catalogo,
    validar_asientos,
)
from netsuite_gl.config import CONFIG_DEFAULT  # noqa: E402
from netsuite_gl.poblado import construir_base  # noqa: E402
from netsuite_gl.propuestas import (  # noqa: E402
    MOTIVO_NOTA_CREDITO,
    MOTIVO_SIN_PROVEEDOR,
    proponer_facturas_sin_registro,
)
from netsuite_gl.salida import manifiesto_a_json  # noqa: E402

CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"
EJEMPLO_JOURNAL = SKILL / "ejemplos" / "asientos_journal.json"
CUENTAS = {c.numero: c for c in CONFIG_DEFAULT.cuentas}
AP = CONFIG_DEFAULT.cuenta_proveedores
IVA = CONFIG_DEFAULT.cuenta_iva
HOSPEDAJE = "6100-020"
ALIMENTOS = "6100-010"
INACTIVA = next(c.numero for c in CONFIG_DEFAULT.cuentas if c.inactiva)
CLASE_INACTIVA = next(c.nombre for c in CONFIG_DEFAULT.clases if c.inactiva)


def _cuenta(numero: str) -> str:
    return f"{numero} {CUENTAS[numero].nombre}"


def _par(debito: LineaCarga, credito: str = "1.00") -> Tuple[LineaCarga, LineaCarga]:
    """Una línea bajo prueba más su contrapartida válida en alimentos."""
    return (debito, _linea(ALIMENTOS, credito=credito))


def _linea(cuenta: str, debito: str = "0", credito: str = "0", **otros: Any) -> LineaCarga:
    return LineaCarga(
        cuenta=cuenta,
        debito=Decimal(debito),
        credito=Decimal(credito),
        clase=otros.get("clase", "COMERCIAL"),
        entidad=otros.get("entidad"),
        memo=otros.get("memo", ""),
    )


def _journal(id_externo: str = "AJ-0001", **cambios: Any) -> AsientoCarga:
    base = AsientoCarga(
        id_externo=id_externo,
        fecha=date(2026, 7, 31),
        periodo="Jul 2026",
        memo="Reclasificación de gasto",
        referencia=None,
        lineas=(
            _linea(HOSPEDAJE, debito="100.00", memo="a hospedaje"),
            _linea(ALIMENTOS, credito="100.00", memo="desde alimentos"),
        ),
    )
    return dataclasses.replace(base, **cambios)


def _factura(id_externo: str = "VB-0001", **cambios: Any) -> AsientoCarga:
    base = AsientoCarga(
        id_externo=id_externo,
        fecha=date(2026, 7, 10),
        periodo="Jul 2026",
        memo="Hospedaje",
        referencia="TST-10",
        lineas=(
            _linea(HOSPEDAJE, debito="100.00", memo="hospedaje"),
            _linea(IVA, debito="16.00", memo="IVA"),
            _linea(AP, credito="116.00", entidad="PROV-0001", memo="proveedor"),
        ),
    )
    return dataclasses.replace(base, **cambios)


@pytest.fixture(scope="module")
def base() -> Any:
    return construir_base(CFDIS)


@pytest.fixture(scope="module")
def catalogo(base: Any) -> Any:
    return leer_catalogo(base.conexion)


def _reglas(errores: Any) -> List[str]:
    return [e.regla for e in errores]


# ---------------------------------------------------------------- CSV válidos


def test_journal_valido_genera_csv_exacto(catalogo: Any) -> None:
    texto = generar_csv((_journal(),), catalogo, FORMATO_JOURNAL)
    esperado = (
        "External ID,Date,Posting Period,Memo,Account,Debit,Credit,Class,Name,Line Memo\n"
        f"AJ-0001,31/07/2026,Jul 2026,Reclasificación de gasto,{_cuenta(HOSPEDAJE)},100.00,,"
        "COMERCIAL,,a hospedaje\n"
        f"AJ-0001,31/07/2026,Jul 2026,Reclasificación de gasto,{_cuenta(ALIMENTOS)},,100.00,"
        "COMERCIAL,,desde alimentos\n"
    )
    assert texto == esperado


def test_vendor_bill_valido_deja_proveedores_implicito(catalogo: Any) -> None:
    texto = generar_csv((_factura(),), catalogo, FORMATO_VENDOR_BILL)
    esperado = (
        "External ID,Vendor,Date,Posting Period,Reference No.,Memo,Account,Amount,Class,Line Memo\n"
        f"VB-0001,PROV-0001,10/07/2026,Jul 2026,TST-10,Hospedaje,{_cuenta(HOSPEDAJE)},100.00,COMERCIAL,hospedaje\n"
        f"VB-0001,PROV-0001,10/07/2026,Jul 2026,TST-10,Hospedaje,{_cuenta(IVA)},16.00,COMERCIAL,IVA\n"
    )
    assert texto == esperado


def test_csv_escapa_comas_y_comillas(catalogo: Any) -> None:
    memo = 'Ajuste "especial", julio'
    texto = generar_csv((_journal(memo=memo),), catalogo, FORMATO_JOURNAL)
    filas = list(csv.reader(io.StringIO(texto)))
    assert filas[1][3] == memo
    assert "\r" not in texto


def test_csv_es_determinista(catalogo: Any) -> None:
    asientos = (_journal(), _journal("AJ-0002"))
    uno = hashlib.sha256(generar_csv(asientos, catalogo, FORMATO_JOURNAL).encode()).hexdigest()
    dos = hashlib.sha256(generar_csv(asientos, catalogo, FORMATO_JOURNAL).encode()).hexdigest()
    assert uno == dos


def test_journal_con_proveedores_y_entidad_es_valido(catalogo: Any) -> None:
    asiento = _journal(
        lineas=(
            _linea(AP, debito="50.00", entidad="PROV-0001", clase=None),
            _linea(HOSPEDAJE, credito="50.00", clase=None),
        )
    )
    assert validar_asientos((asiento,), catalogo, FORMATO_JOURNAL) == ()


# ---------------------------------------------------------------- reglas de validación


@pytest.mark.parametrize(
    "asiento, regla",
    [
        (_journal(lineas=(_linea(HOSPEDAJE, debito="1.00"),)), "lineas_insuficientes"),
        (_journal(lineas=(_linea(HOSPEDAJE, debito="-1.00"), _linea(ALIMENTOS, credito="-1.00"))), "importe_invalido"),
        (_journal(lineas=(_linea(HOSPEDAJE, debito="1.00", credito="1.00"), _linea(ALIMENTOS))), "importe_invalido"),
        (_journal(lineas=(_linea(HOSPEDAJE, debito="1.005"), _linea(ALIMENTOS, credito="1.005"))), "importe_invalido"),
        (_journal(lineas=_par(_linea(HOSPEDAJE, debito="100.00"), credito="99.99")), "asiento_descuadrado"),
        (_journal(lineas=_par(_linea("9999-999", debito="1.00"))), "cuenta_inexistente"),
        (_journal(lineas=_par(_linea(INACTIVA, debito="1.00"))), "cuenta_inactiva"),
        (_journal(periodo="Dec 2030"), "periodo_inexistente"),
        (_journal(periodo="Q3 2026"), "periodo_no_registro"),
        (_journal(periodo="May 2026", fecha=date(2026, 5, 31)), "periodo_cerrado"),
        (_journal(fecha=date(2026, 8, 1)), "fecha_fuera_de_periodo"),
        (_journal(lineas=_par(_linea(HOSPEDAJE, debito="1.00", clase="NO EXISTE"))), "clase_inexistente"),
        (_journal(lineas=_par(_linea(HOSPEDAJE, debito="1.00", clase=CLASE_INACTIVA))), "clase_inexistente"),
        (_journal(lineas=_par(_linea(AP, debito="1.00", entidad="PROV-9999"))), "proveedor_inexistente"),
        (_journal(lineas=_par(_linea(AP, debito="1.00"))), "proveedor_requerido"),
        (_journal(memo="=HYPERLINK(1)"), "texto_formula"),
        (_journal(lineas=_par(_linea(HOSPEDAJE, debito="1.00", memo="+1"))), "texto_formula"),
    ],
)
def test_regla_de_journal_rechaza(catalogo: Any, asiento: AsientoCarga, regla: str) -> None:
    errores = validar_asientos((asiento,), catalogo, FORMATO_JOURNAL)
    assert regla in _reglas(errores)


@pytest.mark.parametrize(
    "asiento, regla",
    [
        (_factura(referencia=None), "referencia_requerida"),
        (_factura(referencia="@cmd"), "texto_formula"),
        (_factura(lineas=_par(_linea(HOSPEDAJE, debito="1.00"))), "factura_sin_proveedores"),
        (
            _factura(
                lineas=(
                    _linea(HOSPEDAJE, debito="2.00"),
                    _linea(AP, credito="1.00", entidad="PROV-0001"),
                    _linea(AP, credito="1.00", entidad="PROV-0001"),
                )
            ),
            "factura_sin_proveedores",
        ),
        (
            _factura(
                lineas=(
                    _linea(HOSPEDAJE, debito="3.00"),
                    _linea(ALIMENTOS, credito="1.00"),
                    _linea(AP, credito="2.00", entidad="PROV-0001"),
                )
            ),
            "factura_linea_credito",
        ),
    ],
)
def test_regla_de_vendor_bill_rechaza(catalogo: Any, asiento: AsientoCarga, regla: str) -> None:
    errores = validar_asientos((asiento,), catalogo, FORMATO_VENDOR_BILL)
    assert regla in _reglas(errores)


def test_archivo_vacio_e_ids_duplicados(catalogo: Any) -> None:
    assert _reglas(validar_asientos((), catalogo, FORMATO_JOURNAL)) == ["archivo_vacio"]
    errores = validar_asientos((_journal(), _journal()), catalogo, FORMATO_JOURNAL)
    assert _reglas(errores) == ["id_externo_duplicado"]


def test_formato_desconocido_falla(catalogo: Any) -> None:
    with pytest.raises(ErrorEntrada, match="formato"):
        validar_asientos((_journal(),), catalogo, "excel")


def test_un_error_rechaza_el_archivo_completo_y_lista_todos(catalogo: Any) -> None:
    malo = _journal(
        "AJ-0002",
        periodo="May 2026",
        fecha=date(2026, 5, 31),
        lineas=(_linea("9999-999", debito="10.00"), _linea(ALIMENTOS, credito="9.00")),
    )
    with pytest.raises(CargaRechazada) as rechazo:
        generar_csv((_journal(), malo), catalogo, FORMATO_JOURNAL)
    errores = rechazo.value.errores
    assert _reglas(errores) == ["asiento_descuadrado", "periodo_cerrado", "cuenta_inexistente"]
    assert all(e.id_externo == "AJ-0002" for e in errores)
    assert errores[2] == ErrorCarga("AJ-0002", 1, "cuenta_inexistente", errores[2].mensaje)
    assert "3 errores" in str(rechazo.value)
    assert list(errores) == sorted(errores, key=lambda e: (e.id_externo, e.linea or 0, e.regla))


# ---------------------------------------------------------------- entrada JSON


def _linea_json(**cambios: Any) -> Dict[str, Any]:
    linea: Dict[str, Any] = {
        "cuenta": HOSPEDAJE, "debito": "1.00", "credito": "0.00", "clase": None, "entidad": None, "memo": "",
    }
    linea.update(cambios)
    return linea


def _json_asiento(**cambios: Any) -> Dict[str, Any]:
    asiento: Dict[str, Any] = {
        "id_externo": "AJ-0001",
        "fecha": "2026-07-31",
        "periodo": "Jul 2026",
        "memo": "Reclasificación",
        "referencia": None,
        "lineas": [
            _linea_json(debito="100.00", clase="COMERCIAL", memo="x"),
            _linea_json(cuenta=ALIMENTOS, debito="0.00", credito="100.00", clase="COMERCIAL", memo="y"),
        ],
    }
    asiento.update(cambios)
    return asiento


def test_json_valido_se_convierte_en_asientos() -> None:
    (asiento,) = asientos_desde_json(json.dumps({"asientos": [_json_asiento()]}))
    assert asiento == _journal(
        memo="Reclasificación",
        lineas=(_linea(HOSPEDAJE, debito="100.00", memo="x"), _linea(ALIMENTOS, credito="100.00", memo="y")),
    )


@pytest.mark.parametrize(
    "documento, fragmento",
    [
        ("{no es json", "JSON"),
        ("[]", "objeto"),
        ('{"otra": []}', "asientos"),
        ('{"asientos": {}}', "lista"),
        (json.dumps({"asientos": [_json_asiento(fecha="31/07/2026")]}), "fecha"),
        (json.dumps({"asientos": [_json_asiento(fecha="2026-W31-5")]}), "fecha"),
        (json.dumps({"asientos": [_json_asiento(id_externo="")]}), "id_externo"),
        (json.dumps({"asientos": [_json_asiento(referencia=5)]}), "referencia"),
        (json.dumps({"asientos": [_json_asiento(extra=1)]}), "extra"),
        (json.dumps({"asientos": [_json_asiento(lineas=[_linea_json(debito=1.0)])]}), "debito"),
        (json.dumps({"asientos": [_json_asiento(lineas=[_linea_json(credito="abc")])]}), "credito"),
        (json.dumps({"asientos": [_json_asiento(lineas=[_linea_json(clase=3)])]}), "clase"),
        (json.dumps({"asientos": [_json_asiento(lineas="x")]}), "lineas"),
        (json.dumps({"asientos": [_json_asiento(lineas=[{"cuenta": HOSPEDAJE}])]}), "debito"),
        (json.dumps({"asientos": ["x"]}), "objeto"),
    ],
)
def test_json_invalido_falla_con_mensaje_claro(documento: str, fragmento: str) -> None:
    with pytest.raises(ErrorEntrada, match=fragmento):
        asientos_desde_json(documento)


def test_ejemplo_versionado_de_journal_es_valido(catalogo: Any) -> None:
    asientos = asientos_desde_json(EJEMPLO_JOURNAL.read_text(encoding="utf-8"))
    assert len(asientos) >= 2
    assert validar_asientos(asientos, catalogo, FORMATO_JOURNAL) == ()


# ---------------------------------------------------------------- propuestas


def test_propuestas_cubren_cada_cfdi_sin_registro(base: Any) -> None:
    manifiesto = json.loads(manifiesto_a_json(base.manifiesto))
    sin_registro = [p["uuid"] for p in manifiesto["discrepancias"]["sin_registro"]]
    tipos = {
        u: base.conexion.execute(
            "SELECT custrecord_cfdi_tipo FROM customrecord_cfdi_recibido WHERE custrecord_cfdi_uuid = ?", (u,)
        ).fetchone()[0]
        for u in sin_registro
    }
    propuesta = proponer_facturas_sin_registro(base.conexion, CONFIG_DEFAULT)
    assert [a.id_externo for a in propuesta.asientos] == [f"CFDI-{u}" for u in sin_registro if tipos[u] == "I"]
    assert [(p.uuid, p.motivo) for p in propuesta.pendientes] == [
        (u, MOTIVO_NOTA_CREDITO) for u in sin_registro if tipos[u] == "E"
    ]
    catalogo = leer_catalogo(base.conexion)
    assert validar_asientos(propuesta.asientos, catalogo, FORMATO_VENDOR_BILL) == ()
    for asiento in propuesta.asientos:
        proveedores = [linea for linea in asiento.lineas if linea.cuenta == AP]
        assert len(proveedores) == 1 and proveedores[0].entidad
        assert sum(linea.debito for linea in asiento.lineas) == proveedores[0].credito


def test_propuesta_en_periodo_cerrado_rechaza_todo_el_archivo() -> None:
    base = construir_base(CFDIS)
    propuesta = proponer_facturas_sin_registro(base.conexion, CONFIG_DEFAULT)
    assert propuesta.asientos
    periodo = propuesta.asientos[0].periodo
    base.conexion.execute("UPDATE accountingperiod SET closed = 'T' WHERE periodname = ?", (periodo,))
    with pytest.raises(CargaRechazada) as rechazo:
        generar_csv(propuesta.asientos, leer_catalogo(base.conexion), FORMATO_VENDOR_BILL)
    afectados = sorted(a.id_externo for a in propuesta.asientos if a.periodo == periodo)
    assert sorted(e.id_externo for e in rechazo.value.errores) == afectados
    assert set(_reglas(rechazo.value.errores)) == {"periodo_cerrado"}


def test_propuesta_sin_periodo_queda_rechazada() -> None:
    base = construir_base(CFDIS)
    uuid = base.manifiesto.sin_registro[0]
    base.conexion.execute(
        "UPDATE customrecord_cfdi_recibido SET custrecord_cfdi_fecha = '2031-01-15', custrecord_cfdi_tipo = 'I' "
        "WHERE custrecord_cfdi_uuid = ?",
        (uuid,),
    )
    propuesta = proponer_facturas_sin_registro(base.conexion, CONFIG_DEFAULT)
    asiento = next(a for a in propuesta.asientos if a.id_externo == f"CFDI-{uuid}")
    assert asiento.periodo == ""
    errores = validar_asientos((asiento,), leer_catalogo(base.conexion), FORMATO_VENDOR_BILL)
    assert "periodo_inexistente" in _reglas(errores)


def test_nota_de_credito_y_proveedor_faltante_quedan_pendientes() -> None:
    base = construir_base(CFDIS)
    nota, sin_proveedor = base.manifiesto.sin_registro[:2]
    base.conexion.execute(
        "UPDATE customrecord_cfdi_recibido SET custrecord_cfdi_tipo = 'E' WHERE custrecord_cfdi_uuid = ?", (nota,)
    )
    base.conexion.execute(
        "UPDATE customrecord_cfdi_recibido SET custrecord_cfdi_nombre_emisor = 'EMISOR SIN ALTA' "
        "WHERE custrecord_cfdi_uuid = ?",
        (sin_proveedor,),
    )
    propuesta = proponer_facturas_sin_registro(base.conexion, CONFIG_DEFAULT)
    assert sorted((p.uuid, p.motivo) for p in propuesta.pendientes) == sorted(
        [(nota, MOTIVO_NOTA_CREDITO), (sin_proveedor, MOTIVO_SIN_PROVEEDOR)]
    )
    propuestos = {a.id_externo for a in propuesta.asientos}
    assert f"CFDI-{nota}" not in propuestos and f"CFDI-{sin_proveedor}" not in propuestos
    assert len(propuesta.asientos) == len(base.manifiesto.sin_registro) - 2
