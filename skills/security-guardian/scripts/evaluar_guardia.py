#!/usr/bin/env python3
"""Evalúa prompt_guard contra el set de casos: tasa de detección y de falsos positivos.

    python3 skills/security-guardian/scripts/evaluar_guardia.py [--casos <jsonl>]
        [--deteccion-minima 0.90] [--falsos-maximos 0.05]

Clases de caso: `inyeccion` (debe marcarse), `benigno` (no debe marcarse) y `evasion`
(evasión conocida y documentada: se reporta aparte y también dentro de una tasa total).
Imprime un reporte JSON determinista. Códigos: 0 cumple los umbrales, 1 no los
cumple, 2 casos o argumentos inválidos.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from guardia import FAMILIAS, inspeccionar  # noqa: E402

ESQUEMA = "evaluacion_prompt_guard/v1"
CASOS_POR_OMISION = Path(__file__).resolve().parents[1] / "eval" / "casos.jsonl"
DETECCION_MINIMA = Decimal("0.90")
FALSOS_MAXIMOS = Decimal("0.05")
DIEZMILESIMO = Decimal("0.0001")
INYECCION, BENIGNO, EVASION = "inyeccion", "benigno", "evasion"
CLASES = (INYECCION, BENIGNO, EVASION)
ORIGENES = ("cargo", "cfdi")
CAMPOS = frozenset({"id", "clase", "origen", "idioma", "texto", "familia", "nota"})
_IDIOMA = re.compile(r"^[a-z]{2}$")
CUMPLE, NO_CUMPLE, INVALIDO = 0, 1, 2


class CasosInvalidos(ValueError):
    """El archivo de casos no cumple su formato."""


@dataclass(frozen=True)
class Caso:
    id: str
    clase: str
    origen: str
    idioma: str
    texto: str
    familia: Optional[str]
    nota: str


# --- lectura --------------------------------------------------------------------


def _texto(objeto: Dict[str, Any], campo: str, contexto: str) -> str:
    valor = objeto[campo]
    if not isinstance(valor, str):
        raise CasosInvalidos(f"{contexto}: {campo} debe ser texto")
    return valor


def _caso(objeto: Any, contexto: str) -> Caso:
    if not isinstance(objeto, dict):
        raise CasosInvalidos(f"{contexto}: se esperaba un objeto JSON")
    faltan, sobran = sorted(CAMPOS - set(objeto)), sorted(set(objeto) - CAMPOS)
    if faltan:
        raise CasosInvalidos(f"{contexto}: faltan campos: {', '.join(faltan)}")
    if sobran:
        raise CasosInvalidos(f"{contexto}: campos desconocidos: {', '.join(sobran)}")
    caso = Caso(_texto(objeto, "id", contexto), _texto(objeto, "clase", contexto), _texto(objeto, "origen", contexto),
                _texto(objeto, "idioma", contexto), _texto(objeto, "texto", contexto), objeto["familia"],
                _texto(objeto, "nota", contexto))
    _validar(caso, contexto)
    return caso


def _validar(caso: Caso, contexto: str) -> None:
    if not caso.id.strip():
        raise CasosInvalidos(f"{contexto}: id vacío")
    if caso.clase not in CLASES:
        raise CasosInvalidos(f"{contexto}: clase {caso.clase!r} no es {', '.join(CLASES)}")
    if caso.origen not in ORIGENES:
        raise CasosInvalidos(f"{contexto}: origen {caso.origen!r} no es {', '.join(ORIGENES)}")
    if not _IDIOMA.match(caso.idioma):
        raise CasosInvalidos(f"{contexto}: idioma {caso.idioma!r} no es un código de dos letras")
    if not caso.texto.strip():
        raise CasosInvalidos(f"{contexto}: texto vacío")
    esperada_valida = caso.familia is None if caso.clase == BENIGNO else caso.familia in FAMILIAS
    if not esperada_valida:
        raise CasosInvalidos(f"{contexto}: familia {caso.familia!r} inválida para la clase {caso.clase}")


def leer_casos(ruta: Path) -> Tuple[Caso, ...]:
    """Los casos del JSONL, validados; `CasosInvalidos` ante el primer problema."""
    try:
        lineas = ruta.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise CasosInvalidos(f"{ruta.name}: no se pudo leer: {error}") from error
    casos: List[Caso] = []
    vistos: Dict[str, int] = {}
    for numero, linea in enumerate(lineas, 1):
        contexto = f"{ruta.name}, línea {numero}"
        try:
            objeto = json.loads(linea)
        except json.JSONDecodeError as error:
            raise CasosInvalidos(f"{contexto}: JSON inválido ({error.msg})") from error
        caso = _caso(objeto, contexto)
        if caso.id in vistos:
            raise CasosInvalidos(f"{contexto}: id {caso.id} repetido (ya en la línea {vistos[caso.id]})")
        vistos[caso.id] = numero
        casos.append(caso)
    return tuple(casos)


# --- evaluación -----------------------------------------------------------------


def _tasa(parte: int, total: int) -> str:
    if total == 0:
        return str(Decimal(0).quantize(DIEZMILESIMO))
    return str((Decimal(parte) / Decimal(total)).quantize(DIEZMILESIMO, rounding=ROUND_HALF_UP))


def _bolsa(parte: int, total: int, nombre: str) -> Dict[str, Any]:
    return {nombre: parte, "total": total, "tasa": _tasa(parte, total)}


def evaluar(casos: Sequence[Caso], deteccion_minima: Decimal = DETECCION_MINIMA,
            falsos_maximos: Decimal = FALSOS_MAXIMOS) -> Dict[str, Any]:
    """El reporte de la evaluación; `cumple` exige ambos umbrales."""
    obtenidas = {c.id: tuple(h.familia for h in inspeccionar(c.texto)) for c in casos}
    de = {clase: [c for c in casos if c.clase == clase] for clase in CLASES}
    no_detectados = [c.id for c in de[INYECCION] if not obtenidas[c.id]]
    equivocadas = [{"id": c.id, "esperada": c.familia, "obtenidas": list(obtenidas[c.id])}
                   for c in de[INYECCION] if obtenidas[c.id] and c.familia not in obtenidas[c.id]]
    falsos = [{"id": c.id, "familias": list(obtenidas[c.id])} for c in de[BENIGNO] if obtenidas[c.id]]
    evasiones = [c.id for c in de[EVASION] if obtenidas[c.id]]
    inyecciones, benignos = len(de[INYECCION]), len(de[BENIGNO])
    detectados = inyecciones - len(no_detectados)
    deteccion = _bolsa(detectados, inyecciones, "detectados")
    falsos_positivos = _bolsa(len(falsos), benignos, "marcados")
    return {
        "esquema": ESQUEMA,
        "casos": {clase: len(de[clase]) for clase in CLASES},
        "deteccion": deteccion,
        "falsos_positivos": falsos_positivos,
        "familia_correcta": _bolsa(detectados - len(equivocadas), inyecciones, "aciertos"),
        "evasiones_conocidas": {"detectadas": len(evasiones), "total": len(de[EVASION]),
                                "no_detectadas": [c.id for c in de[EVASION] if not obtenidas[c.id]]},
        "deteccion_con_evasiones": _bolsa(detectados + len(evasiones), inyecciones + len(de[EVASION]),
                                          "detectados"),
        "por_familia": {f: {"esperados": sum(1 for c in de[INYECCION] if c.familia == f),
                            "detectados": sum(1 for c in de[INYECCION] if c.familia == f and f in obtenidas[c.id])}
                        for f in FAMILIAS},
        "fallos": {"no_detectados": no_detectados, "familia_equivocada": equivocadas, "falsos_positivos": falsos,
                   "evasiones_detectadas": evasiones},
        "umbrales": {"deteccion_minima": str(deteccion_minima), "falsos_positivos_maximos": str(falsos_maximos)},
        "cumple": (inyecciones > 0 and Decimal(deteccion["tasa"]) >= deteccion_minima
                   and Decimal(falsos_positivos["tasa"]) <= falsos_maximos),
    }


# --- CLI ------------------------------------------------------------------------


class _ErrorArgumentos(Exception):
    pass


class _Analizador(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _ErrorArgumentos(message)


def _proporcion(texto: str) -> Decimal:
    try:
        valor = Decimal(texto)
    except InvalidOperation:
        raise argparse.ArgumentTypeError(f"{texto!r} no es un número") from None
    if not Decimal(0) <= valor <= Decimal(1):
        raise argparse.ArgumentTypeError(f"{texto} debe estar entre 0 y 1")
    return valor


def main(argv: Optional[Sequence[str]] = None) -> int:
    analizador = _Analizador(prog="evaluar_guardia.py", description="Evalúa prompt_guard contra el set de casos.")
    analizador.add_argument("--casos", type=Path, default=CASOS_POR_OMISION, help="JSONL de casos")
    analizador.add_argument("--deteccion-minima", type=_proporcion, default=DETECCION_MINIMA)
    analizador.add_argument("--falsos-maximos", type=_proporcion, default=FALSOS_MAXIMOS)
    try:
        args = analizador.parse_args(argv)
        casos = leer_casos(args.casos)
    except (_ErrorArgumentos, CasosInvalidos) as error:
        print(f"evaluar_guardia: {error}", file=sys.stderr)
        return INVALIDO
    reporte = evaluar(casos, args.deteccion_minima, args.falsos_maximos)
    print(json.dumps(reporte, ensure_ascii=False, sort_keys=True, indent=2))
    return CUMPLE if reporte["cumple"] else NO_CUMPLE


if __name__ == "__main__":
    sys.exit(main())
