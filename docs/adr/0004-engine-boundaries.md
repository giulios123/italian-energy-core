# ADR 0004 — Confini dei motori

## Stato

Accettato

## Decisione

Pricing determina costi, Billing ricostruisce bollette, Comparison confronta risultati e Recommendation interpreta preferenze/rischio. Ogni confine usa request/result immutabili e protocolli distinti.

## Conseguenze

Una recommendation non può correggere o alterare il costo calcolato. Gli adapter applicativi restano esterni al core.
