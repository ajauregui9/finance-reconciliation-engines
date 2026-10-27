# Especificación: revisión del estado de resultados antes de cerrar un mes

Este documento es la spec del módulo `scripts/auditoria_pl/` y de su CLI
`scripts/run_pl_audit.py`. Describe solo lo que el código hace hoy. Todo número
que aparece en `config/parametros.example.json` es un valor de ejemplo redondo;
no viene de ninguna empresa.

## 1. Propósito

Antes de cerrar un mes contable conviene separar dos cosas: cambios reales del
negocio y señales de que los números todavía no están completos o están mal
clasificados. El revisor recibe una exportación mensual del estado de
resultados (una fila por cuenta, mes actual y mes anterior) y produce un
reporte JSON con cuatro bloques:

1. **Bloqueos**: condiciones que vuelven provisional todo el reporte.
2. **Bandas**: razones del estado de resultados contra un corredor declarado.
3. **Publicidad por marca**: gasto de publicidad de cada marca contra su venta.
4. **Variaciones**: cambios de mes contra mes, por cuenta, filtrados por materialidad.

El revisor no consulta el ERP ni escribe en él. Es una función pura sobre dos
documentos JSON más un periodo.

## 2. Entradas

### 2.1 Periodo

Argumento obligatorio con forma `AAAA-MM`. No existe valor por omisión. Si no
coincide con el campo `periodo` de la exportación, la corrida se rechaza: así no
se audita por error el archivo de otro mes.

### 2.2 Exportación (`exportacion_pl/v1`)

| Campo | Regla |
|---|---|
| `esquema` | Exactamente `exportacion_pl/v1` |
| `periodo` | `AAAA-MM` |
| `fecha_extraccion` | Fecha ISO en que se sacó la exportación del ERP |
| `cuentas[]` | Lista no vacía; `cuenta` única por fila |
| `cuentas[].cuenta`, `.nombre` | Texto; la cuenta no puede ir vacía |
| `cuentas[].anterior`, `.actual` | Montos del mes anterior y del mes auditado |
| `cuentas[].polizas_manuales_actual` | Opcional (cero si falta): parte de `actual` que proviene de pólizas manuales |
| `marcas[]` | `marca` única, `venta`, `publicidad` |
| `provisiones[]` | `cuenta` única, `creado`: monto creado en el mes |

Convención de signos: ingresos y gastos van en positivo en su sentido natural;
una devolución o una reversa resta.

### 2.3 Configuración (`auditoria_pl_config/v1`)

El lector de configuración rechaza cualquier llave desconocida y cualquier llave
faltante. Así no puede quedar en la config una llave que el código ignore: si
existe, tiene efecto y tiene prueba.

| Llave | Efecto |
|---|---|
| `esquema` | Versión del formato; otra versión se rechaza |
| `rubros.ingreso`, `.costo`, `.gasto_venta`, `.gasto_admin`, `.bajo_ebitda` | Prefijos de cuenta de cada rubro. Ningún prefijo puede ser prefijo de otro. `ingreso` no puede ir vacío |
| `cuentas_sin_polizas_manuales` | Cuentas de ingreso cuya parte de pólizas manuales se aparta de la base de las bandas |
| `madurez.dias_minimos_tras_cierre` | Días mínimos entre el fin del periodo y la fecha de extracción |
| `madurez.cuentas_nomina` | Cuentas que deben traer movimiento en el mes |
| `madurez.provisiones_obligatorias` | Cuentas de provisión que deben tener un monto creado en el mes |
| `bandas.<métrica>.minimo_pct`, `.maximo_pct`, `.favorable` | Corredor de cada métrica y el lado que es bueno (`alto` o `bajo`) |
| `publicidad.cuenta` | Cuenta del estado de resultados que debe cuadrar con la suma por marca |
| `publicidad.objetivo_pct` | Proporción esperada de publicidad sobre venta; mide el exceso |
| `publicidad.alerta_pct` | Proporción a partir de la cual una marca se reporta |
| `materialidad.piso_monto` | Piso absoluto de una variación material |
| `materialidad.piso_pct_ingreso` | Piso relativo, en % de la base de ingreso |
| `materialidad.piso_mencion` | Monto mínimo para listar una variación como mención |
| `materialidad.variacion_pct_minima` | Cambio porcentual mínimo contra el mes anterior |
| `materialidad.tope_materiales` | Máximo de variaciones materiales que se listan |

Validaciones cruzadas: `minimo_pct <= maximo_pct`; `objetivo_pct <= alerta_pct`;
`0 < piso_mencion <= piso_monto`; `tope_materiales >= 1`; cada cuenta de
`cuentas_sin_polizas_manuales` cae en un prefijo de `rubros.ingreso`.

## 3. Montos y redondeo

Todo monto es `Decimal`. La conversión ocurre una sola vez, al leer: texto o
número JSON pasa por `Decimal(str(x))` y se redondea a centavos con
`ROUND_HALF_UP`. Se rechazan booleanos, `NaN`, infinitos y textos que no sean un
número. Los porcentajes se redondean igual, a dos decimales, y toda comparación
contra un umbral usa el porcentaje ya redondeado: el mismo valor que sale en el
reporte.

El CLI rechaza además un JSON con la misma llave repetida en un objeto, en lugar
de quedarse en silencio con la última.

## 4. Reglas

### 4.1 Clasificación por rubro

