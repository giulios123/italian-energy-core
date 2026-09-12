# ADR 0013 — Recommendation deterministica e consultiva

## Stato

Accettata per la Spec 009 v0.9.0.

## Decisione

Il Recommendation Engine riceve un `ComparisonResult` già calcolato e una
policy strutturata. Applica filtri hard sull'evidenza candidata e sceglie la
candidata con il minor totale comparabile fra quelle che soddisfano i vincoli e
la soglia minima di risparmio. Se nessuna candidata è ammissibile, raccomanda
`stay_current`.

La tolleranza `low` ammette soltanto fixed; `medium` ammette anche indexed con
cap sull'intera formula di ogni fascia; `high` ammette ogni rischio supportato.
La soglia economica è in EUR, inclusiva e riferita allo stesso periodo del
confronto. Una soglia assente mantiene compatibilità con i payload legacy ma
non abilita automaticamente lo switch.

Le evidenze mancanti o non verificate escludono la singola candidata quando
sono necessarie per la policy. Duplicati, ID sconosciuti, policy
contraddittorie o risultati economici incompleti invalidano l'intera richiesta.

## Conseguenze

- Il costo resta esclusiva responsabilità di Pricing, Billing e Comparison.
- La raccomandazione è auditabile tramite evidenze, codici, provenance e
  assunzioni; non è una previsione di mercato.
- Il modulo `recommendation` resta indipendente da Portale Offerte, web,
  database e AI. L'adapter vive nel confine `portal_offers`.
- La policy legacy resta deserializzabile; la forma canonica normalizzata è
  usata per ID e per la determinismo.
