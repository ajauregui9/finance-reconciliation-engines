"""Pruebas del verificador de referencias de la documentación (`tools/check_links.py`).

Cada prueba arma un árbol sintético en `tmp_path` con su propio conjunto de rutas
publicables; la última prueba corre el verificador sobre el repo real con las rutas
publicables por omisión.
"""
from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import pytest

ROOT = Path(__file__).resolve().parents[1]
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import check_links as cl  # noqa: E402

SCRIPT = ROOT / "tools" / "check_links.py"
PUBLICADAS = ("README.md", "skills", "docs/adr", "tests")


# --- utilidades -----------------------------------------------------------------


def _arbol(raiz: Path, archivos: Dict[str, str]) -> Path:
    for relativa, contenido in archivos.items():
        ruta = raiz / relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(contenido, encoding="utf-8")
    return raiz


def _base(raiz: Path, extra: Dict[str, str]) -> Path:
    """Árbol mínimo: README, un skill con código, spec y prueba, más un ADR."""
    archivos = {
        "README.md": "raiz\n",
        "skills/demo/motor/__init__.py": "",
        "skills/demo/motor/cruce.py": "X = 1\n",
        "skills/demo/specs/cruce.md": "# spec\n",
        "skills/demo/config/ejemplo.json": "{}\n",
        "docs/adr/0001-decision.md": "# adr\n",
        "tests/test_demo_cruce.py": "",
        "tests/test_demo_salida.py": "",
    }
    archivos.update(extra)
    return _arbol(raiz, archivos)


def _rotas(raiz: Path, publicadas: Sequence[str] = PUBLICADAS) -> List[Tuple[str, int, str, str]]:
    return [(r.referencia.documento, r.referencia.linea, r.referencia.destino, r.motivo)
            for r in cl.verificar(raiz, publicadas)]


def _correr(argv: Sequence[str]) -> Tuple[int, str, str]:
    salida, errores = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(errores):
        codigo = cl.main(list(argv))
    return codigo, salida.getvalue(), errores.getvalue()


# --- enlaces de Markdown --------------------------------------------------------


def test_enlace_relativo_existente_pasa(tmp_path: Path) -> None:
    texto = "Ver [spec](skills/demo/specs/cruce.md) y [ADR](docs/adr/0001-decision.md).\n"
    raiz = _base(tmp_path, {"README.md": texto})
    assert _rotas(raiz) == []


def test_enlace_relativo_inexistente_se_reporta_con_linea(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "# Titulo\n\nVer [motor viejo](skills/demo/scripts/viejo.py).\n"})
    assert _rotas(raiz) == [("README.md", 3, "skills/demo/scripts/viejo.py", "inexistente")]


def test_enlace_se_resuelve_contra_la_carpeta_del_documento(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {
        "skills/demo/README.md": "[ok](specs/cruce.md) [mal](skills/demo/specs/cruce.md) [arriba](../../README.md)\n",
        "README.md": "raiz\n",
    })
    assert _rotas(raiz) == [("skills/demo/README.md", 1, "skills/demo/specs/cruce.md", "inexistente")]


def test_urls_anclas_y_correos_se_ignoran(tmp_path: Path) -> None:
    texto = ("[web](https://example.com/x.md) [ancla](#seccion) [correo](mailto:a@example.com)\n"
             "[con ancla](skills/demo/specs/cruce.md#reglas) ![img](skills/demo/config/ejemplo.json)\n")
    raiz = _base(tmp_path, {"README.md": texto})
    assert _rotas(raiz) == []


def test_enlace_de_referencia_se_verifica(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "Ver [spec][s].\n\n[s]: skills/demo/specs/borrada.md\n"})
    assert _rotas(raiz) == [("README.md", 3, "skills/demo/specs/borrada.md", "inexistente")]


def test_enlace_que_sale_de_la_raiz_se_reporta(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "[fuera](../otro_repo/README.md)\n"})
    assert _rotas(raiz) == [("README.md", 1, "../otro_repo/README.md", "fuera_de_la_raiz")]


def test_enlace_con_espacios_codificados(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "[doc](skills/demo/con%20espacio.md)\n",
                            "skills/demo/con espacio.md": "x\n"})
    assert _rotas(raiz) == []


# --- rutas en código en línea ---------------------------------------------------


def test_ruta_en_backticks_inexistente_se_reporta(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "El motor `skills/demo/scripts/cruce_viejo.py` ya no existe.\n"})
    assert _rotas(raiz) == [("README.md", 1, "skills/demo/scripts/cruce_viejo.py", "inexistente")]


