---
name: llm-extraction-qc
description: CFDI field extraction with Claude through forced tool use, screened by prompt_guard before the call and validated after it by deterministic rules and a cross-check against known CFDIs. The LLM proposes, deterministic code decides; any disagreement goes to human review.
---

# LLM extraction QC

## When to use
- Extract issuer RFC, receiver RFC, UUID, date, subtotal, VAT, total and currency from CFDI XML
  or from the text of a printed invoice, without trusting the model's output.
- Measure per-field precision and recall of an extraction model against known answers.
- Check how many planted prompt injections the guard flags before any model call.

## Steps
1. Recorded mode (default, no network, no key):
   `python3 skills/llm-extraction-qc/run_llm_extraction.py --salida <existing dir>`.
2. Read `evaluacion.md`: decisions, guard detection, per-field metrics, routing safety, cost,
   model-vs-engine and model-vs-truth discrepancies.
3. Live mode only when asked: `pip install -r requirements-llm.txt`, `ANTHROPIC_API_KEY` in the
   environment, `--modo vivo` (add `--grabar <dir>` to re-record fixtures). Keep the cost caps
   (`--max-documentos`, `--max-tokens`) low on a first run.
4. Exit code `3` means a cost cap stopped the run; nothing was written. Exit code `2` means an
   input, the key, the SDK or the API failed; read stderr.

## Rules
- Recorded-mode metrics come from synthetic fixtures: they validate the evaluation pipeline,
  not Claude's accuracy. Say so whenever you quote them.
- A document flagged by `prompt_guard` is never sent to the model. A document that is not
  flagged is still untrusted text.
- Never accept a model value that disagrees with the deterministic engine; `concordante` is a
  proposal for a person, not a write to any system.
- Never print, log or store the API key; the SDK reads it from the environment.
- See `README.md` for the overview and `specs/extraccion_llm.md` for the full contract.
