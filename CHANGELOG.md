# Changelog

## [0.1.0] - 2026-09-06

### Added

- Domain core immutabile e validato con Pydantic v2.
- Modelli per denaro, periodi, consumi, tariffe fisse/indicizzate, mercato, provenance, cost breakdown e risultati.
- AST tipizzato per formule indicizzate, senza esecuzione arbitraria.
- Protocolli separati per pricing, billing, comparison e recommendation.
- Test unitari e property-based per invarianti del domain core.

### Not included

- Calcolo fixed/indexed pricing, billing reale, importer ARERA e golden bill; sono coperti dalle spec successive.
