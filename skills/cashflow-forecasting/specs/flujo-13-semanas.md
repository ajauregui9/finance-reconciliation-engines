# Spec: flujo de efectivo de 13 semanas (paquete `flujo`)

Esta spec describe el comportamiento del paquete `skills/cashflow-forecasting/flujo/`.
Se escribió antes que el código; el código se implementa desde aquí.

## 1. Propósito

A partir de cinco insumos tabulares y una fecha de corte, el paquete proyecta la
posición de caja semana por semana durante un horizonte fijo de 13 semanas. Cada
insumo pasa por un adaptador que lo traduce a **filas contrato**; un ensamblador
valida las filas, cuadra cada fuente al centavo y arma la tabla semanal. Solo si
todo cuadra se escriben las salidas (JSON, JSONL y xlsx).

## 2. Calendario

- La fecha de corte `C` es un argumento obligatorio (`AAAA-MM-DD`).
- La semana `n` (1..13) cubre los días `[C + 7(n-1), C + 7n - 1]`, ambos inclusive.
  El horizonte termina en `C + 90`.
- El índice de semana de una fecha `f >= C` es `(f - C).days // 7 + 1`. Un índice
  mayor que 13 significa "fuera de horizonte".
- El número de semanas (13) es la definición del producto y vive en una sola
  constante; no es un parámetro de la config.

## 3. Config (`flujo_config/v1`)

JSON estricto: llaves desconocidas o faltantes son error. Los números se leen como
`Decimal` (nunca `float`); un peso de la curva escrito como texto usa solo dígitos
ASCII (`"٠.٥"` es error).

```text
esquema          "flujo_config/v1"
moneda           código de moneda; cada fila de cada insumo debe traer la misma
insumos          objeto con exactamente cinco rutas (relativas al archivo de config
                 o absolutas): saldos_bancarios, cxc_antiguedad, cxp_programadas,
                 nomina, impuestos
curva_cobranza   lista de tramos (sección 5)
```

Cada ruta de `insumos` alimenta exactamente un adaptador; no hay rutas opcionales ni
rutas ignoradas. La salida registra, por fuente, el nombre del archivo leído, su
SHA-256 y el número de registros, para demostrar que cada ruta se usó.

## 4. Insumos

Todos son CSV UTF-8 con encabezado. El conjunto de columnas debe ser exactamente el
esperado (sin faltantes ni sobrantes). Cada error de fila reporta archivo, número de
fila y campo. Ninguna fila se descarta en silencio: o entra al flujo, o se reporta en
una partida de conciliación (fuera de horizonte, no cobrable), o se cuenta como
registro en cero (solo CxC, sección 4.2), o la corrida falla.

Montos: texto decimal (`1234.56`) con signo opcional y hasta dos decimales,
convertido a `Decimal` en una sola frontera (la compartida, `frontera`): solo
dígitos ASCII, sin separador de miles, exponentes ni espacios internos. **Un insumo
nunca se redondea**: `10.005`, `١٠٠.٠٠` o `1,000.00` son error (código 3), no un
monto redondeado; `-0.00` se lee como `0.00`. Texto vacío, no numérico, infinito o
NaN es error. Fechas ISO `AAAA-MM-DD` con dígitos ASCII, también en `--corte`
(código 2); otra forma (`20261102`, `2026-W45-1`) es error.

| Fuente | Columnas | Llave única | Reglas |
|---|---|---|---|
| `saldos_bancarios` | cuenta, banco, fecha_saldo, moneda, saldo | cuenta | al menos una fila; `fecha_saldo = C`; el saldo puede ser negativo (sobregiro) |
| `cxc_antiguedad` | cliente_id, cliente, factura, fecha_factura, fecha_vencimiento, moneda, saldo | factura | saldo de cualquier signo (4.2); `fecha_factura <= C`; `fecha_vencimiento >= fecha_factura` |
| `cxp_programadas` | proveedor_id, proveedor, factura, fecha_programada, moneda, monto | (proveedor_id, factura) | `monto > 0`; fecha anterior a `C` = vencido (4.1) |
| `nomina` | periodo, descripcion, fecha_pago, moneda, monto | periodo | `monto > 0`; fecha anterior a `C` = vencido (4.1) |
| `impuestos` | impuesto, periodo_fiscal, fecha_limite, moneda, monto | (impuesto, periodo_fiscal) | `monto > 0`; fecha anterior a `C` = vencido (4.1) |

