# Código clean-room desde specs propias, verificado con una compuerta de similitud

Este repo es una recreación pública de procesos de conciliación y cierre. Ningún archivo se porta de código existente: cada módulo se escribe desde una spec en palabras propias y se prueba con datos sintéticos. Antes de publicar, una compuerta de similitud por líneas verifica que ningún archivo supere el 30% contra el material de referencia privado, que nunca entra al repo. Todos los umbrales son parámetros de config con valores de ejemplo redondos, no una calibración real.

## Considered Options

- Partir de código existente y renombrar: rechazado, porque la estructura y la calibración no serían propias.
- Cubrir varios marketplaces: rechazado, porque uno bien hecho (Amazon) demuestra lo mismo con menos superficie.

## Consequences

La compuerta corre a mano antes de publicar, nunca en CI público, porque necesita el material de referencia. Los specs viven junto a cada motor y son la fuente de verdad del comportamiento.
