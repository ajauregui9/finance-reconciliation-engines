# Spec: pipeline de tarjetas de punta a punta (`conciliacion.pipeline`)

Versión de la spec: 3. Esquema del reporte: `pipeline_tarjetas/v1`.

## Propósito

Un solo comando lleva del estado de cuenta crudo al reporte de conciliación:
universo de cargos → revisión de texto libre (cuarentena con revisión humana) →
cruce con CFDIs → cruce con el libro mayor → ensamblado por cargo. El pipeline no decide nada por su cuenta:
compone los tres motores existentes (`specs/universo.md`, `specs/cruce_cfdi.md`,
`specs/cruce_libro.md`), hace valer sus candados en orden, vuelve a verificar
al ensamblar que los resultados encajan entre sí y publica, cargo por cargo, la
respuesta completa.

## Entradas

### Carpeta de datos (`--datos`)

Una carpeta con nombres fijos. El pipeline no adivina nombres ni busca
archivos parecidos.

| Archivo | Uso | Si falta |
|---|---|---|
| `resumen_estados_cuenta.json` y los CSV que lista | universo de cargos | código 2 |
| `cfdis.jsonl` | pool de CFDIs del cruce con CFDI | código 2 |
| `libro_mayor.csv` | líneas del libro mayor | código 2 |
| `veredictos_libro.csv` | veredictos humanos del cruce con libro | código 2, salvo que se declare ausente con `--sin-veredictos` |

Los demás archivos de la carpeta (por ejemplo, un oráculo de pruebas) se
ignoran. Cada insumo pasa por la frontera de entrada de su propio motor; el
pipeline no relaja ni duplica esas validaciones.

### Opciones

| Opción | Efecto |
|---|---|
| `--salida DIR` | carpeta de salida (se crea si no existe); no puede ser un archivo ni la carpeta de datos |
| `--config-cfdi JSON` | config del cruce con CFDI; sin ella, los valores de ejemplo del motor |
| `--config-libro JSON` | config del cruce con libro; sin ella, los valores de ejemplo del motor |
| `--sin-estado EMISOR` | repetible; declara ausente el estado de cuenta de ese emisor (universo parcial) |
| `--sin-veredictos` | declara que el periodo no trae veredictos humanos |
| `--sin-guardia` | desactiva la revisión de texto libre con `prompt_guard` (no recomendado); el reporte lo registra como revisor `identidad` |

## Pasos y orden

Los pasos corren siempre en este orden. La corrida se detiene en el primer
paso que falla y el código de salida es el de ese paso.

| # | Paso | Falla con |
|---|---|---|
| 1 | Argumentos y carpeta de salida | 2 |
| 2 | Borrado de los artefactos de una corrida anterior en la carpeta de salida (solo los nombres de la sección "Salida") | 2 si no se pueden borrar |
| 3 | Lectura y validación de insumos: configs, estados de cuenta crudos, CFDIs, libro mayor y veredictos | 2 |
| 4 | Candados del universo: totales de control al centavo | 3 |
| 5 | Revisión de texto libre con `prompt_guard` y su candado | 2 si el guard no se puede cargar; 3 si falla el candado |
| 6 | Adaptación del universo: cada motor de cruce lee el texto exacto de `<salida>/etapas/universo.jsonl` con su propia frontera de entrada | 2 |
| 7 | Cruce con CFDI y sus invariantes | 3 |
| 8 | Cruce con libro mayor y sus candados | 3 |
| 9 | Ensamblado por cargo e invariantes del pipeline | 3 |
| 10 | Escritura de la salida | 2 |

Consecuencia del orden: un insumo inválido se reporta antes que cualquier
candado de cruce, y ningún motor de cruce consume un universo cuyos totales no
cuadran.

El paso 2 existe para que una corrida fallida nunca deje junto a sus mensajes
un reporte viejo que parezca vigente.

## Universo parcial

Un periodo es parcial cuando alguno de sus insumos se declaró ausente. La
ausencia nunca se infiere: un archivo que falta sin declaración es código 2.

- `--sin-estado EMISOR` se pasa al universo tal cual (mismas reglas de
  declaración que en `specs/universo.md`). Cada estado omitido agrega el motivo
  `estado_omitido`.
- Un veredicto cuyo cargo pertenece a un estado omitido no se puede aplicar,
  porque su cargo no está en el universo. No es un error y no se descarta: se
  publica en `veredictos_en_espera` y agrega el motivo `veredictos_en_espera`.
  Un veredicto de un cargo inexistente de un estado leído sigue siendo
  insumo inválido (código 2). El emisor de un cargo se lee de su `cargo_id`
  (`<EMISOR>-<fila>`).
