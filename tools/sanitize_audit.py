#!/usr/bin/env python3
"""Sanitizer de PII, identificadores fiscales, credenciales y huellas narrativas (`sanitize_audit.py`).

Revisa todos los archivos de texto (UTF-8 estricto) y los XML internos y metadatos de los
libros `.xlsx` para garantizar que no se filtre:
  1. Llaves de API, JWTs o tokens de proyectos en la nube.
  2. Rutas locales del desarrollador (`/Users/...`, `/home/...`).
  3. RFCs mexicanos no genéricos (se permiten los RFC genéricos del SAT y `RFC_*`).
  4. UUIDs fiscales no sintéticos (se permiten los UUID de prueba con prefijo de ceros).
  5. CLABEs bancarias de 18 dígitos.
  6. Correos de dominios que no son de ejemplo.
  7. Huellas narrativas de origen: fechas con forma de bitácora de fixes,
     referencias a hallazgos y auditorías, aprobaciones y cargos, vocabulario de flujo
     interno y seudónimos de empresa conocidos.

Alcance de las reglas:
  - Estructuradas (alcance "linea"): la línea física completa de cualquier archivo.
  - Narrativas (alcance "texto"): solo el texto que lee una persona. En `.py`, los
    comentarios y strings (incluye docstrings), nunca identificadores ni código; si el
    módulo no tokeniza, la línea completa (falla cerrada). En `.xlsx`, los nodos de texto
    fuera de fórmulas. En el resto (Markdown, JSON, YAML...), la línea completa.
  - `H\\d` y las fechas `mes-AAAA` sueltas solo cuentan en fragmentos de prosa (con al
    menos un espacio): así no se marcan celdas (`ws["H1"]`, `A1:H20`) ni etiquetas de
    periodo (`"jul-2026"`). Tampoco `H1 2026` / `H2-2026` / `H1 FY27` (semestres).
  - "hallazgo" y "auditoría" sueltos son vocabulario del propio auditor de P&L; solo se
    marcan como referencia: `hallazgo H1`, `hallazgos v4`, `auditoría Mayo`,
    `auditoría 2026-08-21`, `auditoría externa`.

Excepciones: `tools/sanitize_exceptions.json` (o `--exceptions`) es la lista versionada de
falsos positivos legítimos; cada entrada exige una justificación. Las rutas se comparan
relativas a la raíz auditada (en modo archivo, relativas al directorio actual).

Códigos de salida: 0 limpio, 1 con alertas, 2 configuración inválida.
"""
from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import re
import sys
import tokenize
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Sequence, Set, Tuple

ALCANCE_LINEA = "linea"
ALCANCE_TEXTO = "texto"
ALCANCES = frozenset({ALCANCE_LINEA, ALCANCE_TEXTO})


@dataclass(frozen=True)
class Regla:
    """Regla de detección. Varias reglas pueden compartir `id` (una misma categoría)."""

    id: str
    patron: str
    descripcion: str
    alcance: str = ALCANCE_LINEA


class Alerta(NamedTuple):
    linea: int
    regla: str
    descripcion: str


@dataclass(frozen=True)
class Excepcion:
    """Exime `reglas` en los archivos que coinciden con `ruta` (y en las líneas con `coincide`)."""

    reglas: Tuple[str, ...]
    ruta: str
    coincide: Optional[str]
    justificacion: str


