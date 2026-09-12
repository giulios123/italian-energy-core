# ADR 0010 — Composizione e matrice di copertura del Billing v0.6

## Stato

Accettato e concretizzato dalla Spec 006

## Decisione

Lo snapshot ARERA 2026 viene acquisito con `fetch_and_import(year=2026)` e
accettato soltanto se `VERIFIED`, completo dei due segmenti e dei nove mesi
contigui. Il digest `b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`
è congelato negli artefatti JSON; il raw XLSX resta fuori dal repository.

`AreraDomesticRuleSetComposer` produce due ruleset distinti. Le sole componenti
eseguibili sono i totali `network_total` e `system_total`; gli atomici sono
conservati come evidenza di controllo e `CDISPD` resta commerciale. Ogni mese ha
regole proprie per preservare l'ordine di arrotondamento. La fiscalità usa solo
provenance versionata ADM/Gazzetta Ufficiale/Normattiva.

La proratazione annuale segue `MONTHLY_TWELFTHS_PARTIAL_365`: dodicesimi con
rounding commerciale del tasso mensile per mesi interi, giorni/365 per segmenti
parziali e successivo rounding monetario. Le fasce di potenza sono esplicite e
non sovrapposte. `BillingCoverageMatrix` rifiuta gap e overlap e `resolve()`
restituisce il minimo livello delle voci attraversate.

## Conseguenze

Il package base può caricare ruleset e matrice JSON senza l'extra XLSX. Il
Billing Engine mantiene la possibilità di ricevere ruleset custom verificati;
la futura Spec 007 dovrà consultare obbligatoriamente la matrice. Una voce
`golden_reconciled` resta limitata all'intervallo del golden effettivamente
riconciliato e non amplia la copertura normativa.
