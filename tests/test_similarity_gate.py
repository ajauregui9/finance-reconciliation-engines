"""Pruebas de la compuerta clean-room de similitud (`tools/similarity_gate.py`).

Todas las pruebas construyen árboles sintéticos en `tmp_path`: un "original"
ficticio, un árbol copiado (incluye un archivo renombrado) y un árbol distinto.
Nunca se lee el material de referencia real.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Sequence

import pytest

ROOT = Path(__file__).resolve().parents[1]
_TOOLS = str(ROOT / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)

import similarity_gate as sg  # noqa: E402

SCRIPT = ROOT / "tools" / "similarity_gate.py"
MARCA_SECRETA = "UMBRAL_SECRETO_CALIBRACION = 0.4321"
CARPETA_CONFIDENCIAL = "cliente_confidencial"


# --- utilidades de fixture -------------------------------------------------


def _escribir(ruta: Path, lineas: Sequence[str]) -> Path:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    return ruta


def _codigo(prefijo: str, n_funciones: int) -> List[str]:
    """Genera código sintético cuyas líneas son únicas para cada prefijo."""
    lineas: List[str] = []
    for i in range(n_funciones):
        lineas.extend(
            [
                f"def {prefijo}_paso_{i}({prefijo}_monto_{i}):",
                f"    {prefijo}_base_{i} = {prefijo}_monto_{i} * {i + 2}",
                f"    return {prefijo}_base_{i} - {i}",
                "",
            ]
        )
    return lineas


@pytest.fixture()
def arboles(tmp_path: Path):
    """Crea un original sintético, un árbol copiado y un árbol distinto."""
    original = tmp_path / "original"
    _escribir(original / CARPETA_CONFIDENCIAL / "motor_a.py", _codigo("cruce", 30))
    _escribir(original / CARPETA_CONFIDENCIAL / "motor_b.py", _codigo("pac", 30))
    _escribir(original / "util" / "norm.py", [MARCA_SECRETA] + _codigo("norm", 20))

    copiado = tmp_path / "copiado"
    _escribir(copiado / "skills" / "modulos" / "motor_a.py", _codigo("cruce", 30))
    # Renombrado: mismo contenido que motor_b.py con otro nombre.
    _escribir(copiado / "skills" / "modulos" / "emparejador.py", _codigo("pac", 30))
    _escribir(copiado / "tools" / "normalizador.py", [MARCA_SECRETA] + _codigo("norm", 20))

    distinto = tmp_path / "distinto"
    _escribir(distinto / "skills" / "modulos" / "motor_a.py", _codigo("nuevo_motor", 30))
    _escribir(distinto / "skills" / "modulos" / "emparejador.py", _codigo("nuevo_par", 30))
    _escribir(distinto / "tools" / "normalizador.py", _codigo("nuevo_norm", 20))

    return {"original": original, "copiado": copiado, "distinto": distinto}


def _correr(monkeypatch, original: Path, repo: Path, *extra: str) -> int:
    monkeypatch.setenv(sg.VARIABLE_ORIGINAL, str(original))
    return sg.main(["--raiz", str(repo), *extra])


def _por_archivo(resultados) -> dict:
    return {r.archivo: r for r in resultados}


# --- normalización y métrica -----------------------------------------------


def test_normalizar_ignora_vacias_sangria_y_lineas_solo_puntuacion():
    texto = "def f(x):\n\n        return x\n    )\n  ],\n\t}\nprint('ñandú ✓')\n"
    assert sg.normalizar_lineas(texto) == ("def f(x):", "return x", "print('ñandú ✓')")


def test_normalizar_texto_vacio_devuelve_tupla_vacia():
    assert sg.normalizar_lineas("") == ()
    assert sg.normalizar_lineas("\n   \n\t\n") == ()


def test_similitud_identica_es_uno():
    lineas = tuple(sg.normalizar_lineas("\n".join(_codigo("a", 5))))
    assert sg.medir_similitud(lineas, lineas) == (len(lineas), 1.0)


def test_similitud_disjunta_es_cero():
    a = sg.normalizar_lineas("\n".join(_codigo("a", 5)))
    b = sg.normalizar_lineas("\n".join(_codigo("b", 5)))
    assert sg.medir_similitud(a, b) == (0, 0.0)


def test_similitud_con_entradas_vacias_es_cero_sin_dividir_entre_cero():
    lineas = sg.normalizar_lineas("x = 1\ny = 2")
    assert sg.medir_similitud((), lineas) == (0, 0.0)
    assert sg.medir_similitud(lineas, ()) == (0, 0.0)
    assert sg.medir_similitud((), ()) == (0, 0.0)


def test_similitud_detecta_extracto_corto_de_un_original_grande():
    original = sg.normalizar_lineas("\n".join(_codigo("grande", 50)))
    extracto = original[30:40]
    coincidentes, similitud = sg.medir_similitud(extracto, original)
    assert coincidentes == 10
    assert similitud == 1.0


def test_similitud_detecta_original_completo_incrustado_en_archivo_mayor():
    # 10 líneas del original dentro de un archivo de 40: 25% del archivo,
    # pero el original entero está copiado (ratio simétrico 2*10/50 = 40%).
    original = tuple(f"original_linea_{i} = {i}" for i in range(10))
    nuevo = tuple(f"nueva_linea_{i} = {i}" for i in range(30)) + original
    coincidentes, similitud = sg.medir_similitud(nuevo, original)
    assert coincidentes == 10
    assert similitud == pytest.approx(0.40)


# --- variable de entorno ----------------------------------------------------


def test_resolver_original_sin_variable_lanza_error_claro():
    with pytest.raises(sg.ErrorConfiguracion) as exc:
        sg.resolver_ruta_original({})
    assert sg.VARIABLE_ORIGINAL in str(exc.value)


@pytest.mark.parametrize("valor", ["", "   "])
def test_resolver_original_con_variable_vacia_lanza_error(valor):
    with pytest.raises(sg.ErrorConfiguracion):
        sg.resolver_ruta_original({sg.VARIABLE_ORIGINAL: valor})


def test_resolver_original_inexistente_no_revela_la_ruta(tmp_path):
    ruta = tmp_path / "ruta_privada_inexistente"
    with pytest.raises(sg.ErrorConfiguracion) as exc:
        sg.resolver_ruta_original({sg.VARIABLE_ORIGINAL: str(ruta)})
    assert "ruta_privada_inexistente" not in str(exc.value)
    assert str(tmp_path) not in str(exc.value)


def test_resolver_original_que_es_archivo_lanza_error(tmp_path):
    archivo = _escribir(tmp_path / "no_soy_carpeta.py", ["x = 1"])
    with pytest.raises(sg.ErrorConfiguracion):
        sg.resolver_ruta_original({sg.VARIABLE_ORIGINAL: str(archivo)})


def test_resolver_original_valido_devuelve_ruta_absoluta(tmp_path):
    ruta = sg.resolver_ruta_original({sg.VARIABLE_ORIGINAL: str(tmp_path)})
    assert ruta == tmp_path.resolve()


def test_main_sin_variable_de_entorno_no_aprueba(monkeypatch, capsys, arboles):
    monkeypatch.delenv(sg.VARIABLE_ORIGINAL, raising=False)
    codigo = sg.main(["--raiz", str(arboles["distinto"])])
    salida = capsys.readouterr()
    assert codigo == sg.SALIDA_ERROR_CONFIG
    assert codigo != 0
    assert sg.VARIABLE_ORIGINAL in salida.err
    assert "APROBADO" not in salida.out.replace("NO APROBADO", "")


# --- árboles sintéticos: copiado y distinto --------------------------------


def test_arbol_copiado_falla_la_compuerta(monkeypatch, capsys, arboles):
    codigo = _correr(monkeypatch, arboles["original"], arboles["copiado"])
    salida = capsys.readouterr().out
    assert codigo == sg.SALIDA_RECHAZADO
    assert "NO APROBADO" in salida
    assert "3 de 3" in salida


def test_arbol_distinto_aprueba_la_compuerta(monkeypatch, capsys, arboles):
    codigo = _correr(monkeypatch, arboles["original"], arboles["distinto"])
    salida = capsys.readouterr().out
    assert codigo == sg.SALIDA_APROBADO
    assert "NO APROBADO" not in salida
    assert "APROBADO" in salida


def test_arbol_copiado_detecta_renombrado_por_contenido(arboles):
    resultados = _por_archivo(sg.evaluar(arboles["copiado"], arboles["original"]))
    renombrado = resultados["skills/modulos/emparejador.py"]
    assert renombrado.original == "motor_b.py"
    assert renombrado.criterio == sg.CRITERIO_CONTENIDO
    assert renombrado.similitud == 1.0

    homonimo = resultados["skills/modulos/motor_a.py"]
    assert homonimo.original == "motor_a.py"
    assert homonimo.criterio == sg.CRITERIO_NOMBRE
    assert homonimo.similitud == 1.0


def test_arbol_distinto_reporta_par_homonimo_con_similitud_baja(arboles):
    resultados = _por_archivo(sg.evaluar(arboles["distinto"], arboles["original"]))
    homonimo = resultados["skills/modulos/motor_a.py"]
    assert homonimo.original == "motor_a.py"
    assert homonimo.criterio == sg.CRITERIO_NOMBRE
    assert homonimo.similitud < sg.UMBRAL_DEFAULT
    sin_par = resultados["skills/modulos/emparejador.py"]
    assert sin_par.original is None
    assert sin_par.criterio == sg.CRITERIO_NINGUNO
    assert sin_par.similitud == 0.0


def test_homonimo_reescrito_no_oculta_copia_renombrada(tmp_path):
    original = tmp_path / "original"
    _escribir(original / "motor.py", _codigo("viejo_motor", 10))
    _escribir(original / "conciliador.py", _codigo("viejo_conc", 10))
    repo = tmp_path / "repo"
    # Se llama como un original, pero su contenido es copia del otro.
    _escribir(repo / "motor.py", _codigo("viejo_conc", 10))
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.original == "conciliador.py"
    assert resultado.criterio == sg.CRITERIO_CONTENIDO
    assert resultado.similitud == 1.0


def test_empate_prefiere_coincidencia_por_nombre(tmp_path):
    original = tmp_path / "original"
    _escribir(original / "a.py", _codigo("gemelo", 8))
    _escribir(original / "b.py", _codigo("gemelo", 8))
    repo = tmp_path / "repo"
    _escribir(repo / "b.py", _codigo("gemelo", 8))
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.original == "b.py"
    assert resultado.criterio == sg.CRITERIO_NOMBRE


def test_emparejamiento_por_nombre_ignora_mayusculas(tmp_path):
    original = tmp_path / "original"
    _escribir(original / "Motor_A.py", _codigo("otro", 5))
    repo = tmp_path / "repo"
    _escribir(repo / "motor_a.py", _codigo("propio", 5))
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.original == "Motor_A.py"
    assert resultado.criterio == sg.CRITERIO_NOMBRE


@pytest.mark.parametrize("orden", [("a", "b"), ("b", "a")])
def test_varios_homonimos_toma_el_mas_parecido(tmp_path, orden):
    original = tmp_path / "original"
    copia = _codigo("homonimo", 10)
    contenidos = {"a": copia, "b": _codigo("ajeno", 10)}
    primero, segundo = orden
    _escribir(original / "1_primero" / "motor.py", contenidos[primero])
    _escribir(original / "2_segundo" / "motor.py", contenidos[segundo])
    repo = tmp_path / "repo"
    _escribir(repo / "motor.py", copia)
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.similitud == 1.0
    assert resultado.criterio == sg.CRITERIO_NOMBRE


def test_lineas_comunes_desordenadas_no_desplazan_a_la_mejor_coincidencia(tmp_path):
    # La similitud es por secuencia de líneas, no por bolsa de líneas.
    r = [f"repo_linea_{i} = calcular({i})" for i in range(10)]
    original = tmp_path / "original"
    _escribir(original / "a_desordenado.py", list(reversed(r[3:])))
    _escribir(original / "b_en_orden.py", r[:6] + [r[9], r[8]])
    repo = tmp_path / "repo"
    _escribir(repo / "nuevo.py", r)
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.original == "b_en_orden.py"
    assert resultado.coincidentes == 7
    assert resultado.similitud == pytest.approx(14 / 18)


# --- umbral -----------------------------------------------------------------


def _arbol_con_lineas_copiadas(tmp_path: Path, copiadas: int):
    """Archivo de 20 líneas con `copiadas` líneas tomadas de un original de 100."""
    original = tmp_path / "original"
    lineas_originales = [f"original_{i} = calcular_original({i})" for i in range(100)]
    _escribir(original / "fuente.py", lineas_originales)
    repo = tmp_path / "repo"
    propias = [f"propia_{i} = calcular_propia({i})" for i in range(20 - copiadas)]
    _escribir(repo / "nuevo.py", lineas_originales[40 : 40 + copiadas] + propias)
    return original, repo


def test_umbral_por_defecto_es_treinta_por_ciento():
    assert sg.UMBRAL_DEFAULT == 0.30


def test_exactamente_en_el_umbral_aprueba(monkeypatch, capsys, tmp_path):
    original, repo = _arbol_con_lineas_copiadas(tmp_path, copiadas=6)
    assert _correr(monkeypatch, original, repo) == sg.SALIDA_APROBADO
    assert "30.0%" in capsys.readouterr().out


def test_por_encima_del_umbral_falla(monkeypatch, capsys, tmp_path):
    original, repo = _arbol_con_lineas_copiadas(tmp_path, copiadas=8)
    assert _correr(monkeypatch, original, repo) == sg.SALIDA_RECHAZADO
    assert "40.0%" in capsys.readouterr().out


def test_umbral_es_configurable(monkeypatch, tmp_path):
    original, repo = _arbol_con_lineas_copiadas(tmp_path, copiadas=8)
    assert _correr(monkeypatch, original, repo, "--umbral", "0.5") == sg.SALIDA_APROBADO
    assert _correr(monkeypatch, original, repo, "--umbral", "0.1") == sg.SALIDA_RECHAZADO


@pytest.mark.parametrize("valor", ["-0.1", "1.5", "abc", "nan", "inf", "30"])
def test_umbral_invalido_termina_con_error(monkeypatch, capsys, arboles, valor):
    with pytest.raises(SystemExit) as exc:
        _correr(monkeypatch, arboles["original"], arboles["distinto"], "--umbral", valor)
    assert exc.value.code == sg.SALIDA_ERROR_CONFIG
    assert "umbral" in capsys.readouterr().err.lower()


# --- reporte: solo nombres, líneas y porcentajes ---------------------------


def test_reporte_muestra_nombre_lineas_y_porcentaje(monkeypatch, capsys, tmp_path):
    original, repo = _arbol_con_lineas_copiadas(tmp_path, copiadas=8)
    _correr(monkeypatch, original, repo)
    salida = capsys.readouterr().out
    linea = next(fila for fila in salida.splitlines() if "nuevo.py" in fila)
    assert "8/20" in linea
    assert "40.0%" in linea
    assert "fuente.py" in linea


def test_reporte_nunca_imprime_contenido_ni_ruta_del_original(monkeypatch, capsys, arboles):
    _correr(monkeypatch, arboles["original"], arboles["copiado"])
    salida = capsys.readouterr()
    todo = salida.out + salida.err
    assert "UMBRAL_SECRETO" not in todo
    assert "0.4321" not in todo
    assert "def pac_paso" not in todo
    assert "pac_monto" not in todo
    assert str(arboles["original"]) not in todo
    assert str(arboles["original"].resolve()) not in todo
    assert CARPETA_CONFIDENCIAL not in todo


def test_reporte_ordena_de_mayor_a_menor_similitud(monkeypatch, capsys, tmp_path):
    original = tmp_path / "original"
    _escribir(original / "fuente.py", [f"original_{i} = {i}" for i in range(100)])
    repo = tmp_path / "repo"
    _escribir(repo / "a_bajo.py", ["original_0 = 0"] + [f"p_{i} = 0" for i in range(9)])
    _escribir(repo / "z_alto.py", [f"original_{i} = {i}" for i in range(9)] + ["p = 0"])
    _correr(monkeypatch, original, repo)
    salida = capsys.readouterr().out
    assert salida.index("z_alto.py") < salida.index("a_bajo.py")


# --- exclusiones ------------------------------------------------------------


def test_excluye_tests_docs_entornos_caches_y_no_codigo(monkeypatch, capsys, arboles):
    repo = arboles["distinto"]
    copia = _codigo("pac", 30)
    for relativa in (
        "tests/test_copia.py",
        "docs/ejemplo.py",
        ".venv/lib/copia.py",
        "venv/lib/copia.py",
        "__pycache__/copia.py",
        ".pytest_cache/copia.py",
        ".mypy_cache/copia.py",
        "skills/tests/copia.py",
        "notas.txt",
        "datos.csv",
    ):
        _escribir(repo / relativa, copia)
    assert _correr(monkeypatch, arboles["original"], repo) == sg.SALIDA_APROBADO
    salida = capsys.readouterr().out
    assert "copia.py" not in salida
    assert "notas.txt" not in salida


def test_ignora_entornos_virtuales_dentro_del_original(tmp_path):
    original = tmp_path / "original"
    _escribir(original / "propio.py", _codigo("propio_original", 5))
    _escribir(original / ".venv" / "lib" / "terceros.py", _codigo("terceros", 10))
    repo = tmp_path / "repo"
    _escribir(repo / "vendor.py", _codigo("terceros", 10))
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.similitud == 0.0


def test_extensiones_configurables(monkeypatch, tmp_path):
    original = tmp_path / "original"
    _escribir(original / "consulta.sql", [f"SELECT campo_{i} FROM tabla_{i};" for i in range(10)])
    _escribir(original / "tarifas.yaml", [f"tarifa_{i}: {i * 3}" for i in range(10)])
    repo = tmp_path / "repo"
    _escribir(repo / "consulta.sql", [f"SELECT campo_{i} FROM tabla_{i};" for i in range(10)])
    _escribir(repo / "tarifas.yaml", [f"tarifa_{i}: {i * 3}" for i in range(10)])
    _escribir(repo / "propio.py", _codigo("propio", 3))

    por_defecto = _por_archivo(sg.evaluar(repo, original))
    assert "consulta.sql" in por_defecto
    assert "tarifas.yaml" not in por_defecto

    con_yaml = _por_archivo(sg.evaluar(repo, original, extensiones=(".yaml",)))
    assert set(con_yaml) == {"tarifas.yaml"}
    assert _correr(monkeypatch, original, repo, "--ext", ".yaml") == sg.SALIDA_RECHAZADO


def test_extension_invalida_termina_con_error(monkeypatch, arboles):
    with pytest.raises(SystemExit) as exc:
        _correr(monkeypatch, arboles["original"], arboles["distinto"], "--ext", "py")
    assert exc.value.code == sg.SALIDA_ERROR_CONFIG


def test_original_dentro_del_repo_no_se_compara_consigo_mismo(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _escribir(repo / "propio.py", _codigo("propio", 5))
    original = repo / "referencia_local"
    _escribir(original / "viejo.py", _codigo("viejo", 5))
    resultados = sg.evaluar(repo, original)
    assert [r.archivo for r in resultados] == ["propio.py"]
    assert resultados[0].similitud == 0.0


def test_repo_dentro_del_original_no_cuenta_como_candidato(tmp_path):
    original = tmp_path / "original"
    _escribir(original / "viejo.py", _codigo("viejo", 5))
    repo = original / "portafolio"
    _escribir(repo / "propio.py", _codigo("propio", 5))
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.similitud == 0.0
    assert resultado.original is None


# --- casos borde y errores --------------------------------------------------


def test_repo_sin_archivos_de_codigo_no_aprueba(monkeypatch, capsys, tmp_path):
    original = tmp_path / "original"
    _escribir(original / "viejo.py", _codigo("viejo", 3))
    repo = tmp_path / "repo"
    _escribir(repo / "notas.txt", ["nada de código"])
    assert _correr(monkeypatch, original, repo) == sg.SALIDA_ERROR_CONFIG
    assert "repo" in capsys.readouterr().err.lower()


def test_original_sin_archivos_de_codigo_no_aprueba(monkeypatch, capsys, tmp_path):
    original = tmp_path / "original"
    _escribir(original / "notas.txt", ["solo texto"])
    repo = tmp_path / "repo"
    _escribir(repo / "propio.py", _codigo("propio", 3))
    assert _correr(monkeypatch, original, repo) == sg.SALIDA_ERROR_CONFIG
    salida = capsys.readouterr()
    assert "original" in salida.err.lower()
    assert str(original) not in salida.err


def test_original_igual_al_repo_no_aprueba(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    _escribir(repo / "propio.py", _codigo("propio", 3))
    assert _correr(monkeypatch, repo, repo) == sg.SALIDA_ERROR_CONFIG


def test_raiz_del_repo_inexistente_no_aprueba(monkeypatch, capsys, arboles, tmp_path):
    codigo = _correr(monkeypatch, arboles["original"], tmp_path / "no_existe")
    assert codigo == sg.SALIDA_ERROR_CONFIG
    assert "repo" in capsys.readouterr().err.lower()


def test_original_ilegible_no_aprueba_y_no_revela_su_ruta(monkeypatch, capsys, tmp_path):
    original = tmp_path / "original"
    _escribir(original / CARPETA_CONFIDENCIAL / "viejo.py", _codigo("viejo", 3))
    (original / CARPETA_CONFIDENCIAL / "roto.py").symlink_to(tmp_path / "destino_inexistente.py")
    repo = tmp_path / "repo"
    _escribir(repo / "propio.py", _codigo("propio", 3))
    assert _correr(monkeypatch, original, repo) == sg.SALIDA_ERROR_CONFIG
    error = capsys.readouterr().err
    assert "roto.py" in error
    assert CARPETA_CONFIDENCIAL not in error
    assert str(tmp_path) not in error


def test_archivo_del_repo_ilegible_no_aprueba(monkeypatch, capsys, tmp_path):
    original = tmp_path / "original"
    _escribir(original / "viejo.py", _codigo("viejo", 3))
    repo = tmp_path / "repo"
    _escribir(repo / "propio.py", _codigo("propio", 3))
    (repo / "skills").mkdir()
    (repo / "skills" / "roto.py").symlink_to(tmp_path / "destino_inexistente.py")
    assert _correr(monkeypatch, original, repo) == sg.SALIDA_ERROR_CONFIG
    assert "skills/roto.py" in capsys.readouterr().err


def test_archivo_vacio_en_repo_tiene_similitud_cero(tmp_path):
    original = tmp_path / "original"
    _escribir(original / "viejo.py", _codigo("viejo", 3))
    repo = tmp_path / "repo"
    (repo).mkdir()
    (repo / "__init__.py").write_text("", encoding="utf-8")
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.lineas == 0
    assert resultado.similitud == 0.0


def test_original_con_bytes_no_utf8_y_unicode_no_rompe(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    (original / "latino.py").write_bytes("nombre = 'Conciliación'\nañadir = 1\n".encode("latin-1"))
    _escribir(original / "unicode.py", ["mensaje = 'Póliza ✓ ñandú'", "total = sumar(\"';--\")"])
    repo = tmp_path / "repo"
    _escribir(repo / "unicode.py", ["mensaje = 'Póliza ✓ ñandú'", "total = sumar(\"';--\")"])
    (resultado,) = sg.evaluar(repo, original)
    assert resultado.similitud == 1.0


def test_volumen_grande_termina_rapido_y_encuentra_la_copia(tmp_path):
    # Encabezado y cierre comunes: toda pareja comparte algunas líneas, así que
    # las cotas de poda trabajan con intersecciones distintas de cero.
    comun = ["from __future__ import annotations", "import os", "import sys"]
    cierre = ['if __name__ == "__main__":', "main()"]
    original = tmp_path / "original"
    for i in range(400):
        lineas = comun + _codigo(f"orig{i}", 40) + cierre
        _escribir(original / f"mod_{i:03d}" / f"archivo_{i:03d}.py", lineas)
    repo = tmp_path / "repo"
    for i in range(15):
        _escribir(repo / f"nuevo_{i:02d}.py", comun + _codigo(f"repo{i}", 40) + cierre)
    _escribir(repo / "renombrado.py", comun + _codigo("orig217", 40) + cierre)

    inicio = time.perf_counter()
    resultados = _por_archivo(sg.evaluar(repo, original))
    duracion = time.perf_counter() - inicio

    assert resultados["renombrado.py"].original == "archivo_217.py"
    assert resultados["renombrado.py"].similitud == 1.0
    otros = [r for k, r in resultados.items() if k != "renombrado.py"]
    assert len(otros) == 15
    assert all(0.0 < r.similitud < 0.1 for r in otros)
    assert duracion < 20.0


# --- extremo a extremo (subproceso) ----------------------------------------


def _subproceso(env_extra: dict, *args: str) -> subprocess.CompletedProcess:
    entorno = {k: v for k, v in os.environ.items() if k != sg.VARIABLE_ORIGINAL}
    entorno.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=entorno,
        timeout=120,
        check=False,
    )


def test_cli_sin_variable_de_entorno_sale_con_error(arboles):
    proceso = _subproceso({}, "--raiz", str(arboles["distinto"]))
    assert proceso.returncode == sg.SALIDA_ERROR_CONFIG
    assert sg.VARIABLE_ORIGINAL in proceso.stderr


def test_cli_arbol_copiado_sale_distinto_de_cero(arboles):
    proceso = _subproceso(
        {sg.VARIABLE_ORIGINAL: str(arboles["original"])}, "--raiz", str(arboles["copiado"])
    )
    assert proceso.returncode == sg.SALIDA_RECHAZADO
    assert "emparejador.py" in proceso.stdout
    assert str(arboles["original"]) not in proceso.stdout + proceso.stderr


def test_cli_arbol_distinto_sale_con_cero(arboles):
    proceso = _subproceso(
        {sg.VARIABLE_ORIGINAL: str(arboles["original"])}, "--raiz", str(arboles["distinto"])
    )
    assert proceso.returncode == sg.SALIDA_APROBADO, proceso.stdout + proceso.stderr


def test_coincidencia_de_pocas_lineas_no_reprueba():
    assert sg.supera_umbral(0.60, 0.30, coincidentes=3) is False
    assert sg.supera_umbral(0.60, 0.30, coincidentes=sg.MIN_LINEAS_COINCIDENTES) is True
