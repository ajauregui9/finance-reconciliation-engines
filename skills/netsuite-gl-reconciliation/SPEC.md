# Spec: cuadre CFDI ↔ libro mayor con SuiteQL sobre un esquema sintético

Módulo `netsuite_gl` (ADR 0002). Todo lo que aquí se describe corre con la
biblioteca estándar de Python (`sqlite3`, `csv`, `json`, `decimal`, `hashlib`).

## 1. Alcance

Alcance declarado: **SuiteQL vía conector MCP + CSV import; sin REST/SuiteScript.**

- La experiencia que se demuestra es SuiteQL ejecutado vía un conector MCP y cargas por
  CSV import. No hay cliente REST, OAuth/TBA, RESTlets ni SuiteScript, y no se agregan.
- Las queries se escriben en dialecto SuiteQL (estilo Oracle) y se ejecutan contra una base
  SQLite en memoria que imita las tablas de NetSuite. Una capa de compatibilidad traduce lo
  que SQLite no entiende (sección 5).
- Ningún archivo se escribe en el ERP. El CSV de carga es un archivo para revisión humana;
  subirlo es una acción manual fuera del módulo.

## 2. Insumo: CFDIs sintéticos

Se lee `examples/synthetic/cfdis.jsonl` solo en modo lectura. Cada línea es un
objeto JSON. Se valida al leer y cualquier falla detiene la lectura con `ErrorInsumo`,
indicando número de línea y campo:

- Campos obligatorios: `uuid`, `serie`, `folio`, `fecha_emision`, `tipo_comprobante`,
  `direccion`, `rfc_emisor`, `nombre_emisor`, `rfc_receptor`, `moneda`, `tipo_cambio`,
  `subtotal`, `iva`, `total`, `total_mxn`, `concepto`, `uuid_relacionado`.
- Los montos son texto decimal (nunca números JSON). Se convierten a `Decimal` con
  cuantización a 0.01 `ROUND_HALF_UP`.
- `subtotal + iva = total`. En MXN, `total_mxn = total`. En USD, `tipo_cambio` es
  obligatorio; el subtotal en MXN es `round(subtotal × tipo_cambio, 2)` y el IVA en MXN es
  `total_mxn − subtotal_mxn` (nunca negativo).
- `uuid` único en el archivo.

Clasificación (ningún registro se descarta en silencio; los excluidos se cuentan por motivo
en el manifiesto):

| Motivo | Regla |
|---|---|
| universo | `direccion = recibido`, `rfc_receptor` = RFC de la empresa, `tipo_comprobante` ∈ {I, E} |
| `emitido` | `direccion = emitido` (nómina y cualquier comprobante que la empresa emite) |
| `receptor_ajeno` | recibido, pero el receptor no es la empresa (p. ej. RFC genérico) |
| `tipo_no_aplica` | recibido por la empresa con un tipo distinto de I/E |

## 3. Esquema sintético

Nombres de tablas y columnas al estilo SuiteQL. Los booleanos son texto `'T'`/`'F'` como en
NetSuite. Las fechas son texto ISO (`AAAA-MM-DD`). Los montos se guardan en columnas
`NUMERIC` y se insertan como texto decimal (nunca `float`).

| Tabla | Columnas |
|---|---|
| `account` | `id`, `acctnumber`, `fullname`, `accttype` (`AcctPay`, `Expense`, `OthCurrAsset`), `isinactive` |
| `accountingperiod` | `id`, `periodname`, `startdate`, `enddate`, `isposting`, `isquarter`, `isyear`, `closed` |
| `classification` | `id`, `name`, `fullname`, `isinactive` |
| `vendor` | `id`, `entityid`, `companyname`, `custentity_mx_rfc`, `isinactive` |
| `transaction` | `id`, `tranid`, `trandate`, `type` (`VendBill`, `VendCred`), `postingperiod`, `entity`, `memo`, `posting`, `custbody_mx_cfdi_uuid` |
| `transactionline` | `transaction`, `id`, `linesequencenumber`, `mainline`, `taxline`, `class`, `entity`, `memo` |
| `transactionaccountingline` | `transaction`, `transactionline`, `account`, `debit`, `credit`, `amount`, `posting` |
| `customrecord_cfdi_recibido` | `id`, `name`, `custrecord_cfdi_uuid`, `custrecord_cfdi_fecha`, `custrecord_cfdi_tipo`, `custrecord_cfdi_rfc_emisor`, `custrecord_cfdi_nombre_emisor`, `custrecord_cfdi_serie`, `custrecord_cfdi_folio`, `custrecord_cfdi_concepto`, `custrecord_cfdi_subtotal`, `custrecord_cfdi_iva`, `custrecord_cfdi_total`, `custrecord_cfdi_uuid_relacionado` |