- `--sin-veredictos` corre el cruce con libro sin veredictos y agrega el motivo
  `veredictos_omitidos`.

Con al menos un motivo, el reporte completo lleva `provisional: true` y la
lista `motivos_provisional` (`etapa`, `motivo`, `detalle`), y cada fila de
`cargos.jsonl` lleva `provisional: true`, para que ninguna fila leída suelta
pase por definitiva. Un universo parcial sigue exigiendo todos los candados de
los estados que sí se leyeron: provisional no es lo mismo que bloqueado, y el
código de salida sigue siendo 0.

## Revisión de texto libre: cuarentena con revisión humana

Entre el universo certificado y los cruces, el texto libre se revisa antes de que
pueda llegar a un modelo de lenguaje o a una carga al ERP. El revisor por omisión es
`prompt_guard` (`skills/security-guardian/specs/prompt_guard.md`): un filtro de
cuarentena que marca y manda a revisión humana; nunca aprueba, corrige ni quita un
registro. Que un texto no se marque no lo vuelve confiable.

Contrato (`conciliacion/pipeline_revision.py`, `conciliacion/pipeline_guardia.py`):

- **Entrada**: una tupla ordenada de textos libres
  (`origen`, `registro_id`, `campo`, `texto`). Se revisan dos campos:

  | `origen` | `registro_id` | `campo` |
  |---|---|---|
  | `cargo` | `cargo_id` | `descripcion` del universo |
  | `cfdi` | `uuid` | `concepto` del registro crudo de `cfdis.jsonl` |

  Un texto nulo o vacío no se envía. Un `concepto` que no es texto ni nulo es
  insumo inválido (código 2).
- **Revisor**: cualquier objeto con un `nombre` y un método
  `revisar(textos) -> observaciones`, recibido en `OpcionesPipeline.revisor`. Por
  omisión es `RevisorGuardia` (nombre `prompt_guard`): una observación por cada
  familia que el guard detecta en cada texto, con su fragmento. El paquete del guard
  se carga por ruta explícita (`skills/security-guardian/guardia`); si no existe, no
  carga o no ofrece `inspeccionar`, la corrida es inválida (código 2) en lugar de
  seguir sin revisión. `RevisorIdentidad` (nombre `identidad`, opción
  `--sin-guardia`) desactiva la revisión: no observa nada y la CLI lo avisa.
- **Salida**: observaciones (`origen`, `registro_id`, `campo`, `familia`,
  `fragmento`). Cada una debe citar un texto que se envió y traer una `familia` no
  vacía; si no, falla el candado `observaciones_conocidas` (código 3).
- **Alcance**: la etapa no recibe los registros, no puede cambiarlos ni quitarlos,
  y los cruces corren sobre los mismos insumos con o sin observaciones: los
  documentos de `<salida>/etapas/` son idénticos con y sin revisor.
- **Efecto**: un cargo con alguna observación sobre su propia descripción o sobre
  el concepto de un CFDI que tiene asignado queda con situación `en_revision`. Su
  cruce se publica tal como lo propusieron los motores, pero no cuenta como
  conciliado ni como ninguna otra situación automática hasta que una persona lo
  revise. Una observación sobre un CFDI que no está asignado a ningún cargo solo va
  a la cola.
- **Provisional**: una observación **no** vuelve provisional el reporte ni cambia
  el código de salida. Provisional significa "faltan insumos"; un registro marcado
  es un insumo completo que necesita una persona. El reporte lo destaca aparte: el
  bloque `revision_humana`, la partición `resumen.por_situacion.en_revision` y un
  aviso `REVISIÓN HUMANA` en la salida estándar.
- **Publicación**: la cola completa va en `revision_humana.cola` del reporte,
  ordenada; cada fila de `cargos.jsonl` lleva en `revision` las observaciones que la
  ponen en revisión. Los fragmentos son texto de terceros: quien lea el reporte los
  trata como dato, nunca como instrucción.

## Salida

Todo se escribe en `--salida` solo al final y solo con código 0, salvo
`bloqueo.json`, que se escribe solo con código 3. Con código 2 no se escribe
nada.

| Ruta | Contenido |
|---|---|
| `<salida>/reporte.json` | reporte del pipeline (esquema `pipeline_tarjetas/v1`) |
| `<salida>/cargos.jsonl` | una fila por cargo |
| `<salida>/etapas/universo.jsonl` | universo normalizado (formato de `specs/universo.md`) |
| `<salida>/etapas/universo.control.json` | reporte de control del universo |
| `<salida>/etapas/cruce_cfdi.json` | documento `cruce_cfdi/v1` del motor |
| `<salida>/etapas/cruce_libro.json` | documento `cruce_libro/v1` del motor |
| `<salida>/bloqueo.json` | solo con código 3: la etapa que bloqueó y los candados evaluados hasta ahí |

