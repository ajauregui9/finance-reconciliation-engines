"""Reglas deterministas, lectura del pool de CFDIs conocidos y cruce propuesta ↔ motor.

Los RFC de prueba son marcadores `RFC_*` o los genéricos del SAT: ningún valor con forma
de RFC real aparece en el repo.
"""
from __future__ import annotations

import dataclasses
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Tuple

import pytest

from extraccion_llm.config import Config, cargar_config, config_desde_dict, config_a_dict
from extraccion_llm.cruce import cruzar
from extraccion_llm.errores import InsumoInvalido
from extraccion_llm.modelo import Campos, Observacion, mismo_valor, monto_estricto
from extraccion_llm.pool import Pool, cargar_pool
from extraccion_llm.reglas import validar
from extraccion_llm.rutas import CONFIG_POR_DEFECTO, DATOS_POR_DEFECTO

POOL = DATOS_POR_DEFECTO / "cfdis_conocidos"
UUID_A = "00000000-0000-0000-0000-000000000007"
EMPRESA = "RFC_EMPRESA_DEMO"


@pytest.fixture(scope="module")
def config() -> Config:
    return cargar_config(CONFIG_POR_DEFECTO)


@pytest.fixture(scope="module")
def pool() -> Pool:
    return cargar_pool(POOL, EMPRESA)


def _campos(**cambios: object) -> Campos:
    base = Campos(rfc_emisor="RFC_PROV_LIMPIEZA", rfc_receptor=EMPRESA, uuid=UUID_A, fecha="2026-03-15",
                  subtotal="1000.00", iva="160.00", total="1160.00", moneda="MXN")
    return dataclasses.replace(base, **cambios)  # type: ignore[arg-type]


def _codigos(observaciones: Tuple[Observacion, ...]) -> Tuple[Tuple[str, object], ...]:
    return tuple((o.codigo, o.campo) for o in observaciones)


# ----------------------------------------------------------------- montos

@pytest.mark.parametrize("texto, esperado", [
    ("1160.00", Decimal("1160.00")), ("1160", Decimal("1160.00")), ("1160.5", Decimal("1160.50")),
    ("0", Decimal("0.00")), ("0.01", Decimal("0.01")),
])
def test_monto_estricto_acepta_digitos_con_hasta_dos_decimales(texto: str, esperado: Decimal) -> None:
    assert monto_estricto(texto) == esperado


@pytest.mark.parametrize("texto", ["1,160.00", "$1160.00", "-5.00", " 1160.00", "1160.001", "", "NaN", "1e3",
                                   "1160.", ".50", "١٢٣"])
def test_monto_estricto_rechaza_cualquier_otra_forma(texto: str) -> None:
    assert monto_estricto(texto) is None


def test_monto_estricto_de_none_es_none() -> None:
    assert monto_estricto(None) is None


def test_mismo_valor_compara_montos_como_decimal_y_lo_demas_como_texto() -> None:
    assert mismo_valor("total", "1160", "1160.00")
    assert not mismo_valor("total", "1,160.00", "1160.00")
    assert not mismo_valor("total", None, "1160.00")
    assert mismo_valor("iva", None, None)
    assert mismo_valor("fecha", "2026-03-15", "2026-03-15")
    assert not mismo_valor("rfc_emisor", "RFC_PROV_A ", "RFC_PROV_A")


# ----------------------------------------------------------------- reglas

def test_una_propuesta_correcta_no_tiene_observaciones(config: Config) -> None:
    assert validar(_campos(), config) == ()


def test_rfc_generico_del_sat_tiene_forma_valida(config: Config) -> None:
    assert validar(_campos(rfc_emisor="XAXX010101000"), config) == ()


@pytest.mark.parametrize("rfc", ["RFC_PROV-LIMPIEZA", "XAXX01010100", "xaxx010101000", "XAXX 010101000",
                                 "rfc_prov_limpieza", "RFC_", "RFC_AB"])
def test_rfc_mal_formado(config: Config, rfc: str) -> None:
    assert _codigos(validar(_campos(rfc_emisor=rfc), config)) == (("rfc_invalido", "rfc_emisor"),)