Un saldo bancario con otra fecha significa que los insumos no corresponden al corte
pedido: es error, no se reacomoda. Las reglas de fecha y de llave única se validan en
todo registro, incluidos los de saldo cero o negativo.

### 4.1 Egresos vencidos

Un egreso programado (proveedores, nómina o impuestos) con fecha anterior a `C` no se
pagó y sigue pendiente. No se rechaza ni se descarta:

- su fila contrato va en la **semana 1** con `fecha = C` (se asume pagadero de
  inmediato) y lleva `marca = "vencido"`;
- el importe completo entra al flujo; no hay "fuera de horizonte" para un vencido;
- el aviso `egresos_vencidos` (sección 8) cuenta las filas y suma su importe.

Un monto `<= 0` sigue siendo error, vencido o no.

### 4.2 Saldos de CxC según su signo

- **Positivo**: se reparte con la curva de cobranza (sección 5).
- **Negativo** (anticipo de cliente o nota de crédito por aplicar): se acepta y
  **resta íntegro en la semana 1**, con `fecha = C`, concepto `cobranza_clientes`,
  monto negativo y `marca = "saldo_acreedor"`. No pasa por la curva: no tiene tramo,
  estimación no cobrable ni parte fuera de horizonte. Razón: es un importe conocido
  que se compensa contra la cobranza del cliente o se devuelve; repartirlo con pesos
  de cobranza inventaría un calendario y una "no cobrabilidad" que no existen.
  Restarlo en la semana 1 es la lectura prudente: nunca adelanta caja.
- **Cero** (después de redondear a centavos; `-0.004` también es cero): no genera
  fila contrato. El registro se cuenta en `registros_en_cero` del resultado de la
  fuente y en el aviso `cxc_saldo_cero`. Ninguna otra fuente admite registros en cero.

El cuadre de la sección 7 incluye los saldos negativos en `total_insumo` y en las
filas, así que sigue siendo exacto al centavo.

## 5. Curva de cobranza

Cada tramo tiene `tramo` (nombre único), `dias_desde`, `dias_hasta` (enteros o `null`
para "sin límite") y `pesos` (lista no vacía de fracciones). La curva se aplica solo
a saldos positivos (sección 4.2).

- **Antigüedad** de una factura: `(C - fecha_vencimiento).days`. Cero o negativa
  significa "por vencer"; positiva, días vencidos.
- Los tramos, en el orden de la config, deben cubrir todos los enteros sin huecos ni
  traslapes: el primero abre con `null`, el último cierra con `null` y cada
  `dias_desde` es el `dias_hasta` anterior más uno.
- Cada peso está en `[0, 1]` y la suma de los pesos de un tramo es `<= 1`. La parte
  que falta para 1 es la **estimación no cobrable** de ese tramo.
- **Ancla**: una factura por vencer empieza a cobrarse en la semana de su vencimiento;
  una vencida, en la semana 1. El peso `k` (base 0) cae en la semana `ancla + k`.
- **Reparto al centavo**: con `P_k` = suma acumulada de pesos hasta `k`, el monto de
  la pieza `k` es `r(S·P_k) - r(S·P_{k-1})`, donde `r` redondea a centavos y
  `P_{-1} = 0`. La suma telescópica de las piezas es exactamente `r(S·P_total)`; la
  estimación no cobrable es `S - r(S·P_total)`.
- Una pieza que cae después de la semana 13 se acumula en "fuera de horizonte". Las
  piezas de 0.00 no generan fila.

## 6. Fila contrato

```text
fuente       una de las cinco fuentes
concepto     saldo_inicial | cobranza_clientes | pago_proveedores | pago_nomina | pago_impuestos
semana       entero 1..13
fecha        fecha del flujo, dentro de la semana (las piezas de cobranza usan el
             primer día de su semana; el saldo inicial usa C)
referencia   identificador legible del documento de origen (texto no vacío)
contraparte  banco, cliente, proveedor o autoridad (texto no vacío)
monto        Decimal con dos decimales, con signo de caja
marca        null, "vencido" o "saldo_acreedor"
```

Cada fuente produce un solo concepto. Signos: `saldo_inicial` cualquiera, en la
semana 1; `cobranza_clientes` positivo, salvo con marca `saldo_acreedor` (negativo);
los tres `pago_*` negativos.

Marcas: `vencido` solo en conceptos `pago_*`; `saldo_acreedor` solo en
`cobranza_clientes`. Toda fila con marca va en la semana 1 con `fecha = C`. Una marca
fuera de ese catálogo es error.

