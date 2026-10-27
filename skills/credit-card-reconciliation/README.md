# Corporate card reconciliation: statement → charge universe → CFDI → general ledger

Deterministic reconciliation of corporate card charges against received CFDIs (Mexican
tax invoices) and against the general ledger. Every amount is `Decimal`, every stage has
integrity checks that stop the run, and two runs on the same inputs are byte-identical.
All inputs in this repo are synthetic ([`examples/synthetic/`](../../examples/synthetic/README.md)).

| Stage | Code | Spec (Spanish) | What it decides |
|---|---|---|---|
| Charge universe | [`conciliacion/universo.py`](conciliacion/universo.py), [`layouts.py`](conciliacion/layouts.py), [`montos.py`](conciliacion/montos.py) | [`specs/universo.md`](specs/universo.md) | Raw statement rows become normalized charges. The layout comes only from an exact header match; control totals must reconcile to the cent; unparseable rows are kept and flagged, never dropped |
| Charge ↔ CFDI | `conciliacion/cruce_cfdi*.py` | [`specs/cruce_cfdi.md`](specs/cruce_cfdi.md) | Which received CFDIs back each charge (exact amount, original currency, amount within tolerance, or a sum of 2-3 CFDIs of one issuer) and, if none, one reason why |
| Charge ↔ ledger | `conciliacion/cruce_libro*.py`, [`nombres.py`](conciliacion/nombres.py) | [`specs/cruce_libro.md`](specs/cruce_libro.md) | Whether an entry on the card's ledger account records the charge, with bucket-vendor risk; human verdicts are an input that is never overwritten, and disagreements are reported |
| Pipeline | `conciliacion/pipeline*.py` | [`specs/pipeline.md`](specs/pipeline.md) | Runs the stages in order, screens free text with `prompt_guard`, re-checks the cross-stage invariants and publishes one row per charge |

## Usage

One command runs the whole pipeline on the synthetic inputs:

```bash
PYTHONPATH=skills/credit-card-reconciliation python3 -m conciliacion.pipeline \
    --datos examples/synthetic --salida "$(mktemp -d)"
```

Optional flags: `--config-cfdi <json>`, `--config-libro <json>`, `--sin-estado EMISOR`
(declares a statement missing; the report is marked `provisional`), `--sin-veredictos`
(declares that there are no human verdicts) and `--sin-guardia` (turns the free-text review
off; not recommended, and the run says so).

Each stage also has its own command line:

```bash
export PYTHONPATH=skills/credit-card-reconciliation
OUT="$(mktemp -d)"
python3 -m conciliacion.universo examples/synthetic --salida "$OUT/universo.jsonl"
python3 -m conciliacion.cruce_cfdi --universo examples/synthetic/universo_cargos_esperado.jsonl \
    --cfdis examples/synthetic/cfdis.jsonl --salida "$OUT/cruce_cfdi.json"
python3 -m conciliacion.cruce_libro --universo examples/synthetic/universo_cargos_esperado.jsonl \
    --libro examples/synthetic/libro_mayor.csv --veredictos examples/synthetic/veredictos_libro.csv \
    --salida "$OUT/cruce_libro.json"
```

`conciliacion.cruce_cfdi` also reads a folder of CFDI 3.3/4.0 XML files (`--cfdis-xml <dir>`),
parsed only through `defusedxml` with DTDs forbidden.

## Free text is screened, not trusted

Every charge description and CFDI concept goes through `prompt_guard`
([`skills/security-guardian`](../security-guardian/README.md)) before anything else can read
it. A flagged record is listed in the `revision_humana` queue of `reporte.json` (record id,
field, family and fragment) and its charge gets the situation `en_revision`: the engines'
match is still shown, but it is not accepted automatically until a person reviews it. A flag
does not make the report provisional (that is reserved for missing inputs); the queue, the
`en_revision` count and a `REVISIÓN HUMANA` notice make it stand out instead. The synthetic
data plants three injected CFDI concepts so the demo shows the queue.

## Output

`reporte.json` (every stage lock, pipeline invariants, totals and the human review queue),
`cargos.jsonl` (one row per charge with its CFDI(s), tier, ledger entry, reason and review
observations) and each engine's own document under `<output-dir>/etapas/`. Exit codes: `0`
report written, `2` invalid argument or input, or `prompt_guard` cannot be loaded (nothing
written), `3` a lock or invariant failed (only `bloqueo.json` is written).

On the synthetic data: 199 charges, 161 backed by a CFDI, 145 with a ledger entry, 2 left
`en_revision`, 5 verdict conflicts reported, all locks green.

## Matching rules in one paragraph each

- **CFDI.** A received CFDI is a candidate when its receiver is the company, its issuer is
  not a generic RFC and its date falls in an asymmetric window around the charge. A greedy
  pass with a documented total order assigns one-to-one matches first; only then are sums
  of 2-3 CFDIs of one issuer tried, bounded by a per-issuer candidate cap. A CFDI backs at
  most one charge. A charge without a match gets exactly one reason (`sin_candidato`,
  `fuera_de_ventana`, `fuera_de_tolerancia`, `solo_rfc_generico`, ...).
- **Ledger.** Only lines on the card's own account, on the right side and within the amount
  tolerance are candidates. Names are compared with an exact, integer-only similarity
  measure (stopwords computed per side); a bucket vendor's name proves nothing, so it needs
  a close date instead and is flagged with `riesgo_cubeta`. The assignment is greedy and
  exclusive per entry.

Tolerances, windows and thresholds live in [`config/cruce_cfdi.example.json`](config/cruce_cfdi.example.json)
and [`config/cruce_libro.example.json`](config/cruce_libro.example.json). They are round
example values that fit the synthetic data, not a calibration.

## Limits

- The assignment is greedy with a total order, not an optimal (bipartite) matching. A rare
  early choice can leave a charge unmatched that another assignment would cover; the ledger
  engine reports it as `candidato_ocupado`.
- The two statement layouts (`ALFA_V1`, `BETA_V1`) are synthetic. No PDF or xlsx statement
  is parsed.
- The ledger engine does not resolve aliases (a payment gateway descriptor versus the legal
  name) and does not match one entry against several charges.
- Nothing here suggests an expense account, writes to an ERP, validates CFDI seals or SAT
  status, or calls a language model.

## Tests

```bash
python3 -m pytest tests/test_universo_*.py tests/test_cruce_cfdi_*.py tests/test_cruce_libro_*.py tests/test_pipeline_*.py -q
```

The oracle tests compare each engine against `examples/synthetic/oraculo.json`, the known
answer written by the generator. See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the module map.
