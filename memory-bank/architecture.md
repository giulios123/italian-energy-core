# Architecture

- `domain/` contiene modelli e invarianti senza I/O.
- `pricing/`, `billing/`, `comparison/` e `recommendation/` espongono contratti separati; `pricing/` include evaluator fixed e indexed stateless.
- `billing/` riceve un `PricingResult` già calcolato e un `RegulatoryRuleSet` verificato; non importa evaluator pricing concreti né fonti ARERA.
- I ruleset selezionano profili per classificazione esplicita e le percentuali seguono dipendenze acicliche su componenti o categorie.
- `market/` conserva dati indice e provenance.
- `arera/` acquisisce e normalizza il workbook elettrico domestico ARERA 2026 in
  un bundle source-faithful; la trasformazione successiva verso ruleset
  fatturabili resta separata e non automatica.
- `portal_offers/` acquisisce i cataloghi commerciali ufficiali in snapshot
  verificabili e li normalizza verso il Comparison Engine, restando distinto
  dall'importer regolatorio ARERA e dal Billing Engine.
- `comparison/` orchestra soltanto contratti già normalizzati: preflight della
  matrice, Pricing fixed/indexed, Billing all-in e ranking; non interpreta
  eligibility o condizioni testuali.
- `recommendation/` interpreta un `ComparisonResult` con policy hard ed
  evidenza candidata verificata; non ricalcola né muta costi o ranking.
- `portal_offers/` espone l'adapter verso Recommendation, mantenendo la
  dipendenza unidirezionale dal catalogo al motore generico.
- Il Comparison Engine passa sempre `external_items=()` al Billing Engine; le
  partite esterne verificate vengono restituite come evidenza separata.
- `integration/` è il confine pubblico Core–Platform: manifesta capability e
  schema ID, orchestra soltanto replay storici domestici BT tramite la façade e
  serializza gli aggregati registrati senza introdurre trasporto o persistenza.

I modelli canonici sono Pydantic v2 frozen; gli importi usano Decimal.
