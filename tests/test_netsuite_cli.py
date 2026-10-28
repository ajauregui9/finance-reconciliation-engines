"""Pruebas de la CLI del módulo NetSuite y de sus compromisos de alcance (ADR 0002)."""
from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "netsuite-gl-reconciliation"
for ruta in (SKILL, ROOT / "tools"):
    if str(ruta) not in sys.path:
        sys.path.insert(0, str(ruta))

import sanitize_audit  # noqa: E402
from netsuite_gl.cli import main  # noqa: E402
from netsuite_gl.consultas import ORDEN_CONSULTAS  # noqa: E402

CFDIS = ROOT / "examples" / "synthetic" / "cfdis.jsonl"
SCRIPT = SKILL / "run_netsuite_gl.py"
EJEMPLO_JOURNAL = SKILL / "ejemplos" / "asientos_journal.json"
FRASE_ALCANCE = "SuiteQL via MCP connector + CSV import; no REST/SuiteScript"


def _hashes(carpeta: Path) -> Dict[str, str]:
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(carpeta.iterdir())}


def test_consultar_escribe_un_csv_por_query_y_el_manifiesto(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["consultar", "--salida", str(tmp_path / "a")]) == 0
    nombres = {p.name for p in (tmp_path / "a").iterdir()}
    assert nombres == {f"{n}.csv" for n in ORDEN_CONSULTAS} | {"discrepancias_plantadas.json"}
    assert "cuadre_cfdi_gl" in capsys.readouterr().out


def test_consultar_dos_veces_da_los_mismos_sha256(tmp_path: Path) -> None:
    assert main(["consultar", "--salida", str(tmp_path / "a"), "--cfdis", str(CFDIS)]) == 0
    assert main(["consultar", "--salida", str(tmp_path / "b"), "--cfdis", str(CFDIS)]) == 0
    assert _hashes(tmp_path / "a") == _hashes(tmp_path / "b")


def test_consultar_a_stdout_con_filtro(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["consultar", "--consulta", "duplicados_registro"]) == 0
    salida = capsys.readouterr().out
    assert salida.startswith("# duplicados_registro (")
    assert "uuid,referencia,num_registros,primera_transaccion,ultima_transaccion" in salida
    assert "# saldos_cuenta_periodo_clase" not in salida


def test_consultar_query_desconocida_sale_con_2(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["consultar", "--consulta", "no_existe"]) == 2
    assert "no_existe" in capsys.readouterr().err


def test_cfdis_inexistente_sale_con_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discrepancias", "--cfdis", str(tmp_path / "nada.jsonl")]) == 2
    assert "no existe" in capsys.readouterr().err


def test_discrepancias_imprime_y_escribe_el_manifiesto(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["discrepancias"]) == 0
    impreso = json.loads(capsys.readouterr().out)
    assert impreso["esquema"] == "netsuite_discrepancias/v1"
    destino = tmp_path / "m.json"
    assert main(["discrepancias", "--salida", str(destino)]) == 0
    assert json.loads(destino.read_text(encoding="utf-8")) == impreso


def test_traducir_imprime_sql_sin_construcciones_suiteql(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["traducir", "saldos_cuenta_periodo_clase"]) == 0
    salida = capsys.readouterr().out
    assert "BUILTIN" not in salida and "NVL" not in salida and "SELECT" in salida


