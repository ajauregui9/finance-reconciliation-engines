# Spec: cruce cargo ↔ CFDI (`conciliacion.cruce_cfdi`)

Versión de la spec: 1. Esquema de salida: `cruce_cfdi/v1`.

## Propósito

Para cada cargo del universo de cargos, el motor decide qué CFDIs recibidos lo
respaldan, con qué tier de evidencia, y, si no encuentra respaldo, por qué. La
asignación es exclusiva: un CFDI respalda como máximo a un cargo.

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
     consumidores que necesitan subtotal e IVA (la extracción con LLM). Mismo
     parser, mismas validaciones y mismo orden por `uuid`; devuelve cada CFDI
     junto con dos montos en la moneda del comprobante, sin convertir:
     `subtotal` = `SubTotal` (obligatorio en esta función) e `iva_trasladado` =
     el atributo `TotalImpuestosTrasladados` del nodo `Impuestos` hijo directo
     del comprobante o, si ese atributo falta, la suma de `Importe` de los
     `Traslado` de ese nodo con `Impuesto="002"` (un traslado `Exento` sin
     `Importe` aporta cero; otro sin `Importe` es un error). Sin nodo
     `Impuestos` o sin traslados, el IVA es 0.00. Los impuestos por concepto
     nunca se suman. Ambos montos pasan por la misma conversión a `Decimal`
     (0.01, `ROUND_HALF_UP`) y un valor negativo es un error. El motor de cruce
     no usa estos montos: `cargar_cfdis_xml` no cambia y no exige `SubTotal`.

     **Decisión: el lector solo lee el desglose; no valida que cuadre con
     `Total`.** Razones: (1) el lector es compartido con el motor, y rechazar
     ahí un comprobante detendría todo el cruce por un CFDI que ya fue timbrado
     (la aritmética la revisa quien timbra); (2) la identidad completa es
     `SubTotal − Descuento + trasladados − retenidos (+ impuestos locales) =
     Total`, y una versión parcial rechazaría CFDIs válidos con retenciones o
     impuestos locales; (3) el consumidor compara los montos campo por campo:
     en la extracción con LLM, un desglose que no cuadra o que difiere del
     propuesto termina en revisión humana. Límite: con IEPS,
     `TotalImpuestosTrasladados` lo incluye, así que `iva_trasladado` queda por
     encima del IVA; un consumidor que lo compare contra un IVA falla cerrado
     (discrepancia).
3. **Config** (JSON, opcional). Si falta, se usan los valores de ejemplo de
   `config/cruce_cfdi.example.json`, que coinciden con los parámetros del
   conjunto sintético.

### Validación de insumos (código de salida 2)

- Cada línea JSONL debe ser un objeto JSON. Una línea vacía o ilegible es un
  error con número de línea; nunca se salta.
- Montos: cadena o número (no booleano). Se convierten una sola vez con
  `Decimal(str(x))` y se cuantizan a 0.01 con `ROUND_HALF_UP`. Los tipos de
  cambio no se usan.
- Fechas ISO (`AAAA-MM-DD`; en CFDIs también se acepta fecha y hora y se toma
  la fecha).
- `cargo_id` y `uuid` no se repiten. `estado = ok` exige `fecha`.
- `total` y `total_mxn` de un CFDI no son negativos: el signo lo da el tipo.
- Una config con llaves desconocidas o valores fuera de rango es inválida.

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
  sí sola para un cruce.

## Tiers de evidencia

Uno a uno (un cargo, un CFDI candidato), evaluados en este orden:

| Tier | Condición | Rango |
|---|---|---|
| `monto_exacto` | diferencia en pesos = 0 | 0 |
| `moneda_original` | cargo y CFDI en la misma moneda extranjera y diferencia en esa moneda ≤ `tolerancias.moneda_original` | 1 |
| `monto_tolerancia` | 0 < diferencia en pesos ≤ `tolerancias.uno_a_uno` | 2 |

