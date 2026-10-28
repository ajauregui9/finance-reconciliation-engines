# 13-week cash flow forecast

A small, deterministic 13-week cash flow model. It reads an opening bank balance, an
accounts receivable aging report and three schedules of planned payments (suppliers,
payroll, taxes), turns every source into **contract rows**, and assembles a weekly table
whose balances reconcile to the cent. All inputs in this repo are synthetic.

After `python3 -m pip install -e .` at the repository root:

```bash
python3 -m flujo --config skills/cashflow-forecasting/config/flujo_ejemplo.json \
    --corte 2026-11-02 --salida "$(mktemp -d)"
```

`--config`, `--corte` (cutoff date, `YYYY-MM-DD`) and `--salida` (output directory) are all
required. Input paths inside the config are relative to the config file, not to the current
folder. On success the command prints a one-line JSON summary and writes three files.

## What it does

1. **Adapters** (`flujo/fuentes/`): one per input file. Each validates its CSV (exact
   column set, ISO dates, decimal amounts, unique keys, currency, dates consistent with the
   cutoff) and returns contract rows plus a reconciliation: input total, amount outside the
   13-week horizon, for receivables the estimated uncollectible part, and the count of
   zero-balance receivables. Overdue payments and receivable credit balances follow the
   rules in [Special cases](#special-cases).
2. **Collection curve** (`flujo/curva.py`): each receivable falls in an aging bucket
   (days past due at the cutoff). The bucket's weekly weights spread its balance over
   weeks, starting at week 1 for overdue invoices and at the due-date week for invoices not
   yet due. Weights may add up to less than 1; the rest is the uncollectible estimate.
3. **Assembler** (`flujo/ensamblador.py`): checks that all five sources are present, that
   every contract row matches the schema, and that each source reconciles to the cent
   (`rows + outside horizon + uncollectible = input total`). It then builds exactly 13 weeks
   and verifies the table invariants: contiguous weeks, `closing(n) = opening(n) + net(n)`,
   `closing(n) = opening(n+1)`, and per-concept totals equal to their rows.
4. **Writers**: deterministic JSON/JSONL and an xlsx workbook (openpyxl) whose amounts are
   numeric cells with a `#,##0.00` format, never text.

Nothing is written unless every check passes.

## Special cases

None of these stops the run or disappears silently; each one is flagged on its rows and
counted in the `avisos` (alerts) block of the JSON output, the `Resumen` sheet and the
one-line CLI summary.

| Case | Treatment | Row mark | Alert |
|---|---|---|---|
| Scheduled payment (supplier, payroll or tax) dated **before** the cutoff | Still unpaid: the full amount goes to **week 1**, dated on the cutoff | `vencido` | `egresos_vencidos` (rows, amount) |
| Receivable with a **negative** balance (customer advance or credit note) | Accepted; the full amount is **subtracted in week 1**, dated on the cutoff. It skips the collection curve: no bucket, no uncollectible estimate, nothing outside the horizon | `saldo_acreedor` | `cxc_saldo_acreedor` (rows, amount) |
| Receivable with a balance of **exactly zero** (after rounding to cents) | No contract row; the record is counted in the source's `registros_en_cero` | none | `cxc_saldo_cero` (records) |

Why week 1 for credit balances: the amount is known and will be netted against the
customer's collections or refunded, so spreading it with collection weights would invent
a schedule and an "uncollectible" share that do not exist. Recognising it in week 1 is
the prudent reading: it never pulls cash forward. Per-source reconciliation still holds
to the cent because the negative balances are part of both the input total and the rows.

A zero or negative amount on a scheduled payment is still an input error (exit 3).

## Inputs

All paths come from the config; every one of them is used and traced in the output
(file name, SHA-256 and record count per source).

| Source key | Columns | Rules |
|---|---|---|
| `saldos_bancarios` | cuenta, banco, fecha_saldo, moneda, saldo | at least one account; `fecha_saldo` = cutoff |
| `cxc_antiguedad` | cliente_id, cliente, factura, fecha_factura, fecha_vencimiento, moneda, saldo | balance of any sign (see special cases); invoice date <= cutoff; due date >= invoice date |
| `cxp_programadas` | proveedor_id, proveedor, factura, fecha_programada, moneda, monto | amount > 0; a date before the cutoff is overdue |
| `nomina` | periodo, descripcion, fecha_pago, moneda, monto | amount > 0; a date before the cutoff is overdue |
| `impuestos` | impuesto, periodo_fiscal, fecha_limite, moneda, monto | amount > 0; a date before the cutoff is overdue |

The example config (`config/flujo_ejemplo.json`) points at `examples/synthetic_flujo/` and
defines five aging buckets with round example weights. The weights are illustrative
parameters, not a calibration.

## Outputs

| File | Content |
|---|---|
| `flujo_13_semanas.json` | Schema `flujo_13_semanas/v1`: weeks (opening, inflows and outflows by concept, net, closing), per-source reconciliation (including `registros_en_cero`), `avisos`, horizon totals. Amounts as `"-1234.56"` strings, sorted keys, no timestamps or absolute paths: same inputs, same SHA-256. |
| `filas_contrato.jsonl` | One contract row per line (with its `marca`), sorted by week, concept, source and reference. |
| `flujo_13_semanas.xlsx` | Sheets `Flujo` (concepts by week 1..13), `Filas contrato` (with a `marca` column), `Fuentes`, `Resumen` (with the alerts). Amounts are numeric cells. The file is byte-for-byte deterministic: fixed author, created/modified set to midnight of the cutoff, no save timestamp, and every zip entry dated 1980-01-01 with fixed permissions. Same inputs, same SHA-256. |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | outputs written |
| 1 | the output directory could not be written |
| 2 | invalid arguments or config (including an invalid collection curve) |
| 3 | an input is missing, unreadable, or has an invalid schema or value |
| 4 | an assembler invariant failed |

## Layout

```
skills/cashflow-forecasting/
├── config/flujo_ejemplo.json      example config (relative paths to examples/synthetic_flujo/)
├── specs/flujo-13-semanas.md      behavioral spec (Spanish), written before the code
└── flujo/                         the package (python3 -m flujo)
    ├── cli.py                     argument parsing, orchestration, exit codes
    ├── config.py                  strict config and collection-curve validation
    ├── calendario.py              13 seven-day weeks starting at the cutoff
    ├── curva.py                   aging bucket lookup and cent-exact weekly split
    ├── contrato.py                sources, concepts, contract row and its schema check
    ├── lectura.py                 strict CSV reading with file/row/column error messages
    ├── fuentes/                   adapters: saldos.py, cxc.py, egresos.py (3 schedules)
    ├── ensamblador.py             reconciliation, weekly table, invariants
    ├── avisos.py                  alerts: overdue payments, credit and zero balances
    ├── salida_json.py             JSON and JSONL writers
    ├── salida_xlsx.py             xlsx writer
    ├── empaque_xlsx.py            fixed workbook metadata and normalized zip packaging
    ├── dinero.py                  the single Decimal boundary for amounts
    └── errores.py                 error classes and their exit codes
```

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the design decisions.

## Synthetic data and tests

```bash
python3 -m generador_flujo                         # regenerates examples/synthetic_flujo/
python3 -m pytest tests/test_flujo_*.py -q
```

The generator is seeded and writes byte-identical files; its parameters (counts, amount
ranges, planted edge cases) live in `examples/generador_flujo/parametros.json`. A test
regenerates the data and fails if the versioned files differ.

## Out of scope

Multiple currencies, estimating the actual payment date of an overdue payable (it is
assumed in week 1), applying a credit balance against specific invoices of the same
customer, new-sales forecasting, and reconciliation against actual bank movements.
