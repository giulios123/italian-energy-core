# ADR 0007 — Ruleset normativi e Billing

## Stato

Accettato

## Decisione

Il Billing Engine riceve ruleset normativi già normalizzati e versionati. Ogni
parametro e regola usati devono essere `VERIFIED` e provvisti di provenance; il
motore non contiene aliquote o selezioni normative hard-coded. L'applicabilità è
selezionata da una classificazione esplicita della fornitura.

## Conseguenze

La 004 resta deterministica e indipendente dagli importer. La Spec 005 potrà
produrre ruleset compatibili conservando raw snapshot e warning di parsing.
