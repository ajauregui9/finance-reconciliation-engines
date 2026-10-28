"""Pruebas de la frontera de entrada del cruce con libro mayor."""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAIZ_SKILL = ROOT / "skills" / "credit-card-reconciliation"
if str(RAIZ_SKILL) not in sys.path:
    sys.path.insert(0, str(RAIZ_SKILL))

from conciliacion import cruce_libro_config as cfg  # noqa: E402
from conciliacion import cruce_libro_insumos as ins  # noqa: E402
from conciliacion.cruce_libro_insumos import ErrorInsumo  # noqa: E402
from conciliacion.cruce_libro_modelo import ConfigCruceLibro, VentanaDias  # noqa: E402

SINTETICO = ROOT / "examples" / "synthetic"
EJEMPLO_CONFIG = RAIZ_SKILL / "config" / "cruce_libro.example.json"
ENCABEZADO_LIBRO = ("asiento_id,linea,fecha,periodo,origen,cuenta,nombre_cuenta,proveedor_id,"
                    "proveedor_nombre,proveedor_rfc,referencia,memo,debe,haber,moneda")


def _cargo(**cambios: object) -> Dict[str, object]:
    base: Dict[str, object] = {"cargo_id": "ALFA-0001", "emisor": "ALFA", "estado": "ok", "fecha": "2026-07-01",
                               "descripcion": "CAFE LUNA", "monto": "10.00", "tipo_movimiento": "cargo"}
    return {**base, **cambios}


def _jsonl(tmp_path: Path, filas: List[Dict[str, object]]) -> Path:
    ruta = tmp_path / "universo.jsonl"
    ruta.write_text("".join(json.dumps(f) + "\n" for f in filas), encoding="utf-8")
    return ruta


def _libro(tmp_path: Path, filas: List[str], encabezado: str = ENCABEZADO_LIBRO) -> Path:
    ruta = tmp_path / "libro.csv"
    ruta.write_text("\n".join([encabezado] + filas) + "\n", encoding="utf-8")
    return ruta


def _fila_libro(asiento: str = "AS-1", linea: str = "1", fecha: str = "2026-07-02", debe: str = "0.00",
                haber: str = "10.00", moneda: str = "MXN") -> str:
    return (f"{asiento},{linea},{fecha},2026-07,TARJETA,2105-001,TARJETA,PRV-1,CAFETERIA LUNA,RFC_X,"
            f"EDC,MEMO,{debe},{haber},{moneda}")


def _veredictos(tmp_path: Path, filas: List[str], encabezado: str = "cargo_id,veredicto,asiento_id,nota") -> Path:
    ruta = tmp_path / "veredictos.csv"
    ruta.write_text("\n".join([encabezado] + filas) + "\n", encoding="utf-8")
    return ruta


# ------------------------------------------------------------------- montos
class TestFronteraDeMontos:
    @pytest.mark.parametrize("valor, esperado", [
        ("10.00", "10.00"), ("-1234.5", "-1234.50"), ("7", "7.00"), (" 3.10 ", "3.10"),
    ])
    def test_convierte_texto_a_decimal_con_centavos_sin_redondear(self, valor: object, esperado: str) -> None:
        resultado = ins.a_monto(valor, "prueba")
        assert isinstance(resultado, Decimal)
        assert str(resultado) == esperado

    @pytest.mark.parametrize("valor", [True, None, "abc", "1,234.56", "", float("nan"), float("inf"), "1e3", [],
                                       7, 10.005, Decimal("2.345"), "10.005"])
    def test_rechaza_lo_que_no_es_un_monto(self, valor: object) -> None:
        with pytest.raises(ErrorInsumo, match="prueba"):
            ins.a_monto(valor, "prueba")


