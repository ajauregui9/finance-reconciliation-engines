# LLM extraction QC: the LLM proposes, deterministic code decides

Claude reads a CFDI (XML) or the text of its printed representation and proposes twelve
fields through a forced tool call. `prompt_guard` screens the text before it reaches the
model; afterwards, deterministic rules and a cross-check against the known-CFDI pool decide.
Any disagreement goes to `revision_humana`; nothing is accepted automatically.

> **Honesty note.** The recorded responses shipped in `examples/synthetic_llm/` are
> **synthetic fixtures written by the generator**, not Claude responses. Metrics from
> `--modo grabado` validate the evaluation pipeline, not Claude's accuracy. Real metrics
> come from `--modo vivo`, which can re-record the fixtures with `--grabar`. The report
> states this in its `advertencia` field.

The full contract (Spanish) is in `specs/extraccion_llm.md`.

## Quick start

```bash
mkdir -p out
python3 skills/llm-extraction-qc/run_llm_extraction.py --salida out/                 # recorded mode, no network
python3 skills/llm-extraction-qc/run_llm_extraction.py --salida out/ --max-tokens 5000   # exit 3: cost cap

# Live mode (optional dependency, needs a key in the environment):
pip install -r requirements-llm.txt
export ANTHROPIC_API_KEY=...            # never stored or printed by this tool
mkdir -p out/vivo out/regrabadas
python3 skills/llm-extraction-qc/run_llm_extraction.py --modo vivo --salida out/vivo --grabar out/regrabadas
python3 skills/llm-extraction-qc/run_llm_extraction.py --salida out/ --grabadas out/regrabadas   # replay
```

Outputs: `evaluacion.json` and `evaluacion.md` in the `--salida` folder (it must exist).
Two recorded runs produce byte-identical files (same SHA-256).

| Exit code | Meaning |
|---|---|
| `0` | Report written (a document the API never answered goes to review with `error_api`) |
| `2` | Invalid argument, config or input; recorded response missing or stale; `ANTHROPIC_API_KEY` or the SDK missing in live mode; API key rejected (401/403); a client error that is not an API error; missing folder |
| `3` | Document or token cap exceeded (no report is written; consumption so far goes to stderr) |

## How it works

1. **Guard first.** The full document text goes through `guardia.inspeccionar` (the installed
   `guardia` package, imported through `conciliacion.pipeline_guardia`; exit 2 if it cannot be
   imported). **A flagged document is not sent to the
   model**: it goes straight to human review with reason `bloqueado_por_guardia`. Sending it
   could never make it acceptable and would only spend tokens; ADR 0003 places the guard
   before any LLM call. Not being flagged does not make a document trustworthy, which is why
   the checks below never depend on the guard.
2. **Forced tool use.** One tool, `registrar_cfdi`, forced with
   `tool_choice = {"type": "tool", "name": "registrar_cfdi"}`. Its JSON schema fixes the
   structure (exactly twelve keys, string or null, `additionalProperties: false`, and
   `"strict": true` when `herramienta_estricta` is on) but not the formats: a pattern on the RFC
   would push the model to "fix" a misprinted RFC and hide the error.
3. **Deterministic checks** on the proposal: RFC shape, UUID shape, ISO date, plain decimal
   amounts, the full CFDI identity `subtotal − discount + VAT + IEPS − ISR withheld − VAT
   withheld = total` with `Decimal` (within `tolerancia_cuadre`, one cent in the example
   config), allowed currency, receiver is the company. The eight fields every CFDI has are
   required; discount, IEPS and the two withholdings are optional amounts where `null` means
   "not on the document" and counts as 0.00.
4. **Cross-check against the pool.** The proposed UUID locates the CFDI in the known-CFDI XML
   pool, read by the card-reconciliation engine's XML reader (`defusedxml` only; it is the
   only module in the repo allowed to parse XML). All twelve fields are compared against what
   that reader returns (both RFCs, UUID, date, currency and the seven amounts, with VAT and IEPS
   read per tax code); each difference is a `discrepancia_motor` with both values. Comparing subtotal and VAT matters:
   a model that changes the breakdown but keeps the sum passes every rule and is still caught
   here.
5. **Decision.** No observation at all: `concordante` (nothing is written anywhere, approval
   stays human). Anything else: `revision_humana`.

**Known limit.** Only the taxes in the schema enter the identity: VAT and IEPS transferred,
ISR and VAT withheld. A CFDI with local taxes (the `implocal` complement) or another tax does
not add up and always goes to review, which fails closed (see `specs/extraccion_llm.md` and
`skills/credit-card-reconciliation/specs/cruce_cfdi.md`).

The ground truth (`verdad.jsonl`) is used only to measure, never to decide.

## Cost limits

Configured in `config/extraccion_llm.example.json` and overridable by flag:

- `limites.max_documentos` (`--max-documentos`): model calls per run, checked after the guard
  and before the first call.
