# ADR 0005 — Modelli canonici

## Stato

Accettato

## Decisione

Usare Pydantic v2 frozen come modello canonico pubblico, con `extra=forbid`, discriminatori e JSON Schema. Non duplicare dataclass di dominio e DTO Pydantic nella v0.1.

## Conseguenze

La libreria ha una singola dipendenza runtime, interoperabilità JSON immediata e validazione uniforme. Il dominio dipende da Pydantic ma non da framework applicativi.