FORBIDDEN_PATTERNS: Tuple[Regla, ...] = (
    # 1. Llaves de API, JWTs y credenciales de nube
    Regla("llave_publicable", r"sb_publishable_[A-Za-z0-9_-]{20,}", "Llave API publicable en vivo detectada"),
    Regla(
        "jwt",
        r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+",
        "Token JWT en vivo detectado",
    ),
    Regla("llave_secreta", r"sk-[A-Za-z0-9]{20,}", "Llave API secreta (sk-...) detectada"),
    Regla(
        "url_nube",
        r"https://(?!your-project-id)[a-z0-9]{20}\.supabase\.co",
        "URL de proyecto en la nube en vivo detectada",
    ),
    # 2. Rutas locales del sistema operativo
    Regla("ruta_macos", r"/Users/[A-Za-z0-9_.-]+/", "Ruta absoluta de usuario macOS (/Users/...) detectada"),
    Regla("ruta_linux", r"/home/(?!user\b)[A-Za-z0-9_.-]+/", "Ruta absoluta de usuario Linux (/home/...) detectada"),
    # 3. RFCs, sin los genéricos del SAT ni los marcadores RFC_* de prueba
    Regla(
        "rfc",
        r"\b(?!XAXX010101000\b|XEXX010101000\b|RFC_[A-Z0-9_]+\b)[A-ZÑ&]{3,4}\d{6}[A-Z0-9]{3}\b",
        "RFC mexicano no genérico detectado (usa XAXX010101000 o RFC_SAMPLE)",
    ),
    # 4. UUIDs de CFDI, sin los sintéticos con prefijo de ceros
    Regla(
        "uuid",
        r"\b(?!00000000-0000-0000-0000-0000000000\d{2}\b)[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "UUID no sintético detectado (usa 00000000-0000-0000-0000-000000000000)",
    ),
    # 5. CLABEs de 18 dígitos
    Regla("clabe", r"\b\d{18}\b", "CLABE bancaria de 18 dígitos detectada"),
    # 6. Correos de dominios que no son de ejemplo
    Regla(
        "correo",
        r"\b[A-Za-z0-9._%+-]+@(?!company\.com\b|example\.com\b|users\.noreply\.github\.com\b)"
        r"[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        "Correo de dominio que no es de ejemplo detectado",
    ),
)

# Meses en español e inglés, abreviados o completos.
_MES = (
    r"(?:ene(?:ro)?|jan(?:uary)?|feb(?:rero|ruary)?|mar(?:zo|ch)?|abr(?:il)?|apr(?:il)?"
    r"|may(?:o)?|jun(?:io|e)?|jul(?:io|y)?|ago(?:sto)?|aug(?:ust)?|sep(?:t(?:iembre|ember)?)?"
    r"|set(?:iembre)?|oct(?:ubre|ober)?|nov(?:iembre|ember)?|dic(?:iembre)?|dec(?:ember)?)\.?"
)
# "jul-2026", "6-jul-2026", "jun 2026", "25 de julio de 2026".
_FECHA_MES = r"(?:\d{1,2}[-\s](?:de\s+)?)?" + _MES + r"[-\s]+(?:de\s+)?(?:19|20)\d{2}\b"
# Prefijo para reglas que solo aplican a prosa: el fragmento contiene al menos un espacio.
_PROSA = r"^(?=.*\s).*?"