Suma:

| Tier | Condición |
|---|---|
| `suma` | entre `suma.min_cfdis` y `suma.max_cfdis` CFDIs candidatos del mismo `rfc_emisor`, todos libres tras la fase uno a uno, cada uno con afinidad ≥ `afinidad_minima`, y cuyo valor firmado sumado en pesos difiere del monto en ≤ `tolerancias.suma` |

Las notas de crédito restan: una factura más su nota de crédito puede formar
una suma, y una nota de crédito sola puede respaldar un abono (monto negativo).
El vínculo `uuid_relacionado` no interviene en la decisión.

## Asignación greedy y precedencia

El motor hace una **asignación greedy** en dos fases; no es un emparejamiento
óptimo (no resuelve un problema bipartito de costo mínimo). Cada fase ordena sus
propuestas con un orden total y recorre la lista una vez: una propuesta se
acepta si su cargo sigue sin cruce y todos sus CFDIs siguen libres.

**Precedencia: un cruce uno a uno gana sobre una suma de 2–3 CFDIs.** La fase
uno a uno termina por completo antes de que empiece la de sumas. En
consecuencia: un cargo resuelto uno a uno nunca llega al tier de suma, y un
CFDI tomado uno a uno por cualquier cargo ya no está disponible para sumas de
otro cargo. Es la misma precedencia que asume el oráculo sintético.

Orden total de la fase uno a uno (de mejor a peor):

1. rango del tier (menor primero);
2. afinidad de nombre (mayor primero);
3. diferencia (menor primero; en la moneda que usó el tier);
4. |delta| (menor primero);
5. delta no negativo antes que negativo (el CFDI suele emitirse después);
6. `cargo_id` y luego `uuid`, en orden lexicográfico.

Orden total de la fase de sumas:

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

Un cargo sin cruce recibe exactamente un motivo. Se evalúan en este orden y
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
resumen      cargos, con_cruce, sin_cruce, por_evidencia{}, por_motivo{},
             cfdis_en_pool, cfdis_asignados, advertencias
invariantes  [{nombre, cumple, detalle}]
cargos       uno por cargo, ordenados por cargo_id:
  cargo_id, cfdis[] (uuids ordenados), evidencia, motivo_sin_cruce,
  diferencia, moneda_diferencia, delta_dias[] (alineado con cfdis),
  afinidad_nombre, cfdis_descartados[{uuid, motivo}], advertencias[]
```

Montos y afinidades se escriben como cadenas (`"0.00"`), nunca como números.
En una suma, `diferencia` es la del total del grupo y `afinidad_nombre` la
menor del grupo. En `moneda_original`, `diferencia` está en esa moneda.

## Invariantes (candados)

Se recalculan sobre el resultado, de forma independiente al algoritmo, y se
publican en la salida. Si alguno falla, la corrida no escribe la salida y
termina con código 3.

1. `cobertura`: cada cargo del universo aparece exactamente una vez.
2. `exclusividad`: ningún CFDI está asignado a dos cargos.
3. `cfdis_conocidos`: todo CFDI asignado existe en el pool.
4. `evidencia_o_motivo`: cada cargo tiene evidencia o motivo, nunca ambos ni
   ninguno; tiene CFDIs si y solo si tiene evidencia.
5. `coherencia_tier`: al recalcular, cada cruce cumple las condiciones de su
   tier (incluye: CFDIs candidatos, en ventana, del mismo emisor en sumas).
6. `maximalidad_uno_a_uno`: no queda un par (cargo, CFDI) que califique uno a
   uno con el cargo sin cruce uno a uno y el CFDI sin asignar uno a uno.

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
- No valida sellos, timbres ni el estatus del CFDI ante el SAT.
- No valida la aritmética del CFDI (`SubTotal`, impuestos, `Total`).
- No toma ni sobrescribe veredictos humanos ni decide deducibilidad.
- No llama a ningún LLM ni a servicios externos.
