# Core 0.13.10 — revisione dei documenti ufficiali

2026-11-05. Spec 022, ADR 0017 D31 e nota di integrazione 0.13.10.

Core emette richieste legate a versione, anchor e periodo; una decisione
amministrativa esplicita può attestare equivalenza, rifiutare o revocare.
Anchor e risultati storici rimangono immutabili. La verifica corrente resta
obbligatoria e valori/applicabilità diversi non possono essere approvati come
equivalenti, neppure riusando una decisione precedente sullo stesso digest.

Verifica locale:

- 1.027 test passati, coverage con rami 95,03% (gate 95% invariato).
- Ruff check/format, mypy src/tests, diff check e lock offline superati.
- Entrambi i golden privati residente/non residente superati.
- Wheel e sdist costruite; import isolato e capability nuova verificati.
- Regressioni test-first su richiesta, consenso, periodo, digest e coverage
  offline; serializzazione legacy preservata.

Non è stata registrata alcuna approvazione del documento IVA live.
Pubblicazione, verifica degli artefatti pubblicati, adozione Platform e deploy
sono milestone distinte, da documentare dopo il rispettivo completamento.
