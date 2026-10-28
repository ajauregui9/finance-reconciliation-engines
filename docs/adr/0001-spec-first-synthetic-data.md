# Cada motor se escribe desde una spec propia, con datos 100% sintéticos

Este repo implementa procesos de conciliación y cierre financiero. Cada motor se escribe desde una spec propia que vive junto a él y se prueba solo con datos 100% sintéticos, sembrados por generadores del propio repo. Los resultados esperados no se escriben a mano: los generadores producen oráculos junto con los datos y las pruebas comparan contra ellos. Todos los umbrales, tolerancias, ventanas y bandas son parámetros de config con valores de ejemplo redondos, no una calibración real.

## Considered Options

- Datos anonimizados: rechazado, porque la anonimización nunca es completa y no permite sembrar casos borde a voluntad.
- Resultados esperados escritos a mano: rechazado, porque se desincronizan de los datos; el oráculo generado cambia junto con la semilla.
- Cubrir varios marketplaces: rechazado, porque uno bien hecho (Amazon) demuestra lo mismo con menos superficie.

## Consequences

Las specs son la fuente de verdad del comportamiento: un cambio de comportamiento empieza en la spec y en sus pruebas. Cualquier persona puede regenerar los datos y los oráculos con la semilla publicada y obtener los mismos bytes. Los valores de config son ilustrativos y deben recalibrarse antes de usar un motor con datos reales.
