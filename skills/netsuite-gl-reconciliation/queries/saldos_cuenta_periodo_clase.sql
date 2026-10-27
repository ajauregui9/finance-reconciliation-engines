-- @descripcion: Saldos del libro mayor por periodo de registro, cuenta y clase.
-- @montos: debito, credito, saldo
--
-- Solo cuenta líneas contabilizadas de transacciones contabilizadas, y solo periodos de
-- registro: el anual y los trimestres son de resumen y duplicarían los montos.
-- saldo = debito - credito (positivo = saldo deudor).
SELECT
    BUILTIN.DF(t.postingperiod) AS periodo,
    BUILTIN.DF(tal.account) AS cuenta,
    BUILTIN.DF(tl.class) AS clase,
    ROUND(SUM(NVL(tal.debit, 0)), 2) AS debito,
    ROUND(SUM(NVL(tal.credit, 0)), 2) AS credito,
    ROUND(SUM(NVL(tal.debit, 0)) - SUM(NVL(tal.credit, 0)), 2) AS saldo
FROM transactionaccountingline tal
    INNER JOIN transaction t ON t.id = tal.transaction
    INNER JOIN transactionline tl
        ON tl.transaction = tal.transaction AND tl.id = tal.transactionline
    INNER JOIN accountingperiod ap ON ap.id = t.postingperiod
    INNER JOIN account a ON a.id = tal.account
WHERE t.posting = 'T'
    AND tal.posting = 'T'
    AND ap.isposting = 'T'
GROUP BY ap.startdate, t.postingperiod, a.acctnumber, tal.account, tl.class
ORDER BY ap.startdate, a.acctnumber, clase
