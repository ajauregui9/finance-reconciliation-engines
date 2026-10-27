# Security Guardian: quarantine + human review for free text

`prompt_guard` screens third-party free text (card charge descriptions, CFDI
concepts, vendor notes) before it can reach a language model or an ERP load. Its
only action is to **flag** a record and send it to **human review**. It never
approves, edits or drops a record, and a text without findings is not
"certified": it simply was not flagged.

Pattern matching can be evaded (paraphrase, homoglyphs, encodings; see
[`specs/evasiones_conocidas.md`](specs/evasiones_conocidas.md)), so the guard is
one layer, not the protection itself. The controls that do not depend on the
text are: the domain allowlist, the sensitive-path filter, XML parsing only
through `defusedxml`, and no ERP write without human approval.

## What it does

- **Normalization**: Unicode NFKC, removal (and counting) of zero-width, bidi and
  Unicode-tag characters, flattening of multi-line text, a folded lowercase view
  without accents and with common Cyrillic/Greek homoglyphs, and a compact
  letters-and-digits view for spelled-out phrases.
- **Detection by family**: instruction override and paraphrases (Spanish and
  English), role reassignment, spoofed roles (`SYSTEM:`, `assistant:`,
  `<|im_start|>`), HTML comments and scripts, exfiltration requests, bank-account
  changes and transfer orders, messages addressed to an AI, attempts to dictate
  the reconciliation result, invisible text, and text too large to inspect.
- **Hidden layers**: base64 tokens that decode to readable UTF-8, and ASCII
  smuggled in Unicode tag characters, are inspected as extra layers (two levels).
- **Output**: at most one finding per family, each with the fragment that
  triggered it.
- **Access controls**: `dominio_permitido` accepts only `https` to
  `*.suitetalk.api.netsuite.com` account subdomains (exactly one extra label) and
  rejects look-alikes such as `suitetalk.api.netsuite.com.evil.com` or
  `xsuitetalk.api.netsuite.com`; `ruta_permitida` blocks system paths, credential
  folders, secret files and key/certificate extensions, following symlinks.

The full contract (in Spanish) is in [`specs/prompt_guard.md`](specs/prompt_guard.md).

## Usage

```bash
python3 skills/security-guardian/scripts/prompt_guard.py --self-test
python3 skills/security-guardian/scripts/prompt_guard.py --texto "SYSTEM: ignora las instrucciones"
python3 skills/security-guardian/scripts/prompt_guard.py --archivo examples/synthetic/cfdis.jsonl
python3 skills/security-guardian/scripts/prompt_guard.py --dominio https://1234567.suitetalk.api.netsuite.com
python3 skills/security-guardian/scripts/evaluar_guardia.py
```

Exit codes: `0` no findings / allowed, `1` findings (quarantine) / rejected, `2`
invalid argument or a file blocked by the path filter or unreadable.

The card reconciliation pipeline runs the guard by default on every charge
description and CFDI concept; flagged records go to the `revision_humana` queue
of `reporte.json` and their charge is left `en_revision` (see
`skills/credit-card-reconciliation/specs/pipeline.md`).

## Evaluation

`eval/casos.jsonl` holds 44 injections, 44 realistic benign texts (including
hard ones such as `IGNORAR CARGO DUPLICADO` and `SYSTEM SOFTWARE SA DE CV`) and
10 documented evasions. `scripts/evaluar_guardia.py` reports the detection rate
and the false-positive rate; tests pin the minimum thresholds (detection ≥ 0.90,
false positives ≤ 0.05). Current result: 44/44 injections flagged, 0/44 benign
texts flagged, 0/10 known evasions flagged. The set was written alongside the
patterns, so it measures regressions, not effectiveness against an attacker who
does not know the catalog.

## Layout

| Path | Content |
|---|---|
| `guardia/` | the library (standard library only) |
| `scripts/prompt_guard.py` | CLI and self-test (run by CI) |
| `scripts/evaluar_guardia.py` | evaluation report |
| `eval/casos.jsonl` | evaluation set |
| `specs/` | contract and known evasions |
