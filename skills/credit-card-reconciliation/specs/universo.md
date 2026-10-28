# Spec: universo de cargos

Esta spec define cómo se obtiene el universo de cargos de un periodo a partir de
los estados de cuenta crudos de los emisores de tarjeta. El universo es el lado
izquierdo de todo cruce posterior (CFDI y libro mayor). La implementación vive en
`conciliacion/universo.py`, `conciliacion/layouts.py` y `conciliacion/montos.py`.

## Propósito

Convertir cada fila de cada estado de cuenta crudo en un cargo normalizado, con
campos canónicos y tipos estrictos, sin perder ninguna fila, y demostrar con
candados que lo leído cuadra al centavo con los totales de control que publica
el propio estado de cuenta.

## Entradas

Una carpeta con:

1. `resumen_estados_cuenta.json`: el manifiesto del periodo. Lista los estados
   de cuenta que forman el periodo y, para cada uno, sus totales de control.
   Esquema `resumen_estados_cuenta/v1`; cada estado trae `archivo`, `emisor`,
   `nombre_emisor`, `layout`, `moneda`, `periodo_inicio`, `periodo_fin`, `corte`,
   `num_movimientos`, `total_cargos`, `total_abonos`, `total_neto`,
   `saldo_anterior` y `saldo_al_corte`.
2. Un CSV por estado de cuenta, con el nombre indicado en `archivo`.

El resumen es la única fuente de qué archivos se leen. Otros archivos de la
carpeta (por ejemplo, el libro mayor) se ignoran porque no son estados de cuenta.

### Validación del resumen (frontera de entrada)

El resumen es dato externo y se valida completo antes de leer ningún CSV:

- `esquema` debe ser exactamente `resumen_estados_cuenta/v1` y la lista de
  estados no puede estar vacía.
- `archivo` debe ser un nombre de archivo simple: sin separadores de carpeta,
  sin `..` y sin empezar con punto. Así ningún resumen puede hacer leer un
  archivo fuera de la carpeta de entrada.
- `emisor` debe ser un identificador en mayúsculas (`A-Z`, dígitos y `_`,
  empezando con letra); se usa para formar el `cargo_id`.
- `emisor` y `archivo` no se repiten entre estados.
- Las fechas son ISO (`AAAA-MM-DD`) y `periodo_inicio <= periodo_fin`.
- Los montos son texto con exactamente dos decimales (`-1234.56`), sin
  separador de miles ni espacios. Un número JSON se rechaza: el resumen nunca
  trae floats y aquí no se convierte ninguno.
- Montos del resumen, importes de celda y tipos de cambio se leen con la
  frontera compartida (`frontera`, en `skills/_comun/frontera`): solo dígitos
  ASCII (`١٢.٣٤` no es 12.34) y ningún redondeo (`12.345` no es 12.35). En una
  celda se recortan espacios y tabuladores ASCII al borde; cualquier otro
  carácter (un espacio no ASCII, una coma de miles mal puesta) deja la fila
  como `monto_invalido` (o `moneda_original_invalida`, si es el importe de
  origen o el tipo de cambio).
- `num_movimientos` es un entero no negativo (no se aceptan booleanos).
- `layout` debe ser un layout conocido y `moneda` debe ser la moneda de
  facturación de ese layout.

Cualquier violación detiene la corrida con un mensaje que nombra el estado y el
campo.

## Detección de layout

El layout de cada CSV se determina **solo** por coincidencia exacta de su
primera fila (el encabezado completo) contra el catálogo de layouts conocidos:
mismas columnas, mismo orden, mismo texto, sin recortar espacios. Lo único que
se tolera es una marca BOM de UTF-8 al inicio del archivo, porque es parte de la
codificación y no del encabezado.

- Si el encabezado no coincide con ningún layout, la corrida se detiene con un
  mensaje que nombra el archivo y muestra el encabezado leído. No hay
  heurísticas, no hay coincidencia parcial y no se adivina por el contenido de
  las filas.
- Si el layout detectado no es el que declara el resumen para ese archivo, la
  corrida también se detiene.
- Un archivo vacío (sin encabezado) o que no es UTF-8 válido detiene la corrida.

Esto importa porque los dos layouts escriben fechas en orden distinto
(día/mes frente a mes/día) y entre los días 1 y 12 ambos formatos son
indistinguibles por contenido.

### Catálogo de layouts

| Layout | Moneda de facturación | Fechas | Importe | Tarjeta | Marca de pago |
|---|---|---|---|---|---|
| `ALFA_V1` | `MXN` | `DD/MM/AAAA` | Una columna firmada, con o sin separador de miles | `****NNNN` | `PAGO RECIBIDO` |
| `BETA_V1` | `MXN` | `MM/DD/AAAA` | Dos columnas sin signo (`Charges`, `Credits`), sin separador de miles | `NNNN` | `PAYMENT RECEIVED` |

Encabezado de `ALFA_V1`: `Fecha de operación`, `Fecha de aplicación`,
`Descripción`, `Titular`, `Tarjeta`, `Moneda origen`, `Importe origen`,
`Tipo de cambio`, `Importe MXN`.