`customrecord_cfdi_recibido` no es una tabla estándar de NetSuite: es un registro
personalizado de este diseño, que en una cuenta real se llenaría por CSV import con la
descarga de CFDIs recibidos. Así el cruce completo se expresa en SuiteQL. Sus montos están
en MXN.

`transactionline.id` solo es único dentro de su transacción (llave compuesta
`transaction, id`), igual que en SuiteQL. `amount = debit − credit`; el lado vacío es `NULL`.

## 4. Poblado determinista

Catálogos fijos de la config (valores de ejemplo):

- Cuentas: proveedores (`AcctPay`), IVA acreditable (`OthCurrAsset`), varias de gasto y una
  cuenta de gasto inactiva que nunca recibe movimientos.
- Clases: `ADMINISTRACION`, `COMERCIAL`, `MERCADOTECNIA`, `OPERACIONES` y una inactiva.
- Periodos: un periodo anual, sus trimestres (de resumen, `isposting = 'F'`) y los meses
  configurados (de registro). Los meses cerrados de la config llevan `closed = 'T'`.
  Nombres al estilo NetSuite: `Jul 2026`, `Q3 2026`, `FY 2026`.
- Cada concepto de CFDI se asigna a una pareja (cuenta de gasto, clase) por una tabla de la
  config, con una pareja por omisión documentada. Una nota de crédito usa la pareja de la
  factura que referencia (`uuid_relacionado`) si está en el universo.

Construcción:

1. Proveedores: uno por pareja (`rfc_emisor`, `nombre_emisor`) del universo, en orden;
   `entityid = PROV-0001…`.
2. Registro personalizado: un renglón por CFDI del universo, ordenado por `uuid`.
3. Transacciones: un CFDI tipo I genera un `VendBill` y uno tipo E un `VendCred`, en orden
   (`fecha_emision`, `uuid`), con ids consecutivos desde el primero de la config.
   `tranid = serie-folio`, `trandate = fecha_emision`, `postingperiod` = mes que contiene la
   fecha, `posting = 'T'`.
4. Líneas de cada transacción (todas con la clase del concepto):
   - línea 0, `mainline = 'T'`, cuenta de proveedores, con el proveedor: total.
   - línea 1, gasto: subtotal.
   - línea 2, `taxline = 'T'`, IVA acreditable: IVA (solo si es mayor que cero).
   - `VendBill`: proveedores al haber, gasto e IVA al debe. `VendCred`: al revés.
   - Toda transacción cuadra: suma de `debit` = suma de `credit`.

### Discrepancias plantadas

Cada CFDI del universo recibe una llave `sha256("<semilla>:<uuid>")`. Se ordenan por esa
llave y se toman bloques consecutivos, en este orden, con los tamaños de la config. Un CFDI
recibe a lo sumo una discrepancia.

| Discrepancia | Qué se planta | Qué la detecta |
|---|---|---|
| `sin_registro` | El CFDI está en el registro personalizado, pero no se crea transacción | `cfdi_sin_registro` |
| `monto_distinto` | Gasto y proveedores se registran con `delta` de más (el asiento sigue cuadrado). Los `delta` se toman en ciclo de la config | `cuadre_cfdi_gl` con `diferencia = signo × delta` (signo −1 en notas de crédito) |
| `duplicado` | Una segunda transacción idéntica (mismo `tranid`, fecha, periodo, UUID y líneas) con el siguiente id libre | `duplicados_registro` y `cuadre_cfdi_gl` (`diferencia` = total firmado del CFDI, 2 transacciones) |
| `periodo_equivocado` | `postingperiod` = el mes de registro siguiente al de la fecha; `trandate` no cambia | `periodo_equivocado` |

`ErrorPoblado` (explícito, nunca se ajusta en silencio) si: los bloques piden más CFDIs que
el universo; un `delta` deja el gasto en cero o negativo; falta el mes de registro de una
fecha o el mes siguiente para un periodo equivocado.

