-- @descripcion: CFDIs recibidos sin ninguna transacción de proveedor contabilizada con su UUID.
-- @montos: subtotal, iva, total
--
-- Una transacción con posting = 'F' (por ejemplo, pendiente de aprobación) no cuenta como
-- registro: el CFDI sigue sin reflejarse en el libro mayor.
SELECT
    c.custrecord_cfdi_uuid AS uuid,
    c.custrecord_cfdi_fecha AS fecha,
    c.custrecord_cfdi_tipo AS tipo,
    c.custrecord_cfdi_serie || '-' || c.custrecord_cfdi_folio AS referencia,
    c.custrecord_cfdi_rfc_emisor AS rfc_emisor,
    c.custrecord_cfdi_nombre_emisor AS emisor,
    c.custrecord_cfdi_concepto AS concepto,
    c.custrecord_cfdi_subtotal AS subtotal,
    c.custrecord_cfdi_iva AS iva,
    c.custrecord_cfdi_total AS total
FROM customrecord_cfdi_recibido c
WHERE NOT EXISTS (
    SELECT 1
    FROM transaction t
    WHERE t.custbody_mx_cfdi_uuid = c.custrecord_cfdi_uuid
        AND t.posting = 'T'
        AND t.type IN ('VendBill', 'VendCred')
)
ORDER BY c.custrecord_cfdi_uuid