REGLAS_NARRATIVAS: Tuple[Regla, ...] = (
    # 1. Fechas con forma de bitácora de fixes
    Regla(
        "fecha_bitacora",
        r"(?i)\b(?:hot)?fix(?:ed|es)?\b[\s:(\-]*(?:del?\s+)?\d{4}-\d{2}-\d{2}\b",
        "Fecha de bitácora de fix (fix AAAA-MM-DD)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "fecha_bitacora",
        r"(?i)\b(?:corregid[oa]s?|arreglad[oa]s?|parchad[oa]s?|parche)\b[^.\n]{0,20}?"
        r"(?:\d{4}-\d{2}-\d{2}\b|\b" + _FECHA_MES + ")",
        "Fecha de bitácora de corrección (corregido en mes AAAA)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "fecha_bitacora",
        r"(?i)\b(?:desde|hasta|a\s+partir\s+del?|since|until|as\s+of)\s+(?:el\s+|the\s+)?" + _FECHA_MES,
        "Fecha de bitácora de vigencia (desde mes-AAAA)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "fecha_bitacora",
        r"(?i)" + _PROSA + r"\b(?:\d{1,2}-)?" + _MES + r"-(?:19|20)\d{2}\b",
        "Fecha mes-AAAA en prosa (bitácora)",
        ALCANCE_TEXTO,
    ),
    # 2. Referencias a hallazgos y auditorías
    Regla(
        "referencia_auditoria",
        _PROSA + r"(?<![\w$:\"'=])H\d{1,2}(?![\w$\"'])(?!:\$?[A-Za-z])(?![\s-]?(?:(?:19|20)\d{2}|FY\s?\d{2,4})\b)",
        "Referencia a hallazgo (H1, H2...)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "referencia_auditoria",
        r"(?i)\bhallazgos?\b\s*(?:#\s*)?(?:[a-z]{1,2}-?\d+|\d+)\b",
        "Referencia a hallazgo identificado (hallazgo H1, hallazgos v4)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "referencia_auditoria",
        r"(?i)\bauditor[ií]as?\b[\s(]+(?:del?\s+)?(?:(?:19|20)\d{2}\b|\d{1,2}[-/]\d|" + _MES
        + r"\b|extern[ao]s?\b|intern[ao]s?\b|anual(?:es)?\b|v\d+\b|r\d+\b|q[1-4]\b)",
        "Referencia a una auditoría concreta (auditoría Mayo, auditoría externa)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "referencia_auditoria",
        r"(?i)\b(?:external|internal)\s+audit(?:ors?|s)?\b",
        "Referencia a una auditoría concreta (external audit)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "referencia_auditoria",
        r"(?i)\bv\d+\s*[._-]?\s*r\d+\b",
        "Referencia a versión y ronda de revisión (v4 R3)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "referencia_ticket",
        r"(?i)\bticket\s*#?\d{1,3}\b|\bdocs/tickets?\b|plan-remediacion",
        "Referencia a un ticket o plan de trabajo interno (ticket 03, docs/tickets)",
        ALCANCE_TEXTO,
    ),
    # 3. Aprobaciones y cargos
    Regla(
        "aprobacion_cargo",
        r"(?i)\b(?:autorizad[oa]s?|aprobad[oa]s?|approved|authori[sz]ed|signed[\s-]off)\s+(?:por|by)\b",
        "Aprobación atribuida (autorizado por, approved by)",
        ALCANCE_TEXTO,
    ),
    Regla("aprobacion_cargo", r"(?i)\bv[oº]\.?\s?b[oº]\b\.?", "Visto bueno atribuido (VoBo)", ALCANCE_TEXTO),
    Regla("aprobacion_cargo", r"\b(?:CFO|CEO|COO)\b", "Cargo directivo (CFO, CEO, COO)", ALCANCE_TEXTO),
    Regla(
        "aprobacion_cargo",
        r"\bController\b|(?i:\bfinancial\s+controller\b)",
        "Cargo directivo (Controller)",
        ALCANCE_TEXTO,
    ),
    Regla(
        "aprobacion_cargo",
        r"(?i)\b(?:director(?:a|es|as)?|contralor(?:a|es|as)?|gerentes?)\b",
        "Cargo directivo (Director, Contralor, Gerente)",
        ALCANCE_TEXTO,
    ),
    # 4. Vocabulario de flujo interno. "oficial" regulatorio (DOF, SAT, Banxico, NOM,
    #    tipo de cambio) no es huella de origen y se deja pasar.
    Regla(
        "flujo_interno",
        r"(?i)(?<!diario )(?<!cambio )(?<!norma )\boficial(?:es|mente)?\b"
        r"(?!\s+(?:del?\s+)?(?:la\s+)?(?:sat|banxico|dof|federaci[oó]n)\b)",
        "Vocabulario de flujo interno (oficial)",
        ALCANCE_TEXTO,
    ),
    Regla("flujo_interno", r"(?i)\bpromovid[oa]s?\b", "Vocabulario de flujo interno (promovido)", ALCANCE_TEXTO),
    Regla(
        "flujo_interno",
        r"(?i)\bvalidated\s+period\s+close\b|\bcierre\s+validado\b",
        "Vocabulario de flujo interno (validated period close)",
        ALCANCE_TEXTO,
    ),
    # 5. Seudónimos de empresa conocidos (agregar aquí los nuevos)
    Regla(
        "seudonimo_empresa",
        r"(?i)(?<![a-z])enterprise[\s_-]?corp(?![a-z])",
        "Seudónimo de empresa conocido (EnterpriseCorp)",
        ALCANCE_TEXTO,
    ),
)

DEFAULT_REPLACEMENTS: List[Tuple[str, str]] = [
    (r"/Users/[A-Za-z0-9_.-]+/", "~/"),
    (r"/home/(?!user\b)[A-Za-z0-9_.-]+/", "~/"),
    (
        r"\b(?!00000000-0000-0000-0000-0000000000\d{2}\b)[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
        r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b",
        "00000000-0000-0000-0000-000000000000",
    ),
]

BINARY_SKIP_EXTENSIONS = frozenset({".xls", ".png", ".jpg", ".jpeg", ".pdf", ".zip", ".pyc"})
EXTENSIONES_PYTHON = frozenset({".py", ".pyi"})
# `.git` también es archivo en worktrees y submódulos (apunta con ruta absoluta al repo).
DIRECTORIOS_OMITIDOS = frozenset(
    {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".venv", "venv", "ENV", "htmlcov"}
)
ARCHIVOS_OMITIDOS = frozenset({".git", ".DS_Store", ".coverage"})
MAX_ALERTAS_POR_ARCHIVO = 5
LARGO_MINIMO_JUSTIFICACION = 20

