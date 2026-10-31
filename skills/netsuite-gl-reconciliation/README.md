# NetSuite GL reconciliation: CFDI ↔ general ledger with SuiteQL

**Scope: SuiteQL via MCP connector + CSV import; no REST/SuiteScript.**

This module shows the part of the NetSuite work that runs without a live account: SuiteQL
queries run through an MCP connector, plus loads through CSV import (see
[ADR 0002](../../docs/adr/0002-netsuite-scope-suiteql-only.md)). The author also built a
RESTlet with token-based authentication; it is not reproduced here because it needs a live
account to deploy and test, and a REST client against a mock would only test the mock. This
module has no REST client, OAuth/TBA, RESTlet or SuiteScript.

The queries are plain SuiteQL. Here they run against an in-memory SQLite database that mimics
the SuiteQL tables, filled deterministically from the synthetic CFDIs in `examples/synthetic/`. A small,
documented compatibility layer translates the few SuiteQL constructs that SQLite lacks.

Standard library only (`sqlite3`, `csv`, `json`, `decimal`). All amounts are `Decimal`; in the
synthetic database they are stored as integer cents, so every SQL sum is exact integer arithmetic.

## Quick start

```bash
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py consultar                  # all queries to stdout
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py consultar --salida out/    # one CSV per query + manifest
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py consultar --consulta cuadre_cfdi_gl
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py discrepancias              # planted-discrepancy manifest
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py traducir saldos_cuenta_periodo_clase
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py generar-csv --desde-sin-registro --salida bills.csv
python3 skills/netsuite-gl-reconciliation/run_netsuite_gl.py generar-csv \
    --asientos skills/netsuite-gl-reconciliation/ejemplos/asientos_journal.json --formato journal --salida je.csv
```

Every command accepts `--cfdis PATH` (default `examples/synthetic/cfdis.jsonl`, read only).
Exit codes: `0` success, `2` invalid input or arguments, `3` load file rejected (errors on
stderr, no file written).

## Layout

| Path | Content |
|---|---|
| `SPEC.md` | Full specification (Spanish) |
| `queries/*.sql` | The five SuiteQL queries, each with a `-- @descripcion` / `-- @montos` header |
| `netsuite_gl/cfdis.py` | Reads and validates `cfdis.jsonl`; splits the universe from excluded records |
| `netsuite_gl/montos.py`, `fechas.py` | The single `Decimal` boundary (to and from integer cents) and strict `YYYY-MM-DD` dates |
| `netsuite_gl/esquema.py`, `periodos.py`, `filas.py`, `poblado.py` | Schema DDL and deterministic population |
| `netsuite_gl/discrepancias.py` | Hash-based choice of planted discrepancies and the manifest model |
| `netsuite_gl/compat.py` | SuiteQL → SQLite compatibility layer |
| `netsuite_gl/consultas.py` | Loads, translates and runs the `.sql` files |
| `netsuite_gl/carga_*.py`, `propuestas.py` | Load-file model, validation, CSV rendering, proposals |
| `netsuite_gl/cli.py`, `run_netsuite_gl.py` | Command line |
| `ejemplos/asientos_journal.json` | Valid journal input example |

## Synthetic schema

