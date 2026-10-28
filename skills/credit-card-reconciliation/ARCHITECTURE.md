# Architecture: corporate card reconciliation (`conciliacion`)

The behavioral contracts are the four specs in [`specs/`](specs/) (Spanish). This page
explains how the package is put together and why.

## Why naive matching fails

- Card statements are produced by different issuers with different layouts; two of them
  write dates in opposite day/month order, which is ambiguous for days 1-12.
- A CFDI is issued days after the charge, sometimes split into several invoices, sometimes
  with a credit note, and sometimes to a generic RFC that proves nothing.
- The ledger often books a card charge under a bucket vendor that groups many merchants, so
  the vendor name is no evidence; and bank descriptors rarely spell the vendor's name the way
  the ERP does.

## Data flow

```text
resumen_estados_cuenta.json + statement CSVs
        │
        ▼
 universo.py (layouts.py, montos.py)      control-total locks per statement (exit 3)
        │  etapas/universo.jsonl
        ▼
 pipeline_revision.py + pipeline_guardia.py   prompt_guard on descriptions and CFDI concepts
        │  observations only; records are never changed
        ├──────────────────────────────┐
        ▼                              ▼
 cruce_cfdi*.py  ◄─ cfdis.jsonl     cruce_libro*.py, nombres.py  ◄─ libro_mayor.csv,
 (invariants, exit 3)               (locks, exit 3)                 veredictos_libro.csv
        │                              │
        └──────────────┬───────────────┘
                       ▼
 pipeline_filas.py + pipeline_invariantes.py   one row per charge, invariants recomputed
                       ▼
 pipeline_reporte.py   reporte.json, cargos.jsonl, etapas/*  (or bloqueo.json)
```

## Modules

| Module | Responsibility |
|---|---|
| [`universo.py`](conciliacion/universo.py) | Summary validation, layout detection, normalization, control-total locks, partial universe, CLI |
| [`layouts.py`](conciliacion/layouts.py) | Catalog of statement layouts (exact header) and per-field row interpretation |
| [`montos.py`](conciliacion/montos.py) | Amount parsing and formatting for the universe (`Decimal` only) |
| `cruce_cfdi_insumos.py`, `cruce_cfdi_xml.py` | Input boundary of the CFDI engine: JSONL or XML (`defusedxml` only) to frozen records |
| `cruce_cfdi_config.py` | Config schema, example defaults and range checks |
| `cruce_cfdi_candidatos.py`, `cruce_cfdi_nombres.py` | Candidate rules, date and amount indexes, name affinity |
| `cruce_cfdi_motor.py` | Four-phase greedy assignment (one-to-one, then sums, first with enough name affinity and then by amount only as `monto_sin_afinidad`) and the reason for each unmatched charge |
| `cruce_cfdi_invariantes.py`, `cruce_cfdi_salida.py`, `cruce_cfdi.py` | Invariants recomputed on the result, deterministic output, CLI |
| `cruce_libro_insumos.py`, `cruce_libro_config.py` | Input boundary and config of the ledger engine |
| [`nombres.py`](conciliacion/nombres.py) | Integer-only name similarity with per-side stopwords (`fractions.Fraction`) |
| `cruce_libro_motor.py` | Candidates, evaluation and greedy exclusive assignment per entry |
| `cruce_libro_veredictos.py` | Human verdicts: proposal, conflicts and final result |
| `cruce_libro_salida.py`, `cruce_libro.py` | Locks, summary, deterministic output, CLI |
| `pipeline_etapas.py` | Reads every input and wraps each engine without relaxing its boundary |
| `pipeline_revision.py`, `pipeline_guardia.py` | Free-text review stage and the `prompt_guard` reviewer, imported as the installed `guardia` package (exit 2 if it cannot be imported) |
| `pipeline_filas.py`, `pipeline_invariantes.py` | Per-charge rows (an amount-only CFDI match is `cfdi_por_revisar`, never backed), summary partitions and pipeline invariants |
| `pipeline_reporte.py`, `pipeline_modelo.py`, `pipeline.py` | Output documents, shared vocabulary, orchestration and CLI |

## Design decisions

- **One money boundary per engine.** Amounts become `Decimal` once, when read
  (`Decimal(str(x))`, quantized to cents with `ROUND_HALF_UP`). Configs reject JSON floats.
- **Layout by exact header, never by content.** Guessing from the rows cannot tell
  `DD/MM` from `MM/DD`. An unknown header stops the run and shows the header read.
- **Nothing is dropped.** An unparseable row enters the universe with `estado =
  ininterpretable` and its reasons, counts in the control totals and fails the
  `montos_legibles` lock if its amount is unreadable.
- **Greedy with a total order.** Both engines sort every proposal by a key that ends in
  identifiers, so two proposals never tie and the result does not depend on input order.
  It is not an optimal assignment, and the specs say so.
- **Affinity first, then one-to-one before sums.** Evidence with enough issuer-name affinity
  is assigned before any amount-only match, and within each level one-to-one goes before
  sums. A charge resolved in one phase never reaches the next, and a CFDI taken in one phase
  is not available to another charge later. An amount-only match keeps its CFDIs but is
  published as `monto_sin_afinidad` and never counted as backed, so the error goes to a
  person instead of a silent match. Sums are bounded by a per-issuer candidate cap, so the
  work per charge is fixed.
- **Invariants recomputed independently.** Coverage, exclusivity, tier coherence and
  totals are recalculated on the result without trusting the algorithm. A failure exits
  with 3: the CFDI engine writes nothing, the ledger engine writes its document with the
  failing lock so it can be reviewed, and the pipeline writes only `bloqueo.json`.
- **Human verdicts as input.** The ledger engine first proposes without looking at verdicts,
  then compares, then applies them and re-runs the rest with the cited entries reserved.
- **Quarantine, not filtering.** The review stage only returns observations; the engines run
  on the same inputs with or without it, so the stage documents are identical either way.
- **Determinism.** Sorted keys, LF, no timestamps or absolute paths; two runs give the same
  SHA-256 for every file.

## Tests

| Files | Cover |
|---|---|
| `tests/test_universo_*.py` | layouts, amounts, locks, partial universe, CLI against the expected universe |
| `tests/test_cruce_cfdi_*.py` | input boundary, XML reader, name affinity, engine tiers and order, invariants, CLI, oracle |
| `tests/test_cruce_libro_*.py` | input boundary, name similarity, engine, verdicts and conflicts, CLI, oracle |
| `tests/test_pipeline_*.py` | stages, free-text review and guard wiring, planted injections, assembly and invariants, CLI exit codes, end-to-end determinism and oracle |