RUTA_PROPIA = os.path.realpath(__file__)
RUTA_EXCEPCIONES_DEFAULT = os.path.join(os.path.dirname(RUTA_PROPIA), "sanitize_exceptions.json")

_TOKENS_TEXTO = frozenset(
    t
    for t in (
        tokenize.COMMENT,
        tokenize.STRING,
        getattr(tokenize, "FSTRING_MIDDLE", None),  # Python 3.12+
        getattr(tokenize, "TSTRING_MIDDLE", None),  # Python 3.14+
    )
    if t is not None
)
_FORMULA_XML = re.compile(r"<((?:\w+:)?(?:f|formula\d?))\b[^>]*(?<!/)>.*?</\1>")
_ETIQUETA_XML = re.compile(r"<[^>]*>")

_LineaAuditable = Tuple[int, str, Tuple[str, ...]]


# ── Carga y validación de configuración ──────────────────────────────────────


def _compilar(patron: str, contexto: str) -> None:
    try:
        re.compile(patron)
    except re.error as exc:
        raise ValueError(f"{contexto}: regex inválida {patron!r}: {exc}") from exc


def _regla_personalizada(item: Any, indice: int) -> Regla:
    contexto = f"regla personalizada #{indice}"
    try:
        patron, descripcion = item["pattern"], item["description"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{contexto}: requiere 'pattern' y 'description'") from exc
    alcance = item.get("alcance", ALCANCE_LINEA)
    if alcance not in ALCANCES:
        raise ValueError(f"{contexto}: 'alcance' debe ser uno de {sorted(ALCANCES)}")
    _compilar(patron, contexto)
    return Regla(str(item.get("id", f"personalizada_{indice}")), patron, descripcion, alcance)


def _reemplazo_personalizado(item: Any, indice: int) -> Tuple[str, str]:
    contexto = f"reemplazo personalizado #{indice}"
    try:
        patron, reemplazo = item["pattern"], item["replacement"]
    except (KeyError, TypeError) as exc:
        raise ValueError(f"{contexto}: requiere 'pattern' y 'replacement'") from exc
    _compilar(patron, contexto)
    return patron, reemplazo


def load_custom_rules(rules_path: Optional[str]) -> Tuple[List[Regla], List[Tuple[str, str]]]:
    """Reglas integradas (estructuradas + narrativas) más las de un JSON opcional."""
    reglas = list(FORBIDDEN_PATTERNS) + list(REGLAS_NARRATIVAS)
    reemplazos = list(DEFAULT_REPLACEMENTS)
    if not rules_path:
        return reglas, reemplazos
    with open(rules_path, "r", encoding="utf-8") as f:
        datos = json.load(f)
    if not isinstance(datos, dict):
        raise ValueError(f"{rules_path}: se esperaba un objeto JSON")
    nuevas = [_regla_personalizada(item, i) for i, item in enumerate(datos.get("forbidden_patterns", []), 1)]
    nuevos = [_reemplazo_personalizado(item, i) for i, item in enumerate(datos.get("replacements", []), 1)]
    return reglas + nuevas, reemplazos + nuevos


def _validar_excepcion(entrada: Any, indice: int, ids_validos: Set[str]) -> Excepcion:
    contexto = f"excepción #{indice}"
    if not isinstance(entrada, dict):
        raise ValueError(f"{contexto}: debe ser un objeto JSON")
    reglas = entrada.get("reglas")
    if not isinstance(reglas, list) or not reglas or not all(isinstance(r, str) for r in reglas):
        raise ValueError(f"{contexto}: 'reglas' debe ser una lista no vacía de ids de regla")
    desconocidas = sorted(set(reglas) - ids_validos)
    if desconocidas:
        raise ValueError(f"{contexto}: reglas desconocidas {desconocidas}")
    ruta = entrada.get("ruta")
    if not isinstance(ruta, str) or not ruta.strip():
        raise ValueError(f"{contexto}: 'ruta' (glob relativo a la raíz auditada) es obligatoria")
    coincide = entrada.get("coincide")
    if coincide is not None:
        if not isinstance(coincide, str):
            raise ValueError(f"{contexto}: 'coincide' debe ser una regex en texto")
        _compilar(coincide, contexto)
    justificacion = entrada.get("justificacion")
    if not isinstance(justificacion, str) or len(justificacion.strip()) < LARGO_MINIMO_JUSTIFICACION:
        raise ValueError(f"{contexto}: 'justificacion' es obligatoria (mínimo {LARGO_MINIMO_JUSTIFICACION} caracteres)")
    return Excepcion(tuple(reglas), ruta.strip(), coincide, justificacion.strip())


def cargar_excepciones(ruta: str, ids_validos: Set[str]) -> Tuple[Excepcion, ...]:
    """Carga y valida la lista de excepciones. Cualquier entrada inválida es un error."""
    with open(ruta, "r", encoding="utf-8") as f:
        datos = json.load(f)
    if not isinstance(datos, dict) or not isinstance(datos.get("excepciones"), list):
        raise ValueError(f"{ruta}: se esperaba un objeto con la lista 'excepciones'")
    return tuple(_validar_excepcion(e, i, ids_validos) for i, e in enumerate(datos["excepciones"], 1))


def excepciones_para_ruta(ruta_relativa: str, excepciones: Sequence[Excepcion]) -> Tuple[Excepcion, ...]:
    """Excepciones cuyo glob `ruta` coincide con la ruta relativa (separador `/`)."""
    ruta = ruta_relativa.replace(os.sep, "/")
    return tuple(e for e in excepciones if fnmatch.fnmatchcase(ruta, e.ruta))


# ── Extracción del texto auditable ───────────────────────────────────────────


def _fragmentos_python(contenido: str) -> Optional[Dict[int, Tuple[str, ...]]]:
    """Comentarios y strings de un módulo por línea física; None si no tokeniza."""
    fragmentos: Dict[int, List[str]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(contenido).readline):
            if tok.type not in _TOKENS_TEXTO:
                continue
            for desfase, pieza in enumerate(tok.string.split("\n")):
                fragmentos.setdefault(tok.start[0] + desfase, []).append(pieza)
    except (tokenize.TokenError, SyntaxError):
        return None
    return {linea: tuple(piezas) for linea, piezas in fragmentos.items()}


def _lineas_de_texto(contenido: str, ext: str) -> List[_LineaAuditable]:
    lineas = contenido.split("\n")
    fragmentos = _fragmentos_python(contenido) if ext in EXTENSIONES_PYTHON else None
    if fragmentos is None:  # no es Python o no tokeniza: toda la línea es texto
        return [(n, linea, (linea,)) for n, linea in enumerate(lineas, 1)]
    return [(n, linea, fragmentos.get(n, ())) for n, linea in enumerate(lineas, 1)]


def _fragmentos_xml(linea: str) -> Tuple[str, ...]:
    """Nodos de texto de una línea XML, sin fórmulas ni marcado (celdas, rangos)."""
    sin_formulas = _FORMULA_XML.sub("", linea)
    return tuple(t for t in _ETIQUETA_XML.split(sin_formulas) if t.strip())


# ── Auditoría ────────────────────────────────────────────────────────────────


def _coincide_regla(regla: Regla, texto: str, fragmentos: Sequence[str]) -> bool:
    if regla.alcance == ALCANCE_LINEA:
        return re.search(regla.patron, texto) is not None
    return any(re.search(regla.patron, fragmento) for fragmento in fragmentos)


def _exenta(regla_id: str, texto: str, excepciones: Sequence[Excepcion]) -> bool:
    return any(
        regla_id in exc.reglas and (exc.coincide is None or re.search(exc.coincide, texto) is not None)
        for exc in excepciones
    )


def _auditar_lineas(
    lineas: Sequence[_LineaAuditable],
    reglas: Sequence[Regla],
    excepciones: Sequence[Excepcion],
    prefijo: str = "",
) -> List[Alerta]:
    """Una alerta por (línea, id de regla): la primera regla de la categoría que coincide."""
    alertas: List[Alerta] = []
    for num, texto, fragmentos in lineas:
        vistas: Set[str] = set()
        for regla in reglas:
            if regla.id in vistas or not _coincide_regla(regla, texto, fragmentos):
                continue
            vistas.add(regla.id)
            if not _exenta(regla.id, texto, excepciones):
                alertas.append(Alerta(num, regla.id, prefijo + regla.descripcion))
    return alertas


def _audit_xlsx(filepath: str, patterns: Sequence[Regla], excepciones: Sequence[Excepcion]) -> List[Alerta]:
    """Revisa todas las partes XML y metadatos (`docProps/`, `xl/`) de un `.xlsx`."""
    alertas: List[Alerta] = []
    try:
        with zipfile.ZipFile(filepath, "r") as zf:
            for member in sorted(zf.namelist()):
                if not member.endswith((".xml", ".rels")):
                    continue
                texto = zf.read(member).decode("utf-8", errors="replace")
                lineas = [(n, linea, _fragmentos_xml(linea)) for n, linea in enumerate(texto.splitlines(), 1)]
                alertas.extend(_auditar_lineas(lineas, patterns, excepciones, f"[{member}] "))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, EOFError, zlib.error) as exc:
        alertas.append(Alerta(1, "xlsx", f"Archivo .xlsx corrupto o ilegible: {exc}"))
    return alertas


