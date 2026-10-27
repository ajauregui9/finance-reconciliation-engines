"""Generador sintético determinista de insumos de conciliación de tarjetas.

Uso típico:

    from generador_sintetico import ConfigGenerador, generar, escribir_salida
    datos = generar(ConfigGenerador(semilla=4242))
    escribir_salida(datos, Path("examples/synthetic"))
"""
from .config import ConfigGenerador
from .ensamblado import generar
from .escritura import NOMBRES_ARCHIVO, escribir_salida
from .modelo import Datos
from .verificacion import verificar

__all__ = ["ConfigGenerador", "Datos", "NOMBRES_ARCHIVO", "escribir_salida", "generar", "verificar"]
