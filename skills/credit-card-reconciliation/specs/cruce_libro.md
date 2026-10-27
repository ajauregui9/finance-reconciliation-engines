# Spec: cruce cargo ↔ libro mayor

Esta spec define el motor que decide, para cada cargo del universo, si ya quedó
registrado en el libro mayor y en qué asiento. Se escribió antes que el código y
el código se escribió desde aquí. La implementación vive en
`conciliacion/cruce_libro*.py` y `conciliacion/nombres.py`.

## Propósito

Responder, cargo por cargo, una pregunta concreta: "¿hay en el libro mayor un
asiento que registre este cargo?". La respuesta trae su evidencia, su riesgo y,
cuando no hay registro, un motivo que distingue con honestidad por qué no lo hay.
El motor recibe además los veredictos que una persona ya dio sobre algunos
cargos; los respeta tal cual y reporta dónde su propia propuesta no coincide.

## Entradas

### 1. Universo de cargos (`--universo`, JSONL)

Una línea JSON por cargo, tal como la produce el normalizador del universo
(el archivo `universo_cargos_esperado.jsonl` del generador sintético tiene la
misma forma). El motor lee el archivo; no importa el módulo del universo.

Campos que usa (los demás se ignoran):

| Campo | Regla |
|---|---|
| `cargo_id` | texto no vacío, único en el archivo |
| `emisor` | texto no vacío; debe tener cuenta de tarjeta en la config |
| `estado` | `ok` o cualquier otro valor (fila no interpretable) |
| `fecha` | ISO `AAAA-MM-DD`; obligatoria si `estado = ok` |
| `descripcion` | texto (puede estar vacío) |
| `monto` | texto decimal firmado en MXN (`-1234.56`) |
| `tipo_movimiento` | `cargo`, `abono` o `pago` |

### 2. Libro mayor (`--libro`, CSV)

Una fila por línea de póliza. Columnas obligatorias: `asiento_id`, `linea`,
`fecha`, `cuenta`, `proveedor_id`, `proveedor_nombre`, `debe`, `haber`, `moneda`.
Las demás columnas se conservan fuera del análisis. `linea` es un entero;
`debe`/`haber` son decimales no negativos; `moneda` debe ser la moneda de la
config (el motor compara importes en una sola moneda). El par
(`asiento_id`, `linea`) no se repite.

### 3. Veredictos humanos (`--veredictos`, CSV, opcional)

Columnas obligatorias: `cargo_id`, `veredicto`, `asiento_id`, `nota`.

- `veredicto = registrado` exige `asiento_id` (un asiento que exista en el libro).
- `veredicto = no_registrado` exige `asiento_id` vacío.
- Cada `cargo_id` aparece a lo más una vez y debe existir en el universo.
- `nota` es texto libre; se copia a la salida y nunca se interpreta.

Un archivo solo con encabezado es válido (cero veredictos). Si la opción no se
pasa, la corrida es equivalente a un archivo sin veredictos.

### 4. Config (`--config`, JSON, opcional)

Si no se pasa, se usan los valores por omisión del código, que son los mismos
de `config/cruce_libro.example.json`. Todos los valores son de ejemplo,
redondos, y sirven para los datos sintéticos; no son la calibración de ningún
proceso real.

| Llave | Ejemplo | Significado |
|---|---|---|
| `esquema` | `cruce_libro_config/v1` | versión del formato |
| `cuentas_tarjeta` | `{"ALFA": "2105-001", ...}` | cuenta contable de cada emisor |
| `proveedores_cubeta` | `["PRV-0999"]` | proveedores cuyo nombre no prueba identidad |
| `tolerancia_monto` | `"1.00"` | diferencia máxima de importe, en pesos |
| `ventana_busqueda_dias` | `{"min": -30, "max": 30}` | dónde se buscan candidatos |
| `ventana_cubeta_dias` | `{"min": 0, "max": 5}` | fecha exigida a un candidato cubeta |
| `umbral_similitud` | `"0.50"` | similitud mínima de nombre |
| `nombres` | ver "Similitud de nombres" | reglas de comparación de nombres |
| `max_candidatos_reporte` | `5` | cuántos candidatos se muestran por cargo |
| `moneda_libro` | `"MXN"` | única moneda aceptada en el libro |

