# Finance automation blueprint: deterministic reconciliation, month-end close and AI guardrails

**Author:** Arturo Jáuregui · **Stack:** Python 3.9-3.12, standard library plus openpyxl
(xlsx output) and defusedxml (CFDI XML) · **Published:** October 2026

> **Clean-room illustrative recreation with 100% synthetic data.** Every module in this
> repository was written from a spec that lives next to it ([ADR 0001](docs/adr/0001-clean-room-rewrite.md))
> and runs only on seeded, synthetic data: company and vendor names, RFCs (`RFC_*`
> placeholders), UUIDs and amounts are fictitious. Every tolerance, window, rate and band
> is a round example value in a config file, not a calibration.

The repository recreates, for illustration, a set of finance-operations workflows: corporate
card reconciliation against Mexican CFDIs (tax invoices) and the general ledger, an Amazon
month-end accrual close, a 13-week cash flow, CFDI-to-ledger checks written in SuiteQL, a
pre-close P&L review, a quarantine filter for prompt injection in free text, and an LLM
extraction pipeline in which the model proposes and deterministic code decides.

Shared rules across modules:

- **`Decimal` money with one input boundary.** External values become `Decimal` once
  (`Decimal(str(x))`, quantized to cents with `ROUND_HALF_UP`); no float enters a money
  calculation.
- **Locks, not warnings.** Integrity checks (control totals, exclusivity, coverage,
  double entry) stop the run with a non-zero exit code. No row is dropped silently.
- **Deterministic output.** Sorted keys, no timestamps, no absolute paths in output files:
  two runs on the same inputs produce the same SHA-256, and tests check it.
- **Free text is data.** `prompt_guard` flags suspicious text for human review; it never
  approves anything, and nothing in the repository writes to an ERP.

Specs, code comments and the [glossary](GLOSSARY.md) are in Spanish; READMEs are in English.

## Capabilities

