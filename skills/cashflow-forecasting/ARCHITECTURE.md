# Architecture: 13-week cash flow (`flujo`)

The behavioral contract is [`specs/flujo-13-semanas.md`](./specs/flujo-13-semanas.md).
This page explains how the package is put together and why.

## Pipeline

```
config JSON ──► config.py (strict schema, Decimal numbers, collection curve)
                    │
   5 CSV inputs ──► fuentes/*  ── one adapter per source ──►  ResultadoFuente
                    │                                          (contract rows +
                    │                                           reconciliation)
                    ▼
               ensamblador.py
                 1. all five sources present, none repeated
                 2. every contract row passes the schema check
                 3. per-source reconciliation, exact to the cent
                 4. build 13 weeks
                 5. table invariants
                    │
                    ▼
        avisos.py (overdue payments, credit and zero balances)
                    │
                    ▼
        salida_json.py / salida_xlsx.py + empaque_xlsx.py  (rendered in memory)
                    │
                    ▼
               cli.py writes the three files only if 1-5 passed
```

## Contract rows

Every source is translated into the same row shape before anything is summed:
`fuente, concepto, semana, fecha, referencia, contraparte, monto, marca`. A source maps
to exactly one concept; amounts carry cash sign (collections positive, payments negative,
opening balances any sign and always in week 1 on the cutoff date). `marca` is empty on
ordinary rows; `vencido` (payments only) and `saldo_acreedor` (collections only, negative)
flag rows placed in week 1 on the cutoff date by a special-case rule, and the schema
check enforces exactly that. The assembler trusts
nothing it did not validate, so a buggy adapter fails the run (exit 4) instead of
producing a plausible-looking table.

Each adapter also reports what did not become a row: the part of a source that falls after
week 13, for receivables the uncollectible estimate, and the number of zero-balance
receivables (`registros_en_cero`, the only source allowed to report it). That makes "rows +
outside horizon + uncollectible = input total" checkable for every source, so no amount is
dropped silently, and every zero-amount record is counted.

## Decisions

- **Weeks start on the cutoff date**, not on a calendar weekday. Week `n` covers
  `[cutoff + 7(n-1), cutoff + 7n - 1]`. The horizon length (13) is the product definition
  and lives in one constant; it is not configurable.
- **Cent-exact split.** A receivable of balance `S` with cumulative weights `P_k` gets
  `round(S·P_k) - round(S·P_{k-1})` in its k-th week. The pieces telescope to
  `round(S·P_total)`, so the split can never create or lose a cent.
- **Anchor by due date.** Overdue invoices start collecting in week 1; invoices not yet
  due start in the week they fall due. Pieces landing after week 13 are reported as
  outside the horizon.
- **Inputs must match the cutoff.** A bank balance dated on another day or an invoice issued
  after the cutoff means the files belong to a different cutoff. The run fails (exit 3)
  rather than guessing.
- **Overdue payments are still owed.** A scheduled payment dated before the cutoff goes to
  week 1, dated on the cutoff, marked `vencido` and counted in the `egresos_vencidos` alert.
  The model does not guess a later payment date.
- **Credit balances go to week 1 in full.** A negative receivable (customer advance or credit
  note) is a known amount that will be netted or refunded; running it through the collection
  curve would invent a schedule and an uncollectible share. It is subtracted from week-1
  collections, marked `saldo_acreedor`, with no uncollectible estimate. A zero balance yields
  no row and is counted (`cxc_saldo_cero`). Alerts are always present, at zero when unused.
- **Strict parsing.** CSV headers must have exactly the expected columns; JSON configs reject
  unknown or repeated keys and are parsed with `Decimal` so no float ever exists. Amount
  strings are converted in one place (`dinero.a_monto`) and rounded half-up to cents.
- **Determinism.** JSON and JSONL use sorted keys, fixed row order, LF and no timestamps or
  absolute paths, so identical inputs give an identical SHA-256. The xlsx is deterministic
  too: `empaque_xlsx.py` sets a fixed author and created/modified dates (midnight of the
  cutoff), writes the workbook without openpyxl's save-time stamp, and repacks the zip with
  every entry dated 1980-01-01 (the earliest date the format allows), fixed permissions and
  a fixed origin system. A test runs the CLI twice with the clock moved a day and compares
  the SHA-256 of the workbook.
- **No hard-coded amounts or counts.** Amounts, weights and example sizes live in the config
  and in the generator parameters. A static test tokenizes the package and the generator and
  fails on any numeric literal other than 0 and 1 outside a named module constant.

## Error model

`errores.py` defines `ErrorConfig` (exit 2), `ErrorInsumo` (exit 3) and `ErrorInvariante`
(exit 4); each carries its own exit code, and every message names the file, row and column,
or the source and week, that failed. Write failures exit with 1. Nothing is caught and
ignored.

## Tests

| File | Covers |
|---|---|
| `tests/test_flujo_curva.py` | calendar, bucket boundaries, cent-exact split, anchoring, curve validation |
| `tests/test_flujo_fuentes.py` | each adapter, invalid schemas and values, cutoff consistency, overdue payments, credit and zero balances |
| `tests/test_flujo_ensamblador.py` | source presence, contract-row schema and marks, zero-record counts, per-source reconciliation, table invariants, alerts |
| `tests/test_flujo_cli.py` | end-to-end runs on the synthetic data, JSON and xlsx byte determinism, xlsx numeric cells and metadata, alerts against the generator's planted cases, exit codes |
| `tests/test_flujo_generador.py` | generator determinism, versioned data, planted edge cases and special cases, control totals |
| `tests/test_flujo_dinero.py` | the Decimal boundary |
| `tests/test_flujo_literales.py` | no hard-coded amounts or counts |