def test_ruta_en_backticks_se_resuelve_contra_carpetas_superiores(tmp_path: Path) -> None:
    # Una spec cita rutas relativas a su skill (`motor/cruce.py`) y a la raíz (`docs/adr/...`).
    texto = "Implementación en `motor/cruce.py`; config en `config/ejemplo.json`; ver `docs/adr/0001-decision.md`.\n"
    raiz = _base(tmp_path, {"skills/demo/specs/otra.md": texto})
    assert _rotas(raiz) == []


def test_textos_que_no_son_rutas_se_ignoran(tmp_path: Path) -> None:
    texto = ("Fechas `DD/MM/AAAA`, esquema `cruce_cfdi/v1`, `I/E`, `0.16/1.16`, `debe/haber`,\n"
             "plantillas `<salida>/reporte.json` y `$RUNNER_TEMP/a/b.json`, absoluta `/tmp/x.json`,\n"
             "url `https://example.com/a/b.md`, casa `~/.ssh/id_rsa`, flecha `a.json -> b/c.json`, `cierre.json`.\n")
    raiz = _base(tmp_path, {"README.md": texto})
    assert _rotas(raiz) == []


def test_codigo_en_la_etiqueta_de_un_enlace_no_se_resuelve_aparte(tmp_path: Path) -> None:
    # La etiqueta es texto para leer; lo que se verifica es el destino del enlace.
    texto = "[`motor/`](skills/demo/motor/) y [`viejo/`](skills/demo/viejo/), suelto `otro/`.\n"
    raiz = _base(tmp_path, {"README.md": texto})
    assert _rotas(raiz) == [
        ("README.md", 1, "skills/demo/viejo/", "inexistente"),
        ("README.md", 1, "otro/", "inexistente"),
    ]


def test_marcador_en_mayusculas_se_ignora(tmp_path: Path) -> None:
    # Convención de ayuda de CLI: `--salida DIR` escribe `DIR/manifiesto.json`.
    raiz = _base(tmp_path, {"README.md": "Escribe `DIR/manifiesto.json` y `AAAA/MM/x.csv`; no `Skills/x.py`.\n"})
    assert _rotas(raiz) == [("README.md", 1, "Skills/x.py", "inexistente")]


def test_carpeta_con_diagonal_final(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"skills/demo/README.md": "Código en `motor/` y en `scripts/`.\n"})
    assert _rotas(raiz) == [("skills/demo/README.md", 1, "scripts/", "inexistente")]


def test_ruta_que_empieza_con_carpeta_raiz_sin_extension(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "Paquete `skills/demo/motor`; viejo `skills/demo/engine`.\n"})
    assert _rotas(raiz) == [("README.md", 1, "skills/demo/engine", "inexistente")]


def test_patron_con_asterisco(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "Pruebas `tests/test_demo_*.py`; viejas `tests/test_engines*.py`.\n"})
    assert _rotas(raiz) == [("README.md", 1, "tests/test_engines*.py", "inexistente")]


def test_mayusculas_distintas_cuentan_como_inexistente(tmp_path: Path) -> None:
    # El CI corre en Linux: `Specs/Cruce.md` no existe aunque el disco local no distinga mayúsculas.
    raiz = _base(tmp_path, {"README.md": "Ver `skills/demo/Specs/Cruce.md`.\n"})
    assert _rotas(raiz) == [("README.md", 1, "skills/demo/Specs/Cruce.md", "inexistente")]


# --- bloques de código ----------------------------------------------------------


def test_bloque_verifica_rutas_que_empiezan_con_carpeta_raiz(tmp_path: Path) -> None:
    texto = (
        "Uso:\n"
        "```bash\n"
        "PYTHONPATH=skills/demo python3 -m motor --config skills/demo/config/ejemplo.json \\\n"
        "    --salida \"$OUT/x.json\" --datos ../../examples/viejo\n"
        "python3 skills/demo/scripts/viejo.py --entrada out/cosa.json\n"
        "python3 -m pytest tests/test_demo_*.py -q\n"
        "```\n"
    )
    raiz = _base(tmp_path, {"README.md": texto})
    assert _rotas(raiz) == [("README.md", 5, "skills/demo/scripts/viejo.py", "inexistente")]


def test_backticks_dentro_de_un_bloque_no_se_leen_como_codigo_en_linea(tmp_path: Path) -> None:
    texto = "~~~text\nsalida `etapas/universo.jsonl` dentro del bloque\n~~~\nFuera: `motor/inexistente.py`.\n"
    raiz = _base(tmp_path, {"skills/demo/README.md": texto})
    assert _rotas(raiz) == [("skills/demo/README.md", 4, "motor/inexistente.py", "inexistente")]


# --- conjunto publicado ---------------------------------------------------------


