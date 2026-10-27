# Architecture: pre-close P&L review (`auditoria_pl`)

The behavioral contract is [`specs/auditoria_pl.md`](specs/auditoria_pl.md) (Spanish). This
page explains how the package is put together and why.

## Data flow

```text
--periodo YYYY-MM ─┐
config JSON ───────┼─► run_pl_audit.py (duplicate-key check, exit codes)
export JSON ───────┘          │
                              ▼
                validacion.py / config.py / exportacion.py   strict input boundary
                              │  frozen records, Decimal amounts
                              ▼
                       auditoria.auditar  (pure function)
       ┌──────────┬───────────┼────────────┬──────────────┬──────────────┐
       ▼          ▼           ▼            ▼              ▼              ▼
   rubros.py  madurez.py   bandas.py   publicidad.py  variaciones.py  bloqueos.py
   (groups,   (month       (ratios vs  (brand split   (month over     (collects
   revenue    maturity)    corridors)  and alerts)    month, by       blockers)
   base)                                              materiality)
                              │
                              ▼
                    salida.py  canonical JSON (sorted keys, amounts as text)
```

## Modules

| Module | Responsibility |
|---|---|
| [`run_pl_audit.py`](scripts/run_pl_audit.py) | Command line: arguments, reading, duplicate JSON keys, exit codes `0`/`2`/`3` |
| `scripts/auditoria_pl/validacion.py` | Typed readers for decoded JSON; every error names the field |
| `scripts/auditoria_pl/config.py` | `auditoria_pl_config/v1`: unknown or missing keys rejected, cross-field checks |
| `scripts/auditoria_pl/exportacion.py` | `exportacion_pl/v1`: accounts, brands and provisions, duplicates rejected |
| `scripts/auditoria_pl/dinero.py` | The only `Decimal` conversion and the percentage rounding |
| `scripts/auditoria_pl/rubros.py` | Account groups by prefix and the revenue base without manual journal entries |
| `scripts/auditoria_pl/madurez.py` | Days after month end, payroll activity, required provisions |
| `scripts/auditoria_pl/bandas.py` | Gross margin, selling, administrative and EBITDA ratios against corridors |
| `scripts/auditoria_pl/publicidad.py` | Brand advertising total against the P&L account, spend-over-sales alerts |
| `scripts/auditoria_pl/variaciones.py` | Month-over-month classification into four exclusive classes |
| `scripts/auditoria_pl/bloqueos.py`, `auditoria.py` | Blocker list and the pure orchestration |
| `scripts/auditoria_pl/salida.py` | Canonical JSON output |

## Design decisions

- **The period is always explicit.** There is no default period and it must equal the
  export's `periodo`, so a stale file is never reviewed by mistake.
- **A key that exists has an effect.** The config reader rejects unknown and missing keys,
  and a test checks that the README documents exactly the keys of the example config.
- **Blockers do not hide the rest.** A blocker makes the report provisional (exit `3`), but
  every other section is still computed, so the reviewer sees how far the month is from
  being readable.
- **Favorable is still reported.** A ratio outside its corridor on the good side is listed
  as `fuera_favorable`, because it often means an expense has not been booked yet.
- **No row disappears.** Each account falls in exactly one variance class (`bajo_monto`,
  `bajo_variacion_pct`, `material`, `mencion`); the four counts add up to the number of
  accounts, and material items beyond the cap are counted as omitted.
- **Rounded values decide.** Percentages are rounded half-up to two decimals and every
  threshold comparison uses the rounded value, the same one printed in the report.
- **Determinism.** Sorted keys, two-space indent, no timestamps: the same inputs give the
  same SHA-256.

## What is deliberately not modelled

Seasonality (the comparison is only against the previous month), the ERP class hierarchy,
the reversal of last month's provisions and sign inference. Each one is listed under
"Known limitations" in the [README](README.md).

## Tests

`tests/test_pl_audit_*.py`: input validation, each rule on small fixtures, the bundled sample
end to end, CLI exit codes, determinism, the documentation checks above and the sanitizer.