def audit_file(
    filepath: str, patterns: Sequence[Regla], excepciones: Sequence[Excepcion] = ()
) -> List[Alerta]:
    """Audita un archivo de texto (UTF-8 estricto) o un `.xlsx`. Falla cerrada si no se puede leer.

    `excepciones` ya debe venir filtrada por la ruta del archivo (ver `excepciones_para_ruta`).
    """
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".xlsx":
        return _audit_xlsx(filepath, patterns, excepciones)
    if ext in BINARY_SKIP_EXTENSIONS:
        return []
    try:
        with open(filepath, "r", encoding="utf-8", errors="strict") as f:
            contenido = f.read()
    except UnicodeDecodeError as exc:
        return [Alerta(1, "utf8", f"UTF-8 inválido en archivo de texto: {exc}")]
    except OSError as exc:
        return [Alerta(1, "lectura", f"No se pudo leer el archivo: {exc}")]
    return _auditar_lineas(_lineas_de_texto(contenido, ext), patterns, excepciones)


def sanitize_text(text: str, replacements: Sequence[Tuple[str, str]]) -> str:
    sanitized = text
    for pattern, replacement in replacements:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized


def sanitize_file(
    src_path: str,
    dst_path: str,
    patterns: Sequence[Regla],
    replacements: Sequence[Tuple[str, str]],
) -> int:
    with open(src_path, "r", encoding="utf-8", errors="strict") as f:
        content = f.read()
    sanitized = sanitize_text(content, replacements)
    os.makedirs(os.path.dirname(os.path.abspath(dst_path)), exist_ok=True)
    with open(dst_path, "w", encoding="utf-8") as f:
        f.write(sanitized)
    return len(audit_file(dst_path, patterns))


