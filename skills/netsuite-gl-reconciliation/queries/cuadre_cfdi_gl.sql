-- @descripcion: Cuadre CFDI contra libro mayor: CFDIs registrados cuyo neto en proveedores difiere del total firmado.
-- @montos: total_cfdi, total_gl, diferencia
--
-- Lado CFDI: el total en MXN, negativo si es nota de crédito (tipo E).
-- Lado GL: credit - debit en cuentas de proveedores (AcctPay), sumando todas las
-- transacciones contabilizadas con el mismo UUID. Un registro duplicado aparece aquí con
-- la diferencia igual al total del CFDI y num_transacciones = 2.
SELECT
    cf.uuid,
    cf.emisor,
    cf.total_cfdi,
    gl.total_gl,
    ROUND(gl.total_gl - cf.total_cfdi, 2) AS diferencia,
    gl.num_transacciones
FROM (
    SELECT
        c.custrecord_cfdi_uuid AS uuid,
        c.custrecord_cfdi_nombre_emisor AS emisor,
        CASE WHEN c.custrecord_cfdi_tipo = 'E'
            THEN -c.custrecord_cfdi_total
            ELSE c.custrecord_cfdi_total
        END AS total_cfdi
    FROM customrecord_cfdi_recibido c
) cf
INNER JOIN (
    SELECT
        t.custbody_mx_cfdi_uuid AS uuid,
        COUNT(DISTINCT t.id) AS num_transacciones,
        ROUND(SUM(NVL(tal.credit, 0) - NVL(tal.debit, 0)), 2) AS total_gl
    FROM transaction t
        INNER JOIN transactionaccountingline tal ON tal.transaction = t.id
        INNER JOIN account a ON a.id = tal.account
    WHERE t.posting = 'T'
        AND tal.posting = 'T'
        AND t.type IN ('VendBill', 'VendCred')
        AND a.accttype = 'AcctPay'
    GROUP BY t.custbody_mx_cfdi_uuid
) gl ON gl.uuid = cf.uuid
WHERE ROUND(gl.total_gl - cf.total_cfdi, 2) <> 0
ORDER BY cf.uuid
