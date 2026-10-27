"""Fila contrato: la unidad común en que cada fuente se traduce antes de ensamblar.

Aquí viven el catálogo de fuentes y conceptos, la forma de la fila y la validación
de su esquema. El ensamblador solo confía en filas que pasan `validar_fila`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType
from typing import Mapping, Optional, Sequence, Tuple

from .calendario import Semana
from .dinero import CERO, es_centavos
from .errores import ErrorInvariante

FUENTE_SALDOS = "saldos_bancarios"
FUENTE_CXC = "cxc_antiguedad"
FUENTE_CXP = "cxp_programadas"
FUENTE_NOMINA = "nomina"
FUENTE_IMPUESTOS = "impuestos"
FUENTES: Tuple[str, ...] = (FUENTE_SALDOS, FUENTE_CXC, FUENTE_CXP, FUENTE_NOMINA, FUENTE_IMPUESTOS)
# Solo en CxC un importe 0.00 es un registro válido (se cuenta y no genera fila).
FUENTES_ADMITEN_CERO: Tuple[str, ...] = (FUENTE_CXC,)

CONCEPTO_SALDO = "saldo_inicial"
CONCEPTO_COBRANZA = "cobranza_clientes"
CONCEPTO_PROVEEDORES = "pago_proveedores"
CONCEPTO_NOMINA = "pago_nomina"
CONCEPTO_IMPUESTOS = "pago_impuestos"
CONCEPTOS_ENTRADA: Tuple[str, ...] = (CONCEPTO_COBRANZA,)
CONCEPTOS_SALIDA: Tuple[str, ...] = (CONCEPTO_PROVEEDORES, CONCEPTO_NOMINA, CONCEPTO_IMPUESTOS)
CONCEPTOS_FLUJO: Tuple[str, ...] = CONCEPTOS_ENTRADA + CONCEPTOS_SALIDA

# Marcas: filas que una regla especial ubica en la semana 1, en la fecha de corte.
MARCA_VENCIDO = "vencido"
MARCA_SALDO_ACREEDOR = "saldo_acreedor"
CONCEPTOS_DE_MARCA: Mapping[str, Tuple[str, ...]] = MappingProxyType({
    MARCA_VENCIDO: CONCEPTOS_SALIDA,
    MARCA_SALDO_ACREEDOR: CONCEPTOS_ENTRADA,
})

CONCEPTO_DE_FUENTE: Mapping[str, str] = MappingProxyType({
    FUENTE_SALDOS: CONCEPTO_SALDO,
    FUENTE_CXC: CONCEPTO_COBRANZA,
    FUENTE_CXP: CONCEPTO_PROVEEDORES,
    FUENTE_NOMINA: CONCEPTO_NOMINA,
    FUENTE_IMPUESTOS: CONCEPTO_IMPUESTOS,
})


@dataclass(frozen=True)
class FilaContrato:
    """Un movimiento de caja (o un saldo inicial) ubicado en una semana del horizonte.

    `marca` es `None` en una fila ordinaria; `vencido` o `saldo_acreedor` señalan una
    fila que entró a la semana 1 por la regla de egresos vencidos o de saldos acreedores.
    """

    fuente: str
    concepto: str
    semana: int
    fecha: date
    referencia: str
    contraparte: str
    monto: Decimal
    marca: Optional[str] = None

    def clave_orden(self) -> Tuple[int, str, str, str]:
        return (self.semana, self.concepto, self.fuente, self.referencia)


@dataclass(frozen=True)
class ResultadoFuente:
    """Lo que entrega un adaptador: filas contrato más su conciliación contra el insumo.

    Todos los importes llevan signo de caja. `total_insumo` es la suma de los importes
    del archivo; debe cuadrar con las filas más las partidas que no entran al horizonte.
    `registros_en_cero` cuenta los registros con importe 0.00, que no generan fila.
    """

    fuente: str
    archivo: str
    sha256: str
    registros: int
    total_insumo: Decimal
    filas: Tuple[FilaContrato, ...]
    fuera_horizonte: Decimal
    no_cobrable: Decimal
    registros_en_cero: int = 0

    @property
    def en_horizonte(self) -> Decimal:
        return sum((f.monto for f in self.filas), CERO)


def ordenar_filas(filas: Sequence[FilaContrato]) -> Tuple[FilaContrato, ...]:
    return tuple(sorted(filas, key=FilaContrato.clave_orden))


def _texto_lleno(valor: object) -> bool:
    return isinstance(valor, str) and bool(valor.strip())


def _es_entero(valor: object) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def _validar_identidad(fila: FilaContrato, fuente: str, contexto: str) -> None:
    if fila.fuente != fuente:
        raise ErrorInvariante(
            f"{contexto}: la fila de la fuente '{fila.fuente}' no corresponde al resultado '{fuente}'"
        )
    esperado = CONCEPTO_DE_FUENTE[fuente]
    if fila.concepto != esperado:
        raise ErrorInvariante(f"{contexto}: el concepto '{fila.concepto}' no es el de la fuente ('{esperado}')")
    if not _texto_lleno(fila.referencia):
        raise ErrorInvariante(f"{contexto}: la referencia está vacía")
    if not _texto_lleno(fila.contraparte):
        raise ErrorInvariante(f"{contexto}: la contraparte está vacía")


def _validar_ubicacion(fila: FilaContrato, semanas: Sequence[Semana], contexto: str) -> None:
    if not _es_entero(fila.semana) or not 1 <= fila.semana <= len(semanas):
        raise ErrorInvariante(f"{contexto}: semana {fila.semana!r} fuera del rango 1..{len(semanas)}")
    if not isinstance(fila.fecha, date) or isinstance(fila.fecha, datetime):
        raise ErrorInvariante(f"{contexto}: la fecha debe ser datetime.date, llegó {type(fila.fecha).__name__}")
    semana = semanas[fila.semana - 1]
    if not semana.contiene(fila.fecha):
        raise ErrorInvariante(
            f"{contexto}: la fecha {fila.fecha.isoformat()} cae fuera de la semana {semana.numero} "
            f"({semana.inicio.isoformat()} a {semana.fin.isoformat()})"
        )


def _exigir_semana_1_al_corte(fila: FilaContrato, semanas: Sequence[Semana], que: str, contexto: str) -> None:
    if fila.semana != 1:
        raise ErrorInvariante(f"{contexto}: {que} debe ir en la semana 1")
    if fila.fecha != semanas[0].inicio:
        raise ErrorInvariante(f"{contexto}: {que} debe llevar la fecha de corte")


def _validar_marca(fila: FilaContrato, semanas: Sequence[Semana], contexto: str) -> None:
    if fila.marca is None:
        return
    if not isinstance(fila.marca, str) or fila.marca not in CONCEPTOS_DE_MARCA:
        raise ErrorInvariante(f"{contexto}: marca desconocida {fila.marca!r}")
    if fila.concepto not in CONCEPTOS_DE_MARCA[fila.marca]:
        raise ErrorInvariante(f"{contexto}: la marca '{fila.marca}' no aplica al concepto '{fila.concepto}'")
    _exigir_semana_1_al_corte(fila, semanas, f"una fila con marca '{fila.marca}'", contexto)


def _validar_signo(fila: FilaContrato, contexto: str) -> None:
    if fila.concepto in CONCEPTOS_ENTRADA:
        if fila.marca == MARCA_SALDO_ACREEDOR and fila.monto >= CERO:
            raise ErrorInvariante(f"{contexto}: un saldo acreedor debe restar (monto negativo) y vale {fila.monto}")
        if fila.marca != MARCA_SALDO_ACREEDOR and fila.monto <= CERO:
            raise ErrorInvariante(f"{contexto}: el monto de una entrada debe ser positivo y vale {fila.monto}")
    elif fila.concepto in CONCEPTOS_SALIDA and fila.monto >= CERO:
        raise ErrorInvariante(f"{contexto}: el monto de un pago debe ser negativo y vale {fila.monto}")


def validar_fila(fila: FilaContrato, fuente: str, semanas: Sequence[Semana]) -> None:
    """Lanza `ErrorInvariante` si la fila no cumple el esquema de la fila contrato."""
    if not isinstance(fila, FilaContrato):
        raise ErrorInvariante(f"{fuente}: se esperaba FilaContrato y llegó {type(fila).__name__}")
    contexto = f"fila contrato [{fila.fuente} | {fila.referencia!r}]"
    _validar_identidad(fila, fuente, contexto)
    _validar_ubicacion(fila, semanas, contexto)
    if not es_centavos(fila.monto):
        raise ErrorInvariante(f"{contexto}: el monto {fila.monto!r} debe ser un Decimal finito con dos decimales")
    if fila.concepto == CONCEPTO_SALDO:
        _exigir_semana_1_al_corte(fila, semanas, "el saldo inicial", contexto)
    _validar_marca(fila, semanas, contexto)
    _validar_signo(fila, contexto)