Cada cuenta se asigna al rubro cuyo prefijo coincide. Como los prefijos no se
traslapan, hay a lo más un rubro por cuenta. Una cuenta sin rubro genera el
bloqueo `cuenta_sin_rubro` y su monto se reporta aparte (`sin_rubro`); no se
descarta.

### 4.2 Base de ingreso

`base = total del rubro ingreso - suma de polizas_manuales_actual de las cuentas
listadas en cuentas_sin_polizas_manuales`. El monto apartado se reporta por
cuenta (cero si la cuenta no viene en la exportación). Si la base no es
positiva, la corrida se rechaza porque ninguna razón tiene sentido.

### 4.3 Métricas y bandas

Sobre la base, con `C` = costo, `V` = gasto de venta, `A` = gasto administrativo:

- `margen_bruto = (base - C) / base`
- `gasto_venta = V / base`
- `gasto_admin = A / base`
- `ebitda = (base - C - V - A) / base`

El rubro `bajo_ebitda` (depreciación, intereses) no entra en ninguna métrica,
pero sus cuentas sí entran al análisis de variaciones. Las cuatro métricas se
reportan siempre; solo las que tienen banda se evalúan:

- `dentro`: `minimo_pct <= valor <= maximo_pct` (ambos extremos incluidos).
- `fuera_favorable`: fuera del corredor hacia el lado `favorable`.
- `fuera_desfavorable`: fuera hacia el otro lado.

`desvio_pct` es la distancia al extremo más cercano (cero si está dentro). Un
`fuera_favorable` también merece revisión: suele indicar un gasto que todavía
no se registró.

### 4.4 Publicidad por marca

- Cuadre: la suma de `marcas[].publicidad` debe ser igual, al centavo, al
  `actual` de `publicidad.cuenta` (cero si la cuenta no viene). Si no, bloqueo
  `publicidad_sin_cuadre`.
- Para cada marca con venta positiva: `pct = publicidad / venta`. Si
  `pct > alerta_pct` (estricto), alerta `sobre_umbral` con
  `exceso_sobre_objetivo = publicidad - venta * objetivo_pct / 100`.
- Marca con venta cero o negativa y publicidad distinta de cero: alerta
  `publicidad_sin_venta`, sin porcentaje; como no hay venta que la respalde,
  todo el gasto cuenta como exceso.

### 4.5 Variaciones de mes contra mes

Para cada cuenta: `delta = actual - anterior` y, si `anterior != 0`,
`variacion_pct = |delta| / |anterior| * 100`; si `anterior = 0` la variación es
nula (pasa el filtro porcentual) y, si `actual` no es cero, la cuenta se marca
`cuenta_nueva`.

`piso_material = max(piso_monto, base * piso_pct_ingreso / 100)`.

Cada cuenta cae en exactamente una clase, en este orden:

1. `bajo_monto`: `|delta| < piso_mencion` (incluye las cuentas sin cambio).
2. `bajo_variacion_pct`: `variacion_pct < variacion_pct_minima`.
3. `material`: `|delta| >= piso_material`.
4. `mencion`: el resto.

Materiales y menciones se ordenan por `|delta|` descendente y luego por cuenta.
Solo se listan las primeras `tope_materiales` materiales; las demás se cuentan
en `omitidas_por_tope`. Los conteos de las cuatro clases suman el número de
cuentas.

### 4.6 Bloqueos

| Código | Condición |
|---|---|
| `mes_inmaduro` | `fecha_extraccion - último día del periodo < dias_minimos_tras_cierre` |
| `nomina_sin_registrar` | Una cuenta de `cuentas_nomina` falta o tiene `actual = 0` |
| `provision_sin_crear` | Una cuenta de `provisiones_obligatorias` falta o tiene `creado <= 0` |
| `cuenta_sin_rubro` | Ver 4.1 |
| `publicidad_sin_cuadre` | Ver 4.4 |

Con al menos un bloqueo el reporte lleva `provisional: true`. Las demás
secciones se calculan igual, para que se vea qué tan lejos está el mes.
Las provisiones de la exportación que ninguna regla exige se listan en
`madurez.provisiones_no_exigidas`.

## 5. Salida y códigos

JSON UTF-8 con llaves ordenadas, sangría de dos espacios, salto de línea final
y sin marcas de tiempo: dos corridas con las mismas entradas dan el mismo
SHA-256. Los montos salen como texto (`"-1234.56"`).

| Código | Significado |
|---|---|
| 0 | Reporte sin bloqueos |
| 2 | Argumentos, configuración o exportación inválidos, o salida que no se pudo escribir; no hay reporte |
| 3 | Reporte con al menos un bloqueo (`provisional: true`) |

## 6. Límites declarados

- **Estacionalidad**: la comparación es solo contra el mes inmediato anterior.
  No hay comparación contra el mismo mes del año previo ni ajuste estacional, así
  que un mes de temporada alta producirá variaciones esperadas que el revisor
  igual marca.
- **Jerarquía de clases**: la exportación debe venir ya agregada por marca con
  clase exacta. El revisor no ve la jerarquía del ERP y no puede detectar
  subclases arrastradas.
- **Ciclo de provisiones**: se verifica que la provisión exista en el mes, no
  que la reversa del mes siguiente coincida con la creación.
- **Signos**: no se infieren; la exportación debe seguir la convención de 2.2.
