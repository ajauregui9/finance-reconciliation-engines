"""Pruebas de la CLI y de la salida del cruce con libro mayor: códigos 0/2/3 y SHA-256."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
RAIZ_SKILL = ROOT / "skills" / "credit-card-reconciliation"
if str(RAIZ_SKILL) not in sys.path:
    sys.path.insert(0, str(RAIZ_SKILL))

from conciliacion import cruce_libro  # noqa: E402

SINTETICO = ROOT / "examples" / "synthetic"
UNIVERSO = SINTETICO / "universo_cargos_esperado.jsonl"
LIBRO = SINTETICO / "libro_mayor.csv"
VEREDICTOS = SINTETICO / "veredictos_libro.csv"


def _argv(salida: Path, *, universo: Path = UNIVERSO, libro: Path = LIBRO, veredictos: Any = VEREDICTOS,
          extra: tuple = ()) -> List[str]:
    args = ["--universo", str(universo), "--libro", str(libro), "--salida", str(salida), *extra]
    return args + (["--veredictos", str(veredictos)] if veredictos is not None else [])


def _sha(ruta: Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def _leer(ruta: Path) -> Dict[str, Any]:
    return json.loads(ruta.read_text(encoding="utf-8"))


def _recorrer(valor: Any):  # type: ignore[no-untyped-def]
    if isinstance(valor, dict):
        for v in valor.values():
            yield from _recorrer(v)
    elif isinstance(valor, list):
        for v in valor:
            yield from _recorrer(v)
    else:
        yield valor


# --------------------------------------------------------------------- código 0
class TestCorridaCompleta:
    def test_modulo_corre_desde_la_carpeta_de_la_skill(self, tmp_path: Path) -> None:
        salida = tmp_path / "cruce.json"
        res = subprocess.run([sys.executable, "-m", "conciliacion.cruce_libro", *_argv(salida)],
                             cwd=RAIZ_SKILL, capture_output=True, text=True, check=False)
        assert res.returncode == 0, res.stderr
        resumen = json.loads(res.stdout)
        assert resumen["cargos"] == 199
        assert resumen["candados_ok"] is True
        assert _leer(salida)["esquema"] == "cruce_libro/v1"

    def test_tres_corridas_dan_el_mismo_sha256(self, tmp_path: Path) -> None:
        huellas = set()
        for n in range(3):
            salida = tmp_path / f"cruce_{n}.json"
            assert cruce_libro.main(_argv(salida)) == 0
            huellas.add(_sha(salida))
        assert len(huellas) == 1

    def test_salida_no_depende_de_la_carpeta_de_los_insumos(self, tmp_path: Path) -> None:
        copia = tmp_path / "otra carpeta ñ"
        copia.mkdir()
        for origen in (UNIVERSO, LIBRO, VEREDICTOS):
            shutil.copy(origen, copia / origen.name)
        assert cruce_libro.main(_argv(tmp_path / "a.json")) == 0
        assert cruce_libro.main(_argv(tmp_path / "b.json", universo=copia / UNIVERSO.name,
                                      libro=copia / LIBRO.name, veredictos=copia / VEREDICTOS.name)) == 0
        assert _sha(tmp_path / "a.json") == _sha(tmp_path / "b.json")
        assert str(tmp_path) not in (tmp_path / "b.json").read_text(encoding="utf-8")

    def test_salida_sin_floats_y_montos_en_texto(self, tmp_path: Path) -> None:
        salida = tmp_path / "cruce.json"
        assert cruce_libro.main(_argv(salida)) == 0
        reporte = _leer(salida)
        assert not [v for v in _recorrer(reporte) if isinstance(v, float)]
        for cargo in reporte["cargos"]:
            assert isinstance(cargo["monto"], str)
            for candidato in cargo["candidatos"]["muestra"]:
                assert isinstance(candidato["importe"], str) and isinstance(candidato["diferencia_monto"], str)

    def test_publica_parametros_huellas_y_resumen(self, tmp_path: Path) -> None:
        salida = tmp_path / "cruce.json"
        assert cruce_libro.main(_argv(salida)) == 0
        reporte = _leer(salida)
        assert reporte["insumos"]["universo"] == {"cargos": 199, "sha256": _sha(UNIVERSO)}
        assert reporte["insumos"]["libro"]["sha256"] == _sha(LIBRO)
        assert reporte["insumos"]["veredictos"]["sha256"] == _sha(VEREDICTOS)
        assert reporte["parametros"]["umbral_similitud"] == "0.50"
        resumen = reporte["resumen"]
        assert resumen["cargos"] == 199
        assert sum(resumen["final"]["por_origen"].values()) == 199
        assert resumen["veredictos"]["total"] == 12
        montos = resumen["montos"]
        assert Decimal(montos["final_con_cruce"]) + Decimal(montos["final_sin_cruce"]) == Decimal(montos["universo"])

    def test_muestra_de_candidatos_respeta_el_maximo_y_los_conteos_no(self, tmp_path: Path) -> None:
        config = tmp_path / "c.json"
        config.write_text(json.dumps({"esquema": "cruce_libro_config/v1", "max_candidatos_reporte": 0}),
                          encoding="utf-8")
        salida = tmp_path / "cruce.json"
        assert cruce_libro.main(_argv(salida, extra=("--config", str(config)))) == 0
        cargos = _leer(salida)["cargos"]
        assert all(c["candidatos"]["muestra"] == [] for c in cargos)
        assert sum(c["candidatos"]["total"] for c in cargos) > 0

    def test_sin_veredictos_no_hay_conflictos(self, tmp_path: Path) -> None:
        salida = tmp_path / "cruce.json"
        assert cruce_libro.main(_argv(salida, veredictos=None)) == 0
        reporte = _leer(salida)
        assert reporte["conflictos"] == []
        assert reporte["insumos"]["veredictos"] == {"filas": 0, "sha256": None}
        assert all(c["final"]["origen"] == "motor" for c in reporte["cargos"])


# --------------------------------------------------------------------- código 2
class TestInsumosInvalidos:
    def test_archivo_inexistente_sale_con_2_sin_escribir(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        salida = tmp_path / "cruce.json"
        assert cruce_libro.main(_argv(salida, universo=tmp_path / "nada.jsonl")) == 2
        assert not salida.exists()
        assert "nada.jsonl" in capsys.readouterr().err

    def test_veredicto_de_un_cargo_desconocido_sale_con_2(self, tmp_path: Path) -> None:
        veredictos = tmp_path / "v.csv"
        veredictos.write_text("cargo_id,veredicto,asiento_id,nota\nZETA-0001,no_registrado,,x\n", encoding="utf-8")
        assert cruce_libro.main(_argv(tmp_path / "o.json", veredictos=veredictos)) == 2

    def test_config_invalida_sale_con_2(self, tmp_path: Path) -> None:
        config = tmp_path / "c.json"
        config.write_text(json.dumps({"esquema": "cruce_libro_config/v1", "umbral_similitud": 0.5}),
                          encoding="utf-8")
        assert cruce_libro.main(_argv(tmp_path / "o.json", extra=("--config", str(config)))) == 2

    def test_emisor_sin_cuenta_configurada_sale_con_2(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        config = tmp_path / "c.json"
        config.write_text(json.dumps({"esquema": "cruce_libro_config/v1", "cuentas_tarjeta": {"ALFA": "2105-001"}}),
                          encoding="utf-8")
        assert cruce_libro.main(_argv(tmp_path / "o.json", extra=("--config", str(config)))) == 2
        assert "BETA" in capsys.readouterr().err

    def test_argumento_faltante_sale_con_2(self) -> None:
        with pytest.raises(SystemExit) as salida:
            cruce_libro.main(["--universo", str(UNIVERSO)])
        assert salida.value.code == 2

    def test_salida_imposible_de_escribir_sale_con_2(self, tmp_path: Path) -> None:
        bloqueo = tmp_path / "archivo"
        bloqueo.write_text("x", encoding="utf-8")
        assert cruce_libro.main(_argv(bloqueo / "dentro" / "o.json")) == 2


# --------------------------------------------------------------------- código 3
class TestCandados:
    def test_dos_veredictos_sobre_un_asiento_rompen_exclusividad(self, tmp_path: Path) -> None:
        veredictos = tmp_path / "v.csv"
        veredictos.write_text("cargo_id,veredicto,asiento_id,nota\nALFA-0001,registrado,AS-0050,a\n"
                              "ALFA-0002,registrado,AS-0050,b\n", encoding="utf-8")
        salida = tmp_path / "o.json"
        assert cruce_libro.main(_argv(salida, veredictos=veredictos)) == 3
        candado = _leer(salida)["candados"]["exclusividad"]
        assert candado["ok"] is False
        assert candado["detalle"]["asientos_con_varios_cargos"] == {"AS-0050": ["ALFA-0001", "ALFA-0002"]}

    def test_asiento_descuadrado_rompe_partida_doble(self, tmp_path: Path) -> None:
        lineas = LIBRO.read_text(encoding="utf-8").splitlines()
        lineas[1] = lineas[1].rsplit(",", 3)[0] + ",999.99,0.00,MXN"
        libro = tmp_path / "libro.csv"
        libro.write_text("\n".join(lineas) + "\n", encoding="utf-8")
        salida = tmp_path / "o.json"
        assert cruce_libro.main(_argv(salida, libro=libro)) == 3
        candado = _leer(salida)["candados"]["partida_doble"]
        assert candado["ok"] is False
        assert list(candado["detalle"]["asientos_descuadrados"]) == ["AS-0001"]