Encabezado de `BETA_V1`: `Transaction Date`, `Post Date`, `Description`,
`Card Member`, `Account Ending`, `Foreign Spend Amount`, `Foreign Currency`,
`Exchange Rate`, `Charges`, `Credits`.

Agregar un emisor nuevo es agregar una entrada al catálogo con su encabezado y
su función de interpretación; no se toca el resto del flujo. El catálogo
rechaza al cargarse dos layouts con el mismo encabezado.

## Salida: el cargo normalizado

Un registro por fila de datos (el encabezado no cuenta). Campos:

| Campo | Regla |
|---|---|
| `cargo_id` | `<emisor>-<fila con al menos 4 dígitos>` |
| `emisor`, `layout`, `archivo`, `corte` | Del resumen (el layout, además, verificado contra el encabezado) |
| `fila` | Número de registro de datos, base 1 |
| `fecha` | Fecha de operación ISO, o `null` si no se pudo interpretar |
| `fecha_aplicacion` | Fecha de aplicación ISO, o `null` |
| `descripcion` | Texto crudo con todo bloque de espacios reducido a un espacio y sin espacios en los extremos |
| `titular` | Igual que la descripción |
| `tarjeta_ultimos4` | Los cuatro dígitos finales de la tarjeta |
| `monto` | Importe firmado en la moneda de facturación, texto con dos decimales |
| `moneda` | Moneda de facturación del layout (siempre `MXN` en el catálogo actual) |
| `monto_original` | Importe firmado en la moneda de origen; igual a `monto` si la fila es en moneda de facturación |
| `moneda_original` | Código de tres letras de la moneda de origen |
| `tipo_cambio` | Texto con cuatro decimales, o `null` si la fila es en moneda de facturación |
| `tipo_movimiento` | Ver abajo |
| `estado` | `ok` o `ininterpretable` |
| `motivo` | `null` si `estado = ok`; si no, los motivos de la fila separados por coma |

Convención de signo: un cargo es positivo; una devolución del comercio o un pago
a la tarjeta son negativos. En `BETA_V1` el signo sale de la columna llena
(`Charges` positivo, `Credits` negativo) y el importe extranjero sin signo toma
el mismo signo.

### Tipo de movimiento

- `cargo`: monto mayor que cero.
- `pago`: monto menor que cero y la descripción empieza con la marca de pago del
  layout (sin distinguir mayúsculas).
- `abono`: monto menor que cero en cualquier otro caso.
- `null`: monto desconocido o igual a cero.

### Formato

JSONL en UTF-8 sin BOM, fin de línea LF, una línea por cargo, llaves ordenadas,
sin escapar caracteres no ASCII, sin marcas de tiempo. Las filas se ordenan por
emisor y luego por número de fila (numérico). Con menos de 10 000 filas por
estado ese orden coincide con el orden alfabético de `cargo_id`. Dos corridas
sobre los mismos insumos producen bytes idénticos.

## Filas ininterpretables

Una fila que no se puede interpretar **nunca se descarta**: entra al universo
con `estado = ininterpretable`, su `motivo` y los campos que sí se pudieron
leer. Cada campo se interpreta por separado; un campo ilegible queda en `null`
sin arrastrar a los demás. Cuenta en el número de movimientos y, si su importe
es legible, en las sumas de control.

Catálogo de motivos, en el orden en que se reportan:

| Motivo | Cuándo |
|---|---|
| `fila_vacia` | Todas las celdas vacías (todos los campos quedan en `null`) |
| `columnas_incompletas` | La fila no tiene el mismo número de celdas que el encabezado (todos los campos quedan en `null`) |
| `fecha_invalida` | La fecha de operación no tiene el formato del layout o no existe en el calendario (30 de febrero, 31 de abril) |
| `fecha_aplicacion_invalida` | Lo mismo para la fecha de aplicación |
| `descripcion_vacia` | Descripción vacía |
| `titular_vacio` | Titular vacío |
| `tarjeta_invalida` | La tarjeta no tiene la forma del layout |
| `monto_invalido` | El importe no tiene la forma del layout (signo, decimales, separadores) |
| `monto_ambiguo` | En `BETA_V1`, `Charges` y `Credits` llenas a la vez, o ninguna llena |
| `monto_cero` | Importe igual a cero: no es cargo, ni pago, ni abono |
| `moneda_original_invalida` | Datos de moneda de origen incompletos o contradictorios (ver abajo) |

Moneda de origen:

- `ALFA_V1`: `Moneda origen` es un código de tres letras. Si es la moneda de
  facturación, `Importe origen` debe ser igual a `Importe MXN` y `Tipo de
  cambio` debe estar vacío. Si es otra moneda, `Importe origen` debe ser
  distinto de cero y del mismo signo que `Importe MXN`, y `Tipo de cambio` debe
  ser positivo.
- `BETA_V1`: las tres columnas extranjeras van todas vacías (fila en moneda de
  facturación) o todas llenas con un código distinto de la moneda de
  facturación, un importe positivo y un tipo de cambio positivo.
- El tipo de cambio admite hasta cuatro decimales; más decimales se marcan en
  lugar de redondearse en silencio.

