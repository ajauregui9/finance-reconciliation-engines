# Spec: cruce cargo ↔ CFDI (`conciliacion.cruce_cfdi`)

Versión de la spec: 2. Esquema de salida: `cruce_cfdi/v1`.

## Propósito

Para cada cargo del universo de cargos, el motor decide qué CFDIs recibidos lo
respaldan, con qué tier de evidencia, y, si no encuentra respaldo, por qué. La
asignación es exclusiva: un CFDI se asigna como máximo a un cargo. Un cruce que
solo coincide por monto, sin afinidad de nombre suficiente, no respalda al cargo:
se publica como `monto_sin_afinidad`, pendiente de revisión humana.

## Entradas

1. **Universo de cargos** (JSONL, un objeto por línea; el formato de
   `examples/synthetic/universo_cargos_esperado.jsonl`). El motor usa:
   `cargo_id`, `fecha`, `descripcion`, `monto`, `moneda_original`,
   `monto_original`, `tipo_movimiento` (`cargo`, `abono`, `pago`) y `estado`
   (`ok`, `ininterpretable`). Los demás campos se ignoran.
2. **CFDIs**, en una de dos formas:
   - JSONL con el formato de `examples/synthetic/cfdis.jsonl`. El motor usa:
     `uuid`, `fecha_emision`, `tipo_comprobante`, `direccion`, `rfc_emisor`,
     `nombre_emisor`, `rfc_receptor`, `moneda`, `total`, `total_mxn` y,
     opcionalmente, `uuid_relacionado`.
   - Un directorio con archivos `.xml` de CFDI 3.3 o 4.0 (`--cfdis-xml`). Cada
     XML se traduce al mismo registro. El XML se parsea **solo** con
     `defusedxml` y con DTD prohibida; si la biblioteca no está instalada la
     corrida falla con un mensaje claro. No hay fallback a `xml.etree`.
     Traducción: `uuid` del `TimbreFiscalDigital`; `fecha_emision` = fecha de
     `Fecha`; `direccion = emitido` si el RFC emisor es la empresa y `recibido`
     en otro caso; `total_mxn` = `Total` × `TipoCambio` redondeado a centavos
     (en `MXN` y `XXX` es el mismo `Total`; otra moneda sin `TipoCambio` es un
     error); `uuid_relacionado` = el primer `CfdiRelacionado`. Un directorio sin
     archivos `.xml` o con un UUID repetido es un error.
   - Lectura con desglose (`cruce_cfdi_xml.cargar_cfdis_xml_con_montos`), para
     consumidores que necesitan el desglose fiscal (la extracción con LLM).
     Mismo parser, mismas validaciones y mismo orden por `uuid`; devuelve cada
     CFDI junto con estos montos en la moneda del comprobante, sin convertir
     (0.00 si el concepto no aparece):

     | Campo | Fuente |
     |---|---|
     | `subtotal` | `SubTotal` (obligatorio en esta función) |
     | `descuento` | `Descuento` del comprobante |
     | `iva_trasladado`, `ieps_trasladado` | suma de `Importe` de los `Traslado` con `Impuesto="002"` y `"003"` |
     | `total_trasladados` | `TotalImpuestosTrasladados`; si falta, la suma de todos los `Traslado` |
     | `isr_retenido`, `iva_retenido` | suma de `Importe` de las `Retencion` con `Impuesto="001"` y `"002"` |
     | `total_retenidos` | `TotalImpuestosRetenidos`; si falta, la suma de todas las `Retencion` |

     Traslados y retenciones son los del nodo `Impuestos` hijo directo del
     comprobante; los impuestos por concepto nunca se suman. Sin ese nodo, todo
     es 0.00. Un traslado `Exento` sin `Importe` aporta cero; cualquier otro
     traslado o retención sin `Importe` es un error. Todos los montos pasan por
     la misma frontera que el resto de los insumos (ver "Validación de
     insumos") y un valor negativo o ilegible es un error que nombra el archivo
     y el atributo. El motor de
     cruce no usa estos montos: `cargar_cfdis_xml` no cambia y no exige
     `SubTotal`.

     **Decisión: el lector solo lee el desglose; no valida que cuadre con
     `Total` ni que los totales declarados coincidan con la suma por impuesto.**
     Razones: (1) el lector es compartido con el motor, y rechazar ahí un
     comprobante detendría todo el cruce por un CFDI que ya fue timbrado (la
     aritmética la revisa quien timbra); (2) la identidad completa es
     `SubTotal − Descuento + trasladados − retenidos (+ impuestos locales) =
     Total`, y los impuestos locales viven en un complemento que este lector no
     lee, así que validarla rechazaría CFDIs válidos; (3) el consumidor compara
     los montos campo por campo: en la extracción con LLM, un desglose que no
     cuadra o que difiere del propuesto termina en revisión humana. Como el IVA
     y el IEPS se leen por clave de impuesto, un CFDI con IEPS da su IVA real.
     Límite: los impuestos locales (complemento `implocal`) no se leen; un
     consumidor que cuadre con este desglose falla cerrado ante ellos.
3. **Config** (JSON, opcional). Si falta, se usan los valores de ejemplo de
   `config/cruce_cfdi.example.json`, que coinciden con los parámetros del
   conjunto sintético.

### Validación de insumos (código de salida 2)

- Cada línea JSONL debe ser un objeto JSON. Una línea vacía o ilegible es un
  error con número de línea; nunca se salta.
- Montos: cadena o número (no booleano), con la frontera compartida
  (`frontera`): signo opcional, hasta dos decimales, dígitos ASCII, sin
  separador de miles, exponentes ni espacios internos (los del borde se
  recortan). **Un insumo nunca se redondea**: `100.005`, `١٠٠.٠٠` o `1,000.00`
  son error. Un número JSON entero entra exacto; un float pasa por su `repr` y
  se rechaza si tiene más de dos decimales significativos o más de 15 dígitos
  (`0.1 + 0.2` es `0.30000000000000004`: error). El resultado queda en
  centavos sin cambiar su valor. En el universo los tipos de cambio no se usan.
- XML: `Total`, `SubTotal`, `Descuento`, `Importe` y los totales de impuestos
  siguen la misma regla de montos (el Anexo 20 pide en el comprobante los
  decimales de la moneda). `TipoCambio` es positivo, con hasta seis decimales
  y sin redondear; solo el producto `Total × TipoCambio` se redondea a
  centavos (`ROUND_HALF_UP`). `Fecha` tiene la forma exacta
  `AAAA-MM-DDTHH:MM:SS`.
- Fechas ISO `AAAA-MM-DD` con dígitos ASCII (la misma forma en Python 3.9 a
  3.13: `20260710` o `2026-W28-5` son error); en CFDIs JSONL también se acepta
  `AAAA-MM-DDTHH:MM:SS` y se toma la fecha.
- `cargo_id` y `uuid` no se repiten. `estado = ok` exige `fecha`.
- `total` y `total_mxn` de un CFDI no son negativos: el signo lo da el tipo.
- Una config con llaves desconocidas o valores fuera de rango es inválida; sus
  tolerancias y umbrales siguen la misma regla de montos.

## Definiciones

- **delta**: `fecha_emision` del CFDI menos `fecha` del cargo, en días.
- **Valor firmado** de un CFDI: `+total` si es ingreso (`I`), `-total` si es
  nota de crédito (`E`). Se calcula en pesos (`total_mxn`) y en la moneda del
  comprobante (`total`).
- **Diferencia**: valor absoluto de (valor firmado − monto del cargo).
- **CFDI candidato**: `direccion = recibido`, tipo `I` o `E`, `rfc_receptor`
  igual al RFC de la empresa, `rfc_emisor` que no es genérico y
  `ventana.min ≤ delta ≤ ventana.max` (ambos extremos incluidos). La ventana es
  asimétrica: por defecto admite más días después del cargo que antes.
- **RFC genérico**: los RFC listados en la config (público en general,
  extranjero). Un CFDI con RFC genérico como emisor o como receptor nunca es
  evidencia.
- **Afinidad de nombre**: número entre 0 y 1 que compara la descripción del
  cargo con `nombre_emisor`. Ambos textos se pasan a mayúsculas sin acentos, se
  parten en palabras y se quitan formas societarias, artículos, números puros y
  palabras de menos de 3 letras. Dos palabras son compatibles si son iguales,
  si la más corta (de la misma inicial) aparece en orden dentro de la más
  larga (abreviaturas como `HTL` ↔ `HOTEL`, `OFI` ↔ `OFICINA`) o si comparten un
  prefijo de 4 letras o más. La cobertura de un nombre en otro es la fracción
  de sus palabras que tienen pareja compatible; la afinidad es la mayor de las
  dos coberturas (así es simétrica). Es una señal heurística: nunca basta por
  sí sola para un cruce. La afinidad de un cruce es la de su CFDI (uno a uno) o
  la menor de su grupo (suma).
- **Afinidad suficiente**: afinidad ≥ `afinidad_minima` (umbral inclusivo; con
  `0` toda afinidad es suficiente y el tier `monto_sin_afinidad` no aparece).
  `afinidad_minima` se usa en tres lugares: decide si un cruce por monto
  respalda o queda por revisar; filtra los CFDIs de la fase de sumas con
  afinidad; y sustituye al criterio relajado en los diagnósticos
  `fuera_de_ventana` y `fuera_de_tolerancia`.

### Límite: descriptores de pasarela o agregador

Un descriptor que antepone una pasarela de pago al comercio
(`PGDEMO *FLORERIA JARDIN`) no necesita trato especial: como la afinidad es la
mayor de las dos coberturas, la palabra de la pasarela solo resta en la
cobertura del lado del cargo, y la de la razón social no cambia
(`FLORERIA JARDIN DEMO SA DE CV` queda en 2/3). Cuando el descriptor no nombra al
comercio (`PGDEMO *PEDIDO 4471`) o usa un nombre comercial que no se parece a la
razón social, la afinidad es 0 y el cruce queda `monto_sin_afinidad`: el error
va hacia la revisión humana, nunca hacia un respaldo en silencio. El motor no
quita prefijos de pasarela (achicaría el denominador y subiría la afinidad de
cualquier par) ni compara contra el `concepto` del CFDI: es texto libre de
terceros que ningún motor de cruce lee (lo revisa la cuarentena del pipeline).

## Tiers de evidencia

Un cruce primero califica por monto y después por afinidad. Uno a uno (un cargo,
un CFDI candidato), por monto, evaluados en este orden:

| Tier por monto | Condición | Rango |
|---|---|---|
| `monto_exacto` | diferencia en pesos = 0 | 0 |
| `moneda_original` | cargo y CFDI en la misma moneda extranjera y diferencia en esa moneda ≤ `tolerancias.moneda_original` | 1 |
| `monto_tolerancia` | 0 < diferencia en pesos ≤ `tolerancias.uno_a_uno` | 2 |

Suma por monto: entre `suma.min_cfdis` y `suma.max_cfdis` CFDIs candidatos del
mismo `rfc_emisor`, todos libres al empezar su fase, cuyo valor firmado sumado en
pesos difiere del monto en ≤ `tolerancias.suma`.

Tier publicado:

| Tier | Cuándo | ¿Respalda? |
|---|---|---|
| `monto_exacto`, `moneda_original`, `monto_tolerancia` | uno a uno por monto con afinidad suficiente | sí |
| `suma` | suma por monto con afinidad suficiente en cada CFDI | sí |
| `monto_sin_afinidad` | uno a uno o suma por monto cuya afinidad no es suficiente | no: pendiente de revisión humana |

Un cruce `monto_sin_afinidad` no se rechaza ni se acepta en silencio: ocupa sus
CFDIs (exclusividad: ningún otro cargo los recibe), no lleva motivo de no-cruce,
publica su `afinidad_nombre` y cuenta en el resumen como `por_revisar`, nunca
como `respaldados`. Para saber qué coincidió: `diferencia` 0.00 en `MXN` es monto
exacto; una `moneda_diferencia` extranjera es moneda original; una diferencia
mayor que cero con un CFDI es tolerancia; dos o más CFDIs son una suma.

Las notas de crédito restan: una factura más su nota de crédito puede formar
una suma, y una nota de crédito sola puede respaldar un abono (monto negativo).
El vínculo `uuid_relacionado` no interviene en la decisión.

## Asignación greedy y precedencia

El motor hace una **asignación greedy** en cuatro fases; no es un emparejamiento
óptimo (no resuelve un problema bipartito de costo mínimo). Cada fase ordena sus
propuestas con un orden total y recorre la lista una vez: una propuesta se
acepta si su cargo sigue sin cruce y todos sus CFDIs siguen libres.

| Fase | Propuestas | Tier que asigna |
|---|---|---|
| 1 | uno a uno con afinidad suficiente | `monto_exacto`, `moneda_original`, `monto_tolerancia` |
| 2 | sumas de CFDIs con afinidad suficiente cada uno | `suma` |
| 3 | uno a uno sin afinidad suficiente | `monto_sin_afinidad` |
| 4 | sumas con CFDIs de cualquier afinidad | `monto_sin_afinidad` |

**Precedencia: la evidencia con afinidad gana sobre la que solo coincide por
monto y, dentro de cada nivel, un cruce uno a uno gana sobre una suma de 2–3
CFDIs.** Cada fase termina por completo antes de que empiece la siguiente y
solo ve cargos sin cruce y CFDIs libres. En consecuencia:

- **Empate de monto.** Si dos CFDIs del mismo monto califican para un cargo y
  solo uno tiene afinidad suficiente, gana ese (fase 1), aunque el otro esté más
  cerca en fecha; el otro queda libre. Si ninguno la tiene, decide el orden de
  la fase 3.
- Un CFDI con afinidad dentro de tolerancia gana a uno exacto sin afinidad, y
  una suma con afinidad gana a un uno a uno sin afinidad.
- Un CFDI afín a un cargo se asigna a ese cargo antes de que un cargo ajeno lo
  pueda tomar solo por monto.
- Un cargo resuelto en una fase nunca llega a las siguientes, y un CFDI tomado
  en una fase ya no está disponible para las siguientes. Es la misma
  precedencia que asume el oráculo sintético.

En la fase 4 el tier lo decide la menor afinidad del grupo. Un grupo con
afinidad suficiente en todos sus CFDIs solo llega ahí si el tope por emisor lo
dejó fuera de la fase 2 (con la advertencia `tope_suma_truncado`), y entonces se
publica como `suma`. Si un cargo recibe la misma advertencia en las fases 2 y 4,
se publica una vez.

Orden total de las fases uno a uno (1 y 3), de mejor a peor:

1. rango del tier (menor primero);
2. afinidad de nombre (mayor primero);
3. diferencia (menor primero; en la moneda que usó el tier);
4. |delta| (menor primero);
5. delta no negativo antes que negativo (el CFDI suele emitirse después);
6. `cargo_id` y luego `uuid`, en orden lexicográfico.

Orden total de las fases de sumas (2 y 4):

1. número de CFDIs (menos primero);
2. diferencia (menor primero);
3. afinidad mínima del grupo (mayor primero);
4. mayor |delta| del grupo (menor primero);
5. `cargo_id` y luego la tupla ordenada de `uuid`s.

Los criterios 6 (uno a uno) y 5 (sumas) hacen que dos propuestas nunca empaten,
así que el resultado no depende del orden de los insumos.

## Tope de complejidad de las sumas

Para cada par (cargo, emisor) se consideran a lo más
`suma.max_candidatos_por_emisor` CFDIs (N). Si hay más, se conservan los N de
menor |delta| (desempate por `uuid`) y el cargo recibe la advertencia
`tope_suma_truncado` con el emisor y el conteo original. El trabajo por par
queda acotado por Σ C(N, k) para k entre `min_cfdis` y `max_cfdis`; con los
valores de ejemplo (N = 10, k = 2..3) son 165 combinaciones. La config rechaza
N > 20 y k > 4. Los CFDIs se localizan por fecha con un índice ordenado, así que
el costo de armar candidatos crece con el tamaño de la ventana, no del pool.

## Motivo de no-cruce

Un cargo sin cruce recibe exactamente un motivo (un cargo con cruce
`monto_sin_afinidad` tiene cruce y no lleva motivo). Se evalúan en este orden y
gana el primero que aplica:

| Motivo | Cuándo |
|---|---|
| `fila_ininterpretable` | `estado` distinto de `ok` |
| `no_aplica` | `tipo_movimiento = pago` (pago a la tarjeta) |
| `solo_rfc_generico` | dentro de la ventana existe evidencia de monto (un CFDI uno a uno, o una suma de CFDIs del mismo RFC emisor) formada solo por CFDIs recibidos que fallan únicamente por un RFC genérico |
| `fuera_de_ventana` | un CFDI libre, válido salvo por la fecha, con tier uno a uno, afinidad ≥ mínima y delta a no más de `diagnostico.margen_fuera_de_ventana_dias` del borde de la ventana |
| `fuera_de_tolerancia` | un CFDI candidato libre con afinidad ≥ mínima y `tolerancia < diferencia ≤ diagnostico.banda_fuera_de_tolerancia` |
| `sin_candidato` | ninguno de los anteriores |

Regla de diseño: cuando un diagnóstico relaja un criterio duro (la fecha o el
monto), la afinidad de nombre lo sustituye; así un CFDI ajeno que solo
coincide por azar no se presenta como "casi cruce". Los CFDIs que dispararon
cualquier diagnóstico se listan en `cfdis_descartados` con su propio motivo.

## Salida

JSON UTF-8, llaves ordenadas, sangría de 2, salto de línea final, sin marcas de
tiempo ni rutas. Dos corridas con los mismos insumos dan el mismo SHA-256.

```text
esquema      "cruce_cfdi/v1"
parametros   la config efectiva
insumos      {universo, cfdis}: registros y sha256 del archivo leído (para un
             directorio XML: sha256 de la lista ordenada nombre + sha256 de cada archivo)
resumen      cargos, con_cruce, respaldados, por_revisar, sin_cruce,
             por_evidencia{}, por_motivo{}, cfdis_en_pool, cfdis_asignados,
             advertencias
invariantes  [{nombre, cumple, detalle}]
cargos       uno por cargo, ordenados por cargo_id:
  cargo_id, cfdis[] (uuids ordenados), evidencia, motivo_sin_cruce,
  diferencia, moneda_diferencia, delta_dias[] (alineado con cfdis),
  afinidad_nombre, cfdis_descartados[{uuid, motivo}], advertencias[]
```

Montos y afinidades se escriben como cadenas (`"0.00"`), nunca como números.
En una suma, `diferencia` es la del total del grupo y `afinidad_nombre` la
menor del grupo. En `moneda_original`, `diferencia` está en esa moneda.
`con_cruce` = `respaldados` + `por_revisar`, donde `por_revisar` cuenta los
cruces `monto_sin_afinidad`; `con_cruce` + `sin_cruce` = `cargos`.

## Invariantes (candados)

Se recalculan sobre el resultado, de forma independiente al algoritmo, y se
publican en la salida. Si alguno falla, la corrida no escribe la salida y
termina con código 3.

1. `cobertura`: cada cargo del universo aparece exactamente una vez.
2. `exclusividad`: ningún CFDI está asignado a dos cargos.
3. `cfdis_conocidos`: todo CFDI asignado existe en el pool.
4. `evidencia_o_motivo`: cada cargo tiene evidencia o motivo, nunca ambos ni
   ninguno; tiene CFDIs si y solo si tiene evidencia.
5. `coherencia_tier`: al recalcular, cada cruce cumple las condiciones de monto
   de su tier (incluye: CFDIs candidatos, en ventana, del mismo emisor en sumas;
   para `monto_sin_afinidad`, las de algún tier uno a uno o las de suma), la
   afinidad publicada es la recalculada, y es suficiente si y solo si el tier
   respalda.
6. `maximalidad_uno_a_uno`: no queda un par (cargo, CFDI) que califique uno a
   uno con afinidad suficiente con el cargo sin cruce uno a uno con afinidad y
   el CFDI fuera de esos cruces; ni un par que califique uno a uno (con
   cualquier afinidad) entre un cargo sin cruce y un CFDI sin asignar.

## CLI

```bash
cd skills/credit-card-reconciliation
python3 -m conciliacion.cruce_cfdi --universo <jsonl> --cfdis <jsonl> --salida <json> [--config <json>]
python3 -m conciliacion.cruce_cfdi --universo <jsonl> --cfdis-xml <dir> --salida <json> [--config <json>]
```

| Código | Significado |
|---|---|
| 0 | salida escrita, invariantes cumplidos |
| 2 | insumo o config inválidos, archivo ilegible, carpeta de salida inexistente o `defusedxml` ausente |
| 3 | invariante violado (no se escribe la salida) |

## Lo que este motor NO hace

- No cruza contra el libro mayor ni decide si un cargo está registrado.
- No lee estados de cuenta crudos; recibe el universo ya normalizado.
- No busca la asignación óptima global: es greedy con orden total documentado.
- No convierte divisas: usa `total_mxn` del insumo y, para el tier de moneda
  original, los montos en la moneda de cada lado.
- No usa `forma_pago` (es ruidosa) ni `uuid_relacionado` para decidir.
- No lee el `concepto` del CFDI ni quita prefijos de pasarela de la descripción
  del cargo para calcular la afinidad.
- No decide si un cruce `monto_sin_afinidad` es correcto: lo deja ocupado y
  visible para que una persona lo confirme o lo descarte.
- No valida sellos, timbres ni el estatus del CFDI ante el SAT.
- No valida la aritmética del CFDI (`SubTotal`, impuestos, `Total`).
- No toma ni sobrescribe veredictos humanos ni decide deducibilidad.
- No llama a ningún LLM ni a servicios externos.
