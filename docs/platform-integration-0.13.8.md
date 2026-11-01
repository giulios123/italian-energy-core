# Integrazione Platform — Core 0.13.8 (nota per adozione separata)

Questa nota descrive il contratto Core 0.13.8. La Platform non è stata
modificata e non ha ancora adottato la wheel.

## Contratto Core

Il `contract_version` resta `1`; la capability nuova è
`gme_monthly_publication_lag`. Gli schema ID aggiunti sono:

- `italian-energy/projected-source-bundle/v2`
- `italian-energy/projected-source-preflight-result/v2`
- `italian-energy/projected-domestic-preflight-result/v3`
- `italian-energy/projected-domestic-comparison-result/v3`
- `italian-energy/projected-domestic-recommendation-request/v3`

Il risultato v3 include `verified_inputs.market_selection`, una selezione
tipizzata con `comparison_as_of`, `expected_latest_period`,
`historical_market_period`, `reference_period`,
`reference_value_eur_per_kwh`, `reference_provenance`,
`publication_lag_months` (`0` o `1`), `publication_status` e
`publication_evidence` quando il mese atteso è incompleto. I campi della prova
sono `expected_period`, `pdf_url`, `pdf_http_status`, `archive_url`,
`archive_http_status`, `archive_sha256`, `pdf_checked_at`, `retrieved_at`,
`coverage_start`, `coverage_end`, `workbook_name` e `locator`; i dati archivio
non disponibili restano null e non attestano copertura. La selezione lega
inoltre il riferimento alle dodici osservazioni GME verificate. Il risultato
già espone separatamente `as_of`, periodo dei
consumi `assumptions.historical_consumption_period`, periodo GME
`assumptions.historical_market_period` e riferimento
`assumptions.market_reference_period`/`market_reference_value_eur_per_kwh`.

L'archivio fonte v2 conserva la selezione insieme a `market_history`; i nuovi
risultati la includono nel digest. Il confronto e i preflight restano offline:
la Platform deve passare snapshot ed evidenza congelati dopo l'acquisizione Core.
I lettori dei payload storici continuano ad accettare i vecchi envelope, senza
riscrittura o ricalcolo.

## Aggiornamento richiesto in Platform

In `application/comparison.py::_public_market_reference`, rimuovere il
presupposto che `market_reference_period` coincida sempre con il mese
immediatamente precedente. Validare invece che:

1. `market_selection.comparison_as_of` corrisponda alla data del confronto e
   `expected_latest_period` sia il mese civile immediatamente precedente;
2. `publication_lag_months` sia `0` o `1` e corrisponda alla differenza tra
   mese atteso e `reference_period`;
3. con ritardo `0`, lo stato sia completo e non ci sia una prova di ritardo;
   con ritardo `1`, lo stato sia incompleto e la prova Core sia presente;
4. periodo, valore e provenance del riferimento concordino con assunzioni,
   selezione e ultima delle dodici osservazioni GME verificate; la finestra sia
   consecutiva, ufficiale e terminata nel `reference_period`;
5. il periodo dei consumi continui a essere validato secondo `as_of`, senza
   imporre che coincida con il periodo storico GME.

Il controllo Platform deve fidarsi dei campi Core soltanto dopo la validazione
del contratto tipizzato e della provenance, non inferire il ritardo dal mese
del server. `market_reference_period` resta la fonte del mese PUN da mostrare;
per un confronto del 1° novembre può essere settembre se ottobre è ancora
incompleto e tutte le prove Core sono valide. Un mese di ritardo ulteriore o
metadati incoerenti devono restare bloccanti.

L'adozione della wheel richiede una decisione Platform separata: aggiornare
pin, digest e reader degli schema ID, implementare questo controllo, quindi
eseguire i gate e la verifica economica Platform. Nessuna parte di questi
passaggi è stata eseguita in questo task.