Table and column names follow SuiteQL. Booleans are `'T'`/`'F'`, dates are ISO text, and
`transactionline.id` is only unique inside its transaction. Amounts (`debit`, `credit`,
`amount` and the custom record's amounts) are integer cents in `INTEGER` columns with a type
check; NetSuite stores them as decimals, and the compatibility layer below explains why the
queries do not change. Anything other than a Python integer is rejected before it is inserted.

The database is in memory and is meant to be opened in a `with` block: `construir_base`
returns an object whose exit closes the connection, also on error. Every CLI command opens it
that way.

| Table | Columns |
|---|---|
| `account` | `id, acctnumber, fullname, accttype, isinactive` |
| `accountingperiod` | `id, periodname, startdate, enddate, isposting, isquarter, isyear, closed` |
| `classification` | `id, name, fullname, isinactive` |
| `vendor` | `id, entityid, companyname, custentity_mx_rfc, isinactive` |
| `transaction` | `id, tranid, trandate, type, postingperiod, entity, memo, posting, custbody_mx_cfdi_uuid` |
| `transactionline` | `transaction, id, linesequencenumber, mainline, taxline, class, entity, memo` |
| `transactionaccountingline` | `transaction, transactionline, account, debit, credit, amount, posting` |
| `customrecord_cfdi_recibido` | received CFDIs (uuid, date, type, issuer, series/folio, concept, MXN amounts) |

`customrecord_cfdi_recibido` is not a standard NetSuite table. It is a custom record in this
design: in a real account it would be filled by CSV import from the received-CFDI download,
which lets the whole CFDI ↔ GL match run as SuiteQL.

Population: one vendor per (RFC, name); one `VendBill` per invoice and one `VendCred` per credit
note, with an AP main line, an expense line and a VAT line. Every transaction balances. Payroll
CFDIs and CFDIs issued to someone else are excluded and counted by reason in the manifest.

## Planted discrepancies

Each CFDI gets the key `sha256("<seed>:<uuid>")`. CFDIs are sorted by that key and consecutive
blocks get one discrepancy each (no CFDI gets two). Sizes and deltas are example values in
`netsuite_gl/config.py`.

| Discrepancy | Default count | What is planted | Found by |
|---|---|---|---|
| `sin_registro` | 6 | CFDI in the custom record, no transaction | `cfdi_sin_registro` |
| `monto_distinto` | 6 | Expense and AP booked with an extra delta (100.00, -10.00, 25.00 in turn) | `cuadre_cfdi_gl` |
| `duplicado` | 4 | A second identical transaction with the same UUID | `duplicados_registro`, `cuadre_cfdi_gl` |
| `periodo_equivocado` | 4 | Posted to the following month; the date is unchanged | `periodo_equivocado` |

`discrepancias_plantadas.json` lists every planted item with its expected result. The tests
require each query to return exactly that set: nothing missing, nothing extra.

## Queries

| Query | Returns |
|---|---|
| `saldos_cuenta_periodo_clase` | Debit, credit and balance by posting period, account and class |
| `cfdi_sin_registro` | CFDIs with no posted vendor transaction carrying their UUID |
| `cuadre_cfdi_gl` | Registered CFDIs whose AP net (credit − debit) differs from the signed CFDI total |
| `duplicados_registro` | UUIDs with more than one posted vendor transaction |
| `periodo_equivocado` | Vendor transactions whose posting period does not contain the CFDI date |

## Compatibility layer

`compat.traducir` splits the text into code, `'…'` literals and `"…"` identifiers, drops
comments, and translates code only:

| SuiteQL | SQLite |
|---|---|
| `BUILTIN.DF(x.account)` | scalar subquery: `acctnumber || ' ' || fullname` |
| `BUILTIN.DF(x.class)` | scalar subquery: `classification.fullname` |
| `BUILTIN.DF(x.postingperiod)` | scalar subquery: `accountingperiod.periodname` |
| `BUILTIN.DF(x.entity)` | scalar subquery: `entityid || ' ' || companyname` |
| `BUILTIN.DF(x.type)` | `CASE` with display names (`Bill`, `Bill Credit`, `Journal`) |
| `NVL(a, b)` | `COALESCE(a, b)` |
| `ROUND(x, n)` | `ROUND_CENTAVOS(x, n)`, a function registered on the connection |
| `transaction` (table or column) | `"transaction"` (reserved word in SQLite) |

Any other `BUILTIN.*`, a `BUILTIN.DF` on an unmapped field, or an unclosed literal or comment
raises `ErrorCompatibilidad`. `compat.quitar_comentarios` gives the text that would be sent
through the MCP connector.

**Amounts: decimals in SuiteQL, integer cents in SQLite.** SQLite has no exact decimal type: a
`NUMERIC` column stores `100000000000000.01` as the binary float `100000000000000.02`, and `SUM`
runs in floating point. Storing integer cents makes every sum exact. Adding, subtracting,
negating, `CASE`, `NVL` and comparing against `0` give the same answer in pesos and in cents,
so the SuiteQL text stays as it would be in NetSuite; the scale comes back once, when results
are read. What does depend on the scale is handled explicitly:

| Construct | Treatment |
|---|---|
| `ROUND(x, n)` with `n >= 2` | `ROUND_CENTAVOS` returns the same integer (rounding cents to two or more decimals changes nothing) |
| `ROUND(x, n)` with `n < 2`, or on a float or text | `ROUND_CENTAVOS` fails when the query runs |
| a decimal literal (`> 100.00`) | rejected when translating: it would compare pesos against cents |
| division `/` | rejected when translating: SQLite truncates integer division |
| `AVG`, `CAST(… AS REAL)` | they produce a float, which the read boundary rejects |

Known limit: an integer literal compared against an amount (`debit > 100`) would be read as
cents, and the layer cannot tell it from a count. The queries here only compare amounts with `0`.

## CSV load files

Input is a list of entries (JSON `{"asientos": [...]}`, amounts as strings) or the automatic
proposal: one vendor bill per invoice from `cfdi_sin_registro` (credit notes are listed as
pending, never dropped). Before anything is written, every entry is checked and all errors
are collected. One error rejects the whole file.

Checks: at least two lines; amounts non-negative with at most two decimals and exactly one
side per line; debits = credits per entry; the account exists and is active; the period
exists, is a posting period, is open and contains the date; class and vendor exist and are
active; AP lines carry a vendor; text fields cannot start with `=`, `+`, `-` or `@`
(spreadsheet formula injection). Vendor bills also need a reference and exactly one AP line
on the credit side.

Formats: `journal` (one row per line) and `vendor_bill` (one row per expense or VAT line; the
AP line becomes the `Vendor` column). UTF-8, LF, dates `DD/MM/YYYY`, accounts as
`number name`. The file is for human review; this module never uploads it.

## Determinism

No timestamps and no global randomness. JSON uses sorted keys; CSV uses LF. Two runs with the
same input give byte-identical files (the tests compare SHA-256).

## Limitations

- The queries were written for this synthetic schema and are checked against SQLite here, not
  against a live account. Field names follow SuiteQL, but a real account may need adjustments
  (for example, a different custom record or CFDI UUID field from a localization bundle).
- Amounts are integer cents in SQLite, not decimals as in NetSuite. The compatibility layer keeps
  the SuiteQL text unchanged and rejects the constructs whose result would depend on that scale
  (see above); results are converted once from cents to `Decimal`, and a float in any result
  column is an error, so no float touches money.
- Single currency (MXN) and a single accounting book. USD CFDIs are booked at their MXN total.
- The CSV date format must match the importing user's date preference.

## Tests

```bash
python3 -m pytest tests/test_netsuite_*.py -q
```
