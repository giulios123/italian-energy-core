# ADR 0011 — Semantica del Comparison Engine

## Stato

Accettato e concretizzato dalla Spec 007

## Decisione

Il Comparison Engine riceve offerte già normalizzate e prequalificate e valuta
contratto corrente e candidate nello stesso scenario. La matrice di copertura è
un prerequisito globale: la richiesta viene rifiutata se la combinazione di
classificazione, ruleset e periodo non raggiunge `ruleset_verified`.

Il ranking usa il totale della `Bill` prodotta da Pricing più Billing. Il
Billing Engine riceve sempre `external_items=()`. Le partite esterne verificate
possono essere mostrate come evidenza separata, ma non sono costi comparabili.

Le candidate non calcolabili vengono escluse individualmente con un codice
stabile; un errore sul baseline o sulla copertura invalida l'intero risultato.
L'ordinamento è per totale crescente e `offer_id`, con risparmio definito come
totale corrente meno totale candidato e percentuale positiva quando la candidata
è più economica.

## Conseguenze

Il core non acquisisce il catalogo commerciale, non interpreta condizioni
testuali e non formula raccomandazioni. I consumer devono normalizzare i termini
economici nella tariffa, prequalificare l'utente e mostrare il livello di
copertura e le esclusioni. Il confronto resta riproducibile, auditabile e
indipendente da I/O applicativo.
