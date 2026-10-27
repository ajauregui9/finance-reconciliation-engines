"""Contexto de una corrida: la única pieza con estado mutable del generador.

Encapsula la instancia `random.Random` (nunca el `random` global), el registro
de montos ya usados y el consecutivo de claves internas. Vive solo durante un
intento de generación; todo lo que produce son objetos inmutables. Una etapa que
siembra sobre el conjunto ya ensamblado abre su propio contexto con otra `sal` y
registra con `ocupar` los montos y UUIDs que ya existen.
"""
from __future__ import annotations

import bisect
import calendar
import random
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Sequence, Set, Tuple, TypeVar

from .config import ConfigGenerador
from .dinero import desde_centavos, q4

T = TypeVar("T")

SALTO_SEMILLA = 1_000_003
MAX_SORTEOS = 2000


def periodo_emisor(config: ConfigGenerador, emisor: str) -> Tuple[date, date]:
    """Periodo del estado de cuenta: ALFA es el mes natural; BETA corta el día 28."""
    ultimo = calendar.monthrange(config.anio, config.mes)[1]
    if emisor == "ALFA":
        return date(config.anio, config.mes, 1), date(config.anio, config.mes, ultimo)
    anio_prev, mes_prev = (config.anio, config.mes - 1) if config.mes > 1 else (config.anio - 1, 12)
    dia_inicio = min(29, calendar.monthrange(anio_prev, mes_prev)[1])
    return date(anio_prev, mes_prev, dia_inicio), date(config.anio, config.mes, 28)


class Contexto:
    def __init__(self, config: ConfigGenerador, intento: int, sal: int = 0) -> None:
        self.config = config
        self.intento = intento
        self._rng = random.Random(config.semilla + intento * SALTO_SEMILLA + sal)
        self._montos: Dict[str, List[Decimal]] = {"MXN": [], "USD": []}
        self._uuids: Set[str] = set()
        self._consecutivo = 0

    def ocupar(self, montos: Iterable[Tuple[Decimal, str]], uuids: Iterable[str]) -> None:
        """Registra montos (con su moneda) y UUIDs que ya existen, para no repetirlos ni acercarse a ellos."""
        for monto, moneda in montos:
            self.reservar(monto, moneda)
        self._uuids.update(uuids)

    # ------------------------------------------------------------ azar básico
    def entero(self, minimo: int, maximo: int) -> int:
        return self._rng.randint(minimo, maximo)

    def elegir(self, opciones: Sequence[T]) -> T:
        return opciones[self._rng.randrange(len(opciones))]

    def barajar(self, opciones: Sequence[T]) -> List[T]:
        copia = list(opciones)
        self._rng.shuffle(copia)
        return copia

    def probable(self, porcentaje: int) -> bool:
        return self._rng.randrange(100) < porcentaje

    def clave(self, prefijo: str) -> str:
        self._consecutivo += 1
        return f"{prefijo}{self._consecutivo:05d}"

    def uuid(self) -> str:
        """UUID ficticio determinista con forma 8-4-4-4-12.

        La marca `SINT` (no hexadecimal) evita que pase por un UUID real, y el último
        grupo empieza con dígito para que nunca tenga forma de RFC (letras+6 dígitos).
        """
        while True:
            h = f"{self._rng.getrandbits(128):032X}"
            variante = "89AB"[int(h[16], 16) % 4]
            digito = int(h[20], 16) % 10
            valor = f"SINT{h[0:4]}-{h[4:8]}-4{h[9:12]}-{variante}{h[13:16]}-{digito}{h[21:32]}"
            if valor not in self._uuids:
                self._uuids.add(valor)
                return valor

    # ------------------------------------------------------------------ fechas
    def fecha_entre(self, inicio: date, fin: date) -> date:
        return inicio + timedelta(days=self.entero(0, (fin - inicio).days))

    def delta_en_ventana(self, minimo: int, maximo: int) -> int:
        """Un desfase en [minimo, maximo] recortado a la ventana configurada."""
        bajo = max(minimo, self.config.ventana_min)
        alto = min(maximo, self.config.ventana_max)
        return self.entero(bajo, alto) if bajo <= alto else alto

    # ------------------------------------------------------------------ montos
    def libre(self, monto: Decimal, moneda: str = "MXN") -> bool:
        """True si ningún monto registrado queda a menos de la separación mínima."""
        usados = self._montos[moneda]
        valor = abs(monto)
        i = bisect.bisect_left(usados, valor)
        vecinos = usados[max(0, i - 1):i + 1]
        return all(abs(valor - v) >= self.config.separacion_montos for v in vecinos)

    def reservar(self, monto: Decimal, moneda: str = "MXN") -> Decimal:
        bisect.insort(self._montos[moneda], abs(monto))
        return monto

    def monto(self, minimo: int, maximo: int, moneda: str = "MXN") -> Decimal:
        """Monto al azar en [minimo, maximo] unidades, separado de todo monto previo."""
        for _ in range(MAX_SORTEOS):
            valor = desde_centavos(self.entero(minimo * 100, maximo * 100))
            if self.libre(valor, moneda):
                return self.reservar(valor, moneda)
        raise RuntimeError(f"No hay montos libres en [{minimo}, {maximo}] {moneda}.")

    def porcion(self, total: Decimal, pct_min: int, pct_max: int) -> Decimal:
        """Una fracción de `total` (en %) cuyo monto quede libre; la reserva."""
        for _ in range(MAX_SORTEOS):
            valor = desde_centavos(int(total * self.entero(pct_min, pct_max)))
            if valor > 0 and self.libre(valor):
                return self.reservar(valor)
        raise RuntimeError(f"No hay porciones libres de {total}.")

    def tipo_cambio(self) -> Decimal:
        """Tipo de cambio ficticio MXN por USD, con cuatro decimales."""
        return q4(Decimal(self.entero(172000, 194000)) / 10000)
