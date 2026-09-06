# ADR 0008 — Riconciliazione della bolletta

## Stato

Accettato

## Decisione

La `Bill` calcolata e l'oracle osservato sono modelli distinti. `BillingResult`
contiene una riconciliazione per chiave esplicita; la tolleranza è `0,01 EUR` per
voce e per totale. Una differenza non altera la Bill calcolata.

## Conseguenze

Le bollette reali possono restare private e non devono essere forzate nel modello
normativo. Gli scarti sono auditabili e non vengono compensati con matching fuzzy.
