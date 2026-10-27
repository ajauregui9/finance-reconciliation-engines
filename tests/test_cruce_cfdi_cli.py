"""Pruebas de la salida JSON y de la CLI del cruce cargo ↔ CFDI (códigos 0, 2 y 3)."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SKILL = RAIZ / "skills" / "credit-card-reconciliation"
if str(SKILL) not in sys.path:
    sys.path.insert(0, str(SKILL))

from conciliacion import cruce_cfdi  # noqa: E402
from conciliacion.cruce_cfdi_config import ConfigCruce  # noqa: E402
from conciliacion.cruce_cfdi_invariantes import verificar_invariantes  # noqa: E402
from conciliacion.cruce_cfdi_modelo import Cargo, Cfdi, ResultadoCruce  # noqa: E402
from conciliacion.cruce_cfdi_motor import cruzar  # noqa: E402
from conciliacion.cruce_cfdi_salida import ESQUEMA_SALIDA, armar_salida, serializar  # noqa: E402

SINTETICOS = RAIZ / "examples" / "synthetic"
UNIVERSO = SINTETICOS / "universo_cargos_esperado.jsonl"
CFDIS = SINTETICOS / "cfdis.jsonl"


def _argumentos(salida: Path, universo: Path = UNIVERSO, cfdis: Path = CFDIS, *extra: str) -> List[str]:
    return ["--universo", str(universo), "--cfdis", str(cfdis), "--salida", str(salida), *extra]


class TestSalida:
    def _documento(self) -> Dict[str, Any]:
        dia = date(2026, 7, 10)
        cargos = (Cargo("ALFA-0001", dia, "CAFE LUNA", Decimal("100.00"), "MXN", Decimal("100.00"), "cargo", "ok"),
                  Cargo("ALFA-0002", None, "X", Decimal("5.00"), "MXN", Decimal("5.00"), "cargo",
                        "ininterpretable"))
        cfdis = (Cfdi("U-1", dia, "I", "recibido", "RFC_COM_01", "CAFETERIA LUNA", "RFC_EMPRESA_DEMO", "MXN",
                      Decimal("100.40"), Decimal("100.40")),)
        config = ConfigCruce()
        resultado = cruzar(cargos, cfdis, config)
        invariantes = verificar_invariantes(cargos, cfdis, config, resultado)
        huellas = {"universo": {"registros": 2, "sha256": "a" * 64}, "cfdis": {"registros": 1, "sha256": "b" * 64}}
        return armar_salida(config, resultado, invariantes, huellas, cfdis_en_pool=len(cfdis))

    def test_estructura_y_resumen(self) -> None:
        doc = self._documento()
        assert doc["esquema"] == ESQUEMA_SALIDA == "cruce_cfdi/v1"
        assert set(doc) == {"esquema", "parametros", "insumos", "resumen", "invariantes", "cargos"}
        resumen = doc["resumen"]
        assert (resumen["cargos"], resumen["con_cruce"], resumen["sin_cruce"]) == (2, 1, 1)
        assert resumen["por_evidencia"] == {"monto_exacto": 0, "moneda_original": 0, "monto_tolerancia": 1,
                                            "suma": 0}
        assert resumen["por_motivo"]["fila_ininterpretable"] == 1
        assert (resumen["cfdis_en_pool"], resumen["cfdis_asignados"], resumen["advertencias"]) == (1, 1, 0)

    def test_montos_como_cadenas(self) -> None:
        primero = self._documento()["cargos"][0]
        assert primero == {
            "cargo_id": "ALFA-0001", "cfdis": ["U-1"], "evidencia": "monto_tolerancia",
            "motivo_sin_cruce": None, "diferencia": "0.40", "moneda_diferencia": "MXN", "delta_dias": [0],
            "afinidad_nombre": "1.00", "cfdis_descartados": [], "advertencias": [],
        }

    def test_parametros_publican_la_config(self) -> None:
        parametros = self._documento()["parametros"]
        assert parametros["ventana_dias"] == {"min": -3, "max": 10}
        assert parametros["tolerancias"]["uno_a_uno"] == "1.00"

    def test_serializacion_determinista(self) -> None:
        crudo = serializar(self._documento())
        assert crudo.endswith(b"\n") and not crudo.endswith(b"\n\n")
        assert crudo == serializar(json.loads(crudo.decode("utf-8")))
        texto = crudo.decode("utf-8")
        assert texto.index('"cargos"') < texto.index('"esquema"')


class TestCli:
    def test_corrida_ok_y_sha256_estable(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        a, b = tmp_path / "a.json", tmp_path / "b.json"
        assert cruce_cfdi.main(_argumentos(a)) == 0
        assert cruce_cfdi.main(_argumentos(b)) == 0
        assert hashlib.sha256(a.read_bytes()).hexdigest() == hashlib.sha256(b.read_bytes()).hexdigest()
        doc = json.loads(a.read_text(encoding="utf-8"))
        assert doc["resumen"]["cargos"] == 199
        assert doc["insumos"]["universo"]["sha256"] == hashlib.sha256(UNIVERSO.read_bytes()).hexdigest()
        assert all(i["cumple"] for i in doc["invariantes"])
        assert "199 cargos" in capsys.readouterr().out

    def test_config_explicita(self, tmp_path: Path) -> None:
        config = tmp_path / "c.json"
        config.write_text(json.dumps({"ventana_dias": {"min": -1, "max": 1}}), encoding="utf-8")
        salida = tmp_path / "s.json"
        assert cruce_cfdi.main(_argumentos(salida, UNIVERSO, CFDIS, "--config", str(config))) == 0
        assert json.loads(salida.read_text(encoding="utf-8"))["parametros"]["ventana_dias"] == {"min": -1, "max": 1}

    def test_universo_invalido_sale_con_2(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        malo = tmp_path / "u.jsonl"
        malo.write_text('{"cargo_id": "ALFA-0001"}\n', encoding="utf-8")
        salida = tmp_path / "s.json"
        assert cruce_cfdi.main(_argumentos(salida, malo)) == 2
        assert not salida.exists()
        assert "insumo inválido" in capsys.readouterr().err

    def test_archivo_inexistente_sale_con_2(self, tmp_path: Path) -> None:
        assert cruce_cfdi.main(_argumentos(tmp_path / "s.json", tmp_path / "falta.jsonl")) == 2

    def test_config_invalida_sale_con_2(self, tmp_path: Path) -> None:
        config = tmp_path / "c.json"
        config.write_text('{"tolerancias": {"suma": "-1"}}', encoding="utf-8")
        assert cruce_cfdi.main(_argumentos(tmp_path / "s.json", UNIVERSO, CFDIS, "--config", str(config))) == 2

    def test_carpeta_de_salida_inexistente_sale_con_2(self, tmp_path: Path) -> None:
        assert cruce_cfdi.main(_argumentos(tmp_path / "no" / "s.json")) == 2

    def test_cfdis_y_xml_son_excluyentes(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit) as salida:
            cruce_cfdi.main(_argumentos(tmp_path / "s.json", UNIVERSO, CFDIS, "--cfdis-xml", str(tmp_path)))
        assert salida.value.code == 2

    def test_invariante_violado_sale_con_3_y_no_escribe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def roto(cargos: Any, cfdis: Any, config: ConfigCruce) -> ResultadoCruce:
            bueno = cruzar(cargos, cfdis, config)
            return dataclasses.replace(bueno, cargos=bueno.cargos[1:])

        monkeypatch.setattr(cruce_cfdi, "cruzar", roto)
        salida = tmp_path / "s.json"
        assert cruce_cfdi.main(_argumentos(salida)) == 3
        assert not salida.exists()
        assert "cobertura" in capsys.readouterr().err

    def test_xml_sin_defusedxml_sale_con_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "a.xml").write_text("<x/>", encoding="utf-8")
        monkeypatch.setitem(sys.modules, "defusedxml", None)
        monkeypatch.setitem(sys.modules, "defusedxml.ElementTree", None)
        argumentos = ["--universo", str(UNIVERSO), "--cfdis-xml", str(tmp_path), "--salida", str(tmp_path / "s.json")]
        assert cruce_cfdi.main(argumentos) == 2
        assert "defusedxml" in capsys.readouterr().err

    def test_como_modulo_desde_la_carpeta_del_skill(self, tmp_path: Path) -> None:
        salida = tmp_path / "s.json"
        proceso = subprocess.run(
            [sys.executable, "-m", "conciliacion.cruce_cfdi", *_argumentos(salida)],
            cwd=str(SKILL), capture_output=True, text=True, check=False,
        )
        assert proceso.returncode == 0, proceso.stderr
        assert json.loads(salida.read_text(encoding="utf-8"))["esquema"] == "cruce_cfdi/v1"
