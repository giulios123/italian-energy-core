# Architecture

- `domain/` contiene modelli e invarianti senza I/O.
- `pricing/`, `billing/`, `comparison/` e `recommendation/` espongono contratti separati.
- `market/` conserva dati indice e provenance.
- `arera/` è un confine per futuri importer raw → normalized → canonical.

I modelli canonici sono Pydantic v2 frozen; gli importi usano Decimal.
