# Changelog

## [0.4.0] - 2026-09-06 (locale, non pubblicata)

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
- Il lavoro è consolidato localmente; tag, push e release pubblica restano
  successivi ai gate GitHub.

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
