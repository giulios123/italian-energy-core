# ADR 0006 — Snapshot e versioning ARERA

## Stato

Accettato e concretizzato dalla Spec 005

## Decisione

Gli importer conservano raw snapshot immutabili con timestamp, formato/versione,
provenance, hash e warning. La normalizzazione è separata dal modello canonico
fatturabile e non distrugge il raw.

## Conseguenze

Le importazioni sono auditabili e riproducibili. La Spec 005 concretizza il
primo adapter per il workbook elettrico domestico 2026; il parser non promuove
bytes offline a `VERIFIED` e non crea direttamente un `RegulatoryRuleSet`.
