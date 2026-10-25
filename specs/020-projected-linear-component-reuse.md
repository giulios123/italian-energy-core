# Spec 020 — Riuso delle componenti regolatorie lineari proiettate

Data: 2026-10-25. Stato: scritta, implementata e verificata localmente.

## Ambito

Durante una singola compare() proiettata, le regole lineari di rete, misura
e oneri non leggono il prezzo energia o il mercato. Possono quindi produrre
la stessa componente mensile per più offerte/scenari dello stesso profilo.
Il riuso riguarda soltanto chiamate riuscite a _linear_component del motore
RegulatoryBillingEngine standard, dopo tutti i controlli di evaluate().

## Requisiti

- Chiave completa degli input letti: istanza del motore, regola immutabile,
  finestra, bucket selezionati, profilo consumo, periodo richiesta, fornitura
  completa (potenza inclusa), misure, classificazione, rounding, parametri e
  data di proiezione. Le identità di oggetti immutabili sono accompagnate da
  riferimenti mantenuti nello scope per impedire riciclo degli ID.
- Il contratto commerciale e il suo pricing non sono dipendenze della singola
  componente lineare. Nessun riuso di prezzi energia, bolletta, accise a soglia,
  IVA/percentuali o totale. Duplicati, dipendenze, validazione, eccezioni e
  riconciliazione restano controllati su ogni bolletta.
- Nessun risultato fallito viene memorizzato. Sottoclassi del motore non
  partecipano al riuso, perché potrebbero introdurre dipendenze ulteriori.
- Scope solo per la compare() corrente; ripristino su errore/annidamento e
  isolamento fra chiamate e thread, senza nuove proprietà serializzate.
- Test prima della modifica: confronto JSON completo con motore senza riuso
  su tariffa corrente fissa/indicizzata e tutti gli scenari; variazioni di
  consumo, potenza, profilo, misure/periodo/rounding/parametri; assenza di cache
  degli errori e assenza di riuso fra scope. Suite e coverage >=95%.
- Replay immutabile da 950 offerte: digest risultato/output identici, vista
  pubblica identica, tutte le 951 bollette coerenti; tempi distinti da release.

## Accettazione locale — 25 ottobre 2026

939 test passati, coverage con rami 95,12%; Ruff check/format, mypy e
diff check passano sul checkout adottato. Il replay Platform da 950 offerte
conserva intera vista pubblica e digest risultato/output dello storico;
951 bollette base senza scarti componenti/totale. Le sole valutazioni
lineari osservate scendono da 197.064 a 144. Le cache sono limitate al
confronto e non riusano IVA, accise a soglia, prezzi o totali indicizzati.

L'adozione locale usa mount in sola lettura delle sorgenti Core/Platform;
la metadata installata resta 0.13.6. Nessuna nuova wheel, release, commit,
push o distribuzione esterna. Misure, script, manifest SHA-256 e limiti
del timer nel repository Platform, docs/comparison-performance-2026-10-25/.
