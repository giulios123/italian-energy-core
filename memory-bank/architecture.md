# Architecture

- `domain/` contiene modelli e invarianti senza I/O.
- `pricing/`, `billing/`, `comparison/` e `recommendation/` espongono contratti separati; `pricing/` include evaluator fixed e indexed stateless.
- `billing/` riceve un `PricingResult` già calcolato e un `RegulatoryRuleSet` verificato; non importa evaluator pricing concreti né fonti ARERA.
- I ruleset selezionano profili per classificazione esplicita e le percentuali seguono dipendenze acicliche su componenti o categorie.
- `market/` conserva dati indice e provenance.
- `arera/` è un confine per futuri importer raw → normalized → canonical.

I modelli canonici sono Pydantic v2 frozen; gli importi usano Decimal.
