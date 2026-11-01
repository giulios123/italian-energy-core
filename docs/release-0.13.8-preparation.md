# Core 0.13.8 — preparazione locale

Data: 2026-11-01. Preparazione del rilascio Core 0.13.8. La Platform non è
stata modificata.

## Ambito

Spec 016 e ADR 0018 definiscono l'uso per un solo mese del PUN precedente
quando la pubblicazione GME del mese appena concluso è dimostrata incompleta.
Spec 013 e ADR 0016 conservano il periodo dei consumi e limitano l'eccezione al
solo storico PUN. Acquisizione, selezione tipizzata, input congelati, preflight,
confronto, digest, envelope e CLI sono aggiornati insieme alle regressioni.
La capability nuova è `gme_monthly_publication_lag`; `contract_version` resta
`1`. Vedi anche [nota Platform](platform-integration-0.13.8.md).

## Verifica locale

Completata sul checkout locale:

- Le regressioni nuove sono state eseguite prima dell'implementazione e hanno
  riprodotto i fallimenti sul codice 0.13.7.
- Suite completa: **961 passati**, branch coverage **95,03%** (soglia 95%).
- Ruff check e format, mypy `src tests`, `git diff --check`, `uv lock --check
  --offline`, pre-commit all-files e due golden privati disponibili: superati.
- Build wheel/sdist e smoke isolato: superati. La wheel installata in una
  directory target isolata importa la versione 0.13.8, `contract_version=1`,
  capability nuova e schema confronto v3.

Artefatti locali di preflight (il workflow di release li ricostruisce dal tag):

| Artefatto | SHA-256 |
| --- | --- |
| `dist/italian_energy-0.13.8-py3-none-any.whl` | `80712e6ae4674e1a68d60b64486cb30f360ab469de7d24ff286e470f65187411` |

Acquisizione live GME, integrazione Platform e gate CI remoto non eseguiti. I
test di preflight e confronto coprono il 1° novembre 2026 con consumi novembre
2025–ottobre 2026 e GME ottobre 2025–settembre 2026. Il confronto usa
l'anchor ARERA Q4 già versionato nel repository e fixture dichiarate sintetiche
per consumi e catalogo; la prova di pubblicazione GME è una fixture strutturale,
non un'acquisizione live. Questi test verificano il contratto e la separazione
dei periodi, non attestano fonti aggiornate oltre gli artefatti congelati.

Il gate CI remoto, la pubblicazione e l'adozione della wheel nella Platform
restano decisioni e verifiche separate.