## 7. Ensamblador

Recibe un resultado por fuente: filas contrato más su conciliación (`total_insumo`,
`fuera_horizonte`, `no_cobrable`, todos con signo de caja) y `registros_en_cero`.
Antes de producir nada:

1. **Esquema**: cada fila cumple la sección 6 y su `fuente` coincide con la del
   resultado que la trae. Las cinco fuentes están presentes, sin repetirse.
   `registros_en_cero` es un entero entre 0 y `registros`, y solo `cxc_antiguedad`
   puede reportarlo mayor que 0.
2. **Cuadre por fuente**: `suma(filas) + fuera_horizonte + no_cobrable = total_insumo`,
   exacto al centavo.

Después arma 13 semanas. `saldo_inicial(1)` es la suma de las filas de saldo; cada
semana suma sus filas por concepto (todo concepto aparece en toda semana, en cero si
no hay filas); `flujo_neto(n) = entradas(n) + salidas(n)`;
`saldo_final(n) = saldo_inicial(n) + flujo_neto(n)` y
`saldo_inicial(n+1) = saldo_final(n)`.

3. **Invariantes de la tabla** (se verifican sobre el resultado armado): hay
   exactamente 13 semanas numeradas 1..13 y contiguas; cada saldo final es el saldo
   inicial más el flujo neto; cada saldo final es el inicial de la semana siguiente;
   por concepto, la suma de las 13 semanas es la suma de sus filas.

Cualquier falla detiene la corrida sin escribir archivos.

## 8. Salidas

En el directorio `--salida`:

- `flujo_13_semanas.json` (`flujo_13_semanas/v1`): corte, moneda, semanas (inicio,
  fin, saldo inicial, entradas y salidas por concepto, totales, flujo neto, saldo
  final), conciliación por fuente (incluye `registros_en_cero`), avisos y totales del
  horizonte. Montos como texto `-1234.56`. Llaves ordenadas, sangría 2, UTF-8, LF,
  sin marcas de tiempo ni rutas absolutas: dos corridas iguales dan el mismo SHA-256.
- `filas_contrato.jsonl`: una fila contrato por línea (con su `marca`), ordenadas por
  (semana, concepto, fuente, referencia).
- `flujo_13_semanas.xlsx` (openpyxl): hoja `Flujo` (conceptos en filas, semanas
  1..13 en columnas), hoja `Filas contrato` (con columna `marca`), hoja `Fuentes` y
  hoja `Resumen` (con los avisos). Todo monto es una celda numérica con formato
  `#,##0.00`; nunca texto. El archivo también es determinista byte a byte: autor
  fijo (`flujo`), fechas de creación y modificación = medianoche de `C`, sin el sello
  de hora de guardado, y cada entrada del zip con fecha 1980-01-01 00:00:00, permisos
  y sistema de origen fijos. Dos corridas iguales dan el mismo SHA-256.

**Avisos.** Siempre aparecen los tres, en cero si no hubo casos, cada uno con
`registros` y `monto` (con signo de caja):

| Aviso | Cuenta |
|---|---|
| `cxc_saldo_acreedor` | filas con marca `saldo_acreedor` y su suma (negativa) |
| `cxc_saldo_cero` | registros de CxC con saldo cero (monto siempre 0.00) |
| `egresos_vencidos` | filas con marca `vencido` y su suma (negativa) |

## 9. CLI y códigos de salida

```bash
python3 -m flujo --config <json> --corte AAAA-MM-DD --salida <dir>
```

| Código | Significado |
|---|---|
| 0 | salidas escritas |
| 1 | no se pudo escribir en el directorio de salida |
| 2 | argumentos o config inválidos (incluye curva inválida) |
| 3 | un insumo falta, no se puede leer o tiene esquema o valores inválidos |
| 4 | falló un invariante del ensamblador |

Con código distinto de 0 no se escribe ningún archivo. En éxito se imprime en
stdout un resumen JSON de una línea, que incluye `avisos` (clave del aviso -> número
de registros). Un egreso vencido o un saldo de CxC negativo o en cero no cambia el
código de salida: se informa en los avisos.

## 10. Fuera de alcance

Multimoneda, estimar la fecha real de pago de un egreso vencido (se asume la semana
1), aplicar un saldo acreedor contra facturas específicas del mismo cliente,
pronóstico de ventas nuevas y conciliación contra movimientos bancarios reales.
