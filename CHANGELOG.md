# Changelog

## [0.10.0] - 2026-09-09 (locale, non pubblicata)

### Added

- Contratto Core–Platform v1 in `italian_energy.integration`, con manifest,
  capability e schema ID deterministici.
- Façade sincrona per confronti storici domestici BT elettrici e recommendation
  separata sul risultato già calcolato.
- Envelope JSON canonici fail-closed per gli aggregati pubblici e codici errore
  stabili privi di dettagli sensibili.
- `defusedxml` nella dipendenza base; `openpyxl` resta nell'extra `arera`.

### Verification boundary

- La v0.10.0 è locale e non pubblicata. Nessuna modifica alla Platform,
  commit, tag, push o release è inclusa.
- Confronti correnti/futuri, forecast, gas, persistenza e migrazioni automatiche
  restano fuori contratto.

## [0.9.0] - 2026-09-09 (locale, non pubblicata)

### Added

- `DeterministicRecommendationEngine` per interpretare risultati Comparison
  senza ricalcolare Pricing o Billing.
- Preferenze strutturate su tipo tariffa, rischio indicizzato, durata, sconti e
  soglia minima di risparmio in EUR.
- Evidenza candidata verificata, shortlist, decisione `switch`/`stay_current`,
  esclusioni stabili e `PortalRecommendationAdapter`.

### Not included

- Scoring pesato, forecast, AI, testo commerciale, persistenza o API web.

## Unreleased

### Added

- Implementata localmente la Spec 008 Portale Offerte Importer v0.8.0: modelli
  frontend `ComparisonContext`/`PortalComparisonRequest`, snapshot content-addressed,
  trasporto HTTPS allowlisted, parser XML/CSV source-faithful e market data storici.
- Normalizzazione deterministica delle offerte elettriche domestiche BT Mercato
  Libero e PLACET verso Pricing/Billing/Comparison 007, con validità relativa,
  corrispettivi annuali, provenance, applicabilità e ledger completo delle esclusioni.
- Aggiunte fixture e test di sicurezza, schema drift, duplicati, replay indexed
  multi-indice, ranking end-to-end e invarianti di ordine; branch coverage locale 95%+.

### Verification boundary

- La milestone è locale e non pubblicata: commit, tag, push e release richiedono
  autorizzazione separata. Lo smoke live del Portale resta separato dalla suite offline.

### Documentation

- Implementata localmente la Spec 007 Comparison Engine v0.7.0: confronto
  all-in di offerte normalizzate, ranking deterministico, esclusioni motivate,
  matrice di copertura obbligatoria e partite esterne escluse dal ranking.
- Implementata localmente la Spec 006 Billing Coverage Expansion v0.6.0:
  ruleset BT domestici residente/non residente, matrice di copertura, composer
  deterministico, fiscalità ufficiale versionata e snapshot ARERA 2026 congelato.
- Il golden non residente è stato riconciliato sul bimestre 2026-03-01/2026-05-01
  dal documento privato disponibile; il mapping sanitizzato delle righe impedisce
  riusi e target canonici ambigui.
- Riallineato lo stato documentale: `v0.4.0` è pubblicata come release GitHub;
  `v0.5.0` resta locale e non pubblicata.
- Chiarito che il Comparison Engine opera su offerte già normalizzate e non
  sostituisce un importer del catalogo commerciale del Portale Offerte.

## [0.5.0] - 2026-09-07 (locale, non pubblicata)

### Added

- Spec 005 e importer ARERA per il workbook elettrico domestico 2026.
- Raw snapshot immutabili content-addressed, parsing XLSX con `Decimal`,
  provenance per cella e bundle normalizzati per residenti e non residenti.
- Stati `VERIFIED`, `UNVERIFIED` e `REVIEW_REQUIRED` con controlli fail-closed
  del layout e dei totali; parser disponibile nell'extra `arera`.
- Smoke test live `scripts/verify_arera_import.py` senza persistenza del raw.

