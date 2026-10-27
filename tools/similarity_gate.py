#!/usr/bin/env python3
"""Compuerta clean-room de similitud (`similarity_gate.py`).

Compara cada archivo de código del repo contra el material de referencia y reporta la
similitud por archivo. Es la prueba objetiva del ADR 0001: ningún archivo puede
superar el umbral (30% por defecto) contra el original.

Compuerta previa a publicar: debe pasar antes del primer push al
repo nuevo, junto con el sanitizer y el CI completo. NO corre en el CI público
(publicación), porque el original solo existe en la máquina del autor.

Uso:
    CLEANROOM_ORIGINAL_DIR=<carpeta del original> python3 tools/similarity_gate.py
    python3 tools/similarity_gate.py --umbral 0.25 --ext .py --ext .sql --raiz .

Reglas:
  1. La ruta del original se recibe SOLO por la variable de entorno
     CLEANROOM_ORIGINAL_DIR. Nunca se escribe en el repo ni se imprime.
  2. El reporte solo muestra nombres de archivo, conteos de líneas y
     porcentajes. Nunca imprime contenido del original (del original solo se
     muestra el nombre del archivo, sin su carpeta).
  3. Cada archivo del repo se empareja por nombre y por mejor coincidencia de
     contenido contra todo el original, para detectar archivos renombrados.

Métrica (sobre líneas normalizadas: sin sangría, sin líneas vacías ni líneas
de pura puntuación), con M = líneas coincidentes según `difflib`:
    similitud = max(2M / (líneas_repo + líneas_original), M / líneas_repo)
El primer término es el ratio clásico de difflib (detecta un original completo
incrustado en un archivo mayor); el segundo, la fracción del archivo del repo
que proviene del original (detecta extractos de un original grande).

Códigos de salida:
    0  aprobado: ningún archivo supera el umbral.
    1  no aprobado: al menos un archivo supera el umbral.
    2  error de configuración (variable ausente, ruta inválida, árbol vacío,
       argumentos inválidos). Nunca cuenta como aprobado.
"""
from __future__ import annotations

import argparse
import math
import os
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from types import MappingProxyType
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

VARIABLE_ORIGINAL = "CLEANROOM_ORIGINAL_DIR"
UMBRAL_DEFAULT = 0.30
EXTENSIONES_DEFAULT: Tuple[str, ...] = (".py", ".sql", ".sh", ".js", ".ts", ".json", ".md")

# Carpetas de ruido que se ignoran en ambos árboles (además de toda carpeta oculta).
DIRS_RUIDO: FrozenSet[str] = frozenset(
    {"venv", "env", "__pycache__", "node_modules", "htmlcov", "build", "dist"}
)
# En el repo tampoco se evalúan pruebas ni documentación.
DIRS_EXCLUIDOS_REPO: FrozenSet[str] = DIRS_RUIDO | {"tests", "docs"}

SALIDA_APROBADO = 0
SALIDA_RECHAZADO = 1
SALIDA_ERROR_CONFIG = 2

CRITERIO_NOMBRE = "nombre"
CRITERIO_CONTENIDO = "contenido"
CRITERIO_NINGUNO = "sin coincidencia"

ANCHO_SEPARADOR = 78


class ErrorConfiguracion(Exception):
    """Configuración inválida: la compuerta no puede emitir un veredicto."""


@dataclass(frozen=True)
class ArchivoCodigo:
    ruta: str  # relativa a su raíz, en formato posix; nunca absoluta
    nombre: str
    lineas: Tuple[str, ...]
    conteo: Mapping[str, int] = field(compare=False, repr=False)


@dataclass(frozen=True)
class Resultado:
    archivo: str  # ruta relativa dentro del repo
    lineas: int  # líneas significativas del archivo del repo
    coincidentes: int
    similitud: float
    original: Optional[str]  # solo el nombre del archivo original
    criterio: str


@dataclass(frozen=True)
class Evaluacion:
    resultados: Tuple[Resultado, ...]  # de mayor a menor similitud
    n_originales: int


# --- normalización y métrica -----------------------------------------------


def normalizar_lineas(texto: str) -> Tuple[str, ...]:
    """Quita sangría, líneas vacías y líneas sin ningún carácter alfanumérico."""
    limpias = (linea.strip() for linea in texto.splitlines())
    return tuple(linea for linea in limpias if any(c.isalnum() for c in linea))