def test_destino_existente_pero_no_publicado(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {
        "docs/interno/nota.md": "notas de trabajo\n",
        "README.md": "[nota](docs/interno/nota.md) y `docs/interno/nota.md`\n",
    })
    assert _rotas(raiz) == [
        ("README.md", 1, "docs/interno/nota.md", "no_publicada"),
        ("README.md", 1, "docs/interno/nota.md", "no_publicada"),
    ]


def test_raiz_y_carpetas_de_ruido(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {
        "skills/demo/__pycache__/cache.md": "x\n",
        "skills/demo/README.md": "[raiz](../../) [cache](__pycache__/cache.md) [nada](motor/x/y.py)\n",
    })
    assert _rotas(raiz) == [
        ("skills/demo/README.md", 1, "__pycache__/cache.md", "no_publicada"),
        ("skills/demo/README.md", 1, "motor/x/y.py", "inexistente"),
    ]


def test_documentos_no_publicados_no_se_revisan(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {
        "README.md": "ok\n",
        "docs/interno/nota.md": "[roto](no_existe.md)\n",
        "skills/demo/.pytest_cache/README.md": "[roto](no_existe.md)\n",
        "skills/demo/__pycache__/x.md": "[roto](no_existe.md)\n",
    })
    assert _rotas(raiz) == []


def test_resultado_ordenado_y_determinista(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {
        "skills/demo/README.md": "[b](b.md)\n[a](a.md)\n",
        "README.md": "[z](z.md)\n",
    })
    esperado = [
        ("README.md", 1, "z.md", "inexistente"),
        ("skills/demo/README.md", 1, "b.md", "inexistente"),
        ("skills/demo/README.md", 2, "a.md", "inexistente"),
    ]
    assert _rotas(raiz) == esperado
    assert _rotas(raiz) == esperado


def test_ruta_publicable_inexistente_es_error_de_configuracion(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "ok\n"})
    with pytest.raises(cl.ErrorConfiguracion, match="no existe"):
        cl.verificar(raiz, ("README.md", "carpeta_que_no_existe"))
    with pytest.raises(cl.ErrorConfiguracion, match="fuera de la raíz"):
        cl.verificar(raiz, ("../afuera",))


def test_las_rutas_publicables_por_omision_solo_publican_los_adrs_de_docs() -> None:
    de_docs = [r for r in cl.PUBLICABLES if r.split("/")[0] == "docs"]
    assert de_docs == ["docs/adr"]


# --- CLI ------------------------------------------------------------------------


def test_main_limpio_devuelve_cero(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "[spec](skills/demo/specs/cruce.md)\n"})
    codigo, salida, errores = _correr(["--raiz", str(raiz), *PUBLICADAS])
    assert codigo == 0, errores
    assert "0 referencias rotas" in salida


def test_main_con_rotas_devuelve_uno_y_las_lista(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "[x](skills/demo/borrado.py)\n`skills/demo/fees_reference.json`\n"})
    codigo, salida, _ = _correr(["--raiz", str(raiz), *PUBLICADAS])
    assert codigo == 1
    assert "README.md:1: enlace skills/demo/borrado.py (inexistente)" in salida
    assert "README.md:2: codigo skills/demo/fees_reference.json (inexistente)" in salida
    assert "2 referencias rotas" in salida


def test_main_configuracion_invalida_devuelve_dos(tmp_path: Path) -> None:
    codigo, _, errores = _correr(["--raiz", str(tmp_path / "no_existe")])
    assert codigo == 2
    assert "raíz" in errores
    raiz = _base(tmp_path, {"README.md": "ok\n"})
    codigo, _, errores = _correr(["--raiz", str(raiz), "README.md", "falta.md"])
    assert codigo == 2
    assert "falta.md" in errores


def test_documento_que_no_es_utf8_es_error_de_configuracion(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "ok\n"})
    (raiz / "skills" / "demo" / "latin1.md").write_bytes("caf\xe9\n".encode("latin-1"))
    codigo, _, errores = _correr(["--raiz", str(raiz), *PUBLICADAS])
    assert codigo == 2
    assert "latin1.md" in errores


def test_script_corre_como_proceso(tmp_path: Path) -> None:
    raiz = _base(tmp_path, {"README.md": "[x](no_existe.md)\n"})
    resultado = subprocess.run(
        [sys.executable, str(SCRIPT), "--raiz", str(raiz), *PUBLICADAS],
        capture_output=True, text=True, check=False,
    )
    assert resultado.returncode == 1
    assert "README.md:1: enlace no_existe.md (inexistente)" in resultado.stdout


def test_la_documentacion_del_repo_no_tiene_referencias_rotas() -> None:
    rotas = [cl.formatear(r) for r in cl.verificar(ROOT, cl.PUBLICABLES)]
    assert rotas == []
