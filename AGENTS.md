# Contributing agent instructions

## Ordine di lettura

1. `memory-bank/`
2. spec attiva in `specs/`
3. ADR pertinenti in `docs/adr/`
4. codice e test

## Regole

- Non implementare una funzionalità rilevante senza una spec normativa.
- Scrivere prima i test della logica economica e poi l’implementazione minima.
- Mantenere il dominio indipendente da web framework, cloud SDK, database, MCP, Home Assistant e AI.
- Non introdurre `float` per importi, tariffe o quantità economiche.
- Conservare provenance e distinguere dati certi, dati da verificare e assunzioni.
- Non inventare valori ARERA o regole normative: usare modelli versionati e stato di verifica esplicito.
- Ogni bug economico corretto richiede un regression test.
- Aggiornare `memory-bank/active-context.md` e `memory-bank/progress.md` al termine di ogni milestone.

## Verifica minima

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=italian_energy --cov-branch
git diff --check
```