### Manifiesto

`discrepancias_plantadas.json`, con llaves ordenadas y sin marcas de tiempo:

```text
esquema        "netsuite_discrepancias/v1"
parametros     semilla, tamaños por discrepancia, deltas, rfc_empresa
resumen        cfdis_leidos, universo, transacciones, proveedores, excluidos{motivo: n}
discrepancias  sin_registro[]       {uuid}
               monto_distinto[]     {uuid, delta, diferencia_esperada}
               duplicado[]          {uuid, transacciones[2], diferencia_esperada}
               periodo_equivocado[] {uuid, transaccion, periodo_esperado, periodo_registrado}
```

Cada lista va ordenada por `uuid`. Las pruebas comparan el resultado de cada query contra
este manifiesto: deben coincidir exactamente (ni faltantes ni sobrantes).

## 5. Capa de compatibilidad SuiteQL → SQLite

`compat.traducir(suiteql)` recibe el texto de un archivo `.sql` y devuelve SQL para SQLite.
Pasos:

1. Separa el texto en segmentos de código, literales `'…'` (con `''` como escape) e
   identificadores `"…"`. Solo los segmentos de código se traducen.
2. Quita comentarios `--` y `/* … */`. `compat.quitar_comentarios` devuelve el texto que se
   mandaría por el conector MCP.
3. Traducciones:

| SuiteQL | SQLite |
|---|---|
| `BUILTIN.DF(x.account)` | subconsulta escalar a `account`: `acctnumber || ' ' || fullname` |
| `BUILTIN.DF(x.class)` | subconsulta escalar a `classification.fullname` |
| `BUILTIN.DF(x.postingperiod)` | subconsulta escalar a `accountingperiod.periodname` |
| `BUILTIN.DF(x.entity)` | subconsulta escalar a `vendor`: `entityid || ' ' || companyname` |
| `BUILTIN.DF(x.type)` | `CASE` con los nombres visibles (`Bill`, `Bill Credit`, `Journal`) |
| `NVL(a, b)` | `COALESCE(a, b)` |
| identificador `transaction` (tabla o columna) | `"transaction"`: en SQLite es palabra reservada y debe ir citado |

   La subconsulta escalar equivale a un `LEFT JOIN` por `id` a la tabla de nombres: si la
   referencia es `NULL`, el nombre es `NULL`.
4. Falla con `ErrorCompatibilidad` si: un `BUILTIN.DF` apunta a un campo sin traducción;
   queda cualquier otra construcción `BUILTIN.*`; hay un literal o comentario sin cerrar.

Lo que no necesita traducción: `'T'`/`'F'`, `CASE`, `ROUND`, `COUNT`, `SUM`, `BETWEEN`,
`NOT EXISTS`, `||` y subconsultas son válidos en ambos dialectos.

## 6. Queries

Cada archivo `.sql` de `queries/` empieza con un encabezado de comentarios:

- `-- @descripcion: …` (obligatorio).
- `-- @montos: col1, col2` (opcional): columnas monetarias. Se convierten a `Decimal`
  (frontera única `float → str → Decimal`, 0.01 `ROUND_HALF_UP`). Cualquier `float` en otra
  columna es un error.

Clave desconocida, encabezado sin descripción o columna monetaria ausente del resultado →
`ErrorConsulta`. Todas filtran `posting = 'T'` y ordenan por una llave única.

| Query | Columnas | Contrato |
|---|---|---|
| `saldos_cuenta_periodo_clase` | `periodo`, `cuenta`, `clase`, `debito`, `credito`, `saldo` | Suma por periodo de registro, cuenta y clase; `saldo = debito − credito` |
| `cfdi_sin_registro` | `uuid`, `fecha`, `tipo`, `referencia`, `rfc_emisor`, `emisor`, `concepto`, `subtotal`, `iva`, `total` | CFDIs sin ninguna transacción contabilizada con su UUID |
| `cuadre_cfdi_gl` | `uuid`, `emisor`, `total_cfdi`, `total_gl`, `diferencia`, `num_transacciones` | CFDIs registrados cuyo neto en proveedores (`credit − debit`) difiere del total firmado del CFDI |
| `duplicados_registro` | `uuid`, `referencia`, `num_registros`, `primera_transaccion`, `ultima_transaccion` | UUIDs con más de una transacción de proveedor contabilizada |
| `periodo_equivocado` | `uuid`, `transaccion`, `referencia`, `tipo_transaccion`, `proveedor`, `fecha_cfdi`, `periodo_registrado`, `periodo_esperado` | Transacciones cuyo periodo no contiene la fecha del CFDI |