- `limites.max_tokens` (`--max-tokens`): input + output tokens per run, summed from each
  `response.usage`; the run stops when the total goes over. The overshoot is at most one
  response.
- `precios_usd_por_millon`: price per million tokens, used only for the USD estimate. The
  values are examples; set them to the current price list.

Input and output tokens are recorded per document. Recorded fixtures carry simulated usage
(about four characters per token).

## API errors and retries (live mode)

The SDK client is created with `max_retries=0`; this skill retries on its own, so attempts are
never doubled and every retry is announced on stderr. Policy in `reintentos` of the config:

- **Retried (transient):** 429, any 5xx (including 529 overloaded), and connection errors or
  timeouts with no response. Exponential backoff with "equal" jitter, capped at
  `espera_maxima_s`, up to `max_reintentos` retries per document. A `retry-after` header
  (seconds or HTTP date) is honoured: the retry never happens earlier; if it asks for more than
  `espera_maxima_s`, the document is not retried.
- **Not retried:** other 4xx (validation, not found, too large). The document goes to
  `revision_humana` with reason `error_api` and the batch continues; the same happens when
  retries run out.
- **Stops the run (exit 2):** 401/403 (the key or its permissions are rejected: no document
  could succeed) and any client error that is not an API error. The cost caps still stop the
  run with exit 3.

A document with `error_api` has no response: it adds no tokens, is not re-recorded and is
left out of the per-field metrics. Tests drive all of this with a fake client and an injected
clock.

## Recorded-mode results (synthetic fixtures)

These numbers show that the pipeline and the metrics work; they say nothing about Claude.

| Indicator | Value |
|---|---|
| Documents | 50 (25 XML, 25 printed text) |
| Blocked by the guard (not sent) | 6 |
| Guard detection on planted injections | 6 / 7 = 0.8571 (the miss is a third-person paraphrase, a documented evasion) |
| Guard false positives | 0 / 43 |
| Sent to the model | 44 |
| `concordante` / `revision_humana` | 32 / 18 |
| Fee, freight, discount and IEPS invoices without a planted error | 8 / 8 `concordante` |
| Model-vs-engine discrepancies | 14 fields in 10 documents |
| Concordant documents with a wrong field | 0 |
| Expected-review documents left concordant | 0 |
| Precision / recall of `subtotal` | 0.9545 / 0.9545 |
| Precision / recall of `iva` | 0.9535 / 0.9318 |
| Precision / recall of `total` | 0.9318 / 0.9318 |
| Precision / recall of `iva_retenido` | 1.0000 / 0.8000 |
| Precision / recall of `isr_retenido`, `ieps` | 1.0000 / 0.6667 |

Every planted model error (digit changed in a total, VAT omitted, VAT computed on the total
with the sum kept, IEPS folded into VAT with the sum kept, both withholdings of a fee invoice
omitted, date copied as printed, thousands separators kept, a model obeying the injection the
guard missed) ends in review through a rule or a pool discrepancy.

## Layout

| Path | Content |
|---|---|
| `specs/extraccion_llm.md` | Contract (Spanish) |
| `config/extraccion_llm.example.json` | Model (default `claude-opus-5-5`), caps, prices, rule options, cuadre tolerance, retry policy |
| `extraccion_llm/herramienta.py` | Tool definition, system instructions, request, response interpretation |
| `extraccion_llm/respuesta.py` | SDK boundary: own `Protocol`s, internal response shape |
| `extraccion_llm/vivo.py`, `grabadas.py` | Live extractor (lazy SDK import, retry loop) and recorded extractor |
| `extraccion_llm/reintentos.py` | Which API errors are retried, backoff with jitter, `retry-after` |
| `extraccion_llm/reglas.py`, `pool.py`, `cruce.py` | Deterministic checks, known-CFDI pool, cross-check |
| `extraccion_llm/pipeline.py`, `costo.py` | Orchestration and cost caps |
| `extraccion_llm/evaluacion.py`, `reporte.py` | Metrics and the JSON/markdown report |
| `extraccion_llm/cli.py`, `run_llm_extraction.py` | Command line |

Synthetic inputs live in `examples/synthetic_llm/` and are produced by
`examples/generador_llm/` (see that folder's README).

## Dependencies

Recorded mode uses only the repo's base dependencies (`defusedxml` for the pool). The
`anthropic` SDK is optional (`requirements-llm.txt`) and is imported only when live mode
creates its client. The code is typed against its own `Protocol`s, not the SDK stubs, and the
live-mode tests inject a fake client: no test touches the network or a key.

`herramienta_estricta: true` adds `"strict": true` to the tool definition. If the API or the
chosen model rejects that field, set it to `false`: the local check enforces the same schema
either way.

## What it does not do

- It does not write to an ERP or approve anything.
- It does not read PDFs or images; the `.txt` files simulate extracted text.
- It does not validate seals, stamps or SAT status.
- It does not retry or repair a model response: it only retries transient API errors, and a
  malformed response goes to review.
- Recorded-mode metrics do not measure Claude.
