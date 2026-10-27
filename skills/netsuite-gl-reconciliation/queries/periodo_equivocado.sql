-- @descripcion: Transacciones de proveedor cuyo periodo contable no contiene la fecha del CFDI.
--
-- periodo_esperado es el periodo de registro que contiene la fecha del CFDI; queda vacío si
-- ese periodo no existe en el catálogo.
SELECT
    c.custrecord_cfdi_uuid AS uuid,
    t.id AS transaccion,
    t.tranid AS referencia,
    BUILTIN.DF(t.type) AS tipo_transaccion,
    BUILTIN.DF(t.entity) AS proveedor,
    c.custrecord_cfdi_fecha AS fecha_cfdi,
    BUILTIN.DF(t.postingperiod) AS periodo_registrado,
    (
        SELECT p.periodname
        FROM accountingperiod p
        WHERE p.isposting = 'T'
            AND c.custrecord_cfdi_fecha BETWEEN p.startdate AND p.enddate
    ) AS periodo_esperado
FROM transaction t
    INNER JOIN customrecord_cfdi_recibido c ON c.custrecord_cfdi_uuid = t.custbody_mx_cfdi_uuid
    INNER JOIN accountingperiod ap ON ap.id = t.postingperiod
WHERE t.posting = 'T'
    AND t.type IN ('VendBill', 'VendCred')
    AND c.custrecord_cfdi_fecha NOT BETWEEN ap.startdate AND ap.enddate
ORDER BY c.custrecord_cfdi_uuid, t.id