Los importes y umbrales se escriben como texto (`"1.00"`); un número JSON con
decimales se rechaza para que ningún float entre al cálculo. Una llave
desconocida también se rechaza (un error de dedo no debe pasar en silencio).
`ventana_cubeta_dias` debe caber dentro de `ventana_busqueda_dias`.

## Salida (`--salida`, JSON)

Un solo documento JSON, UTF-8, con llaves ordenadas, sangría de 2 espacios,
fin de línea LF y sin marcas de tiempo ni rutas. Dos corridas con los mismos
insumos producen bytes idénticos (mismo SHA-256).

```text
esquema      "cruce_libro/v1"
parametros   la config efectiva (importes como texto)
insumos      conteos y SHA-256 de cada archivo leído
candados     exclusividad, cobertura, partida_doble -> {ok, detalle}
resumen      conteos de la propuesta y del resultado final, conflictos, montos
conflictos   lista de conflictos veredicto ↔ propuesta, ordenada por cargo_id
cargos       un objeto por cargo, ordenado por cargo_id
```

Cada cargo trae:

- `propuesta`: lo que el motor concluye por sí solo, sin mirar veredictos:
  `asiento_id`, `linea`, `evidencia`, `riesgo_cubeta`, `similitud`,
  `delta_dias`, `diferencia_monto` y `motivo_sin_cruce`.
- `veredicto`: el veredicto humano tal como llegó, o `null`.
- `conflicto`: el tipo de desacuerdo entre veredicto y propuesta, o `null`.
- `final`: lo que vale después de aplicar los veredictos: `asiento_id`,
  `origen` (`motor` o `veredicto_humano`), `riesgo_cubeta`,
  `motivo_sin_cruce` y `reasignado_por_veredicto`.
- `candidatos`: conteos (`total`, `elegibles`, `descartados_por_nombre`,
  `cubeta_fuera_de_fecha`) y una muestra ordenada de hasta
  `max_candidatos_reporte` candidatos con su evaluación. La muestra se recorta;
  los conteos nunca.

## Qué cargos se buscan

1. Si `estado` no es `ok`, no se busca: motivo `fila_ininterpretable`
   (esta regla va primero porque una fila ilegible no ofrece nada confiable).
2. Si `tipo_movimiento = pago`, no se busca: motivo `no_aplica`. Un pago a la
   tarjeta no es un gasto que deba tener registro propio.
3. `cargo` y `abono` se buscan.

## Candidatos

Una línea del libro es candidata para un cargo cuando cumple todo esto:

- su `cuenta` es la cuenta de tarjeta del emisor del cargo;
- el importe está del lado que corresponde: `haber` para un cargo (monto
  positivo), `debe` para un abono (monto negativo), y es mayor que cero;
- `|importe - |monto|| <= tolerancia_monto`;
- `delta_dias = fecha de la línea - fecha del cargo` cae dentro de
  `ventana_busqueda_dias` (ambos extremos inclusive).

La ventana de búsqueda es amplia a propósito: sirve para ver candidatos que
luego se descartan y así poder explicar el motivo del no-cruce. Una línea de
nómina o de cuentas por pagar nunca es candidata, aunque su importe coincida,
porque no está en la cuenta de la tarjeta.

## Evaluación de cada candidato

- **Proveedor-cubeta** (`proveedor_id` en `proveedores_cubeta`): su nombre no
  se compara, porque agrupa muchos comercios y no prueba nada. Para ser
  elegible necesita, además del importe, una fecha dentro de
  `ventana_cubeta_dias`. Si queda fuera, se marca `cubeta_fuera_de_fecha`.
  Un cruce contra la cubeta sale con `evidencia = monto_y_fecha_cubeta` y
  `riesgo_cubeta = true`.
- **Proveedor propio**: se calcula la similitud entre la `descripcion` del
  cargo y el `proveedor_nombre` de la línea. Es elegible si la similitud es
  al menos `umbral_similitud`; si no, se marca `nombre_insuficiente`. Un cruce
  así sale con `evidencia = monto_y_nombre` y `riesgo_cubeta = false`.

## Similitud de nombres

La medida es propia, solo usa enteros y fracciones exactas, y se reporta con
cuatro decimales (`ROUND_HALF_UP`).