def _reglas_para(filepath: str, patterns: Sequence[Regla], ruta_excepciones: Optional[str]) -> Sequence[Regla]:
    """La lista de excepciones cita el vocabulario que exime: solo se revisa con reglas estructuradas."""
    if ruta_excepciones and os.path.realpath(filepath) == os.path.realpath(ruta_excepciones):
        return [r for r in patterns if r.alcance == ALCANCE_LINEA]
    return patterns


def _archivos_auditables(dir_path: str) -> Iterator[str]:
    for root, dirs, files in os.walk(dir_path):
        # os.walk exige podar `dirs` en sitio para no descender a los directorios omitidos.
        dirs[:] = sorted(d for d in dirs if d not in DIRECTORIOS_OMITIDOS)
        for nombre in sorted(files):
            ruta = os.path.join(root, nombre)
            if nombre not in ARCHIVOS_OMITIDOS and os.path.realpath(ruta) != RUTA_PROPIA:
                yield ruta


def _imprimir_alertas_archivo(ruta_rel: str, alertas: Sequence[Alerta]) -> None:
    if not alertas:
        return
    print(f"\n⚠️  {ruta_rel} ({len(alertas)} alerta(s)):")
    for alerta in alertas[:MAX_ALERTAS_POR_ARCHIVO]:
        print(f"   Línea {alerta.linea}: [{alerta.regla}] {alerta.descripcion}")
    if len(alertas) > MAX_ALERTAS_POR_ARCHIVO:
        print(f"   ... y {len(alertas) - MAX_ALERTAS_POR_ARCHIVO} alerta(s) más")


