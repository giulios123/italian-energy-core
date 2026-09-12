# ADR 0014 — Contratto Core–Platform

## Stato

Accettato

## Decisione

Il package canonico resta `italian-energy`, importato come `italian_energy`.
Il Core pubblica un manifest runtime e una superficie stabile in
`italian_energy.integration`.
Le costanti di discovery `CORE_CONTRACT_VERSION`, `CORE_CAPABILITIES` e
`CORE_SCHEMA_IDS` sono derivate dal manifest.

La façade Platform è sincrona, seleziona internamente i ruleset packaged e
espone soltanto replay storici conclusi. Confronto e recommendation restano
operazioni separate; la recommendation interpreta un risultato già calcolato.

Gli aggregati attraversano il confine mediante envelope JSON con contratto,
schema ID e payload canonico. Versioni o schema sconosciuti falliscono chiusi;
la v1 non esegue migrazioni automatiche.

`defusedxml` è una dipendenza base perché la capability Portale deve essere
disponibile nel runtime Platform; `openpyxl` resta confinato all’extra ARERA.

## Conseguenze

La Platform non duplica formule, ruleset, matrice o policy di arrotondamento.
Il package resta utilizzabile senza web framework o database e i payload
persistiti sono autosufficienti rispetto alla versione del contratto.

Il confronto corrente/futuro e qualsiasi forecast richiederanno una spec
economica distinta. L’allineamento del repository Platform è una milestone
successiva e non viene incluso in Spec 010.