def test_generar_csv_desde_sin_registro(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    destino = tmp_path / "facturas.csv"
    assert main(["generar-csv", "--desde-sin-registro", "--salida", str(destino)]) == 0
    primera = destino.read_bytes()
    assert primera.startswith(b"External ID,Vendor,Date")
    assert "asientos" in capsys.readouterr().out
    assert main(["generar-csv", "--desde-sin-registro", "--salida", str(destino)]) == 0
    assert destino.read_bytes() == primera


def test_generar_csv_desde_json_de_journal(tmp_path: Path) -> None:
    destino = tmp_path / "journal.csv"
    args = ["generar-csv", "--asientos", str(EJEMPLO_JOURNAL), "--formato", "journal", "--salida", str(destino)]
    assert main(args) == 0
    assert destino.read_text(encoding="utf-8").startswith("External ID,Date,Posting Period")


def test_generar_csv_rechazado_sale_con_3_y_no_escribe(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    documento = json.loads(EJEMPLO_JOURNAL.read_text(encoding="utf-8"))
    documento["asientos"][0]["lineas"][0]["debito"] = "999999.00"
    entrada = tmp_path / "malo.json"
    entrada.write_text(json.dumps(documento), encoding="utf-8")
    destino = tmp_path / "no.csv"
    args = ["generar-csv", "--asientos", str(entrada), "--formato", "journal", "--salida", str(destino)]
    assert main(args) == 3
    assert not destino.exists()
    assert "asiento_descuadrado" in capsys.readouterr().err


def test_generar_csv_con_json_roto_o_sin_formato_sale_con_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    entrada = tmp_path / "roto.json"
    entrada.write_text("{", encoding="utf-8")
    destino = tmp_path / "x.csv"
    assert main(["generar-csv", "--asientos", str(entrada), "--formato", "journal", "--salida", str(destino)]) == 2
    assert main(["generar-csv", "--asientos", str(EJEMPLO_JOURNAL), "--salida", str(destino)]) == 2
    inexistente = str(tmp_path / "nada.json")
    assert main(["generar-csv", "--asientos", inexistente, "--formato", "journal", "--salida", str(destino)]) == 2
    assert not destino.exists()
    assert capsys.readouterr().err


def _rechazable(tmp_path: Path) -> str:
    documento = json.loads(EJEMPLO_JOURNAL.read_text(encoding="utf-8"))
    documento["asientos"][0]["lineas"][0]["debito"] = "999999.00"
    entrada = tmp_path / "malo.json"
    entrada.write_text(json.dumps(documento), encoding="utf-8")
    return str(entrada)


@pytest.mark.parametrize(
    "argumentos, codigo",
    [
        (["consultar"], 0),
        (["consultar", "--salida", "{tmp}/c"], 0),
        (["discrepancias"], 0),
        (["generar-csv", "--desde-sin-registro", "--salida", "{tmp}/f.csv"], 0),
        (["generar-csv", "--asientos", str(EJEMPLO_JOURNAL), "--formato", "journal", "--salida", "{tmp}/j.csv"], 0),
        (["generar-csv", "--asientos", "{malo}", "--formato", "journal", "--salida", "{tmp}/r.csv"], 3),
        (["generar-csv", "--asientos", str(EJEMPLO_JOURNAL), "--salida", "{tmp}/s.csv"], 2),
    ],
)
def test_cada_comando_cierra_las_conexiones_que_abre(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    argumentos: List[str], codigo: int,
) -> None:
    abiertas: List[sqlite3.Connection] = []
    original = sqlite3.connect

    def registrar(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        abiertas.append(original(*args, **kwargs))
        return abiertas[-1]

    monkeypatch.setattr(sqlite3, "connect", registrar)
    malo = _rechazable(tmp_path)
    assert main([a.format(tmp=tmp_path, malo=malo) for a in argumentos]) == codigo
    capsys.readouterr()
    assert len(abiertas) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        abiertas[0].execute("SELECT 1")


def test_script_corre_como_proceso(tmp_path: Path) -> None:
    resultado = subprocess.run(
        [sys.executable, str(SCRIPT), "consultar", "--consulta", "cfdi_sin_registro"],
        capture_output=True, text=True, check=False, cwd=str(tmp_path),
    )
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.startswith("# cfdi_sin_registro (")


# ---------------------------------------------------------------- alcance y limpieza


def test_readme_declara_el_alcance_textualmente() -> None:
    assert FRASE_ALCANCE in (SKILL / "README.md").read_text(encoding="utf-8")


def _modulos_importados(ruta: Path) -> List[str]:
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    nombres: List[str] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            nombres.extend(alias.name.split(".")[0] for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module and nodo.level == 0:
            nombres.append(nodo.module.split(".")[0])
    return nombres


def test_no_hay_cliente_rest_ni_dependencias_externas() -> None:
    prohibidos = {"requests", "urllib", "http", "httpx", "aiohttp", "socket", "ssl", "oauthlib", "requests_oauthlib"}
    stdlib_permitida = {
        "__future__", "argparse", "collections", "csv", "dataclasses", "datetime", "decimal", "hashlib", "io", "json",
        "pathlib", "re", "sqlite3", "sys", "types", "typing", "netsuite_gl",
        "frontera",  # frontera de entrada compartida del repo (solo biblioteca estándar)
    }
    for ruta in sorted(SKILL.rglob("*.py")):
        importados = set(_modulos_importados(ruta))
        assert not importados & prohibidos, ruta.name
        assert importados <= stdlib_permitida, (ruta.name, importados - stdlib_permitida)


def test_sanitizer_no_encuentra_huellas_en_el_modulo_ni_en_sus_pruebas() -> None:
    reglas, _ = sanitize_audit.load_custom_rules(None)
    rutas = sorted(p for p in SKILL.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    rutas += sorted((ROOT / "tests").glob("test_netsuite_*.py"))
    alertas = [(r.name, a) for r in rutas for a in sanitize_audit.audit_file(str(r), reglas)]
    assert alertas == []


def test_argumentos_invalidos_salen_con_2(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["no-es-comando"]) == 2
    destino = tmp_path / "x.csv"
    args = ["generar-csv", "--desde-sin-registro", "--formato", "journal", "--salida", str(destino)]
    assert main(args) == 2
    assert "vendor_bill" in capsys.readouterr().err
    assert not destino.exists()


def test_ayuda_sale_con_0(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == 0
    assert "consultar" in capsys.readouterr().out