### Verification boundary

- Il bundle ARERA è source-faithful e non è un `RegulatoryRuleSet` fatturabile:
  IVA, accisa, proratazione, selezione CDISPD e assemblaggio restano esclusi.
- Test, coverage, Ruff, format, mypy, pre-commit, build e smoke install devono
  essere verificati localmente prima di qualsiasi release separata.

## [0.6.0] - 2026-09-08 (locale, non pubblicata)

### Added

- Composer deterministico ARERA → ruleset mensili per i segmenti domestici BT.
- Matrice di copertura e loader JSON caricabili senza l'extra XLSX.
- Proratazione TIT mensile con dodicesimi, giorni/365 e rounding commerciale.
- Provenance con locator foglio/cella/sezione e confini di potenza inclusivi o
  esclusivi.

### Verification boundary

- Snapshot ARERA 2026 VERIFIED congelato al digest
  `b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`.
- I golden privati residente e non residente passano entro 0,01 EUR; la matrice
  dichiara `golden_reconciled` soltanto per i rispettivi periodi riconciliati.
- Il documento privato e i JSON sanitizzati restano fuori dal repository; commit,
  tag, push e release della v0.6.0 richiedono autorizzazione separata.

## [0.4.0] - 2026-09-06

### Added

- Spec 004 e `RegulatoryBillingEngine` data-driven per profili, regole lineari,
  soglie, percentuali, proration e pass-through verificati.
- Modelli immutabili per classificazione, misure, ruleset versionati, AST
  quantitativo, observed bill, riconciliazione e `BillingResult`.
- `bill_id` deterministico indipendente dall'oracle e tolleranza esplicita di
  `0,01 EUR` per voce e totale.
- Fixture sintetiche, ruleset pubblico domestico BT residente Q2 2026 e test
  fail-closed per pricing, unità, provenance, arrotondamento, dipendenze
  percentuali e riconciliazione.
- Verificatore end-to-end privato `scripts/verify_private_golden.py` e scenario
  tecnico sanitizzato in `private/`.

### Verification boundary

- Test, branch coverage, Ruff, format e mypy passano localmente.
- Il verificatore del golden privato passa usando la pagina collegata di elementi
  di dettaglio, mantenuta fuori dal repository. La riconciliazione è esatta sulle
  chiavi e resta entro `0,01 EUR` per voce e totale.
- La chiusura tecnica del golden è stata consolidata nella release GitHub
  `v0.4.0`; documento, input e importi osservati restano privati. La
  disponibilità del package su PyPI non è stata richiesta né verificata.

## [0.3.0] - 2026-09-06 (locale, non pubblicata)

### Added

- `IndexedPricingEngine` per indici market-data versionati, AST Decimal e
  conversione EUR/MWh senza arrotondamenti intermedi.
- Validazione di granularità, copertura temporale, gap/overlap e provenance.

## [0.2.0] - 2026-09-06 (locale, non pubblicata)

### Added

- Spec 002 e `FixedPricingEngine` stateless per tariffe fisse.
- Calcolo deterministico di energia, addebiti per kWh/giorno/kW-giorno e `FLAT`.
- Rounding esplicito per componente, provenance, assumptions e pricing ID SHA-256.
- Validazione fail-closed di fasce, validità, unità e basi non supportate.

### Not included

- Billing, fiscalità, importer ARERA e confronto offerte.

## [0.1.0] - 2026-09-06

### Added

- Domain core immutabile e validato con Pydantic v2.
- Modelli per denaro, periodi, consumi, tariffe fisse/indicizzate, mercato, provenance, cost breakdown e risultati.
- AST tipizzato per formule indicizzate, senza esecuzione arbitraria.
- Protocolli separati per pricing, billing, comparison e recommendation.
- Test unitari e property-based per invarianti del domain core.

### Not included

- Calcolo pricing, billing reale, importer ARERA e golden bill; sono coperti dalle spec successive.