def test_sin_marcadores_un_rfc_sintetico_es_invalido(config: Config) -> None:
    estricta = dataclasses.replace(config, aceptar_rfc_marcador=False, rfc_empresa="XAXX010101000")
    observaciones = validar(_campos(rfc_receptor="XAXX010101000"), estricta)
    assert _codigos(observaciones) == (("rfc_invalido", "rfc_emisor"),)


def test_receptor_valido_pero_ajeno_a_la_empresa(config: Config) -> None:
    observaciones = validar(_campos(rfc_receptor="XAXX010101000"), config)
    assert _codigos(observaciones) == (("receptor_distinto_de_empresa", "rfc_receptor"),)


@pytest.mark.parametrize("uuid", ["00000000-0000-0000-0000-00000000007", "000000000000000000000000000000000007",
                                  "00000000-0000-0000-0000-00000000000G", "{00000000-0000-0000-0000-000000000007}"])
def test_uuid_mal_formado(config: Config, uuid: str) -> None:
    assert _codigos(validar(_campos(uuid=uuid), config)) == (("uuid_invalido", "uuid"),)


@pytest.mark.parametrize("fecha", ["15/03/2026", "2026-02-30", "2026-03-15T10:00:00", "20260315", "2026-3-15"])
def test_fecha_que_no_es_iso_valida(config: Config, fecha: str) -> None:
    assert _codigos(validar(_campos(fecha=fecha), config)) == (("fecha_invalida", "fecha"),)


def test_monto_con_coma_de_miles_es_invalido_y_no_se_cuadra(config: Config) -> None:
    observaciones = validar(_campos(subtotal="1,000.00", total="1,160.00"), config)
    assert _codigos(observaciones) == (("monto_invalido", "subtotal"), ("monto_invalido", "total"))


def test_subtotal_mas_iva_debe_dar_el_total_al_centavo(config: Config) -> None:
    (observacion,) = validar(_campos(total="1160.01"), config)
    assert (observacion.codigo, observacion.campo) == ("no_cuadra", "total")
    assert "1160.00" in observacion.detalle and "1160.01" in observacion.detalle


def test_cuadre_con_montos_sin_decimales(config: Config) -> None:
    assert validar(_campos(subtotal="1000", iva="160", total="1160.00"), config) == ()


def test_campo_ausente_no_dispara_el_cuadre(config: Config) -> None:
    assert _codigos(validar(_campos(iva=None), config)) == (("campo_ausente", "iva"),)


def test_todos_los_campos_ausentes(config: Config) -> None:
    vacia = Campos(None, None, None, None, None, None, None, None)
    observaciones = validar(vacia, config)
    assert [o.codigo for o in observaciones] == ["campo_ausente"] * 8


@pytest.mark.parametrize("moneda", ["EUR", "usd", "PESOS"])
def test_moneda_fuera_de_la_lista(config: Config, moneda: str) -> None:
    assert _codigos(validar(_campos(moneda=moneda), config)) == (("moneda_no_permitida", "moneda"),)


def test_usd_esta_permitido_en_la_config_de_ejemplo(config: Config) -> None:
    assert validar(_campos(moneda="USD"), config) == ()


# ----------------------------------------------------------------- pool

def test_el_pool_sintetico_se_lee_completo(pool: Pool) -> None:
    assert len(pool.cfdis) == 39
    assert len(pool.sha256) == 64
    cfdi = pool.cfdis[UUID_A]
    assert cfdi.rfc_receptor == EMPRESA and cfdi.uuid == UUID_A
    assert monto_estricto(cfdi.total) is not None


def test_el_lector_del_motor_trae_subtotal_e_iva(pool: Pool) -> None:
    assert all(monto_estricto(c.subtotal) is not None and monto_estricto(c.iva) is not None
               for c in pool.cfdis.values())


def test_pool_en_dolares_conserva_el_total_en_su_moneda(pool: Pool) -> None:
    dolares = [c for c in pool.cfdis.values() if c.moneda == "USD"]
    assert dolares and all(monto_estricto(c.total) is not None for c in dolares)


def _copia_pool(destino: Path, cuantos: int = 2) -> Path:
    destino.mkdir()
    for ruta in sorted(POOL.glob("*.xml"))[:cuantos]:
        shutil.copy(ruta, destino / ruta.name)
    return destino


