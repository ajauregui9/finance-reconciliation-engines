# Spec: cierre mensual de Amazon por devengo (`cierre_amazon`)

Esta spec describe el comportamiento del paquete `cierre_amazon`. El código se escribe a
partir de este documento. Todos los parámetros numéricos viven en la config y los valores
de `config/cierre.example.json` son ejemplos redondos, no una calibración real.

## 1. Propósito

A partir de los archivos de liquidación de un vendedor en Amazon (más dos fuentes de
publicidad y la venta devengada del ERP) se obtiene, para cada mes declarado:

1. Qué filas pertenecen al mes contable, con el corte horario calculado desde el huso que
   declara cada archivo.
2. La separación entre la cohorte del mes (pedidos del propio mes) y la cohorte cola
   (pedidos de meses anteriores que se liquidan en este).
3. Las tasas efectivas de tarifas medidas solo sobre la cohorte del mes, la provisión de
   tarifas para la venta devengada que aún no se liquida y el reverso de la provisión del
   mes anterior contra la cola real.
4. El gasto de publicidad contado una sola vez, aunque aparezca en varias fuentes.
5. La retención de plataforma comparada contra una tasa y una banda de config.
6. Candados que recalculan los cuadres desde las filas y alertas no bloqueantes.

Todo monto es `Decimal` con dos decimales y redondeo `ROUND_HALF_UP`. La salida JSON es
determinista: llaves ordenadas, montos como texto, sin marcas de tiempo ni rutas absolutas.

## 2. Insumos

Todos viven en un directorio (`--datos`). Los nombres son fijos:

| Archivo | Obligatorio | Contenido |
|---|---|---|
| `liquidacion_AAAA-MM.csv` | al menos uno | Liquidación de un periodo |
| `publicidad_consola.csv` | no | Gasto diario de publicidad por campaña, sin IVA |
| `facturas_publicidad.json` | no | Factura mensual de publicidad |
| `venta_erp.json` | no | Venta neta devengada por mes de pedido, sin IVA |

### 2.1 Liquidación

CSV en UTF-8 (se tolera BOM). Empieza con un preámbulo de pares `clave,valor` que termina
en una fila vacía. Claves obligatorias:

- `Periodo`: `AAAA-MM`, el mes que cubre el archivo en su propio huso.
- `Huso horario`: desfase fijo `UTC±HH:MM`. Un nombre de zona con horario de verano
  (`America/...`) se rechaza con un error explícito.
- `Moneda`: debe coincidir con `moneda` de la config.

Una clave repetida o faltante es un error. Después del preámbulo viene el encabezado, que
debe ser exactamente:

```
Fecha y hora,Tipo,Pedido,Fecha del pedido,SKU,Descripción,Cantidad,Venta de productos,
IVA de la venta,Envío cobrado,IVA del envío,Descuento promocional,IVA del descuento,
Retención de plataforma,Comisión por venta,Tarifa de logística,Otras tarifas,Total
```

(una sola línea en el archivo). Reglas por fila:

- `Fecha y hora` y `Fecha del pedido` usan `AAAA-MM-DD HH:MM:SS` en el huso del archivo.
  `Fecha del pedido` puede ir vacía en filas que no son de pedido.
- La fecha local de `Fecha y hora` debe caer dentro del `Periodo` del archivo.
- Si hay fecha del pedido, no puede ser posterior a `Fecha y hora`.
- Los montos aceptan separador de miles (`"1,234.56"`); vacío significa cero.
- `Cantidad` es un entero; vacío significa cero.
- La suma de las diez columnas de montos debe ser igual a `Total`, al centavo.
- Signos: lo que recibe el vendedor es positivo; tarifas, retenciones y reembolsos de
  venta son negativos.

Dos archivos con el mismo `Periodo` son un error (evita contar dos veces una liquidación).
Cualquier violación detiene la lectura con un error que nombra archivo, fila y columna.
Ninguna fila se descarta.

### 2.2 Consola de publicidad

CSV con encabezado exacto `Fecha,Campaña,Gasto`. `Fecha` es `AAAA-MM-DD` (fecha
calendario del huso de cierre); `Gasto` es el gasto sin IVA. El mes de la fila es el de su
fecha.

### 2.3 Facturas de publicidad

```json
{"esquema": "facturas_publicidad/v1",
 "facturas": [{"mes": "AAAA-MM", "folio": "...", "subtotal": "...", "iva": "...", "total": "..."}]}
```

Un mes repetido es un error.

### 2.4 Venta del ERP

```json
{"esquema": "venta_erp/v1", "venta_neta_por_mes_de_pedido": {"AAAA-MM": "..."}}
```

Es la venta neta (venta de productos más descuentos, menos devoluciones) atribuida al mes
del pedido, sin IVA. Es el ancla del devengo.

### 2.5 Conversión de montos

Existe un solo punto de conversión a `Decimal`: `dinero.a_decimal`. Recibe texto, entero,
`float` o `Decimal`; un `float` pasa por `Decimal(str(x))`. Rechaza booleanos, texto no
numérico, infinitos y NaN. El resultado siempre se cuantiza a 0.01 con `ROUND_HALF_UP`.

