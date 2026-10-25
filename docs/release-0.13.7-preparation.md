# Core 0.13.7 — preparazione del rilascio

Data: 2026-10-25. Rilascio della versione 0.13.7 richiesto dall'utente.

## Ambito

Specs 019/020: riuso locale al confronto delle serializzazioni/provenance e
componenti regolatorie lineari. Sono inclusi implementazione, regressioni e
specifiche; nessun dato cliente o modifica della Platform entra nel package.
Contratto v1, schemi, capability e dipendenze runtime rimangono invariati.

## Gate

Prima della pubblicazione: lock/sync, Ruff check e format, mypy, suite Core
con copertura con branch >=95%, pre-commit, golden privati, build wheel/sdist,
import isolato e ispezione degli artefatti. La sorgente precedente al bump
superava 939 test e 95,12% di coverage con branch.

Dopo il push: CI Python 3.12–3.14 sul commit di rilascio e tag verificato,
GitHub Release, Trusted Publishing, wheel/sdist con digest coincidenti su
GitHub e PyPI, import del package pubblicato in ambiente isolato.

La Platform locale sta usando un mount sorgente, con metadata ancora 0.13.6.
La pubblicazione 0.13.7 non implica adozione della nuova wheel o deployment.
Il replay da 950 offerte e mediana 57,148 s include anche modifiche Platform
separate dalla release Core. Non cambiare i confronti storici per il rilascio.

## Gate locali del package 0.13.7

- Lock/sync locked dev passati: cambia soltanto la versione del progetto,
  nessuna dipendenza aggiornata.
- 939 test passati in 28,44 s; coverage con branch 95,12% (soglia 95%).
- Ruff check/format (187 file), mypy (120 file), pre-commit all-files e
  diff check passano. Entrambi i golden economici privati superati.
- Wheel/sdist costruiti; smoke isolato conferma metadata e import 0.13.7
  da site-packages, ottimizzazioni presenti, contratto v1 e runtime base
  senza openpyxl/pypdf. Tutti i file Python della wheel corrispondono
  alla sorgente verificata; nessun dato privato negli artefatti.
- CI remota, tag, Trusted Publishing e confronto hash PyPI/GitHub restano
  da verificare dopo il push, prima di dichiarare pubblicata la versione.

## Pubblicazione completata

GitHub/PyPI verificati il 2026-10-25: CI main/tag, Trusted Publishing,
attestazioni e hash concordanti. Vedi [evidenze](release-0.13.7-publication.md).
L'adozione Platform rimane separata.