# -------------------------------------------------------------------- config
class TestConfig:
    def test_sin_archivo_usa_los_valores_por_omision(self) -> None:
        assert cfg.cargar_config(None) == ConfigCruceLibro()

    def test_el_ejemplo_versionado_es_igual_a_los_valores_por_omision(self) -> None:
        assert cfg.cargar_config(EJEMPLO_CONFIG) == ConfigCruceLibro()
        assert cfg.config_a_dict(ConfigCruceLibro()) == json.loads(EJEMPLO_CONFIG.read_text(encoding="utf-8"))

    def test_config_parcial_completa_con_valores_por_omision(self, tmp_path: Path) -> None:
        ruta = tmp_path / "c.json"
        ruta.write_text(json.dumps({"esquema": "cruce_libro_config/v1", "tolerancia_monto": "0.50",
                                    "ventana_cubeta_dias": {"min": -1, "max": 2}}), encoding="utf-8")
        leida = cfg.cargar_config(ruta)
        assert leida.tolerancia_monto == Decimal("0.50")
        assert leida.ventana_cubeta == VentanaDias(-1, 2)
        assert leida.umbral_similitud == ConfigCruceLibro().umbral_similitud

    @pytest.mark.parametrize("cambios, mensaje", [
        ({"tolerancia": "1.00"}, "tolerancia"),
        ({"tolerancia_monto": 1.5}, "tolerancia_monto"),
        ({"umbral_similitud": "1.50"}, "umbral"),
        ({"max_candidatos_reporte": True}, "max_candidatos_reporte"),
        ({"ventana_cubeta_dias": {"min": 0, "max": 45}}, "cubeta"),
        ({"ventana_busqueda_dias": {"min": 5}}, "ventana_busqueda_dias"),
        ({"cuentas_tarjeta": {"ALFA": 2105}}, "cuentas_tarjeta"),
        ({"proveedores_cubeta": "PRV-0999"}, "proveedores_cubeta"),
        ({"nombres": {"largo_raiz": 4}}, "largo_raiz"),
        ({"esquema": "otro/v9"}, "esquema"),
        ({"cuentas_tarjeta": []}, "cuentas_tarjeta"),
        ({"nombres": ["largo_min_raiz"]}, "nombres"),
        ({"nombres": {"largo_min_raiz": "4"}}, "largo_min_raiz"),
        ({"tolerancia_monto": "-1.00"}, "negativa"),
        ({"max_candidatos_reporte": -1}, "max_candidatos_reporte"),
    ])
    def test_rechaza_config_invalida_con_mensaje_claro(self, tmp_path: Path, cambios: dict, mensaje: str) -> None:
        ruta = tmp_path / "c.json"
        ruta.write_text(json.dumps({"esquema": "cruce_libro_config/v1", **cambios}), encoding="utf-8")
        with pytest.raises(ErrorInsumo, match=mensaje):
            cfg.cargar_config(ruta)

    def test_json_roto_o_ausente_es_error_de_insumo(self, tmp_path: Path) -> None:
        roto = tmp_path / "roto.json"
        roto.write_text("{", encoding="utf-8")
        with pytest.raises(ErrorInsumo):
            cfg.cargar_config(roto)
        with pytest.raises(ErrorInsumo):
            cfg.cargar_config(tmp_path / "no_existe.json")
        lista = tmp_path / "lista.json"
        lista.write_text("[]", encoding="utf-8")
        with pytest.raises(ErrorInsumo, match="objeto"):
            cfg.cargar_config(lista)


