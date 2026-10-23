# Spec 017 — Applicazione bioraria ai consumi F1/F2/F3

**Stato:** scritta, implementata e verificata localmente il 2026-10-20
**Data:** 2026-10-20

## Problema

Il Portale Offerte normalizza le fasce biorarie come `BF1` e `BF23`, mentre i
consumi del cliente sono normalmente dichiarati nelle fasce `F1`, `F2`, `F3`.
Il motore fisso oggi richiede una corrispondenza letterale e quindi non calcola
un'offerta bioraria sul profilo trifascia. Questo impedisce il confronto sullo
stesso profilo, benché la tariffa bioraria dichiari esplicitamente che F2 e F3
condividono lo stesso prezzo.

## Risultato

Una tariffa bioraria con prezzi `BF1` e `BF23` viene applicata a un profilo
completo `F1`/`F2`/`F3` aggregando esclusivamente i consumi F2 e F3 sotto `BF23`.
`BF1` applica il prezzo ai consumi F1. Il profilo resta immutato e il risultato
mantiene le due componenti biorarie originali; non crea righe F2/F3 sintetiche.

Tariffe monorarie `ALL` e triorarie `F1`/`F2`/`F3` continuano a usare le proprie
regole. Un prezzo nominato non può essere applicato a consumi `ALL`; dati
trifascia incompleti non vengono completati a zero. Core non ricostruisce la
distribuzione dei consumi e non deduce equivalenze tariffarie ulteriori.

## Vincoli

- La mappatura bioraria ammessa è soltanto `BF1 ← F1` e `BF23 ← F2 + F3`.
- Per mappare un profilo trifascia, devono essere presenti le tre bande
  dichiarate `F1`, `F2`, `F3`; una banda mancante resta dato mancante, anche se
  le altre possono essere calcolate.
- Un profilo già espresso come `BF1`/`BF23` continua a essere valutato per
  corrispondenza diretta. Non si converte una banda aggregata `BF23` in prezzi
  F2 e F3 distinti.
- Il confronto bioraria↔trioraria usa i totali calcolati da Core sul medesimo
  profilo. Le singole righe sono confrontabili solo se conservano la stessa
  banda e lo stesso trattamento.
- Gli importi restano `Decimal`; nessun dato mancante diventa zero.

## Criteri di accettazione

| ID | Criterio | Verifica |
| --- | --- | --- |
| AC-017-01 | BF1 applica il prezzo a F1 e BF23 applica il prezzo alla somma di F2 e F3. | Test fisso con importo e quantità attesi |
| AC-017-02 | Il confronto trioraria fissa↔bioraria fissa calcola entrambe sullo stesso profilo trifascia. | Test d'integrazione prospettica Core |
| AC-017-03 | Tariffe nominate contro profilo ALL e profilo trifascia incompleto falliscono chiuso. | Regressioni di input |
| AC-017-04 | Le componenti restano aggregate secondo le bande dichiarate della tariffa. | Test output pricing |

## Stato di avanzamento

- **Scritto:** il 2026-10-20 dopo la precisazione che le fasce mono, bi e tri
  non devono impedire il confronto di offerte sullo stesso profilo.
- **Implementato:** il motore applica BF1 a F1 e BF23 alla somma F2/F3 solo se
  il profilo dichiara tutte le tre fasce o la coppia bioraria. Mantiene una riga
  BF23 aggregata e respinge profili incompleti o incompatibili.
- **Verificato:** regressione unità/prezzi e confronto prospettico trioraria
  fissa↔bioraria fissa sul medesimo profilo passano. Suite completa: 903 test,
  branch coverage 95,02%; Ruff check/format, mypy `src tests` e
  `git diff --check` passano.
