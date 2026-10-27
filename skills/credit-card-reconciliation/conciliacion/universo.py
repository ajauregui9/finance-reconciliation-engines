"""Universo de cargos: de los estados de cuenta crudos al universo normalizado.

Flujo: se valida el resumen del periodo (el manifiesto de qué estados existen y
cuáles son sus totales de control), se lee cada CSV listado, se identifica su
layout por el encabezado exacto, se interpreta cada fila sin descartar ninguna
y se comparan los totales calculados contra los del resumen. La spec completa
está en `specs/universo.md`.

Uso, con cwd en `skills/credit-card-reconciliation`:

    python3 -m conciliacion.universo <dir_crudos> --salida <universo.jsonl>
        [--control <control.json>] [--sin-estado EMISOR ...]

Códigos de salida: 0 universo escrito y candados en verde (posiblemente
provisional), 2 insumo o argumento inválido, 3 un candado no cuadra. Con código
distinto de cero no se escribe ningún archivo.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, NoReturn, Optional, Sequence, Tuple, Union

from .layouts import (
    LAYOUTS,
    EncabezadoDesconocido,
    ErrorInsumo,
    Layout,
    Lectura,
    clasificar_movimiento,
    detectar_layout,
    interpretar_fila,
)
from .montos import leer_monto_resumen, texto_monto, texto_tipo_cambio

__all__ = [
    "CandadoFallido", "Cargo", "Comprobacion", "ControlEstado", "EncabezadoDesconocido",
    "ErrorInsumo", "EstadoResumen", "Universo", "calcular_control", "cargos_de_filas",
    "construir_universo", "exigir_candados", "leer_filas_csv", "leer_resumen", "main",
    "serializar_control", "serializar_universo",
]

NOMBRE_RESUMEN = "resumen_estados_cuenta.json"
ESQUEMA_RESUMEN = "resumen_estados_cuenta/v1"
ESQUEMA_CONTROL = "control_universo/v1"
ESTADO_OK = "ok"
ESTADO_ININTERPRETABLE = "ininterpretable"
SEPARADOR_MOTIVOS = ","
DIGITOS_FILA = 4
SALIDA_OK = 0
SALIDA_INSUMO = 2
SALIDA_CANDADO = 3

_CERO = Decimal("0.00")
_PATRON_EMISOR = re.compile(r"[A-Z][A-Z0-9_]*")
_PATRON_FECHA_ISO = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_CAMPOS_MONTO = ("total_cargos", "total_abonos", "total_neto", "saldo_anterior",
                 "saldo_al_corte")

Numero = Union[int, Decimal]
Escalar = Union[str, int, None]


class CandadoFallido(Exception):
    """Algún total de control del universo no cuadra con el resumen."""


@dataclass(frozen=True)
class EstadoResumen:
    archivo: str
    emisor: str
    nombre_emisor: str
    layout: str
    moneda: str
    periodo_inicio: date
    periodo_fin: date
    corte: date
    num_movimientos: int
    total_cargos: Decimal
    total_abonos: Decimal
    total_neto: Decimal
    saldo_anterior: Decimal
    saldo_al_corte: Decimal


@dataclass(frozen=True)
class Cargo:
    cargo_id: str
    emisor: str
    layout: str
    archivo: str
    corte: date
    fila: int
    fecha: Optional[date]
    fecha_aplicacion: Optional[date]
    descripcion: Optional[str]
    titular: Optional[str]
    tarjeta_ultimos4: Optional[str]
    monto: Optional[Decimal]
    moneda: str
    monto_original: Optional[Decimal]
    moneda_original: Optional[str]
    tipo_cambio: Optional[Decimal]
    tipo_movimiento: Optional[str]
    estado: str
    motivo: Optional[str]


@dataclass(frozen=True)
class Comprobacion:
    nombre: str
    esperado: str
    calculado: str
    cuadra: bool


@dataclass(frozen=True)
class ControlEstado:
    archivo: str
    emisor: str
    layout: str
    comprobaciones: Tuple[Comprobacion, ...]

    @property
    def cuadra(self) -> bool:
        return all(c.cuadra for c in self.comprobaciones)


@dataclass(frozen=True)
class Universo:
    cargos: Tuple[Cargo, ...]
    controles: Tuple[ControlEstado, ...]
    estados_omitidos: Tuple[str, ...]

    @property
    def cuadra(self) -> bool:
        return all(c.cuadra for c in self.controles)

    @property
    def es_provisional(self) -> bool:
        return bool(self.estados_omitidos)


# --- resumen del periodo ------------------------------------------------------


def _leer_texto(ruta: Path, que: str) -> str:
    try:
        return ruta.read_bytes().decode("utf-8-sig")
    except FileNotFoundError:
        raise ErrorInsumo(f"falta {que}: {ruta}") from None
    except OSError as error:
        raise ErrorInsumo(f"no se pudo leer {que} {ruta}: {error.strerror}") from error
    except UnicodeDecodeError as error:
        raise ErrorInsumo(
            f"{ruta.name}: no es UTF-8 válido (byte inválido en la posición {error.start})"
        ) from error


def _campo(obj: Mapping[str, object], nombre: str, donde: str) -> object:
    if nombre not in obj:
        raise ErrorInsumo(f"{donde}: falta el campo {nombre}")
    return obj[nombre]


def _texto_requerido(obj: Mapping[str, object], nombre: str, donde: str) -> str:
    valor = _campo(obj, nombre, donde)
    if not isinstance(valor, str) or not valor.strip():
        raise ErrorInsumo(f"{donde}: el campo {nombre} debe ser texto no vacío")
    return valor


def _nombre_archivo(obj: Mapping[str, object], donde: str) -> str:
    valor = _texto_requerido(obj, "archivo", donde)
    simple = Path(valor).name == valor and "\\" not in valor and not valor.startswith(".")
    if not simple:
        raise ErrorInsumo(f"{donde}: el campo archivo debe ser un nombre simple, sin carpetas")
    return valor


def _fecha_iso(obj: Mapping[str, object], nombre: str, donde: str) -> date:
    valor = _texto_requerido(obj, nombre, donde)
    mensaje = f"{donde}: el campo {nombre} debe ser una fecha AAAA-MM-DD válida"
    if not _PATRON_FECHA_ISO.fullmatch(valor):
        raise ErrorInsumo(mensaje)
    try:
        return date.fromisoformat(valor)
    except ValueError as error:
        raise ErrorInsumo(mensaje) from error


def _monto(obj: Mapping[str, object], nombre: str, donde: str) -> Decimal:
    try:
        return leer_monto_resumen(_campo(obj, nombre, donde), nombre)
    except ValueError as error:
        raise ErrorInsumo(f"{donde}: {error}") from error


def _conteo(obj: Mapping[str, object], nombre: str, donde: str) -> int:
    valor = _campo(obj, nombre, donde)
    if type(valor) is not int or valor < 0:
        raise ErrorInsumo(f"{donde}: el campo {nombre} debe ser un entero no negativo")
    return valor


def _layout_declarado(obj: Mapping[str, object], donde: str) -> Layout:
    nombre = _texto_requerido(obj, "layout", donde)
    if nombre not in LAYOUTS:
        raise ErrorInsumo(
            f"{donde}: el campo layout {nombre!r} no está en el catálogo ({', '.join(LAYOUTS)})")
    layout = LAYOUTS[nombre]
    if _texto_requerido(obj, "moneda", donde) != layout.moneda:
        raise ErrorInsumo(f"{donde}: el campo moneda debe ser {layout.moneda} para {nombre}")
    return layout


def _estado_de_resumen(obj: object, posicion: int) -> EstadoResumen:
    donde = f"{NOMBRE_RESUMEN}, estado #{posicion}"
    if not isinstance(obj, dict):
        raise ErrorInsumo(f"{donde}: cada estado de cuenta debe ser un objeto JSON")
    emisor = _texto_requerido(obj, "emisor", donde)
    if not _PATRON_EMISOR.fullmatch(emisor):
        raise ErrorInsumo(f"{donde}: el campo emisor debe ser MAYÚSCULAS, dígitos o _")
    inicio, fin = (_fecha_iso(obj, n, donde) for n in ("periodo_inicio", "periodo_fin"))
    if inicio > fin:
        raise ErrorInsumo(f"{donde}: periodo_inicio es posterior a periodo_fin")
    montos = {nombre: _monto(obj, nombre, donde) for nombre in _CAMPOS_MONTO}
    return EstadoResumen(
        archivo=_nombre_archivo(obj, donde), emisor=emisor,
        nombre_emisor=_texto_requerido(obj, "nombre_emisor", donde),
        layout=_layout_declarado(obj, donde).nombre, moneda=_texto_requerido(obj, "moneda", donde),
        periodo_inicio=inicio, periodo_fin=fin, corte=_fecha_iso(obj, "corte", donde),
        num_movimientos=_conteo(obj, "num_movimientos", donde), **montos)


def _rechazar_repetidos(estados: Sequence[EstadoResumen]) -> None:
    for campo in ("emisor", "archivo"):
        valores = [getattr(e, campo) for e in estados]
        repetidos = sorted({v for v in valores if valores.count(v) > 1})
        if repetidos:
            raise ErrorInsumo(f"{NOMBRE_RESUMEN}: {campo} repetido: {', '.join(repetidos)}")


def leer_resumen(ruta: Path) -> Tuple[EstadoResumen, ...]:
    """Lee y valida completo el resumen del periodo."""
    try:
        datos = json.loads(_leer_texto(ruta, "el resumen"))
    except json.JSONDecodeError as error:
        raise ErrorInsumo(f"{NOMBRE_RESUMEN}: no es JSON válido ({error.msg})") from error
    if not isinstance(datos, dict):
        raise ErrorInsumo(f"{NOMBRE_RESUMEN}: la raíz debe ser un objeto JSON")
    if datos.get("esquema") != ESQUEMA_RESUMEN:
        raise ErrorInsumo(f"{NOMBRE_RESUMEN}: esquema {datos.get('esquema')!r}; "
                          f"se esperaba {ESQUEMA_RESUMEN!r}")
    lista = datos.get("estados_cuenta")
    if not isinstance(lista, list) or not lista:
        raise ErrorInsumo(f"{NOMBRE_RESUMEN}: estados_cuenta debe ser una lista no vacía")
    estados = tuple(_estado_de_resumen(obj, n) for n, obj in enumerate(lista, 1))
    _rechazar_repetidos(estados)
    return estados


# --- estados de cuenta crudos -------------------------------------------------


def leer_filas_csv(ruta: Path) -> Tuple[Tuple[str, ...], ...]:
    """Todas las filas del CSV como texto, encabezado incluido."""
    texto = _leer_texto(ruta, "el estado de cuenta (si aún no existe, declararlo con "
                              "--sin-estado)")
    try:
        return tuple(tuple(fila) for fila in csv.reader(io.StringIO(texto, newline="")))
    except csv.Error as error:
        raise ErrorInsumo(f"{ruta.name}: CSV ilegible ({error})") from error


def _cargo(estado: EstadoResumen, layout: Layout, fila: int, lectura: Lectura) -> Cargo:
    problemas = lectura.problemas
    return Cargo(
        cargo_id=f"{estado.emisor}-{fila:0{DIGITOS_FILA}d}", emisor=estado.emisor,
        layout=layout.nombre, archivo=estado.archivo, corte=estado.corte, fila=fila,
        fecha=lectura.fecha, fecha_aplicacion=lectura.fecha_aplicacion,
        descripcion=lectura.descripcion, titular=lectura.titular,
        tarjeta_ultimos4=lectura.tarjeta_ultimos4, monto=lectura.monto, moneda=layout.moneda,
        monto_original=lectura.monto_original, moneda_original=lectura.moneda_original,
        tipo_cambio=lectura.tipo_cambio,
        tipo_movimiento=clasificar_movimiento(lectura.monto, lectura.descripcion,
                                              layout.marca_pago),
        estado=ESTADO_ININTERPRETABLE if problemas else ESTADO_OK,
        motivo=SEPARADOR_MOTIVOS.join(problemas) if problemas else None,
    )


def cargos_de_filas(estado: EstadoResumen,
                    filas: Sequence[Sequence[str]]) -> Tuple[Cargo, ...]:
    """Detecta el layout por el encabezado y convierte cada fila en un cargo."""
    if not filas:
        raise ErrorInsumo(f"{estado.archivo}: archivo vacío, sin encabezado")
    layout = detectar_layout(filas[0], estado.archivo)
    if layout.nombre != estado.layout:
        raise ErrorInsumo(f"{estado.archivo}: el encabezado es de {layout.nombre}, pero el "
                          f"resumen declara {estado.layout}")
    return tuple(_cargo(estado, layout, n, interpretar_fila(layout, celdas))
                 for n, celdas in enumerate(filas[1:], 1))


# --- candados -----------------------------------------------------------------


def _comparar(nombre: str, esperado: Numero, calculado: Numero) -> Comprobacion:
    def texto(valor: Numero) -> str:
        return texto_monto(valor) if isinstance(valor, Decimal) else str(valor)
    return Comprobacion(nombre, texto(esperado), texto(calculado), esperado == calculado)


def calcular_control(estado: EstadoResumen, cargos: Sequence[Cargo]) -> ControlEstado:
    """Compara conteo y sumas del universo de un estado contra su resumen."""
    montos = [c.monto for c in cargos if c.monto is not None]
    neto = sum(montos, _CERO)
    comprobaciones = (
        _comparar("num_movimientos", estado.num_movimientos, len(cargos)),
        _comparar("montos_legibles", len(cargos), len(montos)),
        _comparar("total_cargos", estado.total_cargos, sum((m for m in montos if m > 0), _CERO)),
        _comparar("total_abonos", estado.total_abonos, sum((m for m in montos if m < 0), _CERO)),
        _comparar("total_neto", estado.total_neto, neto),
        _comparar("saldo_al_corte", estado.saldo_al_corte, estado.saldo_anterior + neto),
    )
    return ControlEstado(estado.archivo, estado.emisor, estado.layout, comprobaciones)


def exigir_candados(universo: Universo) -> None:
    """Lanza `CandadoFallido` con el detalle si algún total no cuadra."""
    fallas = [f"{control.emisor}/{c.nombre}: esperado {c.esperado}, calculado {c.calculado}"
              for control in universo.controles for c in control.comprobaciones if not c.cuadra]
    if fallas:
        raise CandadoFallido("totales de control que no cuadran: " + "; ".join(fallas))


# --- universo -----------------------------------------------------------------


def _emisores_omitidos(estados: Sequence[EstadoResumen],
                       omitidos: Sequence[str]) -> FrozenSet[str]:
    if isinstance(omitidos, str):
        raise ErrorInsumo("los estados omitidos deben ser una lista de emisores")
    conocidos = {e.emisor for e in estados}
    desconocidos = sorted(set(omitidos) - conocidos)
    if desconocidos:
        raise ErrorInsumo(f"se declaró ausente un emisor que el resumen no lista: {desconocidos}")
    if len(set(omitidos)) != len(omitidos):
        raise ErrorInsumo("un emisor se declaró ausente más de una vez")
    if set(omitidos) == conocidos:
        raise ErrorInsumo("se declararon ausentes todos los estados: no queda nada que leer "
                          "ni que comprobar")
    return frozenset(omitidos)


def construir_universo(carpeta: Union[str, Path], omitidos: Sequence[str] = ()) -> Universo:
    """Construye el universo de la carpeta; no escribe nada.

    `omitidos` declara explícitamente los emisores cuyo estado falta: no se
    leen y el universo queda provisional.
    """
    raiz = Path(carpeta)
    estados = leer_resumen(raiz / NOMBRE_RESUMEN)
    ausentes = _emisores_omitidos(estados, omitidos)
    lotes = [(e, cargos_de_filas(e, leer_filas_csv(raiz / e.archivo)))
             for e in estados if e.emisor not in ausentes]
    cargos = sorted((c for _, del_estado in lotes for c in del_estado),
                    key=lambda c: (c.emisor, c.fila))
    controles = sorted((calcular_control(e, del_estado) for e, del_estado in lotes),
                       key=lambda c: c.emisor)
    return Universo(tuple(cargos), tuple(controles), tuple(sorted(ausentes)))


# --- serialización ------------------------------------------------------------


def _iso(valor: Optional[date]) -> Optional[str]:
    return valor.isoformat() if valor is not None else None


def _importe(valor: Optional[Decimal]) -> Optional[str]:
    return texto_monto(valor) if valor is not None else None


def registro_de_cargo(cargo: Cargo) -> Dict[str, Escalar]:
    """El cargo como objeto JSON: fechas ISO e importes como texto."""
    return {
        "archivo": cargo.archivo, "cargo_id": cargo.cargo_id, "corte": cargo.corte.isoformat(),
        "descripcion": cargo.descripcion, "emisor": cargo.emisor, "estado": cargo.estado,
        "fecha": _iso(cargo.fecha), "fecha_aplicacion": _iso(cargo.fecha_aplicacion),
        "fila": cargo.fila, "layout": cargo.layout, "moneda": cargo.moneda,
        "moneda_original": cargo.moneda_original, "monto": _importe(cargo.monto),
        "monto_original": _importe(cargo.monto_original), "motivo": cargo.motivo,
        "tarjeta_ultimos4": cargo.tarjeta_ultimos4,
        "tipo_cambio": texto_tipo_cambio(cargo.tipo_cambio) if cargo.tipo_cambio is not None else None,
        "tipo_movimiento": cargo.tipo_movimiento, "titular": cargo.titular,
    }


def serializar_universo(universo: Universo) -> str:
    """JSONL determinista: una línea por cargo, llaves ordenadas, fin de línea LF."""
    return "".join(json.dumps(registro_de_cargo(c), ensure_ascii=False, sort_keys=True) + "\n"
                   for c in universo.cargos)


def _control_como_dict(control: ControlEstado) -> Dict[str, object]:
    return {
        "archivo": control.archivo, "emisor": control.emisor, "layout": control.layout,
        "cuadra": control.cuadra,
        "comprobaciones": [{"nombre": c.nombre, "esperado": c.esperado,
                            "calculado": c.calculado, "cuadra": c.cuadra}
                           for c in control.comprobaciones],
    }


def serializar_control(universo: Universo) -> str:
    """Reporte de control determinista (JSON con sangría y llaves ordenadas)."""
    reporte = {
        "esquema": ESQUEMA_CONTROL, "provisional": universo.es_provisional,
        "estados_omitidos": list(universo.estados_omitidos), "cuadra": universo.cuadra,
        "num_cargos": len(universo.cargos),
        "filas_ininterpretables": [{"cargo_id": c.cargo_id, "motivo": c.motivo}
                                   for c in universo.cargos if c.estado != ESTADO_OK],
        "estados": [_control_como_dict(c) for c in universo.controles],
    }
    return json.dumps(reporte, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


# --- CLI ----------------------------------------------------------------------


class _ErrorArgumentos(Exception):
    pass


class _Analizador(argparse.ArgumentParser):
    """argparse que reporta los errores con código 2 desde `main`, sin `sys.exit`."""

    def error(self, message: str) -> NoReturn:
        raise _ErrorArgumentos(message)


def _analizador() -> _Analizador:
    analizador = _Analizador(prog="python3 -m conciliacion.universo",
                             description="Universo de cargos desde estados de cuenta crudos.")
    analizador.add_argument("dir_crudos", type=Path,
                            help=f"carpeta con {NOMBRE_RESUMEN} y los CSV que lista")
    analizador.add_argument("--salida", type=Path, required=True,
                            help="ruta del universo JSONL")
    analizador.add_argument("--control", type=Path, default=None,
                            help="ruta del reporte de control (por omisión, junto al universo)")
    analizador.add_argument("--sin-estado", dest="sin_estado", action="append", default=[],
                            metavar="EMISOR", help="declara ausente el estado de EMISOR "
                            "(repetible); el universo queda provisional")
    return analizador


def ruta_control_por_omision(salida: Path) -> Path:
    if salida.suffix == ".jsonl":
        return salida.with_suffix(".control.json")
    return salida.with_name(salida.name + ".control.json")


def _lineas_de_reporte(universo: Universo) -> List[str]:
    lineas = []
    for control in universo.controles:
        filas = [c for c in universo.cargos if c.emisor == control.emisor]
        marcadas = sum(1 for c in filas if c.estado != ESTADO_OK)
        lineas.append(f"{control.archivo} ({control.emisor}, {control.layout}): "
                      f"{len(filas)} filas, {marcadas} ininterpretables")
        lineas.extend(f"  [{'OK ' if c.cuadra else 'DIF'}] {c.nombre}: esperado={c.esperado} "
                      f"calculado={c.calculado}" for c in control.comprobaciones)
    if universo.es_provisional:
        lineas.append("PROVISIONAL: universo parcial; estados declarados ausentes: "
                      + ", ".join(universo.estados_omitidos))
    return lineas


def _escribir(ruta: Path, texto: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_bytes(texto.encode("utf-8"))


def _fallar(mensaje: str, codigo: int) -> int:
    print(f"ERROR: {mensaje}", file=sys.stderr)
    return codigo


def main(argv: Optional[Sequence[str]] = None) -> int:
    analizador = _analizador()
    try:
        args = analizador.parse_args(argv)
    except _ErrorArgumentos as error:
        print(analizador.format_usage(), end="", file=sys.stderr)
        return _fallar(f"argumentos inválidos: {error}", SALIDA_INSUMO)
    salida: Path = args.salida
    control: Path = args.control or ruta_control_por_omision(salida)
    if control.resolve() == salida.resolve():
        return _fallar("--control no puede ser la misma ruta que --salida", SALIDA_INSUMO)
    try:
        universo = construir_universo(args.dir_crudos, args.sin_estado)
    except ErrorInsumo as error:
        return _fallar(str(error), SALIDA_INSUMO)
    print("\n".join(_lineas_de_reporte(universo)))
    if not universo.cuadra:
        return _fallar("CANDADO: los totales de control no cuadran; no se escribió nada",
                       SALIDA_CANDADO)
    try:
        _escribir(salida, serializar_universo(universo))
        _escribir(control, serializar_control(universo))
    except OSError as error:
        return _fallar(f"no se pudo escribir la salida: {error}", SALIDA_INSUMO)
    print(f"CANDADO: los totales de control cuadran al centavo; {len(universo.cargos)} cargos "
          f"en {salida} y reporte en {control}")
    return SALIDA_OK


if __name__ == "__main__":
    sys.exit(main())
