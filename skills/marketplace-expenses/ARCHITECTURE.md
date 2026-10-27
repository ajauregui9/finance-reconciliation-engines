# Architecture: `cierre_amazon`

## Data flow

```
liquidacion_*.csv ──► lector_liquidacion ─┐
publicidad_consola.csv ─► lector_fuentes ─┤
facturas_publicidad.json ─► lector_fuentes┼─► insumos.Insumos
venta_erp.json ─► lector_fuentes ─────────┘          │
                                                     ▼
config.json ─► config.Config ─► ubicacion.ubicar   (month, category, cohort per row)
                                                     │
                                                     ▼
                                agregacion.agrupar_mes (own cohort, tail, charges, ads, payouts)
                                                     │
            ┌─────────────────┬──────────────────────┼───────────────────┐
            ▼                 ▼                      ▼                   ▼
   tarifas (rates,     publicidad (one       retencion (rate      gasto.armar_gasto
   provision, refs)    authoritative source)  and band)           (accrued lines)
            └─────────────────┴──────────┬───────────┴───────────────────┘
                                         ▼
                         validacion.evaluar_candados (recomputed from rows)
                                         ▼
                              cierre.ResultadoCorrida
                                 │               │
                                 ▼               ▼
                          salida_json     salida_xlsx (write, reopen, compare)
```

## Modules

| Module | Responsibility |
|---|---|
| `dinero.py` | The only place an external value becomes `Decimal` (`a_decimal`); canonical text formats |
| `huso.py` | Fixed-offset parsing, local timestamps, month in a given zone |
| `config.py` | Config validation into an immutable `Config`; categories and ad sources |
| `modelo.py` | Frozen records produced by the readers |
| `lector_liquidacion.py` | Settlement CSV: preamble, exact header, per-row validation |
| `lector_fuentes.py` | Ads console CSV, ad invoices JSON, ERP revenue JSON |
| `insumos.py` | File discovery in the data directory; duplicate-period guard |
| `ubicacion.py` | Closing month, category and cohort of every row |
| `agregacion.py` | Signed sums per group inside a month |
| `tarifas.py` | Effective rates, provision, fee reference ranges |
| `publicidad.py` | Authoritative ad amount and cross-source differences |
| `retencion.py` | Withholding base, observed rate and band check |
| `gasto.py` | Accrued expense lines |
| `validacion.py` | Candados |
| `cierre.py` | Closes all declared months in order and chains provisions |
| `salida_json.py`, `salida_xlsx.py`, `cli.py` | Output and command line |

## Design decisions

**One money boundary.** Readers call `dinero.a_decimal` for every amount. A float goes
through `Decimal(str(x))` and everything is quantized to cents with `ROUND_HALF_UP` right
there. After that point no float exists; rates are exact `Decimal` quotients and are only
rounded when printed.

**Cut-off from the declared zone.** Each file carries its own offset, and the generator
uses three different ones (`UTC-07:00`, `UTC-08:00`, `UTC+00:00`) so rows move forward and
backward across month ends. Assuming a constant shift breaks on two of the boundary cases;
a test proves it.

**Rates from the own cohort only.** Dividing all fees settled in a month by only that
month's own revenue inflates the rate with the tail's fees. Rates use the own cohort on
both sides; the tail is reported apart and recognized through the reversal.

**Provision and full reversal.** Month `t` books `provision(t)` and reverses all of
`provision(t-1)` against the real tail. The run-level identity "accrued = real + last
provision" holds by construction and is tested on the synthetic data.

**Sign preservation.** Expenses are the negation of settlement sums, never an absolute
value. A tail of net refunds yields a negative revenue and a negative fee line, and the
previous provision was negative as well.

**Withholding by settlement month.** The platform withholds when it settles, so numerator
and denominator use the same rows: every order row settled in the month. Rows without
withholding stay in the base so a gap in withholding lowers the observed rate.

**Advertising by category, not by description.** Ads are recognized by the settlement
`Tipo` mapped to `publicidad` in the config. Those rows never feed fee or period-charge
lines. The authoritative source is a config choice; a missing authoritative source stops
the run.

**Candados recompute independently.** `validacion.py` filters the raw located rows by
category and cohort and sums again, without reusing the aggregates. Tests tamper with a
result (duplicated ad line, broken total, missing row) and check that the right candado fails.

**Determinism.** Mappings are sorted, JSON uses `sort_keys`, file names carry no path and
nothing records the time of the run. The workbook is not byte-identical (the library stamps
metadata), so it is verified by content instead.

## Fee reference ranges

Fee references live in the config (`referencias_tarifas`): round example `min`/`max` ranges
per fee concept, compared against the effective rates of the own cohort, with an alert when
a rate falls outside. There is no separate reference file.

## Scope

Only Amazon is implemented. The folder is named for marketplace expenses in general, but no
other marketplace has a reader, a config or tests here.
