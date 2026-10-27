# Marketplace expenses: Amazon month-end close on an accrual basis

[`amazon/cierre_amazon/`](amazon/cierre_amazon/) turns synthetic Amazon settlement files
into a month-end accrual close. Amazon is the only marketplace implemented. All money is
`Decimal`; everything reconciles to the cent, and every reconciliation is re-checked from the
raw rows before the result is trusted.

What it does, per declared month:

- **Cut-off from the file's own time zone.** Each settlement file declares a fixed UTC
  offset. Every timestamp is converted from that offset to the closing time zone from the
  config before choosing the month. No fixed shift between zones is assumed.
- **Tail cohort.** Orders from earlier months that settle this month are separated from
  this month's own orders. Effective fee rates come only from this month's own orders.
- **Accrual.** Fees for revenue that the ERP has booked but that has not settled yet are
  provisioned. Next month the provision is reversed against the real tail.
- **Advertising counted once.** Ad spend can appear in three sources (settlement
  deductions, the ads console, the monthly invoice). The config names the authoritative
  source; the other two are only cross-checks.
- **Platform withholding check.** Withholding is compared against a rate and a band from
  the config. Outside the band it raises an alert in the output.
- **Fee reference ranges.** Optional `min`/`max` ranges per fee concept from the config;
  an effective rate outside its range raises an alert.

The behavioral spec (Spanish) is [`amazon/specs/cierre_amazon.md`](amazon/specs/cierre_amazon.md).
Module design is in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Quick start

```bash
# Close every month in the synthetic data set; JSON to a file, workbook optional.
PYTHONPATH=skills/marketplace-expenses/amazon python3 -m cierre_amazon \
    --datos examples/synthetic_amazon --salida cierre.json --xlsx cierre.xlsx

# Same thing without PYTHONPATH, and only one month in the output.
python3 skills/marketplace-expenses/amazon/cierre_amazon --datos examples/synthetic_amazon --mes 2026-06

# Regenerate the synthetic inputs (deterministic, seed 2026).
python3 examples/generador_amazon
```

Flags: `--config` (defaults to `amazon/config/cierre.example.json`), `--salida` (JSON file;
stdout if omitted), `--xlsx`, `--mes AAAA-MM` (repeatable; filters the output only), and
`--fuente-publicidad liquidacion|consola|factura` (overrides the config).

Exit codes: `0` close complete (alerts may be present), `1` a candado (integrity check)
failed or the workbook did not re-verify, `2` invalid input, config or argument.

## Inputs

All files live in one directory, with fixed names:

| File | Required | Content |
|---|---|---|
| `liquidacion_AAAA-MM.csv` | at least one | Settlement for one period: `key,value` preamble (`Periodo`, `Huso horario`, `Moneda`), blank line, fixed 18-column header |
| `publicidad_consola.csv` | no | Daily ad spend per campaign, before VAT |
| `facturas_publicidad.json` | no | Monthly ad invoice: subtotal, VAT, total |
| `venta_erp.json` | no | Net revenue before VAT by order month; the anchor for the provision |

The reader fails with file, row and column on any problem (unknown header, bad amount,
row outside the declared period, order dated after its settlement, components that do not
add up to `Total`, two files for the same period). Rows are never dropped.

## Config

`amazon/config/cierre.example.json` holds round example values, not a real calibration:

| Key | Example | Meaning |
|---|---|---|
| `huso_cierre` | `UTC-06:00` | Closing time zone |
| `tasa_iva` | `0.16` | VAT rate; converts settlement ad charges to their pre-VAT amount and checks invoices |
| `tipos` | `{"Pedido": "venta", ...}` | Settlement `Tipo` -> category (`venta`, `reembolso`, `cargo_periodo`, `publicidad`, `transferencia`) |
| `publicidad.fuente_autoritativa` | `consola` | Which ad source enters the expense |
| `publicidad.tolerancia` | `1.00` | Allowed difference between ad sources before alerting |
| `retencion.tasa` / `retencion.banda` | `0.08` / `0.01` | Expected withholding rate and allowed band |
| `referencias_tarifas` | `"comision": {"min": "0.10", "max": "0.20"}` | Optional reference range per fee concept |

## Platform withholding: the calculation base

The same definition appears in the spec and in `retencion.py`:

- **Rows:** every order row (`venta` and `reembolso`) settled in the closing month, from any
  cohort. The platform withholds when it settles, so the check follows the settlement month.
- **Base:** sum of (`Venta de productos` + `Descuento promocional`) over those rows, before VAT.
- **Withheld:** minus the sum of `Retención de plataforma` over the same rows.
- **Expected:** `round(base * rate, 2)`. **Observed rate:** `withheld / base`.
- **In band** when `|observed - rate| <= band`.

Rows without withholding stay in the base on purpose: if the platform stops withholding
on part of the sales, the observed rate drops and the alert fires.

## Advertising without double counting

Settlement rows of category `publicidad` are always kept out of the fee and period-charge
lines, whichever source is authoritative. The ad line of the expense is the pre-VAT amount
of the authoritative source and nothing else. The settlement figure is
`round(sum of VAT-inclusive charges / (1 + VAT), 2)`, computed on the monthly sum. If the
authoritative source is missing for a month, the run stops instead of inventing a number.

## Accrual formula

For each fee concept (`comision`, `logistica`, `otras_tarifas`) in month `t`:

```
effective rate(t) = fee(own cohort) / net revenue(own cohort)
pending(t)        = ERP revenue(t) - net revenue(own cohort)
provision(t)      = round(pending(t) * fee(own cohort) / net revenue(own cohort), 2)
accrued fee(t)    = own cohort + provision(t) + real tail(t) - provision(t-1)
```

Subtotals keep their sign: a tail made mostly of refunds is negative and stays negative.
Every declared month is closed in order, so a month's result does not depend on `--mes`.
Across a run without gaps, total accrued fees equal real settled fees plus the last provision
(a test checks this).

## Output

Deterministic JSON (`cierre_amazon/v1`): sorted keys, amounts as strings, rates with six
decimals, file names without paths, no timestamps. Two runs give the same SHA-256. The
optional workbook has `Resumen`, `Gasto devengado`, `Alertas` and `Candados` sheets with
numeric amounts; the CLI reopens it and compares every amount against the result.

## Tests

```bash
python3 -m pytest tests/test_amazon_*.py -q
```

Unit tests for the money boundary, time zones, config and readers; core tests on small
hand-built settlements; output and CLI tests; generator determinism; and an end-to-end test
of the close against the generator's oracle.

## Known limits

- Only fixed UTC offsets. A file whose offset changes mid-period (daylight saving) must be
  split into two files.
- The reversal compares the previous month's provision against the whole current tail. A
  tail older than one month is recognized in full when it arrives.
- ERP revenue is an input; the module does not rebuild it.
- **No brand split.** The close is at account level. SKUs are kept on every row, so a
  per-brand allocation can be added on top later.