def _similitud_de(n_repo: int, n_original: int, comunes: int) -> float:
    if n_repo == 0 or n_original == 0:
        return 0.0
    return max(2 * comunes / (n_repo + n_original), comunes / n_repo)


def medir_similitud(
    lineas_repo: Sequence[str], lineas_original: Sequence[str]
) -> Tuple[int, float]:
    """Devuelve (líneas coincidentes, similitud) entre dos listas normalizadas."""
    if not lineas_repo or not lineas_original:
        return 0, 0.0
    comparador = SequenceMatcher(None, lineas_repo, lineas_original, autojunk=False)
    coincidentes = sum(bloque.size for bloque in comparador.get_matching_blocks())
    return coincidentes, _similitud_de(len(lineas_repo), len(lineas_original), coincidentes)


def _interseccion(a: Mapping[str, int], b: Mapping[str, int]) -> int:
    """Líneas en común como multiconjunto: cota superior barata de M."""
    menor, mayor = (a, b) if len(a) <= len(b) else (b, a)
    return sum(min(n, mayor.get(linea, 0)) for linea, n in menor.items())


# Coincidir en menos líneas que esto no prueba copia: un `__main__.py` de 5 líneas
# comparte `import sys` y `sys.exit(main())` con cualquier script del original.
MIN_LINEAS_COINCIDENTES = 8


def supera_umbral(similitud: float, umbral: float, coincidentes: int = MIN_LINEAS_COINCIDENTES) -> bool:
    return similitud > umbral and coincidentes >= MIN_LINEAS_COINCIDENTES


# --- recorrido de árboles --------------------------------------------------


def _dir_excluido(ruta: Path, excluidos: FrozenSet[str], vetadas: FrozenSet[Path]) -> bool:
    nombre = ruta.name
    if nombre.startswith(".") or nombre in excluidos or nombre.endswith(".egg-info"):
        return True
    return ruta.resolve() in vetadas


def listar_archivos(
    raiz: Path,
    extensiones: Sequence[str],
    excluidos: FrozenSet[str],
    vetadas: FrozenSet[Path] = frozenset(),
) -> List[Path]:
    """Archivos de código bajo `raiz`, ordenados, sin carpetas excluidas o vetadas."""
    sufijos = frozenset(e.lower() for e in extensiones)
    encontrados: List[Path] = []
    for actual, dirs, archivos in os.walk(raiz):
        base = Path(actual)
        # os.walk exige podar en sitio la lista de subcarpetas.
        dirs[:] = sorted(d for d in dirs if not _dir_excluido(base / d, excluidos, vetadas))
        encontrados.extend(base / a for a in sorted(archivos) if Path(a).suffix.lower() in sufijos)
    return encontrados


def _leer(ruta: Path, etiqueta: str) -> Tuple[str, ...]:
    try:
        return normalizar_lineas(ruta.read_text(encoding="utf-8", errors="replace"))
    except OSError as exc:
        # strerror no incluye la ruta; solo se expone la etiqueta (nombre relativo).
        raise ErrorConfiguracion(f"no se pudo leer '{etiqueta}': {exc.strerror}") from None


def cargar_arbol(
    raiz: Path,
    extensiones: Sequence[str],
    excluidos: FrozenSet[str],
    vetadas: FrozenSet[Path],
    es_original: bool,
) -> List[ArchivoCodigo]:
    cargados: List[ArchivoCodigo] = []
    for ruta in listar_archivos(raiz, extensiones, excluidos, vetadas):
        relativa = ruta.relative_to(raiz).as_posix()
        lineas = _leer(ruta, ruta.name if es_original else relativa)
        conteo = MappingProxyType(Counter(lineas))
        cargados.append(ArchivoCodigo(relativa, ruta.name, lineas, conteo))
    return cargados


# --- emparejamiento --------------------------------------------------------


def _comparar(archivo: ArchivoCodigo, original: ArchivoCodigo, criterio: str) -> Resultado:
    coincidentes, similitud = medir_similitud(archivo.lineas, original.lineas)
    return Resultado(
        archivo.ruta, len(archivo.lineas), coincidentes, similitud, original.nombre, criterio
    )


