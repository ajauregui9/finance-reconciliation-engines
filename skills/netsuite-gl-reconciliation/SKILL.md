---
name: netsuite-gl-reconciliation
description: CFDI to general-ledger reconciliation with SuiteQL queries over a synthetic NetSuite-like SQLite schema, plus validated CSV import files. SuiteQL via MCP connector + CSV import; no REST/SuiteScript.
---

# NetSuite GL Reconciliation (SuiteQL + CSV import)

## When to use
- Check that every received CFDI is posted in the general ledger, with the right amount, once,
  and in the right period.
- Get balances by posting period, account and class.
- Prepare a CSV import file (journal or vendor bill) that has passed validation first.

## Scope
SuiteQL via MCP connector + CSV import; no REST/SuiteScript. Do not add a REST, OAuth or
SuiteScript client (ADR 0002). The CSV file is for human review; never upload it or write
to the ERP without a person deciding to do so.

## Steps
1. Run the queries: `python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py consultar --salida <dir>`.
2. Read `cfdi_sin_registro`, `cuadre_cfdi_gl`, `duplicados_registro` and `periodo_equivocado`;
   compare against `discrepancias_plantadas.json` when working with the synthetic data.
3. For missing invoices, draft vendor bills:
   `run_netsuite_gl.py generar-csv --desde-sin-registro --salida bills.csv`. Credit notes are
   reported as pending.
4. For adjustments, write a JSON file of entries and run
   `run_netsuite_gl.py generar-csv --asientos <file> --formato journal --salida je.csv`.
5. If the file is rejected (exit code 3), fix every listed error and run again. A rejected
   file is never partially written.

## Rules
- Queries live in `queries/*.sql`, written in SuiteQL. Only the compatibility layer
  (`netsuite_gl/compat.py`) adapts them to SQLite; never fork a query into a SQLite-only copy.
- Amounts are `Decimal`. The synthetic database stores them as integer cents, so monetary result
  columns must be listed in the query header (`-- @montos:`); an unlisted one would come out in
  cents. Do not write decimal literals or divisions in a query: the compatibility layer rejects
  them because their result would depend on that scale.
- When calling the package from code, open the database in a `with` block around
  `construir_base`, so the SQLite connection is closed even when something fails.
- See `SPEC.md` for the full contract and `README.md` for the overview.
