# italian-energy-core

Libreria Python open source, domain-first e deterministica per modellare, simulare e confrontare offerte di energia elettrica in Italia.

> Release `0.13.0` — rollover degli anchor regolatori e anchor domestico Q4 2026.

Il package installabile è disponibile come wheel e sdist. L'importer Portale
Offerte opera solo su cataloghi open-data ufficiali, replay storici esatti e
offerte elettriche domestiche BT; gas e UI restano fuori scope.

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
pip install italian-energy==0.13.0
```

## Architettura

- `domain/`: value object, entità, provenance e risultati immutabili;
- `pricing/`: contratto del Pricing Engine e evaluator fixed/indexed deterministici;
- `billing/`: contratto e Billing Engine regolatorio con riconciliazione esplicita;
- `comparison/`: confronto deterministico all-in su offerte normalizzate, con matrice di copertura obbligatoria;
- `portal_offers/`: acquisizione allowlisted, snapshot/provenance, parsing e normalizzazione dei cataloghi Mercato Libero/PLACET verso il Comparison Engine;
- `recommendation/`: preferenze strutturate, shortlist e decisione consultiva separate dai costi;
- `market/`: indici del catalogo, report GME ufficiali e dati di mercato;
- `arera/`: discovery regolatoria, parser versionati e snapshot raw; il rollover usa l'extra opzionale `arera` (`openpyxl` per i workbook e `pypdf` per il listino ADM); il base non installa queste dipendenze;
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

## Regulatory Anchor Rollover — Spec 014

`RegulatoryRolloverService` aggiorna la copertura, scopre e acquisisce fonti,
costruisce e verifica un candidate con parser/mapping registrati, lo stagea e
lo promuove con il repository CAS. `refresh_regulatory_anchor` e
`--refresh-anchor` conservano il significato precedente: verificano l'anchor
esistente e non generano il successore.

Il servizio riceve adapter ufficiali e repository tramite protocolli; il Core
mantiene parsing, interpretazione, mapping e scelta dei valori. Il report
restituisce discovery, cursori committabili, candidate, evidenze di coverage,
stato e reason code. La Platform può pianificare il job e persistere questi
artefatti tramite un adapter durevole; tale adapter e il job Platform non sono
inclusi in questo package. `source_preflight` e `resolve_active` sono offline.
Il confronto usa gli snapshot e l'evidenza persistiti, senza riacquisire fonti.

Gli adapter Core coprono gli atti ARERA, gli indici tariffari ARERA, ADM, la
Gazzetta Ufficiale e Normattiva. I parser versionati includono workbook ARERA,
conferme non numeriche della delibera 343, accisa ADM domestica e disposizioni
IVA Normattiva. L'anchor Q4 incluso ha snapshot `2026-10-08`, validità
`[2026-10-01, 2027-01-01)` e ID
`regulatory-anchor:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`.
La sua evidenza ha `source_preflight.ready=true` per `as_of=2026-10-08`; è
datata e va aggiornata per usare l'anchor in date successive. Il PDF 343 fornito
dall'utente è stato acquisito dalla fonte ufficiale con TLS verificato. La
suite Core usa fixture offline e il confronto resta senza rete; il collaudo
PostgreSQL, il job giornaliero persistente e la promozione concorrente Platform
sono verifiche separate.

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
la loro validità verificata. L’anchor incluso nel package ha `as_of=2026-10-08`
e validità `2026-10-01`–`2027-01-01` (estremo finale escluso). La coverage
conferma i digest delle fonti e la discovery datata dei provvedimenti
successivi pertinenti; gli hash coincidenti da soli non bastano. Prima di
confronti in date successive, il Core deve produrre nuova evidence aggiornata.

Per ripetere l'acquisizione e la verifica live delle fonti ufficiali, servono
gli extra opzionali `gme` e `arera`:

```bash
uv run --extra gme --extra arera python -m italian_energy.integration.catalog_cli --date 2026-09-27
uv run python -m italian_energy.integration.projection_cli --date 2026-10-08 --refresh-anchor --review regulatory-review.json --output-anchor refreshed-anchor.json
uv run --extra gme --extra arera python -m italian_energy.integration.projection_cli --date 2026-10-08 --verify-sources --review regulatory-review.json --output-sources projected-sources.json
uv run python -m italian_energy.integration.projection_cli --date 2026-10-08 --sources projected-sources.json --request request.json
```

`--refresh-anchor` scarica e verifica le fonti dell'anchor risolto per la data
richiesta, senza acquisire il catalogo o GME. Scrive un envelope
`RegulatoryAnchorRefreshResult` con lo stesso `anchor.as_of`, le nuove date dei
controlli e l'evidenza dei registri; non riscrive né ripubblica il package. Il
comando termina con stato
`review_required` se una fonte cambia, l’anchor non copre la data o manca la
valutazione dei provvedimenti successivi. La classificazione di un atto nuovo
o incerto resta esplicita: il Core non lo dichiara irrilevante tramite hash o
parole chiave. `--verify-sources` è il percorso live completo: acquisisce
catalogo e storico GME, verifica le fonti note e riusa le revisioni contenute
in `RegulatoryCoverageEvidence`. Se manca la revisione degli atti successivi,
il gate resta incompleto anche con tutti i digest corrispondenti.
`--output-sources` salva gli snapshot e l’evidenza in un
`ProjectedSourceBundle` versionato. `--sources` usa quel bundle offline e non
accede alla rete; `--request PATH` accetta un envelope
`ProjectedDomesticComparisonRequest` con `as_of` corrispondente al bundle e
restituisce il confronto tipizzato, marcato `estimated`.

La Platform deve usare `ProjectedDomesticEnergyService.source_preflight(...).ready`
per abilitare globalmente i confronti, insieme alla propria regola di freschezza
del catalogo, e `preflight(request, ...).ready` prima del confronto cliente.
Questo percorso è locale alla Core; l'allineamento e la persistenza Platform
restano separati.