def _imprimir_resumen(conteo: "Counter[str]", total_archivos: int) -> None:
    print("\n" + "=" * 60)
    if not conteo:
        print(f"✅ AUDITORÍA LIMPIA: {total_archivos} archivos (incluye XML internos de .xlsx) con 0 violaciones.")
        return
    print(f"❌ AUDITORÍA FALLIDA: {sum(conteo.values())} violación(es) en {total_archivos} archivos.")
    print("Alertas por regla:")
    for regla, cantidad in sorted(conteo.items(), key=lambda par: (-par[1], par[0])):
        print(f"  {regla}: {cantidad}")


def audit_directory(
    dir_path: str,
    patterns: Sequence[Regla],
    excepciones: Sequence[Excepcion] = (),
    ruta_excepciones: Optional[str] = None,
) -> int:
    """Audita un árbol completo y devuelve el total de alertas no exentas."""
    print(f"\n🔍 Auditando directorio: {dir_path}")
    print("=" * 60)
    conteo: "Counter[str]" = Counter()
    total_archivos = 0
    for filepath in _archivos_auditables(dir_path):
        ruta_rel = os.path.relpath(filepath, dir_path)
        reglas = _reglas_para(filepath, patterns, ruta_excepciones)
        alertas = audit_file(filepath, reglas, excepciones_para_ruta(ruta_rel, excepciones))
        total_archivos += 1
        conteo.update(alerta.regla for alerta in alertas)
        _imprimir_alertas_archivo(ruta_rel, alertas)
    _imprimir_resumen(conteo, total_archivos)
    return sum(conteo.values())


# ── CLI ──────────────────────────────────────────────────────────────────────


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sanitizer de PII, RFC, credenciales, .xlsx y huellas narrativas")
    parser.add_argument("mode", choices=["audit", "sanitize"], help="Modo: audit o sanitize")
    parser.add_argument("path", help="Archivo o directorio objetivo")
    parser.add_argument("--output", "-o", help="Ruta de salida (modo sanitize de un archivo)")
    parser.add_argument("--rules", help="JSON opcional con reglas adicionales")
    parser.add_argument(
        "--exceptions",
        help="JSON de excepciones justificadas (por omisión, tools/sanitize_exceptions.json si existe)",
    )
    return parser


def _ruta_excepciones(explicita: Optional[str]) -> Optional[str]:
    if explicita:
        return explicita
    return RUTA_EXCEPCIONES_DEFAULT if os.path.exists(RUTA_EXCEPCIONES_DEFAULT) else None


def _modo_audit(
    path: str, patterns: Sequence[Regla], excepciones: Sequence[Excepcion], ruta_excepciones: Optional[str]
) -> None:
    if os.path.isdir(path):
        total = audit_directory(path, patterns, excepciones, ruta_excepciones)
        sys.exit(1 if total > 0 else 0)
    reglas = _reglas_para(path, patterns, ruta_excepciones)
    alertas = audit_file(path, reglas, excepciones_para_ruta(os.path.relpath(path), excepciones))
    if alertas:
        print(f"❌ {len(alertas)} violación(es) en {path}:")
        for alerta in alertas:
            print(f"  Línea {alerta.linea}: [{alerta.regla}] {alerta.descripcion}")
        sys.exit(1)
    print(f"✅ Archivo limpio: {path}")
    sys.exit(0)


def _modo_sanitize(
    path: str, output: Optional[str], patterns: Sequence[Regla], replacements: Sequence[Tuple[str, str]]
) -> None:
    if not output:
        print("Error: el modo sanitize requiere --output.", file=sys.stderr)
        sys.exit(1)
    restantes = sanitize_file(path, output, patterns, replacements)
    if restantes > 0:
        print(f"⚠️  Sanitizado con {restantes} alerta(s) restante(s) que requieren revisión manual.")
    else:
        print(f"✅ Sanitizado: {output}")


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parser().parse_args(argv)
    try:
        patterns, replacements = load_custom_rules(args.rules)
        ruta_exc = _ruta_excepciones(args.exceptions)
        excepciones = cargar_excepciones(ruta_exc, {r.id for r in patterns}) if ruta_exc else ()
    except (OSError, ValueError) as exc:
        print(f"Error de configuración: {exc}", file=sys.stderr)
        sys.exit(2)
    if args.mode == "audit":
        _modo_audit(args.path, patterns, excepciones, ruta_exc)
    else:
        _modo_sanitize(args.path, args.output, patterns, replacements)


if __name__ == "__main__":
    main()
