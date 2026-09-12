# italian-energy-core

Libreria Python open source, domain-first e deterministica per modellare, simulare e confrontare offerte di energia elettrica in Italia.

> Stato: `v0.11.0` — domain core, pricing fixed/indexed, Billing Engine data-driven, importer ARERA, ruleset domestici BT, Comparison Engine, Portale Offerte importer, Recommendation Engine, contratto d'integrazione Core–Platform e current domestic advisor implementati e verificati.

La release GitHub pubblica più recente è `v0.11.0`. Il package installabile è
disponibile come wheel e sdist negli asset della release. L'importer Portale Offerte
opera solo su cataloghi open-data ufficiali, replay storici esatti e offerte
elettriche domestiche BT; gas, UI, persistenza e scheduler restano fuori scope.

## Obiettivi

Il package `italian_energy` è pensato come core riusabile per backend, comparatori, MCP server, frontend, Home Assistant, notebook e servizi cloud. Il dominio non dipende da Azure, AWS/GCP, web framework, database, autenticazione, LLM o sistemi AI.

La logica economica dovrà essere deterministica, testabile, riproducibile e spiegabile. Un LLM non viene usato per calcolare costi.

## Installazione locale

```bash
uv sync --dev
uv run pytest
```

Installazione del package dalla release pubblicata:

```bash
pip install italian-energy==0.11.0
```

## Architettura

- `domain/`: value object, entità, provenance e risultati immutabili;
- `pricing/`: contratto del Pricing Engine e evaluator fixed/indexed deterministici;
- `billing/`: contratto e Billing Engine regolatorio con riconciliazione esplicita;
- `comparison/`: confronto deterministico all-in su offerte normalizzate, con matrice di copertura obbligatoria;
- `portal_offers/`: acquisizione allowlisted, snapshot/provenance, parsing e normalizzazione dei cataloghi Mercato Libero/PLACET verso il Comparison Engine;
- `recommendation/`: preferenze strutturate, shortlist e decisione consultiva separate dai costi;
- `market/`: indici e dati di mercato;
- `arera/`: snapshot raw, importer del workbook domestico ARERA 2026 (extra opzionale `arera`) e composer verso ruleset verificati; `defusedxml` è nella base, `openpyxl` resta opzionale;
- `data/billing/`: ruleset e matrice JSON congelati, caricabili senza dipendenze XLSX.
- `integration/`: manifest, envelope JSON versionati e façade storica Core–Platform;

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
uv run --extra arera python scripts/verify_arera_import.py
# Smoke live separato, con data esplicita (non usato dalla suite)
uv run python scripts/verify_portal_import.py --date 2026-09-08
```

Il verificatore golden usa soltanto il materiale in `private/` e non pubblica
documenti o identificativi. Le regole normative restano nel fixture pubblico;
prezzi e importi del caso reale restano privati.

## Licenza

Apache License 2.0. Vedere [LICENSE](LICENSE).