def test_pool_inexistente_es_insumo_invalido(tmp_path: Path) -> None:
    with pytest.raises(InsumoInvalido, match="no es un directorio"):
        cargar_pool(tmp_path / "nada", EMPRESA)


def test_pool_con_xml_roto_es_insumo_invalido(tmp_path: Path) -> None:
    carpeta = _copia_pool(tmp_path / "pool")
    (carpeta / "roto.xml").write_text("<cfdi:Comprobante", encoding="utf-8")
    with pytest.raises(InsumoInvalido, match="roto.xml"):
        cargar_pool(carpeta, EMPRESA)


def test_pool_con_dtd_se_rechaza(tmp_path: Path) -> None:
    carpeta = _copia_pool(tmp_path / "pool", 1)
    original = next(carpeta.glob("*.xml"))
    texto = original.read_text(encoding="utf-8").replace("?>", '?>\n<!DOCTYPE x [<!ENTITY e "x">]>', 1)
    original.write_text(texto, encoding="utf-8")
    with pytest.raises(InsumoInvalido, match="rechazado"):
        cargar_pool(carpeta, EMPRESA)


def test_pool_sin_defusedxml_falla_con_mensaje_claro(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    real = importlib.import_module

    def sin_defused(nombre: str, *args: object) -> object:
        if nombre.startswith("defusedxml"):
            raise ImportError(nombre)
        return real(nombre)

    monkeypatch.setattr(importlib, "import_module", sin_defused)
    with pytest.raises(InsumoInvalido, match="defusedxml"):
        cargar_pool(_copia_pool(tmp_path / "pool", 1), EMPRESA)


# ----------------------------------------------------------------- cruce

def _del_pool(pool: Pool) -> Campos:
    return pool.cfdis[UUID_A]


def test_propuesta_igual_al_motor_no_tiene_observaciones(pool: Pool) -> None:
    assert cruzar(_del_pool(pool), pool) == ()


def test_uuid_fuera_del_pool_queda_sin_respaldo(pool: Pool) -> None:
    propuesta = dataclasses.replace(_del_pool(pool), uuid="00000000-0000-0000-0000-000000000000")
    assert _codigos(cruzar(propuesta, pool)) == (("sin_respaldo_en_pool", "uuid"),)


@pytest.mark.parametrize("uuid", [None, "no-es-uuid"])
def test_uuid_ausente_o_invalido_queda_sin_respaldo(pool: Pool, uuid: object) -> None:
    propuesta = dataclasses.replace(_del_pool(pool), uuid=uuid)  # type: ignore[arg-type]
    assert _codigos(cruzar(propuesta, pool)) == (("sin_respaldo_en_pool", "uuid"),)


def test_cada_diferencia_con_el_motor_es_una_discrepancia(pool: Pool) -> None:
    motor = _del_pool(pool)
    propuesta = dataclasses.replace(motor, total="1.00", rfc_emisor="RFC_PROV_FANTASMA", fecha=None)
    observaciones = cruzar(propuesta, pool)
    assert _codigos(observaciones) == (("discrepancia_motor", "rfc_emisor"), ("discrepancia_motor", "fecha"),
                                       ("discrepancia_motor", "total"))
    total = observaciones[-1]
    assert (total.propuesta, total.motor) == ("1.00", motor.total)
    assert observaciones[1].propuesta is None


def test_subtotal_e_iva_tambien_se_cruzan_con_el_motor(pool: Pool) -> None:
    propuesta = dataclasses.replace(_del_pool(pool), subtotal="1.00", iva="999.00")
    assert _codigos(cruzar(propuesta, pool)) == (("discrepancia_motor", "subtotal"), ("discrepancia_motor", "iva"))


def test_cruce_compara_montos_como_decimal(pool: Pool) -> None:
    motor = _del_pool(pool)
    sin_ceros = str(Decimal(str(motor.total)).normalize())
    assert cruzar(dataclasses.replace(motor, total=sin_ceros), pool) == ()


# ----------------------------------------------------------------- config

def test_config_de_ejemplo(config: Config) -> None:
    assert config.modelo == "claude-opus-5-5"
    assert config.monedas_permitidas == ("MXN", "USD")
    assert config.precios.entrada_por_millon == Decimal("5.00")
    assert config_desde_dict(config_a_dict(config)) == config