Cuando la moneda de origen es inválida, `moneda_original`, `monto_original` y
`tipo_cambio` quedan en `null`; el `monto` en moneda de facturación se conserva
si es legible.

Una fila en blanco intermedia o final también es una fila (`fila_vacia`): si el
emisor no la cuenta como movimiento, el candado de conteo lo hará visible en vez
de que el normalizador decida en silencio qué es ruido.

## Candados de totales de control

Para cada estado de cuenta leído se calculan, sobre el universo de ese estado:

| Comprobación | Esperado (resumen) | Calculado (universo) |
|---|---|---|
| `num_movimientos` | `num_movimientos` | Número de filas, incluidas las ininterpretables |
| `montos_legibles` | Número de filas | Filas con `monto` legible |
| `total_cargos` | `total_cargos` | Suma de montos positivos |
| `total_abonos` | `total_abonos` | Suma de montos negativos |
| `total_neto` | `total_neto` | Suma firmada de todos los montos legibles |
| `saldo_al_corte` | `saldo_al_corte` | `saldo_anterior` + neto calculado |

Todas deben cuadrar al centavo (igualdad exacta de `Decimal`, sin tolerancia).
Si cualquiera falla, la corrida termina con código distinto de cero y **no
escribe** el universo, para que ninguna etapa posterior consuma un universo que
no cuadra. Una fila con importe ilegible siempre hace fallar `montos_legibles`:
el universo no se puede certificar mientras haya un importe desconocido.

## Universo parcial

Un periodo es parcial cuando falta alguno de sus insumos; sus resultados son
provisionales. En esta etapa el insumo que puede faltar es un estado de cuenta
que el resumen lista.

- Sin declaración, un CSV listado que no existe detiene la corrida (insumo
  faltante). La ausencia nunca se infiere.
- La declaración es explícita y por emisor (`--sin-estado EMISOR`, repetible, o
  el parámetro `omitidos` de la API). El estado declarado no se lee aunque su
  archivo exista, sus candados no se evalúan y el universo queda marcado como
  provisional, con la lista de estados omitidos.
- Declarar un emisor que el resumen no lista, repetir uno, o declarar todos los
  estados ausentes (no quedaría nada que leer ni que comprobar) detiene la
  corrida.
- La marca vive en el reporte de control (`provisional`, `estados_omitidos`).
  Las etapas posteriores la heredan y pueden sumar sus propios insumos
  faltantes.

## Reporte de control

Junto al universo se escribe un JSON con esquema `control_universo/v1`. Por
omisión su ruta es la del universo con `.jsonl` cambiado por `.control.json`
(si el universo no termina en `.jsonl`, se le agrega `.control.json`); la ruta
de control no puede ser la misma que la del universo. Contiene `provisional`,
`estados_omitidos`, `num_cargos`, `filas_ininterpretables` (`cargo_id` y
`motivo`) y, por estado, sus comprobaciones con esperado, calculado y si
cuadra. Mismas reglas de determinismo que el universo.

## CLI y códigos de salida

```bash
# con cwd en skills/credit-card-reconciliation
python3 -m conciliacion.universo <dir_crudos> --salida <universo.jsonl> \
    [--control <control.json>] [--sin-estado EMISOR ...]
```

| Código | Significado |
|---|---|
| 0 | Universo escrito; todos los candados cuadran (puede ser provisional si se declaró un estado ausente) |
| 2 | Insumo o argumento inválido: resumen mal formado, archivo faltante sin declarar, declaración inválida, encabezado desconocido, layout que no coincide con el declarado, archivo vacío o no UTF-8 |
| 3 | Un candado de totales de control no cuadra |

Los mensajes de error van a la salida de error y nombran archivo, estado o
campo. Con código distinto de cero no se escribe ningún archivo.

## API

- `construir_universo(carpeta, omitidos=()) -> Universo`: lee, valida,
  normaliza y calcula los candados; lanza `ErrorInsumo` (o su subclase
  `EncabezadoDesconocido`) ante un insumo inválido. No escribe nada.
- `Universo.cuadra` indica si todos los candados cuadran;
  `exigir_candados(universo)` lanza `CandadoFallido` si no.
- `serializar_universo(universo)` y `serializar_control(universo)` devuelven el
  texto exacto que escribe la CLI.

## Lo que esta etapa NO hace

- No cruza contra CFDIs ni contra el libro mayor.
- No normaliza el nombre del comercio para cruzar (quitar ciudad, referencias o
  prefijos de pasarela): eso pertenece a los motores de cruce. Aquí solo se
  colapsan espacios.
- No convierte monedas ni recalcula el importe de facturación a partir del tipo
  de cambio: toma el importe que cobró el emisor.
- No deduplica: dos filas idénticas son dos cargos.
- No interpreta xlsx ni PDF. La interpretación recibe filas de texto, de modo
  que otra fuente tabular solo necesitaría un lector que produzca esas filas y
  un layout en el catálogo.
- No filtra texto libre por inyección de instrucciones; eso ocurre antes de que
  una descripción llegue a un modelo de lenguaje, en otra etapa.
