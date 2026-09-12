# Spec 010 — Contratto d’integrazione Core–Platform v0.10.0

## Stato

Specifica normativa v0.10.0. L’implementazione locale è autorizzata dal
milestone corrente; commit, tag, push e release restano operazioni separate.

## Contesto

Le Spec 001–009 forniscono modelli immutabili, Pricing, Billing, acquisizione
ARERA e Portale Offerte, confronto all-in e Recommendation. La Platform ha
bisogno di un contratto pubblico stabile per consumare queste capacità senza
conoscere la composizione dei ruleset, la matrice di copertura o le formule.

Il package e il modulo canonici sono quelli già pubblicati nel Core:
`italian-energy` e `italian_energy`. I placeholder `italian-energy-core` e
`italian_energy_core` non fanno parte di questo contratto.

## Obiettivo

Congelare una superficie Python tipizzata e una serializzazione JSON versionata
per la Platform, mantenendo il Core indipendente da web framework, database,
cloud SDK, AI e trasporto HTTP.

## Perimetro

### Incluso

- manifest runtime di versione, contratto, capability e schema ID;
- package pubblico `italian_energy.integration`;
- façade sincrona per replay storici domestici BT elettrici;
- selezione interna dei ruleset e della matrice packaged verificati;
- façade separata per interpretare un confronto già calcolato;
- envelope JSON canonici per gli aggregati necessari alla Platform;
- errori tipizzati con codici stabili e messaggi privi di dati sensibili;
- `defusedxml` come dipendenza base per il percorso Portale;
- fixture contrattuali sintetiche e verifiche da wheel.

### Escluso

- modifiche al repository Platform;
- REST API, persistenza, scheduler, worker, cloud e frontend;
- confronto corrente o futuro, forecast o stime di mercato;
- nuove formule economiche o modifiche semantiche alle Spec 001–009;
- gas, nuovi anni/formati del Portale e OCR/PDF;
- migrazioni automatiche di payload JSON;
- commit, tag, push, release GitHub o pubblicazione PyPI.

## Identità e manifest

Il manifest espone:

- `CORE_CONTRACT_VERSION = "1"`;
- `distribution = "italian-energy"`;
- `import_package = "italian_energy"`;
- versione installata del package;
- capability ordinate e realmente disponibili;
- schema ID supportati.

`CORE_CAPABILITIES` è una tupla immutabile di stringhe derivata dal manifest e
contiene esclusivamente:

`capability_manifest`, `canonical_models`, `canonical_serialization`,
`fixed_pricing`, `indexed_pricing`, `regulatory_billing`, `billing_coverage`,
`comparison`, `portal_offers_import`, `historical_portal_comparison`,
`deterministic_recommendation`.

`CORE_SCHEMA_IDS` espone nello stesso ordine deterministico gli schema ID
registrati dal manifest per la discovery senza importare i modelli.

Non vengono dichiarate capability di confronto corrente, forecast o costo
futuro. La capability ARERA XLSX resta subordinata all’extra `arera` e non è
necessaria alla façade Platform, che usa i ruleset JSON packaged.

## API d’integrazione

Il modulo `italian_energy.integration` è la superficie stabile. Le API di
Pricing, Billing, Comparison, Portale e Recommendation esistenti restano
disponibili per consumer avanzati e non vengono rimosse.
La superficie integration riesporta anche i nove aggregati registrati per
consentire alla Platform di usare modelli e serializer senza conoscere i moduli
interni.

### Richiesta di confronto storico

`HistoricalPortalComparisonRequest` contiene:

- `current_contract`;
- `consumption`;
- `period`;
- `classification`;
- `eligibility`;
- `supplemental_market_data` verificato opzionale;
- `measurements` billing verificate opzionali;
- `external_items` verificati opzionali.

La richiesta deve rappresentare elettricità domestica BT. La residenza deve
essere esplicita e coerente tra classificazione e fornitura.

`HistoricalDomesticEnergyService.compare()`:

1. rifiuta un periodo non concluso prima del download;
2. deriva `as_of` da `period.start`;
3. seleziona il ruleset residente/non residente dal profilo esplicito;
4. carica e verifica la matrice packaged;
5. usa entrambi i cataloghi Mercato Libero e PLACET;
6. applica EUR e percentuali a due decimali con `ROUND_HALF_UP`;
7. invoca il servizio Portale esistente e restituisce `PortalComparisonResult`.

Il servizio resta limitato a replay storici conclusi. Un confronto di offerte
attuali su un periodo futuro richiede una specifica economica separata.

### Raccomandazione

`HistoricalRecommendationRequest` contiene un `PortalComparisonResult` già
calcolato e `RecommendationPreferences`.

`HistoricalDomesticEnergyService.recommend()` usa l’adapter e il motore
Recommendation senza trasporto, download, Pricing, Billing o Comparison.
Confronto e raccomandazione sono due operazioni indipendenti.

## Serializzazione

Gli aggregati supportati usano l’envelope:

```json
{
  "contract_version": "1",
  "schema_id": "italian-energy/contract/v1",
  "payload": {}
}
```

`dump_envelope()` produce UTF-8 canonico con chiavi ordinate e separatori
compatti. `load_envelope()` valida contratto, schema e payload prima di
restituire il tipo canonico.

Decimal è serializzato come stringa, enum come valore, date e timestamp in
ISO-8601. Campi extra, float economici, JSON corrotto, schema sconosciuto e
versione sconosciuta sono rifiutati. La v1 non effettua migrazioni automatiche.

Gli schema ID v1 sono definiti per:

- `SupplyPoint`;
- `Contract`;
- `ConsumptionProfile`;
- `VerifiedMarketData`;
- `HistoricalPortalComparisonRequest`;
- `PortalComparisonResult`;
- `RecommendationPreferences`;
- `HistoricalRecommendationRequest`;
- `Recommendation`.

I bytes grezzi dei file Portale restano esclusi dal payload serializzato.

## Errori

`CoreContractError` espone `CoreErrorCode` con i valori:

`invalid_envelope`, `unsupported_contract_version`, `unsupported_schema`,
`invalid_payload`, `unsupported_scenario`, `unsupported_horizon`,
`coverage_unavailable`, `source_acquisition_failed`,
`source_validation_failed`, `comparison_failed`, `recommendation_failed`.

Il codice è stabile; il dettaglio è deterministico, non contiene payload, dati
personali o URL sorgente e non sostituisce il chaining dell’eccezione interna.

## Acceptance criteria

- Il package installato espone identità, versione e manifest coerenti.
- Capability e schema ID sono ordinati, immutabili e privi di capability future.
- La façade residente e non residente seleziona automaticamente gli artefatti
  corretti e fallisce chiusa su periodo futuro o copertura assente.
- La recommendation non ripete il confronto e non modifica il risultato.
- Tutti gli aggregati registrati hanno round-trip JSON e bytes canonici stabili.
- Versioni, schema, campi extra, float economici e payload invalidi producono
  errori tipizzati.
- La wheel base esegue il percorso Portale con `defusedxml`; l’extra `arera`
  abilita l’importer XLSX senza rendere `openpyxl` obbligatorio nel base.
- La suite precedente resta verde con branch coverage almeno 95%.
- Ruff, format-check, mypy strict, pre-commit, build, smoke install,
  verificatori esistenti e `git diff --check` passano.
- Memory Bank e documentazione registrano v0.10.0 locale non pubblicata.

## Test richiesti

- manifest, metadata wheel, import pubblici e capability;
- envelope per tutti gli aggregati e fixture sintetiche Core→Platform;
- errori di contratto, schema, float, extra e JSON corrotto;
- confronto storico fixed/indexed per residente e non residente;
- periodo futuro, classificazione incoerente, coverage gap e sorgenti non
  verificate/non disponibili;
- recommendation senza trasporto o ricalcolo;
- smoke base/extra e test di compatibilità su Python 3.12, 3.13 e 3.14.
