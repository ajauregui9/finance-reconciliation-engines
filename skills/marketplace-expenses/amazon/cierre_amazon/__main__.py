"""Punto de entrada: `python3 -m cierre_amazon` o `python3 <ruta>/cierre_amazon`."""
import os
import sys


def _asegurar_ruta_del_paquete() -> None:
    """Ejecutado por ruta, el directorio que contiene al paquete aún no está en sys.path."""
    contenedor = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if not __package__ and contenedor not in sys.path:
        sys.path.insert(0, contenedor)


_asegurar_ruta_del_paquete()
from cierre_amazon.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