## 3. Config

```json
{
  "esquema": "config_cierre_amazon/v1",
  "moneda": "MXN",
  "huso_cierre": "UTC-06:00",
  "tasa_iva": "0.16",
  "tipos": {"Pedido": "venta", "Reembolso": "reembolso", "Publicidad": "publicidad", ...},
  "publicidad": {"fuente_autoritativa": "consola", "tolerancia": "1.00"},
  "retencion": {"tasa": "0.08", "banda": "0.01"},
  "referencias_tarifas": {"comision": {"min": "0.10", "max": "0.20"}, ...}
}
```

- `tipos` traduce el `Tipo` de la liquidación a una categoría: `venta`, `reembolso`,
  `cargo_periodo`, `publicidad` o `transferencia`. Un tipo que no está en el mapa queda
  como `sin_clasificar`.
- `publicidad.fuente_autoritativa` es `liquidacion`, `consola` o `factura`.
- `referencias_tarifas` es opcional; sus conceptos son `comision`, `logistica` y
  `otras_tarifas`, con `min <= max`.
- Las tasas se validan: `0 <= tasa_iva < 1`, `0 < retencion.tasa < 1`, `banda >= 0`,
  `tolerancia >= 0`. Cualquier error de config detiene la corrida.

## 4. Corte horario

1. El huso del archivo convierte cada `Fecha y hora` en un instante absoluto.
2. El instante se lleva a `huso_cierre`; el mes contable es el `AAAA-MM` resultante.
3. La cohorte de una fila de pedido es el mes contable de su `Fecha del pedido`,
   calculado igual.

No se supone ningún desfase fijo entre husos: un archivo en `UTC-08:00` y otro en
`UTC+00:00` mueven filas en sentidos opuestos. Los meses que se cierran son los `Periodo`
declarados. Las filas que caen en otro mes se reportan en `filas_fuera_de_meses` con
conteo y total; no se pierden.

## 5. Clasificación y agregación

Para cada mes contable:

- **Filas de pedido**: categorías `venta` y `reembolso`. Deben traer `Pedido` y
  `Fecha del pedido`; si no, es un error.
- **Cohorte del mes**: filas de pedido cuya cohorte es el mes.
- **Cohorte cola**: filas de pedido cuya cohorte es anterior; se agrupan por mes de origen.
  Una cohorte posterior al mes de liquidación es imposible y se rechaza en la lectura.
- **Cargos del periodo**: categoría `cargo_periodo`, agrupados por `Tipo`.
- **Publicidad en la liquidación**: categoría `publicidad`. Nunca entra a otra línea.
- **Transferencias**: categoría `transferencia`. Son pagos al banco, no gasto, pero
  cuentan en el cuadre del total liquidado.
- **Sin clasificar**: se reportan con conteo y total y hacen fallar un candado.

Un agregado suma, por grupo de filas, las diez columnas de montos y el total, cuenta filas
y pedidos distintos (de filas `venta`). La venta neta de un agregado es
`venta de productos + descuento promocional`. Los subtotales conservan su signo: nunca se
toma valor absoluto, porque una cola formada sobre todo por reembolsos es negativa y debe
seguir siéndolo.

## 6. Tarifas, provisión y reverso

Conceptos de tarifa: `comision` (Comisión por venta), `logistica` (Tarifa de logística) y
`otras_tarifas` (Otras tarifas), solo de filas de pedido. El gasto de un concepto es el
negativo de su suma en la liquidación.

1. **Tasa efectiva** del concepto `c` en el mes `t`: `gasto_c(cohorte del mes) /
   venta_neta(cohorte del mes)`. Si la venta neta es cero, no hay tasa y se alerta.
   La cola nunca entra a la tasa.
2. **Venta pendiente**: `venta_erp(t) - venta_neta(cohorte del mes)`. Sin dato del ERP no
   hay provisión y se alerta.
3. **Provisión** del concepto: `q2(venta_pendiente * gasto_c / venta_neta)`.
4. **Reverso**: en el mes `t` se revierte completa la provisión de `t-1` si ese mes se
   cerró en la misma corrida. La cola real de `t` se reconoce completa.
5. **Gasto devengado** del concepto en `t`:
   `cohorte del mes + provisión(t) + cola real(t) - provisión(t-1)`.
   Si hay cola y no hay provisión previa en la corrida, la cola se reconoce sin reverso y se
   alerta.

Consecuencia que se prueba: sumando todos los meses de una corrida sin huecos, el gasto
devengado de tarifas es igual al gasto real liquidado más la provisión del último mes.

Siempre se cierran todos los meses declarados, en orden; `--mes` solo filtra la salida.
Así el resultado de un mes no depende de qué meses se pidieron.

### 6.1 Referencias de tarifas

Si la config trae `referencias_tarifas`, cada tasa efectiva se compara contra su rango
`[min, max]` (inclusivo) y fuera de rango genera la alerta `tasa_fuera_de_referencia`.

Decisión: la tabla de referencia de comisiones que existía como archivo aparte se reemplaza
por esta sección de la config, con rangos redondos de ejemplo, y la comparación se hace de
verdad contra las tasas efectivas. No queda ningún archivo de referencia separado ni valor
de calibración real.