**Por qué no `difflib`.** `SequenceMatcher` devuelve un float, tiene una
heurística de "basura automática" que cambia el resultado según el largo del
texto y su algoritmo es un detalle de implementación que la biblioteca estándar
no promete mantener entre versiones. Para que el resultado sea el mismo en
Python 3.9 y 3.12 sin depender de eso, la medida está escrita aquí, con reglas
explícitas y aritmética exacta (`fractions.Fraction`).

**Tokens.** El texto pasa a mayúsculas, se le quitan los acentos (descomposición
NFKD y descarte de marcas combinantes), todo lo que no sea letra A-Z o dígito se
vuelve espacio y se separa por espacios. Se descartan los tokens de puro dígito
(folios, números de sucursal) y los de una sola letra.

**Stopwords por lado.** Cada lado tiene su propio vocabulario:

- lado izquierdo: las descripciones distintas de los cargos que se buscan;
- lado derecho: los nombres de proveedor distintos de las líneas en cuentas de
  tarjeta.

Un token es stopword de un lado si aparece en al menos
`nombres.min_nombres_stopword` nombres distintos de ese lado, o si está en
`nombres.stopwords_fijas` (formas societarias como `SA`, `CV`, `LLC`). Las
stopwords de un lado solo se quitan de los nombres de ese lado: que un token
sea común entre los descriptores bancarios no dice nada de los nombres del ERP,
y al revés. Si quitar stopwords deja vacío un nombre, ese nombre se usa
completo.

**Enlaces entre tokens.** Dos tokens `a` (izquierda) y `b` (derecha) se enlazan
con un crédito igual al número de caracteres que comparten según la primera
regla que aplique:

1. iguales: el largo del token;
2. truncamiento: el más corto es prefijo del más largo y mide al menos
   `nombres.largo_min_prefijo` (`TAQ`/`TAQUERIA`): el largo del más corto;
3. abreviatura: el más corto mide de 2 a `nombres.largo_max_abreviatura`, empieza
   con la misma letra y sus letras aparecen en orden dentro del más largo
   (`HTL`/`HOTEL`, `NAL`/`NACIONAL`): el largo del más corto;
4. raíz común: comparten un prefijo de al menos `nombres.largo_min_raiz`
   caracteres (`AUTOS`/`AUTOLAVADO`): el largo de ese prefijo.

Además, un token de un lado se enlaza con dos tokens consecutivos del otro lado
cuando se puede partir en dos piezas de al menos `nombres.largo_min_pieza`
caracteres y cada pieza es prefijo del token correspondiente (`DEMOCLOUD` con
`DEMO CLOUD`). Aquí los tokens del otro lado se toman antes de quitar stopwords,
porque una palabra pegada a otra no deja de serlo; los caracteres de una pieza
que es stopword no cuentan como crédito.

**Asignación de enlaces.** Se arman todos los enlaces posibles y se ordenan por
crédito total descendente y luego por posición de los tokens; se aceptan en ese
orden mientras ningún token se use dos veces.

**Medida.** Con `C_izq`, `C_der` = caracteres acreditados en cada lado y `L_izq`,
`L_der` = caracteres de los tokens que no son stopword en cada lado:

    similitud = (C_izq + C_der) / (L_izq + L_der)

Vale 1 cuando cada carácter se explica con el otro lado y 0 cuando no hay
ningún enlace.

## Asignación (greedy global, exclusiva)

El motor no resuelve un problema de asignación óptima; usa una asignación
greedy con orden total:

1. Se forman todos los pares (cargo, candidato elegible) cuyo asiento no esté
   reservado.
2. Se ordenan por esta llave, de mayor a menor prioridad:
   1. evidencia: `monto_y_nombre` antes que `monto_y_fecha_cubeta`;
   2. diferencia de importe ascendente;
   3. similitud descendente (la cubeta cuenta como 0);
   4. `|delta_dias|` ascendente;
   5. `delta_dias` ascendente;
   6. `cargo_id`, `asiento_id` y `linea` ascendentes.
3. Se recorren en ese orden; un par se acepta si ni el cargo ni el asiento
   tienen ya pareja.

La unidad de exclusividad es el asiento: un asiento respalda a lo más un cargo.
Como la llave es un orden total, el resultado no depende del orden de los
archivos de entrada. En un grupo de cargos idénticos frente a asientos idénticos
el desempate por identificadores da un uno a uno estable.

## Motivos de no-cruce

