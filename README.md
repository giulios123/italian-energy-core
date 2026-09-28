# italian-energy-core

Libreria Python open source, domain-first e deterministica per modellare, simulare e confrontare offerte di energia elettrica in Italia.

> Release pubblicata: `v0.12.0` — confronto beta con scenari storici.

La release GitHub pubblica più recente è `v0.12.0`. Il package installabile è
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
pip install italian-energy==0.12.0
```

## Architettura

- `domain/`: value object, entità, provenance e risultati immutabili;
- `pricing/`: contratto del Pricing Engine e evaluator fixed/indexed deterministici;
- `billing/`: contratto e Billing Engine regolatorio con riconciliazione esplicita;
- `comparison/`: confronto deterministico all-in su offerte normalizzate, con matrice di copertura obbligatoria;
- `portal_offers/`: acquisizione allowlisted, snapshot/provenance, parsing e normalizzazione dei cataloghi Mercato Libero/PLACET verso il Comparison Engine;
- `recommendation/`: preferenze strutturate, shortlist e decisione consultiva separate dai costi;
- `market/`: indici del catalogo, report GME ufficiali e dati di mercato;
- `arera/`: snapshot raw, importer del workbook domestico ARERA 2026 (extra opzionale `arera`) e composer verso ruleset verificati; `defusedxml` è nella base, `openpyxl` resta opzionale;
- `data/billing/`: ruleset e matrice JSON congelati, caricabili senza dipendenze XLSX.
- `integration/`: manifest, envelope JSON versionati e façade storica, corrente
  e prospettica Core–Platform;

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

## Acquisire il catalogo reale

```bash
python -m italian_energy.integration.catalog_cli --date 2026-09-27
```

La data è esatta e obbligatoria. Il comando acquisisce XML Mercato Libero, CSV
PLACET/parametri e indici storici ufficiali, valida i dati e stampa un riepilogo
JSON con conteggi, digest e copertura temporale degli indici. Exit code: 0 per
l'acquisizione riuscita, 1 per errori Core, 2 per argomenti non validi.
`verified` descrive il catalogo acquisito: non certifica la copertura necessaria
per un confronto economico. I bytes rimangono in memoria; la Platform ne cura
il salvataggio privato e la pianificazione.

## Confronto prospettico beta — Spec 013

La Core locale confronta dodici mesi completi usando lo storico ufficiale più
recente, senza colmare buchi o ripiegare su mesi arretrati. Per il confronto al
27 settembre 2026 la finestra storica è settembre 2025–agosto 2026 e il periodo
stimato è ottobre 2026–settembre 2027. Consumi e indici sono abbinati allo
stesso mese dell'anno. Gli scenari applicano `0.80`, `1.00` e `1.20` al solo
indice energetico; ranking e recommendation usano il base. Ogni costo o
risparmio futuro è un **valore stimato**.

Il mapping automatico verificato è PUN Index GME: media mensile MGP Baseload,
pubblicata in EUR/MWh e convertita in EUR/kWh con `Decimal`. I prezzi medi GME
F1/F2/F3 restano una serie distinta dal PUN e dai codici PE; il Core non li
assegna automaticamente a un'offerta senza un mapping commerciale esplicito.
Le componenti ARERA e fiscali sono quelle ufficiali applicabili alla data del
confronto e vengono riutilizzate nel futuro come assunzione, senza prolungare la
loro validità verificata.

Per ripetere l'acquisizione e la verifica live delle fonti ufficiali, servono
gli extra opzionali `gme` e `arera`:

```bash
uv run --extra gme --extra arera python -m italian_energy.integration.catalog_cli --date 2026-09-27
uv run --extra gme --extra arera python -m italian_energy.integration.projection_cli --date 2026-09-27 --verify-sources
```

`projection_cli` riporta digest, finestra storica, mapping GME e completezza
dell'ancora. Con `--request PATH` accetta un envelope
`ProjectedDomesticComparisonRequest` con `as_of` corrispondente a `--date` e
restituisce anche il confronto tipizzato, marcato `estimated`. Senza request il
comando verifica le fonti ma non simula input del cliente. Questo percorso è
locale alla Core; l'allineamento e la persistenza Platform restano separati.