def _candidatos_por_contenido(
    archivo: ArchivoCodigo,
    originales: Sequence[ArchivoCodigo],
    omitir: FrozenSet[int],
    piso: float,
) -> List[Tuple[float, int]]:
    """(cota superior, índice) de los originales que podrían superar `piso`, de mayor a menor."""
    n = len(archivo.lineas)
    candidatos: List[Tuple[float, int]] = []
    for indice, original in enumerate(originales):
        m = len(original.lineas)
        if indice in omitir or _similitud_de(n, m, min(n, m)) <= piso:
            continue
        cota = _similitud_de(n, m, _interseccion(archivo.conteo, original.conteo))
        if cota > piso:
            candidatos.append((cota, indice))
    return sorted(candidatos, key=lambda par: (-par[0], par[1]))


def mejor_coincidencia(
    archivo: ArchivoCodigo,
    originales: Sequence[ArchivoCodigo],
    indice_nombres: Mapping[str, Tuple[int, ...]],
) -> Resultado:
    """Mejor par en el original: primero por nombre, luego por contenido (ramificar y acotar)."""
    homonimos = indice_nombres.get(archivo.nombre.lower(), ())
    mejor = Resultado(archivo.ruta, len(archivo.lineas), 0, 0.0, None, CRITERIO_NINGUNO)
    for posicion, indice in enumerate(homonimos):
        candidato = _comparar(archivo, originales[indice], CRITERIO_NOMBRE)
        if posicion == 0 or candidato.similitud > mejor.similitud:
            mejor = candidato
    candidatos = _candidatos_por_contenido(
        archivo, originales, frozenset(homonimos), mejor.similitud
    )
    for cota, indice in candidatos:
        if cota <= mejor.similitud:
            break
        candidato = _comparar(archivo, originales[indice], CRITERIO_CONTENIDO)
        if candidato.similitud > mejor.similitud:
            mejor = candidato
    return mejor


def _indexar_nombres(originales: Sequence[ArchivoCodigo]) -> Dict[str, Tuple[int, ...]]:
    agrupados: Dict[str, List[int]] = defaultdict(list)
    for posicion, original in enumerate(originales):
        agrupados[original.nombre.lower()].append(posicion)
    return {nombre: tuple(posiciones) for nombre, posiciones in agrupados.items()}


def evaluar_arboles(
    raiz_repo: Path,
    raiz_original: Path,
    extensiones: Sequence[str] = EXTENSIONES_DEFAULT,
) -> Evaluacion:
    """Evalúa cada archivo de código del repo contra todo el original."""
    repo = Path(raiz_repo).resolve()
    original = Path(raiz_original).resolve()
    if not repo.is_dir():
        raise ErrorConfiguracion("la raíz del repo no existe o no es una carpeta.")
    if repo == original:
        raise ErrorConfiguracion(f"{VARIABLE_ORIGINAL} apunta al mismo repo que se evalúa.")

    archivos = cargar_arbol(repo, extensiones, DIRS_EXCLUIDOS_REPO, frozenset({original}), False)
    if not archivos:
        raise ErrorConfiguracion("no se encontraron archivos de código en el repo.")
    originales = cargar_arbol(original, extensiones, DIRS_RUIDO, frozenset({repo}), True)
    if not originales:
        raise ErrorConfiguracion(
            "no se encontraron archivos de código en el original; revisa la variable."
        )

    indice = _indexar_nombres(originales)
    resultados = (mejor_coincidencia(a, originales, indice) for a in archivos)
    ordenados = tuple(sorted(resultados, key=lambda r: (-r.similitud, r.archivo)))
    return Evaluacion(ordenados, len(originales))


def evaluar(
    raiz_repo: Path,
    raiz_original: Path,
    extensiones: Sequence[str] = EXTENSIONES_DEFAULT,
) -> List[Resultado]:
    """Resultados por archivo del repo, de mayor a menor similitud."""
    return list(evaluar_arboles(raiz_repo, raiz_original, extensiones).resultados)


# --- configuración y reporte -----------------------------------------------


