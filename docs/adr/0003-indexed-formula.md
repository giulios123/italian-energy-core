# ADR 0003 — Formula indicizzata

## Stato

Accettato

## Decisione

Rappresentare le formule con un AST tipizzato composto da riferimenti indice, costanti prezzo, coefficienti scalari, somme, prodotti e clamp floor/cap. Vietare stringhe eseguite, `eval` e formule non tracciabili.

## Conseguenze

L’ordine delle operazioni è esplicito e validabile per unità. La semantica di valutazione completa sarà normata nella Spec 003.
