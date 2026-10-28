# Pre-close P&L review

A deterministic check of a monthly income statement export before the month is
closed. It answers two questions: *is the month complete enough to read?* and
*what moved enough to deserve an explanation?* It never connects to an ERP and
never writes to one; it reads two JSON files and prints one JSON report.

The full rule set (in Spanish) is the spec in [`specs/auditoria_pl.md`](specs/auditoria_pl.md);
module design is in [`ARCHITECTURE.md`](ARCHITECTURE.md).
Every number in [`config/parametros.example.json`](config/parametros.example.json)
is a round illustrative value, not a calibration.

## Quick start

From the repository root:

```bash
python3 skills/pl-review-methodology/scripts/run_pl_audit.py \
  --periodo 2026-09 \
  --config skills/pl-review-methodology/config/parametros.example.json \
  --entrada examples/sample_data/pl_monthly_sample.json
```

On the bundled sample the report has no blockers, flags selling expense above
its corridor (22.80% against a 15-20% band), raises one brand advertising alert
and lists two material variances (a spend increase and an account with no
prior-month balance) plus two smaller mentions.

## Command line

| Flag | Required | Meaning |
|---|---|---|
| `--periodo` | yes | Period to review, `YYYY-MM`. There is no default; it must match the export's `periodo`. |
| `--config` | yes | Configuration file (`auditoria_pl_config/v1`). |
| `--entrada` | yes | Monthly export (`exportacion_pl/v1`). |
| `--salida` | no | Write the report to this file and print a one-line summary instead of the report. |

| Exit code | Meaning |
|---|---|
| `0` | Report written, no blockers |
| `2` | Invalid arguments, configuration or export, or the output could not be written; no report |
| `3` | Report written with at least one blocker (`provisional: true`) |

## What it checks

1. **Blockers** make the whole report provisional: the export was taken too
   soon after month end, a payroll account has no activity, a required
   provision was not created, an account matches no P&L group, or brand-level
   advertising does not add up to the advertising account.
2. **Bands**: gross margin, selling expense, administrative expense and EBITDA
   as a percentage of the revenue base, each against a min/max corridor with a
   favorable side. Outside on the favorable side is still reported, because it
   often means an expense has not been booked yet.
3. **Revenue base**: manual journal entries on the configured revenue accounts
   are set aside, so a stray provision reversal does not move the ratios.
4. **Brand advertising**: spend over sales per brand against an alert
   threshold, with the excess over a target ratio.
5. **Month-over-month variances** per account, split into material items,
   mentions, below-amount and below-percentage. The four counts always add up
   to the number of accounts, so no row disappears silently.

## Configuration

The reader is strict: an unknown key or a missing key is an error. A key that
the code does not use therefore cannot live in the file.

| Key | Effect |
|---|---|
| `esquema` | Format version; must be `auditoria_pl_config/v1` |
| `rubros.ingreso` | Account prefixes of revenue (cannot be empty) |
| `rubros.costo` | Account prefixes of cost of sales |
| `rubros.gasto_venta` | Account prefixes of selling expense |
| `rubros.gasto_admin` | Account prefixes of administrative expense |
| `rubros.bajo_ebitda` | Account prefixes below EBITDA (depreciation, interest); excluded from every ratio, included in variances |
| `cuentas_sin_polizas_manuales` | Revenue accounts whose manual journal portion is removed from the band base |
| `madurez.dias_minimos_tras_cierre` | Minimum days between period end and the export date |
| `madurez.cuentas_nomina` | Accounts that must have activity in the month (empty list disables the check) |
| `madurez.provisiones_obligatorias` | Provision accounts that must show an amount created in the month (empty list disables the check) |
| `bandas.<metric>.minimo_pct` | Lower bound of the corridor, inclusive |
| `bandas.<metric>.maximo_pct` | Upper bound of the corridor, inclusive |
| `bandas.<metric>.favorable` | `alto` or `bajo`: which side of the corridor is good |
| `publicidad.cuenta` | P&L account that the brand advertising total must match to the cent |
| `publicidad.objetivo_pct` | Target spend over sales; the alert reports the excess over it |
| `publicidad.alerta_pct` | A brand is reported when its spend over sales is strictly above this |
| `materialidad.piso_monto` | Absolute floor of a material variance |
| `materialidad.piso_pct_ingreso` | Relative floor, as % of the revenue base; the larger floor wins |
| `materialidad.piso_mencion` | Minimum absolute change to be listed at all |
| `materialidad.variacion_pct_minima` | Minimum % change against the prior month |
| `materialidad.tope_materiales` | Maximum material variances listed; the rest are counted as omitted |

`<metric>` is one of `margen_bruto`, `gasto_venta`, `gasto_admin`, `ebitda`.
A metric without a band is still computed and reported, just not evaluated.

## Input export

`exportacion_pl/v1`: `periodo`, `fecha_extraccion`, `cuentas[]` (one row per
account with `anterior`, `actual` and the optional `polizas_manuales_actual`),
`marcas[]` (`venta`, `publicidad`) and `provisiones[]` (`creado`). Amounts are
JSON strings such as `"-1234.56"`; they become `Decimal` once, at the input
boundary, rounded half-up to cents. Unknown keys, duplicate accounts, brands
or provisions, and duplicate JSON keys are rejected.

## Output

`reporte_auditoria_pl/v1`, UTF-8, sorted keys, two-space indent, no
timestamps: the same inputs always produce the same bytes (same SHA-256).
Sections: `bloqueos`, `madurez`, `base_ingreso`, `rubros`, `metricas`,
`bandas`, `publicidad`, `variaciones`.

## Known limitations

- **Seasonality is not modelled.** Each account is compared only with the
  previous month. There is no same-month-last-year comparison and no seasonal
  adjustment, so a seasonal peak shows up as a variance that a person has to
  explain away.
- The export must already be aggregated by exact brand class; the reviewer
  cannot see the ERP class hierarchy.
- Provisions are checked for creation in the month, not for a matching
  reversal in the next one.
- Signs are not inferred; the export must follow the convention in the spec.

## Tests

```bash
python3 -m pytest tests/test_pl_audit_*.py -q
```
