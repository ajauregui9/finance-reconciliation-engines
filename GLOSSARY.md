# Conciliación y cierre financiero

Vocabulario de los procesos de conciliación tarjeta ↔ CFDI ↔ libro mayor, cierre de marketplaces y flujo de efectivo que este repo recrea con datos sintéticos.

## Conciliación de tarjetas

**Cargo**:
Un movimiento individual de un estado de cuenta de tarjeta corporativa.
_Avoid_: transacción, movimiento, charge

**Universo de cargos**:
El conjunto completo y normalizado de cargos de un periodo: el lado izquierdo de todo cruce.
_Avoid_: base, dataset

**Cruce**:
La asignación exclusiva de un cargo a uno o más CFDIs o a un registro del libro mayor.
_Avoid_: match, conciliación (para la asignación individual)

**Tier**:
El nivel de confianza de un cruce, según qué evidencia coincide (monto exacto, monto con tolerancia, suma de varios CFDIs).
_Avoid_: score, nivel

**Ventana de fechas**:
El rango asimétrico alrededor de la fecha del cargo dentro del cual un CFDI es candidato.

**RFC genérico**:
Un RFC que no identifica a un contribuyente concreto (público en general, extranjero) y por eso no sirve como evidencia de cruce.

**Proveedor-cubeta**:
Un proveedor del ERP que agrupa gastos de muchos comercios distintos, por lo que su nombre no prueba la identidad del comercio.

**Veredicto humano**:
La categoría que una persona asignó a un cargo; el motor la toma como insumo y nunca la sobrescribe.
_Avoid_: override, corrección manual

**Universo parcial**:
Un periodo cuyos insumos están incompletos; sus resultados se marcan como provisionales.

**Candado**:
Una verificación de integridad cuya falla detiene la corrida con un código de salida distinto de cero.
_Avoid_: check, validación (cuando la falla es bloqueante)

## Cierre de marketplaces

**Devengo**:
El reconocimiento de una venta o un gasto en el periodo en que ocurre, aunque todavía no se liquide.

**Liquidación**:
El pago que el marketplace deposita y que neta ventas, comisiones, publicidad y retenciones.
_Avoid_: settlement, payout

**Cohorte cola**:
Las operaciones de un periodo que el marketplace liquida en el periodo siguiente.

**Retención de plataforma**:
El IVA o ISR que el marketplace retiene al vendedor por ley y que aparece en la liquidación.

## Flujo de efectivo

**Fila contrato**:
La unidad común en que cada fuente de ingreso o egreso se traduce antes de ensamblar el flujo.

**Curva de cobranza**:
La distribución esperada, por semana, de cuándo se cobra una cuenta por cobrar según su antigüedad.
