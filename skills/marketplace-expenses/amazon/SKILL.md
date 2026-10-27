---
name: amazon-month-end-close
description: Accrual month-end close of Amazon settlement files with Decimal money, tail cohort, single-count advertising and a platform withholding band check.
---

# Amazon month-end close

## When to use

You have one or more monthly settlement files from an Amazon seller account and need the
accrued marketplace expense of each month: fees for the month's own orders, a provision for
revenue not yet settled, the reversal of last month's provision, period charges and
advertising, plus a check of the platform withholding.

## How to run

After `python3 -m pip install -e .` at the repository root:

```bash
python3 -m cierre_amazon \
    --datos <directory> [--config <config.json>] [--salida cierre.json] [--xlsx cierre.xlsx] \
    [--mes AAAA-MM] [--fuente-publicidad liquidacion|consola|factura]
```

The data directory must hold `liquidacion_AAAA-MM.csv` files and may hold
`publicidad_consola.csv`, `facturas_publicidad.json` and `venta_erp.json`. Start from
`config/cierre.example.json`; its values are round examples.

## What you get

- A deterministic JSON document (`cierre_amazon/v1`) with, per month: settled totals by
  group, effective rates, pending revenue, provision, accrued expense lines, advertising by
  source, withholding result, alerts and candados.
- Optionally a workbook with numeric amounts, re-read and verified after writing.
- Exit code `0` (complete, alerts allowed), `1` (a candado failed) or `2` (invalid input).

## Rules it enforces

1. The month of each row comes from the time zone the file declares, converted to the
   closing zone.
2. Effective fee rates use only the month's own orders; the tail cohort is reported apart.
3. Advertising enters the expense once, from the configured authoritative source.
4. Withholding base: order rows settled in the month; base = product sales + promotional
   discounts before VAT; alert when `|withheld / base - rate| > band`.
5. Nothing is dropped: unknown row types are reported and fail a candado.

See `specs/cierre_amazon.md` for the full behavior.
