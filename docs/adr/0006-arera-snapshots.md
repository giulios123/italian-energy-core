# ADR 0006 — Snapshot e versioning ARERA

## Stato

Accettato come direzione

## Decisione

I futuri importer conserveranno raw snapshot immutabili con timestamp, formato/versione, provenance, hash e warning. La normalizzazione sarà separata dal modello canonico e non distruggerà il raw.

## Conseguenze

Le importazioni saranno auditabili e riproducibili. Parser e schema concreto sono rinviati alla Spec 005.
