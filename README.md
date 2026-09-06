# italian-energy-core

Libreria Python open source, domain-first e deterministica per modellare, simulare e confrontare offerte di energia elettrica in Italia.

> Stato: `v0.4.0` locale, non pubblicata — domain core, pricing fixed/indexed e Billing Engine data-driven implementati e verificati localmente. Il ruleset pubblico Q2 2026 e il verificatore golden privato sono presenti; la release resta bloccata perché la bolletta disponibile non contiene il dettaglio necessario alla riconciliazione per voce.

## Obiettivi

Il package `italian_energy` è pensato come core riusabile per backend, comparatori, MCP server, frontend, Home Assistant, notebook e servizi cloud. Il dominio non dipende da Azure, AWS/GCP, web framework, database, autenticazione, LLM o sistemi AI.

La logica economica dovrà essere deterministica, testabile, riproducibile e spiegabile. Un LLM non viene usato per calcolare costi.

## Installazione locale

```bash
uv sync --dev
uv run pytest
```

L’installazione del package è compatibile con il futuro flusso:

```bash
pip install italian-energy
```

## Architettura

- `domain/`: value object, entità, provenance e risultati immutabili;
- `pricing/`: contratto del Pricing Engine e evaluator fixed/indexed deterministici;
- `billing/`: contratto e Billing Engine regolatorio con riconciliazione esplicita;
- `comparison/`: confronto deterministico;
- `recommendation/`: interpretazione separata dai costi;
- `market/`: indici e dati di mercato;
- `arera/`: confine per futuri importer, senza parser nella v0.4.

Le spec sono normative. Gli ADR registrano decisioni architetturali. Il Memory Bank descrive lo stato corrente e non sostituisce le spec.

## Sviluppo

Leggere nell’ordine `AGENTS.md`, Memory Bank, spec attiva e ADR pertinenti. Il flusso obbligatorio è:

`spec → test → implementazione minima → verifica → aggiornamento Memory Bank`.

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=italian_energy --cov-branch
pre-commit run --all-files
uv run python scripts/verify_private_golden.py
```

Il verificatore golden usa soltanto il materiale in `private/` e non pubblica
documenti o identificativi. In assenza degli elementi di dettaglio del fornitore
deve fallire in modo esplicito, senza adattare aliquote o importi osservati.

## Licenza

Apache License 2.0. Vedere [LICENSE](LICENSE).
