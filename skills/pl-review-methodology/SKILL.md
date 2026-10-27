---
name: pl-review-methodology
description: Deterministic pre-close review of a monthly P&L export - month maturity blockers, ratio corridors, brand advertising and month-over-month materiality.
---

# Pre-close P&L review

Use this skill when a monthly income statement export has to be reviewed before
the period is closed.

## Steps

1. Get the export in `exportacion_pl/v1` format (see `README.md`) and decide
   which period is being reviewed. The period is always explicit; there is no
   default.
2. Run the reviewer from the repository root:

   ```bash
   python3 skills/pl-review-methodology/scripts/run_pl_audit.py \
     --periodo <YYYY-MM> \
     --config skills/pl-review-methodology/config/parametros.example.json \
     --entrada <export.json> \
     --salida <report.json>
   ```

3. Read the exit code first. `3` means the report is provisional: resolve the
   items in `bloqueos` (immature month, payroll or provision missing, account
   with no P&L group, advertising split that does not add up) before reading
   anything else. `2` means the inputs were rejected; the message on stderr
   names the offending field.
4. Then review `bandas` (both `fuera_desfavorable` and `fuera_favorable`),
   `publicidad.alertas` and `variaciones.materiales`. Mentions are context,
   not findings.
5. Explain each material variance with evidence from the ledger. The reviewer
   only compares against the previous month, so seasonal effects must be
   explained by a person.

## Rules of use

- Do not edit thresholds to make a result go away; change the config only with
  a documented reason.
- Do not add keys to the config: the reader rejects any key it does not use.
