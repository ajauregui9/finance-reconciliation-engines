"""Error común de la frontera de entrada."""
from __future__ import annotations


class ErrorFrontera(ValueError):
    """Un valor externo no cumple la forma que exige su contrato.

    El mensaje describe el valor y la regla que falló, sin contexto de archivo: cada
    motor lo envuelve en su propio error con el archivo, la fila y el campo.
    """
