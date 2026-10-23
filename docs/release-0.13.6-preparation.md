# Core 0.13.6 — preparazione del rilascio

Data: 2026-10-23. Rilascio GitHub/PyPI e successiva adozione Platform
esplicitamente richiesti dall'utente.

## Ambito

Include Specs 016/017/018 e preferenza `ALL` della Spec 008, con codice,
regressioni e documentazione già verificati localmente. Include inoltre i
commit precedenti per gli ID ARERA compatti e il significato energetico.
Il checkout conserva tutte queste modifiche; il rilascio non include dati
cliente, override locali o modifiche UI della Platform.

## Gate

La sorgente prima del bump aveva 924 test / copertura branch 95,08%, Ruff,
format e mypy superati. Per la versione 0.13.6 si eseguono nuovamente suite,
coverage minima 95%, statici, lock, pre-commit, golden privati, build e smoke
isolato della wheel. Dopo il push si richiedono CI Python 3.12–3.14, tag sul
commit verificato, GitHub Release, Trusted Publishing e digest GitHub/PyPI
coincidenti. Pubblicazione e adozione Platform sono registrate separatamente.

La Platform deve scaricare la wheel pubblicata verificando digest e PEP 740,
aggiornare il pin e le immagini, eliminare l'override sorgente dal runtime
attivo e verificare in locale versioni, gate, PostgreSQL e confronto Core.
Nessun deployment di produzione è implicato da questa adozione locale.

## Accettazione locale sul package 0.13.6

- Lock aggiornato soltanto per la versione del progetto; sync locked dev riuscito.
- 924 test passati in 38,73 s; branch coverage 95,08% (soglia 95%).
- Ruff check, format (179 file), mypy (116 file), pre-commit all-files e
  diff check superati.
- Entrambi i golden privati residente/non residente superati; dati privati
  esclusi dagli artefatti.
- Wheel/sdist costruiti; import della wheel in ambiente isolato conferma
  package/manifest 0.13.6. Il runtime base non installa openpyxl o pypdf.
- Il primo lock offline con cache vuota non poteva risolvere le dipendenze;
  lock online successivo riuscito senza aggiornamenti delle dipendenze.

CI remota, pubblicazione e adozione Platform saranno documentate dopo la
verifica dello stato effettivamente pubblicato.