# ------------------------------------------------------------------ universo
class TestUniverso:
    def test_lee_el_universo_sintetico_completo(self) -> None:
        cargos = ins.leer_universo(SINTETICO / "universo_cargos_esperado.jsonl")
        assert len(cargos) == 199
        assert all(isinstance(c.monto, Decimal) for c in cargos)
        assert {c.cargo_id for c in cargos if c.fecha is None} == {
            c.cargo_id for c in cargos if c.estado != "ok"}

    def test_lineas_en_blanco_no_son_filas(self, tmp_path: Path) -> None:
        ruta = tmp_path / "u.jsonl"
        ruta.write_text(json.dumps(_cargo()) + "\n\n   \n", encoding="utf-8")
        assert len(ins.leer_universo(ruta)) == 1

    def test_fila_ininterpretable_conserva_su_estado_sin_fecha(self, tmp_path: Path) -> None:
        (cargo,) = ins.leer_universo(_jsonl(tmp_path, [_cargo(estado="ininterpretable", fecha=None)]))
        assert (cargo.estado, cargo.fecha) == ("ininterpretable", None)

    def test_monto_numerico_se_rechaza(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="campo monto"):
            ins.leer_universo(_jsonl(tmp_path, [_cargo(monto=10.005)]))

    @pytest.mark.parametrize("fila, mensaje", [
        ({"cargo_id": "X"}, "emisor"),
        (_cargo(monto=True), "monto"),
        (_cargo(fecha=None), "fecha"),
        (_cargo(fecha="31/07/2026"), "fecha"),
        (_cargo(tipo_movimiento="retiro"), "tipo_movimiento"),
        (_cargo(cargo_id=""), "cargo_id"),
        (_cargo(descripcion=None), "descripcion"),
    ])
    def test_fila_invalida_detiene_con_linea_y_campo(self, tmp_path: Path, fila: dict, mensaje: str) -> None:
        with pytest.raises(ErrorInsumo, match=mensaje) as error:
            ins.leer_universo(_jsonl(tmp_path, [_cargo(cargo_id="OK-1"), fila]))
        assert "línea 2" in str(error.value)

    def test_cargo_id_repetido_es_error(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="repetido"):
            ins.leer_universo(_jsonl(tmp_path, [_cargo(), _cargo()]))

    def test_linea_que_no_es_objeto_json_es_error(self, tmp_path: Path) -> None:
        ruta = tmp_path / "u.jsonl"
        ruta.write_text("[1, 2]\n", encoding="utf-8")
        with pytest.raises(ErrorInsumo, match="objeto"):
            ins.leer_universo(ruta)
        ruta.write_text("{roto\n", encoding="utf-8")
        with pytest.raises(ErrorInsumo, match="JSON"):
            ins.leer_universo(ruta)

    def test_archivo_inexistente_o_binario_es_error(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo):
            ins.leer_universo(tmp_path / "nada.jsonl")
        binario = tmp_path / "b.jsonl"
        binario.write_bytes(b"\xff\xfe\x00")
        with pytest.raises(ErrorInsumo):
            ins.leer_universo(binario)


# --------------------------------------------------------------------- libro
class TestLibro:
    def test_lee_el_libro_sintetico(self) -> None:
        lineas = ins.leer_libro(SINTETICO / "libro_mayor.csv", "MXN")
        filas = (SINTETICO / "libro_mayor.csv").read_text(encoding="utf-8").splitlines()
        assert len(lineas) == len(filas) - 1
        assert all(isinstance(x.debe, Decimal) and isinstance(x.haber, Decimal) for x in lineas)

    def test_libro_solo_con_encabezado_es_valido(self, tmp_path: Path) -> None:
        assert ins.leer_libro(_libro(tmp_path, []), "MXN") == ()

    @pytest.mark.parametrize("fila, mensaje", [
        (_fila_libro(haber='"1,000.00"'), "haber"),
        (_fila_libro(debe="-5.00"), "debe"),
        (_fila_libro(fecha="2026-13-01"), "fecha"),
        (_fila_libro(linea="uno"), "linea"),
        (_fila_libro(moneda="USD"), "moneda"),
        (_fila_libro(asiento=""), "asiento_id"),
    ])
    def test_fila_invalida_detiene_con_fila_y_campo(self, tmp_path: Path, fila: str, mensaje: str) -> None:
        with pytest.raises(ErrorInsumo, match=mensaje) as error:
            ins.leer_libro(_libro(tmp_path, [_fila_libro(asiento="AS-0"), fila]), "MXN")
        assert "fila 3" in str(error.value)

    def test_columna_faltante_es_error(self, tmp_path: Path) -> None:
        encabezado = ENCABEZADO_LIBRO.replace(",proveedor_nombre", "")
        with pytest.raises(ErrorInsumo, match="proveedor_nombre"):
            ins.leer_libro(_libro(tmp_path, [], encabezado), "MXN")

    def test_archivo_vacio_es_error(self, tmp_path: Path) -> None:
        ruta = tmp_path / "vacio.csv"
        ruta.write_text("", encoding="utf-8")
        with pytest.raises(ErrorInsumo, match="encabezado"):
            ins.leer_libro(ruta, "MXN")

    def test_linea_repetida_en_un_asiento_es_error(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="repetida"):
            ins.leer_libro(_libro(tmp_path, [_fila_libro(), _fila_libro()]), "MXN")

    def test_fila_con_columnas_de_mas_es_error(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="columnas"):
            ins.leer_libro(_libro(tmp_path, [_fila_libro() + ",EXTRA"]), "MXN")