def resolver_ruta_original(entorno: Mapping[str, str]) -> Path:
    """Lee la ruta del original desde el entorno. El mensaje de error nunca la incluye."""
    valor = entorno.get(VARIABLE_ORIGINAL, "").strip()
    if not valor:
        raise ErrorConfiguracion(
            f"la variable de entorno {VARIABLE_ORIGINAL} no está definida. Defínela con "
            "la carpeta del material de referencia (fuera del repo) para correr la compuerta."
        )
    ruta = Path(valor).expanduser().resolve()
    if not ruta.is_dir():
        raise ErrorConfiguracion(
            f"la ruta indicada en {VARIABLE_ORIGINAL} no existe o no es una carpeta."
        )
    return ruta


def formatear_reporte(
    resultados: Sequence[Resultado], umbral: float, n_originales: int
) -> List[str]:
    """Solo nombres de archivo, conteos de líneas y porcentajes."""
    separador = "=" * ANCHO_SEPARADOR
    encabezado = (
        f"Compuerta clean-room de similitud | umbral {umbral:.1%} | "
        f"{len(resultados)} archivo(s) del repo vs {n_originales} del original"
    )
    filas = [
        encabezado,
        separador,
        f"{'ESTADO':<7}{'SIMILITUD':>10}  {'LINEAS':>11}  ARCHIVO -> ORIGINAL (criterio)",
    ]
    for r in resultados:
        estado = "FALLA" if supera_umbral(r.similitud, umbral, r.coincidentes) else "OK"
        lineas = f"{r.coincidentes}/{r.lineas}"
        filas.append(
            f"{estado:<7}{r.similitud:>10.1%}  {lineas:>11}  "
            f"{r.archivo} -> {r.original or '-'} ({r.criterio})"
        )
    fallas = sum(1 for r in resultados if supera_umbral(r.similitud, umbral, r.coincidentes))
    filas.append(separador)
    if fallas:
        filas.append(
            f"RESULTADO: NO APROBADO. {fallas} de {len(resultados)} archivo(s) "
            f"superan el umbral de {umbral:.1%}."
        )
    else:
        filas.append(f"RESULTADO: APROBADO. Ningún archivo supera el umbral de {umbral:.1%}.")
    return filas


def _umbral(texto: str) -> float:
    try:
        valor = float(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"umbral inválido: '{texto}' no es un número.") from None
    if not math.isfinite(valor) or not 0.0 <= valor <= 1.0:
        raise argparse.ArgumentTypeError(
            f"umbral inválido: {texto}. Usa una fracción entre 0 y 1 (p. ej. 0.30)."
        )
    return valor


def _extension(texto: str) -> str:
    ext = texto.strip().lower()
    if not ext.startswith(".") or len(ext) < 2:
        raise argparse.ArgumentTypeError(f"extensión inválida: '{texto}'. Usa la forma '.py'.")
    return ext


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compuerta clean-room: similitud por archivo contra el material de referencia.",
        epilog=f"La ruta del original se lee SOLO de la variable de entorno {VARIABLE_ORIGINAL}. "
        "Compuerta previa a publicar; no corre en el CI público.",
    )
    parser.add_argument(
        "--umbral", type=_umbral, default=UMBRAL_DEFAULT,
        help=f"Fracción máxima de similitud permitida por archivo (default {UMBRAL_DEFAULT}).",
    )
    parser.add_argument(
        "--raiz", type=Path, default=Path(__file__).resolve().parents[1],
        help="Raíz del repo a evaluar (default: la raíz de este repo).",
    )
    parser.add_argument(
        "--ext", dest="extensiones", type=_extension, action="append",
        help="Extensión a evaluar; repetible. Reemplaza el default "
        f"({' '.join(EXTENSIONES_DEFAULT)}).",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    extensiones = tuple(args.extensiones or EXTENSIONES_DEFAULT)
    try:
        original = resolver_ruta_original(os.environ)
        evaluacion = evaluar_arboles(args.raiz, original, extensiones)
    except ErrorConfiguracion as exc:
        print(f"Error: {exc}\nRESULTADO: NO APROBADO (sin veredicto).", file=sys.stderr)
        return SALIDA_ERROR_CONFIG
    print("\n".join(formatear_reporte(evaluacion.resultados, args.umbral, evaluacion.n_originales)))
    if any(supera_umbral(r.similitud, args.umbral, r.coincidentes) for r in evaluacion.resultados):
        return SALIDA_RECHAZADO
    return SALIDA_APROBADO


if __name__ == "__main__":
    sys.exit(main())