Every row links to the code, its spec and its tests; the demo label refers to the commands
in [Demos](#demos), all of which run on the versioned synthetic data.

| Capability | Code | Spec | Tests | Demo |
|---|---|---|---|---|
| Raw card statements to a charge universe: layout by exact header, control totals to the cent, unparseable rows kept and flagged | [`universo.py`](skills/credit-card-reconciliation/conciliacion/universo.py) | [`universo.md`](skills/credit-card-reconciliation/specs/universo.md) | `tests/test_universo_*.py` | D1 |
| Charge ↔ CFDI: exact amount, original currency, tolerance or sum of 2-3 CFDIs of one issuer; exclusive greedy assignment; one reason per unmatched charge; XML through `defusedxml` | [`cruce_cfdi_motor.py`](skills/credit-card-reconciliation/conciliacion/cruce_cfdi_motor.py) | [`cruce_cfdi.md`](skills/credit-card-reconciliation/specs/cruce_cfdi.md) | `tests/test_cruce_cfdi_*.py` | D2 |
| Charge ↔ general ledger: exact name similarity, bucket-vendor risk, human verdicts as input with conflicts reported | [`cruce_libro_motor.py`](skills/credit-card-reconciliation/conciliacion/cruce_libro_motor.py) | [`cruce_libro.md`](skills/credit-card-reconciliation/specs/cruce_libro.md) | `tests/test_cruce_libro_*.py` | D3 |
| End-to-end card pipeline with a human review queue for flagged free text | [`pipeline.py`](skills/credit-card-reconciliation/conciliacion/pipeline.py) | [`pipeline.md`](skills/credit-card-reconciliation/specs/pipeline.md) | `tests/test_pipeline_*.py` | D4 |
| Amazon month-end accrual close: settlement time zones, tail cohort, provision and reversal, advertising counted once, withholding band | [`cierre_amazon/`](skills/marketplace-expenses/amazon/cierre_amazon/) | [`cierre_amazon.md`](skills/marketplace-expenses/amazon/specs/cierre_amazon.md) | `tests/test_amazon_*.py` | D5 |
| 13-week cash flow from bank balances, receivables aging and payment schedules, reconciled per source | [`flujo/`](skills/cashflow-forecasting/flujo/) | [`flujo-13-semanas.md`](skills/cashflow-forecasting/specs/flujo-13-semanas.md) | `tests/test_flujo_*.py` | D6 |
| CFDI ↔ ledger checks as SuiteQL over a synthetic SQLite schema, plus validated CSV import files | [`netsuite_gl/`](skills/netsuite-gl-reconciliation/netsuite_gl/), [`queries/`](skills/netsuite-gl-reconciliation/queries/) | [`SPEC.md`](skills/netsuite-gl-reconciliation/SPEC.md) | `tests/test_netsuite_*.py` | D7 |
| Pre-close P&L review: blockers, ratio corridors, brand advertising, month-over-month materiality | [`auditoria_pl/`](skills/pl-review-methodology/scripts/auditoria_pl/) | [`auditoria_pl.md`](skills/pl-review-methodology/specs/auditoria_pl.md) | `tests/test_pl_audit_*.py` | D8 |
| `prompt_guard`: quarantine and human review for free text, domain allowlist, sensitive-path filter | [`guardia/`](skills/security-guardian/guardia/) | [`prompt_guard.md`](skills/security-guardian/specs/prompt_guard.md), [`evasiones_conocidas.md`](skills/security-guardian/specs/evasiones_conocidas.md) | `tests/test_prompt_guard_*.py` | D9 |
| LLM extraction QC: forced tool use, guard before the call, deterministic rules and a cross-check against known CFDIs after it | [`extraccion_llm/`](skills/llm-extraction-qc/extraccion_llm/) | [`extraccion_llm.md`](skills/llm-extraction-qc/specs/extraccion_llm.md) | `tests/test_extraccion_llm_*.py` | D10 |
| Seeded synthetic data generators with known answers (oracles) | [`generate.py`](examples/generate.py), `examples/generador_*/` | the README of each `examples/synthetic*/` folder | `tests/test_generador_sintetico.py`, `tests/test_*_generador.py` | D11 |

Each skill folder has its own README (overview), SKILL.md (how to use it) and, where the
design needs it, ARCHITECTURE.md.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-dev.txt
python3 -m pytest -q --cov
```

`requirements.txt` holds the runtime dependencies, `requirements-dev.txt` adds the test and
lint tools that CI installs, and `requirements-llm.txt` adds the optional `anthropic` SDK,
needed only for the live mode of the LLM demo.

## Demos

Run from the repository root. Outputs go to a temporary folder; the versioned data is
never modified.

```bash
OUT="$(mktemp -d)"

# D1 charge universe from the raw statements, with control-total locks
PYTHONPATH=skills/credit-card-reconciliation python3 -m conciliacion.universo examples/synthetic \
    --salida "$OUT/universo.jsonl"

# D2 charge <-> CFDI
PYTHONPATH=skills/credit-card-reconciliation python3 -m conciliacion.cruce_cfdi \
    --universo examples/synthetic/universo_cargos_esperado.jsonl \
    --cfdis examples/synthetic/cfdis.jsonl --salida "$OUT/cruce_cfdi.json"

# D3 charge <-> general ledger, with human verdicts
PYTHONPATH=skills/credit-card-reconciliation python3 -m conciliacion.cruce_libro \
    --universo examples/synthetic/universo_cargos_esperado.jsonl \
    --libro examples/synthetic/libro_mayor.csv --veredictos examples/synthetic/veredictos_libro.csv \
    --salida "$OUT/cruce_libro.json"

# D4 whole card pipeline: statements -> universe -> prompt_guard -> CFDI -> ledger
PYTHONPATH=skills/credit-card-reconciliation python3 -m conciliacion.pipeline \
    --datos examples/synthetic --salida "$OUT/tarjetas"

# D5 Amazon month-end close (JSON plus a workbook that is re-read and verified)
PYTHONPATH=skills/marketplace-expenses/amazon python3 -m cierre_amazon \
    --datos examples/synthetic_amazon --salida "$OUT/cierre.json" --xlsx "$OUT/cierre.xlsx"

# D6 13-week cash flow
PYTHONPATH=skills/cashflow-forecasting python3 -m flujo \
    --config skills/cashflow-forecasting/config/flujo_ejemplo.json --corte 2026-11-02 --salida "$OUT/flujo"

# D7 SuiteQL queries on the synthetic schema, then a validated CSV import file
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py consultar --salida "$OUT/suiteql"
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py generar-csv --desde-sin-registro \
    --salida "$OUT/vendor_bills.csv"

# D8 pre-close P&L review
python3 skills/pl-review-methodology/scripts/run_pl_audit.py --periodo 2026-09 \
    --config skills/pl-review-methodology/config/parametros.example.json \
    --entrada examples/sample_data/pl_monthly_sample.json --salida "$OUT/pl.json"

# D9 prompt_guard self-test and evaluation set
python3 skills/security-guardian/scripts/prompt_guard.py --self-test
python3 skills/security-guardian/scripts/evaluar_guardia.py > "$OUT/guard_eval.json"

# D10 LLM extraction QC in recorded mode (no network, no API key)
mkdir -p "$OUT/llm"
python3 skills/llm-extraction-qc/run_llm_extraction.py --salida "$OUT/llm"

# D11 regenerate the card data set into another folder
python3 examples/generate.py --salida "$OUT/synthetic"
```

What the demos report on the versioned data:

| Demo | Result |
|---|---|
| D1 | 199 charges from two statements; all 12 control-total checks reconcile to the cent; 2 unparseable rows kept |
| D2 | 161 of 199 charges backed by at least one CFDI; every unmatched charge has one reason |
| D3 | 145 charges with a ledger entry; 5 conflicts between human verdicts and the engine's proposal reported |
| D4 | 3 free-text records flagged by `prompt_guard`, 2 charges left `en_revision`; 31 locks green |
| D5 | Four months closed, all locks green; one alert: June withholding outside its band |
| D6 | 13 weeks; 2 credit balances and 2 overdue payments placed in week 1, 1 zero balance counted |
| D7 | Each query returns exactly the planted discrepancies: 6 unposted CFDIs, 6 amount mismatches, 4 duplicates (also visible in the balance check) and 4 wrong periods; 6 vendor bills validated and written |
| D8 | No blockers; selling expense at 22.80% against a 15-20% corridor; one brand advertising alert; 2 material variances |
| D9 | 44/44 injections flagged, 0/44 benign texts flagged, 0/10 documented evasions flagged |
| D10 | 40 documents: 6 blocked by the guard before the model, 24 `concordante`, 16 `revision_humana` |

## Limits

- **Greedy, not optimal.** Both matching engines (CFDI and ledger) use a deterministic
  greedy assignment with a documented total order. It is not an optimal or bipartite
  matching: a rare early choice can leave a charge unmatched that another assignment would
  cover (the ledger engine reports that case as `candidato_ocupado`).
- **NetSuite means SuiteQL plus CSV import, on a synthetic schema.** The queries are SuiteQL,
  run here against an in-memory SQLite database that mimics the SuiteQL tables through a
  small documented compatibility layer; they have not been run against a live account in
  this repository. The module writes CSV import files for human review and never uploads
  them. There is no REST client, OAuth/TBA, RESTlet or SuiteScript
  ([ADR 0002](docs/adr/0002-netsuite-scope-suiteql-only.md)).
- **`prompt_guard` is a quarantine with human review, not a security boundary.** Detection
  is pattern based; the guard only flags a record for a person and never approves, edits or
  removes anything. Ten known evasions (leetspeak, paraphrase, another language, split
  base64, ROT13, hex, homoglyphs outside its table, an instruction split across records,
  synonyms, third-person narration) are documented in
  [`evasiones_conocidas.md`](skills/security-guardian/specs/evasiones_conocidas.md) and
  pinned by tests as undetected. The evaluation set was written alongside the patterns, so
  it measures regressions, not resistance to an attacker. The controls that do not depend on
  the text are a domain allowlist, a sensitive-path filter, XML parsed only with
  `defusedxml`, and no ERP write without a person
  ([ADR 0003](docs/adr/0003-prompt-guard-is-quarantine-not-boundary.md)).
- **One marketplace.** Only Amazon is implemented. Other marketplaces, such as Mercado
  Libre or TikTok Shop, are out of scope.
- **No expense-account suggestion.** No module suggests a ledger account for a card charge,
  and nothing writes to an ERP.
- **Recorded LLM metrics validate the pipeline, not Claude.** The recorded responses in
  `examples/synthetic_llm/` are synthetic fixtures written by the generator. Real model
  metrics need `--modo vivo` with an API key and the optional SDK; CI never runs it.
- **The P&L review implements exactly these rules:** blockers (export taken too soon after
  month end, payroll account without activity, required provision not created, account
  without a P&L group, brand advertising that does not add up to its account); four ratio
  corridors (gross margin, selling expense, administrative expense, EBITDA) over a revenue
  base that sets aside manual journal entries on configured accounts; brand spend-over-sales
  alerts; and month-over-month variances classified by materiality. It compares only
  against the previous month: no seasonality, no year-over-year view, no check that a
  provision is reversed, no sign inference, and the export must already be aggregated by
  brand.
- **Cash flow.** One currency, no new-sales forecast, overdue payments assumed in week 1,
  no reconciliation against actual bank movements.
- **Synthetic formats.** The two card statement layouts, the settlement file and the ERP
  exports are formats designed for these demos. No PDF, image or xlsx statement is parsed,
  and CFDI seals or SAT status are never validated.

## Verification

CI ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) runs on Python 3.9, 3.10, 3.11 and
3.12, and every step blocks:

```bash
ruff check .                                  # rules E, F, W, B
mypy                                          # --strict on the paths listed in pyproject.toml
python3 -m pytest -q --cov --cov-report=term-missing
( set -e
  for ruta in skills examples tools .github docs/adr pyproject.toml requirements.txt \
      requirements-dev.txt requirements-llm.txt README.md GLOSSARY.md tests/*.py; do
    python3 tools/sanitize_audit.py audit "$ruta"
  done )
python3 tools/check_links.py                  # relative links and repo paths in published Markdown
python3 skills/security-guardian/scripts/prompt_guard.py --self-test
```

CI also runs the LLM demo twice in recorded mode, with an empty API key, and compares the
two reports byte for byte.

- **Coverage.** Measured on all source code under `skills/`, `tools/` and `examples/`, with
  branch coverage and no omitted files. The required floor is 80%. The threshold configured in
  `pyproject.toml` (`fail_under = 90`) is a ratchet above that floor: it may only move up and
  may never drop below 80, so CI fails on any change that lowers coverage under the ratchet.
  The suite currently measures about 97%.
- **Sanitizer.** [`tools/sanitize_audit.py`](tools/sanitize_audit.py) blocks credentials,
  local paths, non-placeholder RFCs and UUIDs, bank account numbers, non-example e-mail
  domains and narrative traces in everything that is published. Legitimate exceptions are
  versioned with a justification in [`tools/sanitize_exceptions.json`](tools/sanitize_exceptions.json).
- **Reference check.** [`tools/check_links.py`](tools/check_links.py) fails when a relative
  Markdown link, or a repository path written in code, points to a file or folder that does not
  exist or is not published.
- **Similarity gate (manual, before publishing).** [`tools/similarity_gate.py`](tools/similarity_gate.py)
  compares every code file against private reference material that never enters the repository
  and fails if any file exceeds 30% line similarity (ADR 0001). It reads the location only
  from an environment variable, prints only file names and percentages, and does not run in
  public CI because the reference material is not available there:

  ```bash
  CLEANROOM_ORIGINAL_DIR=<private reference folder> python3 tools/similarity_gate.py
  ```

## Repository layout

```text
.
├── skills/
│   ├── credit-card-reconciliation/   statements -> charge universe -> CFDI -> ledger (conciliacion/)
│   ├── marketplace-expenses/         Amazon month-end accrual close (amazon/cierre_amazon/)
│   ├── cashflow-forecasting/         13-week cash flow (flujo/)
│   ├── netsuite-gl-reconciliation/   SuiteQL queries, synthetic schema, CSV import files (netsuite_gl/)
│   ├── pl-review-methodology/        pre-close P&L review (scripts/auditoria_pl/)
│   ├── security-guardian/            prompt_guard quarantine, allowlists, evaluation set (guardia/)
│   └── llm-extraction-qc/            LLM proposes, deterministic code decides (extraccion_llm/)
├── examples/                         seeded generators and the synthetic data they write
├── tests/                            pytest suite (one file group per module)
├── tools/                            sanitizer, reference check, similarity gate
├── docs/adr/                         architecture decision records
├── GLOSSARY.md                       domain vocabulary (Spanish)
├── pyproject.toml                    ruff, mypy, pytest and coverage configuration
└── requirements*.txt                 runtime, development and optional LLM dependencies
```

## License

© 2026 Arturo Jáuregui. All rights reserved.

This repository is shared for portfolio review. You may read the code, clone it and
run the tests and demos to evaluate it. No license is granted to reuse, copy, modify
or distribute it.