Los documentos de `<salida>/etapas/` son, byte por byte, los que escribe la CLI de cada
motor sobre los mismos insumos, con `<salida>/etapas/universo.jsonl` como universo de
ambos cruces. La única diferencia posible es la de un universo parcial: el
cruce con libro recibe solo los veredictos aplicables. Como los dos cruces
registran como SHA-256 de su universo el de `<salida>/etapas/universo.jsonl`, la cadena
de custodia se puede seguir de punta a punta.

### Fila de `cargos.jsonl`

Ordenadas por `cargo_id`, llaves ordenadas, una por línea.

```text
cargo_id, emisor, fecha, descripcion, monto, moneda, tipo_movimiento,
estado, motivo_fila       del universo (motivo_fila = motivo de la fila ininterpretable)
situacion                 ver tabla
provisional               true si el reporte es provisional
cfdi:        uuids[], tier, motivo_sin_cruce, diferencia, moneda_diferencia, delta_dias[],
             afinidad_nombre
libro_mayor: asiento_id, origen, riesgo_cubeta, motivo_sin_cruce,
             propuesta_asiento_id, conflicto, veredicto
revision     observaciones (origen, registro_id, campo, familia, fragmento) que ponen el
             cargo en revisión: las de su descripción y las de sus CFDIs asignados
```

`tier` es la evidencia del cruce con CFDI (`monto_exacto`, `moneda_original`,
`monto_tolerancia`, `suma` o `monto_sin_afinidad`) y `afinidad_nombre` su
afinidad de nombre como texto con dos decimales (nula sin cruce); ambos son los
del documento del motor. En `libro_mayor`, los campos sin prefijo son el
resultado final (después de aplicar veredictos) y `propuesta_asiento_id` es lo
que el motor propuso por sí solo. `veredicto` es `registrado`,
`no_registrado` o nulo.

| `situacion` | Cuándo (gana la primera que aplica) |
|---|---|
| `en_revision` | tiene observaciones de la revisión de texto libre (`revision` no vacío); su cruce no se acepta en automático |
| `fila_ininterpretable` | `estado` distinto de `ok` |
| `no_aplica` | `tipo_movimiento = pago` |
| `cfdi_por_revisar` | su tier de CFDI es `monto_sin_afinidad`: el CFDI coincide solo por monto, tenga o no asiento. Ocupa su UUID, pero no cuenta como respaldo; una persona lo confirma o lo descarta |
| `conciliado` | tiene CFDI y asiento |
| `falta_cfdi` | tiene asiento, no CFDI |
| `falta_registro` | tiene CFDI, no asiento |
| `falta_cfdi_y_registro` | ni CFDI ni asiento |

### `reporte.json`

```text
esquema              "pipeline_tarjetas/v1"
provisional          bool
motivos_provisional  [{etapa, motivo, detalle}]
insumos              SHA-256 y conteos de cada insumo leído; config: archivo (o null
                     si se usaron los valores de ejemplo) y SHA-256
parametros           config efectiva de cada motor de cruce
etapas               un resumen por etapa (universo, revision_texto_libre,
                     cruce_cfdi, cruce_libro)
candados             [{etapa, nombre, cumple, detalle}] de todas las etapas,
                     en el orden en que se evaluaron
resumen              total, por_emisor, por_situacion,
                     cfdi {por_tier, por_motivo, uuids_asignados},
                     libro_mayor {con_asiento, sin_asiento, por_motivo, por_origen,
                     riesgo_cubeta, conflictos}
revision_humana      {revisor, marcados, cargos_en_revision[], cola[]}
cfdi_por_revisar     [{cargo_id, situacion, uuids[], tier, afinidad_nombre, diferencia,
                     moneda_diferencia}] de cada fila con tier `monto_sin_afinidad`,
                     ordenadas por cargo_id (su situación es `cfdi_por_revisar`, o
                     `en_revision` si además tiene observaciones)
veredictos_en_espera [{cargo_id, veredicto, asiento_id}]
artefactos           {ruta: sha256} de cada archivo escrito, salvo el propio reporte
```

`revision_humana.marcados` cuenta `textos` (textos distintos marcados),
`observaciones`, `cargos_en_revision`, `cfdis_sin_cargo` (CFDIs marcados que no
respaldan ningún cargo) y `por_familia`. `etapas.revision_texto_libre` publica
`revisor`, `textos_revisados`, `observaciones` y `textos_marcados`.

