# ADR 0009 — Confine di fiducia dell'importer ARERA

## Stato

Accettato

## Decisione

La verifica automatica distingue autenticità dell'acquisizione e semantica
economica. Soltanto il fetcher che raggiunge l'URL HTTPS ARERA allowlisted,
conserva il raw e supera i controlli strutturali può produrre valori
`VERIFIED`. Il parsing di bytes forniti offline resta `UNVERIFIED`.

Il risultato è un `AreraRegulatoryBundle` source-faithful, non un
`RegulatoryRuleSet` eseguibile. Il bundle conserva valori atomici e totali,
provenance e localizzazioni; non sceglie proratazioni, imposte o inclusioni nel
prezzo commerciale.

## Conseguenze

Il Billing Engine resta indipendente da rete, XLSX e parser ARERA. Ogni
trasformazione successiva verso un ruleset fatturabile deve dichiarare e
verificare separatamente policy, fonti fiscali e copertura temporale. Un cambio
di layout ARERA non può degradare silenziosamente in dati verificati.
