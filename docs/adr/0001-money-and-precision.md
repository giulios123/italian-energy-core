# ADR 0001 — Money e precisione

## Stato

Accettato

## Decisione

Usare `Decimal` per importi, quantità e coefficienti economici. Rifiutare float, NaN e infinito. L’arrotondamento è esplicito tramite `RoundingPolicy` e non viene eseguito implicitamente nei value object.

## Conseguenze

I risultati sono riproducibili e gli errori binari dei float non entrano nel dominio. Le regole di arrotondamento di bolletta restano da definire nelle spec di pricing/billing.