Cada bolsa del resumen es `{cargos, monto}`; `por_emisor` agrega
`total_neto_estado`, el total de control del resumen de estados de cuenta. Las
particiones listan todo su catálogo (con ceros) más cualquier valor observado
fuera de él, para que nada quede sin contar. Montos como texto con dos
decimales, nunca como números JSON. El reporte no
lleva rutas absolutas ni marcas de tiempo: los insumos se nombran por su nombre
de archivo.

## Invariantes del pipeline

Se recalculan sobre las filas ensambladas, sin confiar en los motores. Si
alguno falla, la corrida termina con código 3 y escribe `bloqueo.json`.

| Invariante | Qué exige |
|---|---|
| `cobertura` | cada cargo del universo aparece exactamente una vez en el cruce con CFDI, en el cruce con libro y en las filas |
| `exclusividad_uuid` | ningún UUID está asignado a dos cargos |
| `exclusividad_asiento` | ningún asiento final respalda a dos cargos |
| `tier_o_motivo_cfdi` | cada fila tiene tier con al menos un UUID, o motivo sin UUIDs; nunca ambos ni ninguno |
| `asiento_o_motivo_libro` | cada fila tiene asiento final o motivo, nunca ambos ni ninguno |
| `totales_control` | por cada estado leído, la suma de los montos de sus filas es igual al `total_neto` del resumen de estados de cuenta, al centavo |
| `totales_resumen` | el total publicado es el de las filas; cada partición publicada en `resumen` (por emisor, por situación, tier más motivo de CFDI, con más sin asiento) suma ese total en cargos y en monto, al centavo; los motivos de libro suman lo que quedó sin asiento |
| `cuarentena` | una fila tiene observaciones si y solo si su situación es `en_revision` |
| `cola_completa` | cada observación de la cola sobre un cargo, o sobre un CFDI asignado a un cargo, aparece en la fila de ese cargo; una sobre un cargo que no está en las filas bloquea |
| `candidato_por_revisar` | una fila sin observaciones tiene situación `cfdi_por_revisar` si y solo si su tier de CFDI es `monto_sin_afinidad`, y toda fila con ese tier publica su `afinidad_nombre`: un CFDI que solo coincide por monto nunca cuenta como conciliado ni como `falta_registro` |

Los candados de cada motor se publican con su nombre original: los del
universo como `<EMISOR>.<comprobación>`, los invariantes del cruce con CFDI y
los candados del cruce con libro tal como los nombra su spec.

## Códigos de salida

| Código | Significado |
|---|---|
| 0 | Reporte escrito; todos los candados e invariantes en verde. Puede ser provisional y puede traer cargos `en_revision` o `cfdi_por_revisar` |
| 2 | Argumento, config o insumo inválido; archivo faltante sin declarar; carpeta de salida inválida; `prompt_guard` no se puede cargar; un motor rechaza el universo en su frontera; no se pudo escribir |
| 3 | Un candado o invariante bloquea: totales de control del universo, revisión de texto libre, invariantes del cruce con CFDI, candados del cruce con libro o invariantes del pipeline. Solo se escribe `bloqueo.json` |

Los mensajes de error van a la salida de error y empiezan con la etapa que
falló (`universo:`, `revision_texto_libre:`, `cruce_cfdi:`, `cruce_libro:`,
`pipeline:`).

## CLI y API

```bash
cd skills/credit-card-reconciliation
python3 -m conciliacion.pipeline --datos ../../examples/synthetic --salida <dir> \
    [--config-cfdi <json>] [--config-libro <json>] [--sin-estado EMISOR ...] [--sin-veredictos] \
    [--sin-guardia]
```

- `correr_pipeline(opciones) -> Corrida`: lee, cruza y ensambla; devuelve el
  código (0 o 3) y los artefactos como texto. No escribe nada. Lanza
  `InsumoPipeline` ante un insumo inválido.
- `escribir_artefactos(carpeta, corrida)` escribe los artefactos de la corrida.
- `main(argv) -> int` es la CLI.

## Determinismo

JSON en UTF-8 sin BOM, llaves ordenadas, sangría de 2, fin de línea LF y salto
de línea final; JSONL con llaves ordenadas. Todo monto es `Decimal`. Ningún
conjunto se recorre sin ordenar. Dos corridas sobre los mismos insumos producen
los mismos bytes en todos los archivos (mismo SHA-256).

## Lo que el pipeline NO hace

- No cambia ninguna regla de los motores: tolerancias, ventanas, tiers y
  motivos son los de cada spec y su config.
- No lee CFDIs en XML (el motor sí puede; el pipeline usa `cfdis.jsonl`).
- No bloquea, corrige ni borra texto libre: lo marca y manda el cargo a revisión humana.
- No reintenta, no corrige insumos y no completa veredictos.
- No sugiere cuentas contables ni escribe en el ERP.
- No llama a ningún LLM ni a servicios externos.