# ---------------------------------------------------------------- veredictos
class TestVeredictos:
    CARGOS = frozenset({"ALFA-0001", "ALFA-0002"})
    ASIENTOS = frozenset({"AS-1", "AS-2"})

    def _leer(self, ruta: Path):  # type: ignore[no-untyped-def]
        return ins.leer_veredictos(ruta, self.CARGOS, self.ASIENTOS)

    def test_sin_archivo_no_hay_veredictos(self) -> None:
        assert ins.leer_veredictos(None, self.CARGOS, self.ASIENTOS) == ()

    def test_solo_encabezado_es_valido(self, tmp_path: Path) -> None:
        assert self._leer(_veredictos(tmp_path, [])) == ()

    def test_lee_y_conserva_la_nota_tal_cual(self, tmp_path: Path) -> None:
        nota = 'revisado; "ok" ✓ O\'Brien'
        ruta = tmp_path / "v.csv"
        ruta.write_text("cargo_id,veredicto,asiento_id,nota\n"
                        f'ALFA-0002,no_registrado,,"{nota.replace(chr(34), chr(34) * 2)}"\n'
                        "ALFA-0001,registrado,AS-2,\n", encoding="utf-8")
        primero, segundo = self._leer(ruta)
        assert (primero.cargo_id, primero.veredicto, primero.asiento_id) == ("ALFA-0001", "registrado", "AS-2")
        assert (segundo.asiento_id, segundo.nota) == (None, nota)

    @pytest.mark.parametrize("fila, mensaje", [
        ("ALFA-0001,confirmado,AS-1,", "veredicto"),
        ("ALFA-0001,registrado,,", "asiento_id"),
        ("ALFA-0001,no_registrado,AS-1,", "asiento_id"),
        ("BETA-9999,no_registrado,,", "BETA-9999"),
        ("ALFA-0001,registrado,AS-404,", "AS-404"),
    ])
    def test_veredicto_invalido_detiene_con_fila(self, tmp_path: Path, fila: str, mensaje: str) -> None:
        with pytest.raises(ErrorInsumo, match=mensaje) as error:
            self._leer(_veredictos(tmp_path, [fila]))
        assert "fila 2" in str(error.value)

    def test_cargo_con_dos_veredictos_es_error(self, tmp_path: Path) -> None:
        filas = ["ALFA-0001,no_registrado,,", "ALFA-0001,registrado,AS-1,"]
        with pytest.raises(ErrorInsumo, match="repetido"):
            self._leer(_veredictos(tmp_path, filas))

    def test_columna_faltante_es_error(self, tmp_path: Path) -> None:
        with pytest.raises(ErrorInsumo, match="nota"):
            self._leer(_veredictos(tmp_path, [], "cargo_id,veredicto,asiento_id"))


def test_config_con_emisor_repetido_se_rechaza() -> None:
    with pytest.raises(ValueError, match="emisor"):
        ConfigCruceLibro(cuentas_tarjeta=(("ALFA", "2105-001"), ("ALFA", "2105-009")))


def test_stopwords_fijas_de_config_se_normalizan_a_mayusculas(tmp_path: Path) -> None:
    ruta = tmp_path / "c.json"
    ruta.write_text(json.dumps({"esquema": "cruce_libro_config/v1", "nombres": {"stopwords_fijas": ["sa", "Cv"]}}),
                    encoding="utf-8")
    assert cfg.cargar_config(ruta).nombres.stopwords_fijas == frozenset({"SA", "CV"})


def test_fila_vacia_del_csv_no_es_una_linea(tmp_path: Path) -> None:
    assert len(ins.leer_libro(_libro(tmp_path, [_fila_libro(), "", _fila_libro(linea="2")]), "MXN")) == 2


def test_huella_de_archivo_inexistente_es_error(tmp_path: Path) -> None:
    with pytest.raises(ErrorInsumo, match="no_hay"):
        ins.huella(tmp_path / "no_hay.csv")


def test_huella_es_el_sha256_de_los_bytes(tmp_path: Path) -> None:
    ruta = tmp_path / "x.txt"
    ruta.write_bytes(b"abc")
    assert ins.huella(ruta) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