## 7. CSV de carga

Modelo: un asiento tiene `id_externo`, `fecha`, `periodo` (nombre), `memo`, `referencia`
opcional y líneas (`cuenta` por número, `debito`, `credito`, `clase` opcional, `entidad`
opcional por `entityid`, `memo`).

Entrada JSON: `{"asientos": [...]}`. Los montos son texto; un número JSON, una fecha que no
es ISO o un campo faltante es `ErrorEntrada` inmediato.

Validación previa: se revisan todos los asientos y se juntan todos los errores. Si hay uno
solo, se rechaza el archivo completo (`CargaRechazada` con la lista ordenada) y no se
escribe nada.

| Regla | Condición de error |
|---|---|
| `archivo_vacio` | no hay asientos |
| `id_externo_duplicado` | dos asientos con el mismo `id_externo` |
| `lineas_insuficientes` | menos de dos líneas |
| `importe_invalido` | negativo, más de dos decimales, ambos lados o ninguno |
| `asiento_descuadrado` | suma de débitos ≠ suma de créditos |
| `cuenta_inexistente` / `cuenta_inactiva` | la cuenta no está en `account` o `isinactive = 'T'` |
| `periodo_inexistente` / `periodo_no_registro` / `periodo_cerrado` | el periodo no existe, es de resumen o `closed = 'T'` |
| `fecha_fuera_de_periodo` | la fecha no cae dentro del periodo |
| `clase_inexistente` | la clase no está en `classification` o está inactiva |
| `proveedor_inexistente` | la entidad no está en `vendor` o está inactiva |
| `proveedor_requerido` | línea en cuenta `AcctPay` sin entidad |
| `factura_sin_proveedores` | (vendor bill) no hay exactamente una línea de proveedores al haber |
| `factura_linea_credito` | (vendor bill) una línea que no es de proveedores va al haber |
| `referencia_requerida` | (vendor bill) falta `referencia` |
| `texto_formula` | un texto (memo, referencia) empieza con `=`, `+`, `-` o `@`: una hoja de cálculo lo ejecutaría como fórmula al revisar el archivo |

Formatos de salida (UTF-8 sin BOM, fin de línea LF, fechas `DD/MM/AAAA`, montos con dos
decimales, cuentas como `número nombre`):

- `journal`: una fila por línea: `External ID, Date, Posting Period, Memo, Account, Debit,
  Credit, Class, Name, Line Memo`.
- `vendor_bill`: una fila por línea de gasto o IVA; la línea de proveedores queda implícita
  en `Vendor`: `External ID, Vendor, Date, Posting Period, Reference No., Memo, Account,
  Amount, Class, Line Memo`.

Propuesta automática: `propuestas.proponer_facturas_sin_registro` convierte cada CFDI tipo I
de `cfdi_sin_registro` en un vendor bill (gasto, IVA y proveedores, con la pareja de la
config). Las notas de crédito quedan en una lista de pendientes con motivo
`nota_credito_requiere_vendor_credit`.

## 8. CLI

`python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py <comando>`

| Comando | Efecto |
|---|---|
| `consultar [--consulta N]… [--salida DIR]` | Ejecuta las queries en orden fijo; imprime CSV o escribe `DIR/<query>.csv` y `DIR/discrepancias_plantadas.json` |
| `discrepancias [--salida ARCHIVO]` | Imprime o escribe el manifiesto |
| `traducir N` | Imprime el SQL traducido de una query |
| `generar-csv --salida ARCHIVO (--asientos JSON --formato F \| --desde-sin-registro)` | Valida y escribe el CSV |

Todos aceptan `--cfdis RUTA`. Códigos de salida: `0` éxito, `2` entrada o argumentos
inválidos, `3` CSV rechazado (errores en stderr, ningún archivo escrito).

## 9. Determinismo

Sin marcas de tiempo ni aleatoriedad global. JSON con `sort_keys`, CSV con LF. Dos corridas
con el mismo insumo producen archivos idénticos (mismo SHA-256).