## 7. Publicidad sin doble conteo

La misma inversión puede aparecer en tres fuentes:

| Fuente | De dónde | Base | Monto sin IVA |
|---|---|---|---|
| `liquidacion` | filas `publicidad` del mes | con IVA | `q2(con_iva / (1 + tasa_iva))`, sobre la suma del mes |
| `consola` | `publicidad_consola.csv` | sin IVA | suma del mes |
| `factura` | `facturas_publicidad.json` | desglosada | `subtotal` |

Reglas:

1. Las filas `publicidad` de la liquidación se separan siempre de las tarifas y de los
   cargos del periodo, sin importar qué fuente es la autoritativa.
2. La línea de publicidad del gasto devengado es el monto sin IVA de la fuente
   autoritativa, y solo ese.
3. Las otras fuentes presentes se comparan contra la autoritativa; si la diferencia
   absoluta supera `publicidad.tolerancia`, se emite `publicidad_fuentes_difieren`.
4. La liquidación siempre está presente (puede valer cero). La consola está ausente si
   falta el archivo; la factura, si falta el archivo o la factura de ese mes. Si la fuente
   autoritativa está ausente en un mes, la corrida se detiene con error: no se inventa la
   línea.
5. Si una factura no cumple `subtotal + iva = total` o `iva = q2(subtotal * tasa_iva)`, se
   emite `factura_iva_inconsistente`.

## 8. Retención de plataforma

La base de cálculo es una sola y aparece igual en el código (`retencion.py`) y en los docs:

- **Filas**: todas las filas de pedido (`venta` y `reembolso`) liquidadas en el mes
  contable, de cualquier cohorte. La retención la aplica la plataforma al liquidar, así
  que se mide por mes de liquidación.
- **Base**: `Σ (venta de productos + descuento promocional)` de esas filas, sin IVA.
- **Retenida**: `-Σ retención de plataforma` de las mismas filas.
- **Esperada**: `q2(base * tasa)`.
- **Tasa observada**: `retenida / base`.
- **Dentro de banda** si `|tasa observada - tasa| <= banda`.

Las filas sin retención se quedan en la base a propósito: si la plataforma deja de retener
en parte de las ventas, la tasa observada baja y se alerta. Fuera de banda se emite
`retencion_fuera_de_banda` con la tasa observada, la esperada y la diferencia en pesos
(`retenida - esperada`). Con base cero y retención distinta de cero se emite
`retencion_sin_base`.

## 9. Candados

Cada candado recalcula desde las filas, por un camino distinto al del cierre:

| Candado | Verifica |
|---|---|
| `puente_liquidacion` | Σ total de las filas del mes = Σ de los totales por categoría |
| `puente_cohortes` | Σ total de filas de pedido = cohorte del mes + todas las colas (y lo mismo con la venta neta) |
| `publicidad_una_vez` | Las tarifas y los cargos del periodo recalculados sin las filas `publicidad` son los del gasto, y la línea de publicidad es la de la fuente autoritativa |
| `gasto_suma_lineas` | El total del gasto devengado es la suma de sus líneas |
| `tipos_clasificados` | No hay filas `sin_clasificar` |

Un candado en falla hace que la CLI termine con código 1.

## 10. Alertas

No bloquean. Cada una lleva `codigo`, `mes` y un `mensaje` legible, más datos propios.
Códigos: `retencion_fuera_de_banda`, `retencion_sin_base`, `publicidad_fuentes_difieren`,
`factura_iva_inconsistente`, `tasa_fuera_de_referencia`, `sin_tasa_efectiva`,
`sin_venta_erp`, `cola_sin_provision_previa`. A nivel corrida:
`filas_fuera_de_meses`.

## 11. Salida

JSON con esquema `cierre_amazon/v1`: `parametros`, `archivos` (solo nombre, periodo,
huso, filas y total), `filas_fuera_de_meses`, `meses` (uno por mes, en orden) y `alertas`
de la corrida. Montos con dos decimales como texto; tasas con seis decimales. Dos corridas
con los mismos insumos producen bytes idénticos.

El xlsx opcional tiene las hojas `Resumen`, `Gasto devengado`, `Alertas` y `Candados`,
con montos numéricos (nunca texto) y formato `#,##0.00`. Después de escribirlo, la CLI lo
vuelve a leer y compara cada monto contra el resultado; una diferencia termina con código
1.

Códigos de salida: `0` cierre completo (puede haber alertas), `1` algún candado o la
verificación del xlsx falló, `2` insumo o config inválidos.

## 12. Límites conocidos

- Solo se aceptan desfases fijos. Un archivo cuyo huso cambia a mitad de periodo (horario
  de verano) tendría que partirse en dos archivos.
- El reverso compara la provisión de `t-1` contra toda la cola de `t`. Una cola de dos o
  más meses atrás se reconoce completa en el mes en que llega.
- La venta del ERP se toma como dato; el paquete no la reconstruye.
- No hay reparto por marca: el gasto se cierra a nivel cuenta. El SKU queda disponible en
  las filas para un reparto posterior.