| Motivo | Cuándo |
|---|---|
| `fila_ininterpretable` | la fila del estado de cuenta no se pudo leer |
| `no_aplica` | pago a la tarjeta |
| `sin_candidato` | ninguna línea cumple cuenta, lado, importe y ventana |
| `candidato_ocupado` | hubo candidatos elegibles, pero sus asientos ya respaldan a otro cargo o los reservó un veredicto |
| `descartado_por_nombre` | todos los candidatos son de proveedor propio y ninguno alcanza el umbral de nombre (o los hay de ambos tipos y alguno cayó por nombre) |
| `cubeta_evidencia_insuficiente` | los únicos candidatos son de la cubeta y su fecha queda fuera de la ventana de cubeta |

Precedencia cuando hay varios: `candidato_ocupado`, luego
`descartado_por_nombre`, luego `cubeta_evidencia_insuficiente`. Los conteos de
`candidatos` permiten ver siempre la mezcla completa.

## Veredicto humano y conflictos

El veredicto humano es un insumo y nunca se sobrescribe.

1. **Propuesta.** Primero el motor corre sin mirar veredictos. Lo que resulta
   es la `propuesta` de cada cargo.
2. **Conflictos.** Para cada cargo con veredicto se compara contra su
   propuesta:

   | Veredicto | Propuesta | Conflicto |
   |---|---|---|
   | `registrado` en X | X | ninguno |
   | `registrado` en X | Y distinto de X | `asiento_distinto` |
   | `registrado` en X | sin cruce | `motor_sin_cruce` |
   | `no_registrado` | Y | `motor_con_cruce` |
   | `no_registrado` | sin cruce | ninguno |

3. **Resultado final.** Los cargos con veredicto quedan como dijo la persona
   (`origen = veredicto_humano`). Después el motor corre otra vez solo para los
   cargos sin veredicto, con los asientos citados por veredictos `registrado`
   reservados. Si el resultado de un cargo cambia respecto de su propuesta, se
   marca `reasignado_por_veredicto = true` y se cuenta en el resumen.

`riesgo_cubeta` del resultado final se calcula sobre el asiento final, venga de
donde venga: confirmar un cruce contra la cubeta no le quita el riesgo.

## Candados y códigos de salida

| Candado | Falla cuando |
|---|---|
| `exclusividad` | en el resultado final un asiento respalda a dos cargos (solo puede pasar si dos veredictos citan el mismo asiento) |
| `cobertura` | el número de cargos de salida no es el del universo, o los montos por estado no suman el total al centavo |
| `partida_doble` | algún asiento del libro no cuadra (`suma de debe != suma de haber`) |

| Código | Significado |
|---|---|
| `0` | corrida completa, salida escrita, todos los candados en verde |
| `2` | argumentos, config o insumos inválidos; no se escribe salida |
| `3` | algún candado falló; la salida se escribe igual, con el detalle, para poder revisarla |

Los conflictos entre veredicto y propuesta no son una falla: son información
para la persona que revisa y no cambian el código de salida.

## Determinismo

- Todo importe es `Decimal`. Los valores numéricos de entrada pasan por una sola
  frontera (`Decimal(str(x))`, cuantizado a centavos con `ROUND_HALF_UP`).
- La similitud usa `Fraction`; no hay floats en ninguna comparación.
- Ningún conjunto se recorre sin ordenar; la salida no lleva fechas de corrida.

## Lo que este motor NO hace

- No usa el CFDI ni el RFC del comercio: el cruce con CFDIs es otro motor. El
  único lazo entre el cargo y el proveedor del ERP es el nombre.
- No resuelve alias (un descriptor de pasarela de pago contra la razón social
  real). Si el nombre no se parece, el candidato se descarta y se reporta.
- No busca sumas: un asiento que registra varios cargos en una sola póliza, o
  un cargo registrado en varios asientos, no se cruza.
- No hace asignación óptima: la asignación es greedy con orden total. En casos
  raros, una elección temprana puede dejar sin pareja a un cargo que otra
  asignación sí habría cubierto; el motivo `candidato_ocupado` lo hace visible.
- No convierte monedas: el libro debe venir en la moneda de la config.
- No corrige ni completa veredictos humanos, ni decide entre dos veredictos que
  citan el mismo asiento: lo marca el candado de exclusividad.
- No sugiere la cuenta contable del gasto ni escribe nada en el ERP.
