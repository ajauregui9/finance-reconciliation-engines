-- @descripcion: UUIDs de CFDI con más de una transacción de proveedor contabilizada.
--
-- Agrupa por el UUID guardado en la cabecera (custbody_mx_cfdi_uuid), no por el folio:
-- dos proveedores extranjeros distintos pueden repetir serie y folio.
SELECT
    t.custbody_mx_cfdi_uuid AS uuid,
    MIN(t.tranid) AS referencia,
    COUNT(*) AS num_registros,
    MIN(t.id) AS primera_transaccion,
    MAX(t.id) AS ultima_transaccion
FROM transaction t
WHERE t.posting = 'T'
    AND t.type IN ('VendBill', 'VendCred')
    AND t.custbody_mx_cfdi_uuid IS NOT NULL
GROUP BY t.custbody_mx_cfdi_uuid
HAVING COUNT(*) > 1
ORDER BY t.custbody_mx_cfdi_uuid
