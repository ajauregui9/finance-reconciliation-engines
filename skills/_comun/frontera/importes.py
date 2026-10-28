"""Frontera de entrada de importes: un valor externo se vuelve `Decimal` aquí, una sola vez.

Reglas que comparten todos los motores:

- **Solo dígitos ASCII.** `\\d` en una expresión regular, `Decimal()` e `int()` aceptan
  dígitos de cualquier alfabeto (`Decimal("١٠٠.٥٠")` vale 100.50). Por eso la forma del
  texto se valida con `[0-9]` antes de construir el número.
- **Un insumo nunca se redondea.** Un texto con más decimales de los que admite la forma
  es un error, no un importe redondeado: `"100.005"` no es 100.01. El resultado se lleva a
  la escala de la forma (`"100"` -> `100.00`) solo cuando eso es exacto.
- **Floats solo por conversión explícita.** Un `float` (o `int`/`Decimal`) entra solo si la
  forma lo admite (`numeros=True`). El `float` se convierte con su `repr`, el texto más corto
  que reproduce el mismo binario; si ese texto tiene más de 15 dígitos significativos o más
  decimales significativos de los permitidos, el valor es ambiguo y se rechaza
  (`0.1 + 0.2` es `0.30000000000000004`).
- **Espacios.** Si la forma lo pide se recortan espacios y tabuladores ASCII al borde;
  dentro del número no hay espacios, exponentes, guiones bajos, `NaN` ni `Infinity`.
- **Miles.** Si la forma los admite, las comas de miles son opcionales pero deben estar
  bien colocadas (`1,234.56`); `1,23.45` es un error.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from .errores import ErrorFrontera

CENTAVO = Decimal("0.01")
# Todo decimal de hasta 15 dígitos significativos sobrevive intacto el viaje a float y de
# regreso por `repr`; con más, dos textos distintos pueden dar el mismo float.
DIGITOS_FLOAT_EXACTOS = 15
BORDES = " \t"
_DIGITOS_ASCII = frozenset("0123456789")
_PARTES = re.compile(r"([+-]?)([0-9,]+)(?:\.([0-9]+))?")
_ENTERO_CON_MILES = re.compile(r"[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+")
_ENTERO = re.compile(r"[0-9]+")
_ENTERO_CON_SIGNO = re.compile(r"-?[0-9]+")
_DIGITOS_EJEMPLO = "567890123"


@dataclass(frozen=True)
class FormaImporte:
    """Qué valores acepta una frontera de importes.

    `decimales`: máximo de decimales; `None` admite cualquier cantidad y no cambia la
    escala (umbrales, tasas). `exactos`: exige exactamente `decimales` en el texto.
    `negativo` / `positivo_explicito`: admiten `-` / `+` inicial. `miles`: comas de miles
    opcionales y bien colocadas. `numeros`: admite `int`, `float` (vía `repr`) y `Decimal`
    además de texto. `recortar`: recorta espacios y tabuladores ASCII al borde del texto.
    """

    decimales: Optional[int] = 2
    exactos: bool = False
    negativo: bool = True
    positivo_explicito: bool = False
    miles: bool = False
    numeros: bool = False
    recortar: bool = True

    def __post_init__(self) -> None:
        if self.decimales is not None and self.decimales < 0:
            raise ValueError(f"decimales no puede ser negativo: {self.decimales}")
        if self.exactos and self.decimales is None:
            raise ValueError("exactos exige un número de decimales")


IMPORTE = FormaImporte()


def leer_importe(valor: object, forma: FormaImporte = IMPORTE) -> Decimal:
    """El `Decimal` de un importe externo según `forma`; `ErrorFrontera` si no la cumple."""
    if isinstance(valor, str):
        return _desde_texto(valor, forma)
    if isinstance(valor, bool) or not isinstance(valor, (int, float, Decimal)):
        raise ErrorFrontera(f"no es un importe: llegó {type(valor).__name__} ({valor!r})")
    if not forma.numeros:
        raise ErrorFrontera(f"se espera texto como {_ejemplo(forma)}; llegó un número {type(valor).__name__} "
                            f"({valor!r})")
    return _desde_numero(valor, forma)


def leer_entero(valor: object, *, negativo: bool = False, recortar: bool = True) -> int:
    """Un entero escrito como texto con dígitos ASCII (y `-` inicial si `negativo`)."""
    if not isinstance(valor, str):
        raise ErrorFrontera(f"se espera texto con un entero; llegó {type(valor).__name__} ({valor!r})")
    limpio = valor.strip(BORDES) if recortar else valor
    patron = _ENTERO_CON_SIGNO if negativo else _ENTERO
    if patron.fullmatch(limpio) is None:
        forma = "dígitos ASCII con '-' opcional" if negativo else "solo dígitos ASCII"
        raise ErrorFrontera(f"{valor!r} no es un entero ({forma}){_diagnostico(limpio)}")
    return int(limpio)


# ------------------------------------------------------------------------ texto
def _desde_texto(texto: str, forma: FormaImporte) -> Decimal:
    limpio = texto.strip(BORDES) if forma.recortar else texto
    partes = _PARTES.fullmatch(limpio)
    if partes is None:
        raise ErrorFrontera(f"{texto!r} no es un importe como {_ejemplo(forma)}{_diagnostico(limpio)}")
    signo, entero, fraccion = partes.group(1), partes.group(2), partes.group(3) or ""
    _validar_signo(texto, signo, forma)
    _validar_entero(texto, entero, forma)
    _validar_fraccion(texto, len(fraccion), forma)
    numero = Decimal(signo + entero.replace(",", "") + (f".{fraccion}" if fraccion else ""))
    return _a_escala(numero, texto, forma)


def _diagnostico(limpio: str) -> str:
    if not limpio.strip():
        return ": está vacío"
    if any(c.isnumeric() and c not in _DIGITOS_ASCII for c in limpio):
        return ": contiene dígitos no ASCII"
    if any(c.isspace() for c in limpio):
        return ": contiene espacios"
    return ""


def _validar_signo(texto: str, signo: str, forma: FormaImporte) -> None:
    if signo == "-" and not forma.negativo:
        raise ErrorFrontera(f"{texto!r}: no se admite signo negativo")
    if signo == "+" and not forma.positivo_explicito:
        raise ErrorFrontera(f"{texto!r}: no se admite signo +")


def _validar_entero(texto: str, entero: str, forma: FormaImporte) -> None:
    if "," not in entero:
        return
    if not forma.miles:
        raise ErrorFrontera(f"{texto!r}: no admite separador de miles (se espera {_ejemplo(forma)})")
    if _ENTERO_CON_MILES.fullmatch(entero) is None:
        raise ErrorFrontera(f"{texto!r}: comas de miles mal colocadas (se espera {_ejemplo(forma)})")


def _validar_fraccion(texto: str, cantidad: int, forma: FormaImporte) -> None:
    if forma.decimales is None:
        return
    if forma.exactos and cantidad != forma.decimales:
        raise ErrorFrontera(f"{texto!r} tiene {cantidad} decimales; se exigen exactamente {forma.decimales} decimales")
    if cantidad > forma.decimales:
        raise ErrorFrontera(f"{texto!r} tiene {cantidad} decimales; se admiten a lo más {forma.decimales} decimales "
                            "(un insumo no se redondea)")


# ---------------------------------------------------------------------- números
def _desde_numero(valor: object, forma: FormaImporte) -> Decimal:
    numero = _numero_exacto(valor)
    decimales = _decimales_significativos(numero)
    if forma.decimales is not None and decimales > forma.decimales:
        raise ErrorFrontera(f"{valor!r} tiene {decimales} decimales significativos; se admiten a lo más "
                            f"{forma.decimales} decimales (un insumo no se redondea)")
    if isinstance(valor, float) and _digitos_significativos(numero) > DIGITOS_FLOAT_EXACTOS:
        raise ErrorFrontera(f"el float {valor!r} tiene más de {DIGITOS_FLOAT_EXACTOS} dígitos significativos: "
                            "no representa un importe exacto (escríbelo como texto)")
    if numero < 0 and not forma.negativo:
        raise ErrorFrontera(f"{valor!r}: no se admite un importe negativo")
    return _a_escala(numero, repr(valor), forma)


def _numero_exacto(valor: object) -> Decimal:
    if isinstance(valor, float):
        if not math.isfinite(valor):
            raise ErrorFrontera(f"{valor!r} no es un número finito")
        return Decimal(repr(valor))
    if isinstance(valor, int):
        return Decimal(valor)
    if not isinstance(valor, Decimal) or not valor.is_finite():
        raise ErrorFrontera(f"{valor!r} no es un número finito")
    return valor


def _decimales_significativos(numero: Decimal) -> int:
    """Decimales sin contar ceros finales; `format(..., "f")` es exacto, sin contexto."""
    return len(format(numero, "f").partition(".")[2].rstrip("0"))


def _digitos_significativos(numero: Decimal) -> int:
    return len("".join(str(d) for d in numero.as_tuple().digits).strip("0"))


# ------------------------------------------------------------------------ común
def _a_escala(numero: Decimal, original: str, forma: FormaImporte) -> Decimal:
    """Lleva el número a `forma.decimales`; ya se validó que el cambio es exacto."""
    if forma.decimales is None:
        return numero
    try:
        return numero.quantize(Decimal((0, (1,), -forma.decimales)))
    except InvalidOperation:
        raise ErrorFrontera(f"{original} está fuera del rango representable") from None


def _ejemplo(forma: FormaImporte) -> str:
    signo = "-" if forma.negativo else ""
    entero = "1,234" if forma.miles else "1234"
    if forma.decimales is None:
        return f"{signo}{entero}.5678"
    if forma.decimales == 0:
        return f"{signo}{entero}"
    return f"{signo}{entero}.{_DIGITOS_EJEMPLO[:forma.decimales]}"
