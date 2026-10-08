# Spec 014 — Regulatory Anchor Rollover

**Stato aggiornato al 2026-10-08:** M1–M23 sono implementate localmente. Il
Core ha completato la discovery sui cinque canali, applicato la matrice di
ambito versionata alle fonti che possono modificare i campi modellati,
riacquisito le versioni Normattiva vigenti all'8 ottobre, verificato, staged e
promosso una sola volta il candidate Q4. Il candidate canonico ha ID
`regulatory-anchor-candidate:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`,
digest SHA-256
`902354107ae452185c3a3a7d9d83dab9b2886c27a287378619b8debea0d107db`,
snapshot 2026-10-08 e validità `[2026-10-01, 2027-01-01)`. Il mapping è
validato (13 fatti, 11 decisioni); l'anchor promosso ha ID
`regulatory-anchor:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`
e digest `641c71a677d98cefe6ec562fd5665a54d3620059e61d70c6a00c397238073ddf`.
La coverage e `source_preflight` sono pronti per `as_of=2026-10-08`; la prova
è datata e non vale automaticamente per giorni successivi. I gate Core
aggiornati sono in §25 e M23. Per decisione dell'utente, il package Core
0.13.0 è stato pubblicato dopo i gate Core e lo smoke wheel; Docker,
PostgreSQL e accettazione Platform persistente restano separati e differiti.
Vedi §26–27 per confini ed evidenza del rilascio.
**Ambito:** elettricità domestica BT, residente e non residente, nel percorso
prospettico della Spec 013. Nessun valore per un periodo successivo è attestato
da questa spec. L'esempio A/B del 2026 è una fixture sintetica.

## 1. Stato osservato e gap

| Contratto locale al 2026-10-07 | Limite da colmare |
| --- | --- |
| `DomesticProjectionAnchor` frozen, `as_of`, `validity`, fonti, valori `Decimal` e riferimenti; loader con risoluzione per `as_of` | Q3 e Q4 coesistono come artefatti immutabili. L'anchor Q4 incluso vale `[2026-10-01, 2027-01-01)`; la coverage inclusa è pronta solo per `as_of=2026-10-08`. |
| `refresh_regulatory_anchor(as_of, registry_reviews)` verifica un anchor esistente; `RegulatoryRolloverService` separa discovery, parsing, mapping, validazione, candidate, coverage, staging e promozione | Il refresh legacy non genera successori. Il rollover acquisisce i cinque canali e usa la matrice di fonti versionata per i campi Q4; le scansioni incomplete e gli aggiornamenti collegati ma non interpretati restano bloccanti. |
| `projection_anchor_digest` usa il JSON completo, compreso `retrieved_at`; M1 aggiunge `RegulatoryFact`, build key e schema v2; M4 aggiunge mapping e candidate immutabile; M5–M8 aggiungono coverage, ledger, workflow e contract envelopes | `build_key` esclude `fetched_at`; il digest artefatto include la provenance completa. Il repository Core di riferimento resta in-memory; Platform Spec 013 implementa localmente la persistenza PostgreSQL/Blob per l'uso del job. |
| CLI `projection_cli --refresh-anchor` verifica il package; la façade Python `refresh_regulatory_state` orchestra il rollover tramite porte configurate | L'anchor Q4 è stato verificato, staged e promosso una sola volta; coverage e preflight sono pronti per il giorno documentato. Il CLI non espone `--rollover`; il job invoca la façade Core. |
| Platform, implementazione locale Spec 013: worker separato, repository PostgreSQL/Blob, current/staged/history, coverage, cursor, review, eventi e CAS | La release Core 0.13.0 include gate Core e smoke wheel. PostgreSQL 17, restart/concorrenza persistente e job giornaliero Platform sono fuori da questa release e restano da verificare prima dell'accettazione Platform in produzione. La Platform non implementa policy/parser. |

Il package Core 0.13.0 comprende adapter ufficiali, parser e mapping
versionati, modello candidate, workflow rollover, manifest/schema aggiornati e
gli artefatti Q4 con provenance. La pubblicazione Core non certifica il job o
lo store Platform: il relativo collaudo è separato come specificato in §26.

## 2. Obiettivo, confini e invarianti

La routine periodica Core prepara il prossimo anchor prima della scadenza,
acquisendo fonti ufficiali, interpretando soltanto formati e regole supportati,
verificando completezza e atti successivi, mettendo in staging e promuovendo
all'inizio della validità. La Platform fornisce scheduler, storage e transazioni,
ma non semantica ARERA/fiscale. Nessun I/O in `source_preflight`, `preflight`,
`compare` o `recommend`. Un errore non fa ricadere sul vecchio anchor scaduto.

- Ogni anchor pubblicato è immutabile e versionato. La correzione crea un nuovo
  artefatto ed evento di supersessione/revoca; non aggiorna i bytes storici.
- Ogni stato `VERIFIED` richiede: acquisizione ufficiale, parser/layout
  supportato, mapping versionato, fatti completi per entrambi i profili,
  intervalli coerenti, derivazione esatta, discovery completa sino al cutoff e
  assenza di atti pertinenti non risolti. Un hash uguale è una sola evidenza.
- Nessuna fonte non riconosciuta viene interpretata da PDF/testo libero con
  OCR, keyword matching o LLM. Un atto non supportato potenzialmente pertinente
  richiede review. Un adapter può escludere automaticamente soltanto classi
  estranee al perimetro dimostrate da metadati strutturati e da policy versionata.
- Il riuso di un valore è un'operazione esplicita `carry_forward`: richiede
  validità normativa documentata, eventuale atto di conferma, controllo di
  nuove pubblicazioni e una derivazione auditabile. L'assenza di un nuovo valore
  o un errore di rete non abilita il riuso.
- La validità dell'anchor non attesta i dodici mesi futuri della proiezione.
  Costi e applicazione futura regolatoria restano stime/ipotesi della Spec 013.
- Il dominio non importa web framework, cloud SDK, DB, MCP o AI; valori
  economici e fattori usano `Decimal`, mai `float`.

## 3. Semantica temporale e preparazione anticipata

`validity = [valid_from, valid_until)` su date civili `Europe/Rome`: inizio
incluso, fine esclusa. `snapshot_as_of` è il significato del campo serializzato
`as_of` di `DomesticProjectionAnchor`, che conserva il nome per compatibilità.
Indica la data dello snapshot/interpretazione, non la chiave di selezione: per un candidate
anticipato può precedere `valid_from`. Il validator v2 deve permetterlo e
richiedere che le fonti fossero già pubblicate a quella data; il validator v1
non cambia. `fetched_at`, `discovered_at`, `coverage_checked_at`,
`staged_at` e `promoted_at` sono istanti timezone-aware distinti. Un documento
pubblicato dopo un controllo non può essere considerato coperto da quel
controllo. La durata deriva dall'intersezione dei periodi provati per ogni
fatto e dall'eventuale successivo cambio noto; non è sempre un trimestre.
Il nuovo schema ammette anche intervalli trimestrali se provati; il vecchio
artefatto mensile resta leggibile senza ampliarne la validità.

`RolloverPolicy` è configurazione validata al confine Core: default
`prepare_lead_days=30`, `coverage_max_age=1 giorno civile` per uso operativo,
`discovery_overlap_days=7`, soglie di alert 7/1/0 giorni. Il Core riceve
`as_of` e un clock espliciti, non legge il calendario nel calcolo puro.
Preparazione dovuta se `as_of >= current.valid_until - lead_days`, se non
esiste staged che inizi alla scadenza, o se nuova discovery invalida il piano.
Il job gira quotidianamente anche fuori finestra per rilevare atti imprevisti.
Se le fonti non sono ancora pubblicate, rimane `PREPARING` con
`NEXT_ANCHOR_MISSING`/`SOURCE_UNAVAILABLE`, riprova, allerta e non fabbrica B.

Per promuovere B è necessario
`A.valid_until == B.valid_from <= as_of < B.valid_until` e non devono esserci
gap, overlap o un altro current concorrente. Se il job è in ritardo, conserva
`promoted_at` reale e registra il periodo di indisponibilità; non retrodata
la promozione. Atti con effetto retroattivo generano una revoca auditabile
dell'evidenza interessata e bloccano i nuovi confronti coinvolti.

## 4. Pipeline e discovery verificabile

Fasi interne distinte:

`discover → acquire → parse → interpret/map → validate → build candidate →
verify coverage → stage → promote`.

`refresh_regulatory_coverage` riesamina A senza modificarlo; il rollover usa
gli stessi adapter di discovery ma costruisce un nuovo B. Ogni adapter
restituisce `DiscoverySnapshot` con URL, query/filtri, periodo esplorato,
numero pagine/risultati, ID ordinati, digest dei bytes di indice, versione
dell'adapter, istanti e completezza. La finestra di ricerca parte almeno
dall'ultimo cutoff riuscito meno sette giorni e copre anche modifiche/rettifiche
di atti preesistenti. Un cursore avanza soltanto dopo tutte le pagine e i
controlli; l'assenza di risultati su una pagina rotta non è prova di assenza
di atti. Rileggere l'indice completo per il periodo di rollover e confrontarlo
con il cursore evita perdite per paginazione/ordinamento. Il digest dell'indice
è evidenza dell'osservazione, non di applicabilità.

| Registro/indice ufficiale | Discovery minima da implementare | Uso del risultato |
| --- | --- | --- |
| ARERA [atti e provvedimenti](https://www.arera.it/atti-e-provvedimenti/) e [pagina elettricità/oneri](https://www.arera.it/area-operatori/prezzi-e-tariffe/oneri-generali-di-sistema-e-ulteriori-componenti) | Scansione paginata, date e ID degli atti `R/eel` e `R/com`, dettaglio/annessi e pagina tematica indipendente. Validare conteggi, pagine, ordinamento, link e rettifiche; non dedurre il prossimo URL da un nome file. | Legare un atto e l'annesso strutturato alla famiglia di parser esplicitamente approvata. Atti nuovi fuori famiglia, inclusi quelli che possono modificare accise o oneri, restano da classificare. |
| ADM [aliquote accisa nazionali](https://www.adm.gov.it/portale/aliquote-accisa-nazionali), archivio e avvisi | Scansione di indice corrente, precedenti e avvisi pertinenti; snapshot dell'elenco e dei PDF collegati, data dichiarata e digest. | Un nuovo PDF non è automaticamente una variazione elettrica: solo parser specifico con locator/controlli o review auditata può attestarlo. |
| [Gazzetta Ufficiale, archivio Serie Generale](https://www.gazzettaufficiale.it/ricercaArchivioCompleto/serie_generale/2026) e ricerca per atto | Enumerare tutte le uscite e i sommari nel periodo, compresi supplementi, con identificativi redazionali, date e completezza; incrociare gli atti fiscali in perimetro. | La sola ricerca per parole non è completezza; un nuovo atto potenzialmente modificante non viene dichiarato irrilevante per silenzio. |
| Normattiva, [versioni datate](https://www.normattiva.it/staticPage/faq) e [specifiche Open Data](https://dati.normattiva.it/assets/come_fare_per/API_Normattiva_OpenData.pdf) | Rileggere le versioni datate delle disposizioni usate e, dopo prova dell'endpoint di produzione, interrogare gli atti aggiornati tra due date. Confrontare i modificanti con la Gazzetta. | L'API documentata è una possibile fonte di discovery, non un prerequisito non verificato: autenticazione, endpoint di produzione, limiti e formato vanno certificati in una fixture/live smoke separata. Se non disponibile, l'adapter ufficiale alternativo deve offrire la stessa completezza o fallire chiuso. |

La discovery produce `RegulatoryActFinding` per ciascun nuovo ID nel perimetro:
`supported`, `irrelevant_by_versioned_rule`, `review_required`. Ogni
esclusione conserva rule ID e metadati ufficiali. Il controllo incrociato
ARERA tematico/atti e Gazzetta/Normattiva è obbligatorio dove applicabile.
Tutti e cinque i canali devono avere scan completo alla data operativa;
`registry_reviews` manuali restano una via esplicita per una decisione
eccezionale, mai un flag booleano che dichiari vuoto un registro non letto.

Il classifier Core predefinito riconosce soltanto i metadati esatti già
verificati per ARERA `343/2026/R/com`, Gazzetta `26A04702` e il decreto MEF
`26A04766`. La regola `known-q4-act-review/v1.0.0` mantiene i primi due in
`REVIEW_REQUIRED`. Per il solo decreto `26A04766`, il testo ufficiale verificato
mostra una rideterminazione dell'accisa sul gasolio usato come carburante dal 6
al 10 settembre 2026. La regola `gazzetta-diesel-excise-out-of-scope/v1.0.0`
lo classifica `IRRELEVANT_BY_VERSIONED_RULE` rispetto ai fatti fiscali
dell'anchor elettrico Q4, che inizia il 1° ottobre. La regola richiede canale,
ID atto/documento, date e URL ufficiale esatti; un metadato discordante o un
atto/errata corrige distinto resta review generica. Non si deduce irrilevanza
dal solo titolo, da keyword o da ID simili. Un classifier iniettato per
test/replay sostituisce esplicitamente il default.

## 5. Modelli, parsing e interpretazione

I nuovi modelli frozen vivono in `arera/` o nel dominio regolatorio; i payload
di integrazione vivono in `integration/`. Nomi indicativi ma campi e semantica
sono vincolanti:

| Modello | Dati necessari |
| --- | --- |
| `RegulatorySourceSnapshot` | source/URL ufficiale/ID documento e atto, bytes raw custoditi separatamente, raw SHA-256 e digest dei metadata/facts canonici, fetched_at, published_at, MIME/size, adapter/versione, periodo dichiarato, final URL allowlisted e status di acquisizione. |
| `DiscoverySnapshot` | registro, periodo interrogato, query e pagine/total count, ID trovati, raw index digest, discovered_at, adapter version, cursor di ingresso/uscita, completezza e cross-check. |
| `RegulatoryFact` | fact ID, famiglia/segmento/componente/quota, valore `Decimal` o decisione strutturata di conferma, unità originale e normalizzata, validità half-open, fonte+digest, sheet/cell o sezione/tabella, parser ID/version, raw token, trasformazione esatta, confidence `verified/unverified/review_required`. |
| `MappingDecision` | mapping ID/version, input fact ID, output field, formula/operandi e conversioni, regola di applicabilità, atto di conferma/supersessione, review ID opzionale. |
| `RegulatoryAnchorCandidate` | `build_key`, candidate/anchor ID, schema version, `as_of` (snapshot), validità, set ordinato delle fonti e dei facts, valori/derivazioni, parser/mapping/review version, validation/verification result. Timestamps operativi sono audit separato. |
| `RegulatoryRolloverAttempt` | Chiave di ciclo `(current ID, target start)` più input fingerprint/versione del tentativo, stato del workflow e puntatore candidate se già costruito; transizioni registrate nel ledger append-only. |
| `RegulatoryCoverageResult` | Anchor ID/digest, `as_of`, snapshot di discovery e source checks, coverage evidence, `ready`, codici di blocco e cutoff; non contiene raw bytes. |
| `RegulatoryState` | current ID, staged ID opzionale, generation/revision, cursor per registro, ultimi run, evidenze e revoche append-only, history di promotion; nessun update dei bytes anchor/candidate. |
| `RegulatoryRolloverReport` | `as_of`, active/staged IDs e digest, candidate state, health, giorni alla scadenza, discovery/coverage cutoff, reason codes, retry/review references, azioni effettuate. |

I parser sono registrati per `(source_family, act_type, layout_version)` e
rifiutano ogni variante non approvata con `UNSUPPORTED_REGULATORY_SOURCE` o
`PARSER_FAILURE`. Richiedono struttura/colonne/fogli attesi, units, celle,
profili, periodo e controlli anti duplicato. L'importer XLSX Spec 005 può
essere riusato soltanto se l'anno/layout reale è supportato; il suo bundle
source-faithful non diventa un anchor senza mapping. Per PDF/HTML fiscali
si approva un parser delimitato a documento/tabella/elementi esatti con fixture
golden e controllo dell'atto; nessun estrattore PDF generico promuove valori.
Il parser ADM v1 legge soltanto pagina 5 del PDF di undici pagine, verifica
titolo/sezione/data dichiarata, associa con coordinate la riga «per qualsiasi
applicazione nelle abitazioni» al token EUR/kWh e al riferimento D.M. 30/12/2011.
Le date e gli ID del record devono coincidere con il documento acquisito. Il
periodo del fatto inizia alla data di aggiornamento del listino e usa `date.max`
come estremo aperto tecnico «fino a sostituzione»; questo sentinel non prova da
solo validità futura: coverage e promozione devono dimostrare una discovery ADM
completa e che il documento resti quello corrente al cutoff. Una nuova
data/lista sostituisce il fatto nel candidato; layout, unità o riga non allineati
producono review. L'extra Core `arera` include `pypdf` per il parser.
Il gateway di acquisizione applica HTTPS e host ufficiali allowlisted, limiti
di bytes/tempo, MIME atteso e controllo del redirect finale; conserva sempre
raw digest e metadata prima di interpretare.
Il mapping produce separatamente `network_total`, `system_total`, accisa e
IVA; non somma totali e atomici, non tratta `CDISPD` come regolato, verifica
entrambi i profili e ogni quota attesa. La continuità fiscale richiede prova
esplicita di vigenza e assenza di modificanti, non copia cieca del vecchio JSON.

La validità del fact è distinta dalla validità del documento: la fonte
`arera_588` nell'artefatto corrente ha `effective_period` fino al 2026-04-01,
ma alcuni valori sono citati insieme a conferme successive. Il mapping nuovo
deve rappresentare tale catena, oppure bloccare; non deve estendere il periodo
della fonte cambiando il suo metadata.

## 6. Candidate, verifica, identità e persistenza

La build deterministica ordina facts/fonti e calcola `build_key = SHA-256`
di versione di schema, periodo, digest raw, facts canonici, mapping/parser
versionati e decision IDs. `created_at`, `fetched_at` del rerun, worker ID e
ordine di arrivo non entrano nel build key. La prima acquisizione usata nella
build viene congelata come osservazione immutabile. Un `build_key` esistente
restituisce lo stesso candidate; due bytes/valori diversi per la stessa chiave
producono `DETERMINISM_VIOLATION`, mai una seconda versione silenziosa.

L'anchor pubblicato ha un `anchor_id` semantico content-addressed e un
`artifact_sha256` sui bytes canonici completi effettivamente conservati.
Il digest completo include provenance e timestamps congelati. La
serializzazione canonica riusa envelope UTF-8, key sort, `Decimal` string,
no float, no duplicate keys/non-finite, e versiona schema/canonicalizer.
L'attuale `projection_anchor_digest`/schema v1 conserva la sua semantica per
gli anchor storici: un serializer/digest version-specific non deve aggiungere
campi default v2 ai bytes canonici v1. Il v2 introduce identificatori nuovi
senza ricalcolare o rinominare A. Raw bytes restano in blob privati indirizzati
da digest, fuori dagli envelope Core–Platform. La Platform verifica il digest
a ogni lettura.

`verify_candidate` richiede fonte ufficiale, completezza di discovery, nessun
atto irrisolto, facts/mapping completi, confronti incrociati di unità e periodi,
regole fiscali, validità adiacente a current, parser/mapping supportati e
canonical replay dagli snapshot raw (fixture sintetiche nei test). Uno staged
verificato prima di `valid_from` è condizionato al cutoff delle pubblicazioni:
prima della promotion si esegue nuova discovery, si ricontrollano le fonti di
B e si emette coverage per B riferita esattamente ad `as_of`. Si invalida lo
staging se appare un atto modificante. `STAGED` non rende B current né abilita
il confronto prima di `valid_from`.

Repository Core come `Protocol`, con implementazione in-memory per test.
Platform implementa persistenza: porta privata per i raw bytes che il Core
acquisisce e interpreta (senza esporli in envelope), tabella immutabile per
source snapshot,
discovery, facts, candidate e anchor; ledger append-only per review, stage,
promotion e revoche; riga puntatore `(current_id, staged_id, generation)`.
Vincoli unici su raw digest, build key e anchor ID; `stage` e `promote` usano
compare-and-swap transazionale su generation e ID attesi. Nella transazione
promotion: verificare precondizioni, inserire eventuale anchor immutabile,
spostare current B, svuotare staged, appendere evento e incrementare revision.
Se B è già current con lo stesso digest, il rerun restituisce `already_promoted`;
un altro B/digest produce `PROMOTION_CONFLICT`. I reader vedono A o B, mai
uno stato intermedio. A diventa historical senza mutazione.

## 7. State machine

`CURRENT` è il ruolo del puntatore, non lo stato di un candidate. Il ciclo
persistito del `RegulatoryRolloverAttempt` è
`PREPARING → VERIFIED → STAGED → PROMOTED`, con `REVIEW_REQUIRED` o
`REJECTED` terminali per quella versione; il candidate immutabile compare
soltanto dopo la build. Una correzione
produce un nuovo build key/versione e lega l'evento precedente. `BLOCKED`,
`PREPARATION_NOT_REQUIRED` e `PROMOTION_READY` sono health/action derivati,
non stati salvati nel candidate.

| Stato/evento | Precondizione | Transizione / effetto |
| --- | --- | --- |
| Nessun candidate; lead time non raggiunto | current valido, nessun atto nuovo | `PREPARATION_NOT_REQUIRED`; refresh coverage current continua. |
| Avvio preparation | scadenza vicina o nuovo atto | `PREPARING`; checkpoint discovery/source, idempotency key del ciclo. |
| Build verificata | facts e coverage completi | `VERIFIED`; candidate immutabile. |
| Formato/atto/mapping incerto | scope potenzialmente pertinente | `REVIEW_REQUIRED`; nessuno stage/promotion. |
| Invariante violata | input inconsistente, intervallo invalido, build diversa | `REJECTED`/`BLOCKED` con reason code; nuovo input/versione per riprovare. |
| Stage | candidate `VERIFIED`, contiguità, CAS | `STAGED`, A resta current; rerun stessa chiave è no-op. |
| Promotion due | `as_of >= B.valid_from`, B staged, freshness e discovery del giorno completi, CAS | `PROMOTED`; B current, A historical, evento unico. |
| Promotion non possibile | scadenza A e nessun B pronto, scan stale o conflitto | `BLOCKED`, `source_preflight.ready=false`; mai fallback ad A. |

Un nuovo atto pertinente dopo staging non muta B: appende revoca di verifica,
svuota il puntatore staged tramite CAS, blocca la promotion e costruisce un
nuovo candidate o apre review. Una nuova
evidenza di coverage può essere appesa all'anchor corrente senza mutarlo.
`source_preflight` operativo è pronto solo con anchor current applicabile alla data,
coverage fresh e non revocata, catalogo e storico GME pronti. La lettura
operativa usa la revisione più recente del repository; una copia storica può
essere riprodotta offline come replay, non trattata come readiness live.

## 8. Contratto Python/Platform, scheduling e concorrenza

Superficie pubblica locale effettivamente implementata:

```python
rollover = RegulatoryRolloverService(
    repository,
    registry_adapters=core_configured_registry_adapters,
    source_port=core_configured_source_port,
    policy=rollover_policy,
)
report = rollover.refresh_regulatory_state(
    as_of,
    previous_cursors=stored_cursors,
    previous_snapshots=stored_snapshots,
    reviews=approved_review_artifacts,
)  # discovery/acquisition esplicite e workflow giornaliero

status = rollover.source_preflight(as_of, report.current_coverage)
anchor = rollover.resolve_active(as_of, report.current_coverage)
# source_preflight è tipizzato e offline; resolve_active restituisce
# DomesticProjectionAnchor se pronto, altrimenti None.

ProjectedDomesticEnergyService.source_preflight(
    as_of, catalog, market_history, anchor, coverage_evidence
) -> ProjectedSourcePreflightResult  # offline; compare consuma snapshot/evidence
```

Il costruttore `RegulatoryRolloverService` riceve `RegulatoryRepository`,
adapter di indice, porta di acquisizione e policy. Il Protocol repository è il confine per lo
storage Platform; la sua implementazione deve rendere atomici candidate,
eventi e CAS. I cursori aggiornati sono committabili solo dopo scan completi.
Il callback di classificazione è configurazione/policy del Core, non codice
Platform; se non c'è una regola Core versionata, il finding resta
`REVIEW_REQUIRED`. Gli adapter live Core non sono ancora certificati. La
Platform fornisce scheduler e binding dei protocolli, ma non interpreta atti,
sceglie valori o implementa parser.

Le fasi `discover/acquire/parse/map/verify/stage/promote` sono orchestrate dal
Core e restano testabili separatamente. `ProjectedDomesticEnergyService` ha
`refresh_regulatory_coverage(as_of, registry_reviews, fetch_source)`, già
compatibile con il contratto precedente: verifica il package e le review
fornite, senza discovery automatica né costruzione di B. Il suo alias
`refresh_regulatory_anchor` mantiene lo stesso comportamento. Il rollover
completo usa invece `RegulatoryRolloverService.refresh_regulatory_state` e
restituisce `RegulatoryAnchorCoverageEvidence` basata su discovery e source
checks; i due contratti non vanno confusi o rinominati breaking.

Il CLI `--refresh-anchor` conserva il significato precedente. Non è aggiunto
`--rollover`: senza adapter ufficiali certificati e storage durevole il
comando non può eseguire il job, mentre la façade Python consente test/replay
con repository e porte espliciti. La Platform chiama il servizio dal proprio
worker e persiste il ledger; nessun `--refresh-anchor` genera B.

Job giornaliero Platform, data civile `Europe/Rome` passata al Core:

1. Invoca una sola volta `refresh_regulatory_state(as_of, ...)` con cursori,
   snapshot e review persistiti. Internamente il Core verifica le fonti note,
   esegue discovery, aggiorna la copertura A, decide se preparare B,
   acquisisce/parse/mappa, verifica, stage e promuove se dovuto. Fallimenti
   per fase restano distinti nel report.
2. Acquisisce/persiste catalogo e storico GME con i contratti Core esistenti.
3. Chiama `source_preflight(as_of, coverage)` e `resolve_active`; combina
   `ready` con la sola freschezza catalogo Platform. Non confronta
   `anchor.as_of` con oggi.
4. Il worker cliente ricontrolla revision e `preflight(request, ...).ready`
   prima di `compare`, sempre offline.

Due worker usano la stessa chiave di ciclo `(current anchor ID, target start)`;
ogni tentativo ha inoltre un ID dei suoi input/versioni, così una nuova fonte
o review apre una versione successiva del tentativo senza mutare il precedente:
inserimenti source/candidate sono `put-if-absent` con confronto di digest,
stage/promotion CAS. Un CAS perso rilegge lo stato e restituisce no-op se
l'effetto desiderato è già presente, altrimenti `PROMOTION_CONFLICT`. Nessun
lock distribuito semantico nel dominio; il repository Platform garantisce
transazioni e unicità. L'acquisizione può essere concorrente ma non duplica
artefatti. Un crash tra fetch e stage lascia snapshot riusabili, non state
pointer parziali.

## 9. Failure model e review

I `reason_codes` sono enum stabili nel nuovo schema (detail testuale separato);
le costanti sotto hanno valori wire `lower_snake_case`, coerenti con
`CoreErrorCode` esistente:

| Codice | Classe / effetto |
| --- | --- |
| `SOURCE_UNAVAILABLE` | rete/HTTP/timeout temporaneo; retry, conserva A solo finché valido e coperto. |
| `SOURCE_CHANGED_UNEXPECTEDLY` | digest/schema di fonte conosciuta mutato; nessun valore riusato. |
| `UNSUPPORTED_REGULATORY_SOURCE` | nuovo atto/layout pertinente senza parser; review. |
| `PARSER_FAILURE` | parser supportato non legge la struttura attesa; review. |
| `MAPPING_FAILURE` | unità, componente o derivazione non determinabili; review. |
| `INCOMPLETE_COVERAGE` | pagina/registro/categoria/fact o scan mancante; blocco. |
| `AMBIGUOUS_APPLICABILITY` | effetti o profilo non determinabili; review. |
| `INVALID_VALIDITY_INTERVAL` | gap/overlap, date incoerenti; rigetto. |
| `CANDIDATE_VALIDATION_FAILED` | insieme valori/provenance incompleto; rigetto. |
| `DETERMINISM_VIOLATION` | stesso build key, artefatto diverso; blocco di integrità. |
| `PROMOTION_CONFLICT` | CAS fallito con altro stato; rilegge/riprova se equivalente. |
| `NEXT_ANCHOR_MISSING` | nessun B verificato alla scadenza; blocco. |
| `CURRENT_ANCHOR_EXPIRED` | A fuori validità; preflight falso. |
| `STALE_COVERAGE_EVIDENCE` | cutoff/data/revisione non attuali o revocati; preflight falso. |

Ogni review riceve source/raw digest e link ufficiali, discovery snapshot,
atto, periodo/settore/profilo interessato, parser/mapping versions, facts già
estratti, differenze rispetto ad A, reason, tentativi e deadline. La decisione
ha reviewer, timestamp, razionale, riferimenti normativi, scope/periodo,
`approve_mapping`/`irrelevant`/`reject`, versione e digest; entra come nuovo
artefatto nel build key. Un operatore non modifica il JSON di A o B in-place.
La review può approvare una regola/parser versionato oppure un'eccezione
limitata a uno specifico digest e periodo; non produce un bypass generale.

## 10. Osservabilità e diagramma

Eventi `regulatory.discovery.completed/failed`,
`regulatory.candidate.built/rejected/review_required`,
`regulatory.anchor.staged/promoted`, `regulatory.coverage.revoked` e
`regulatory.preflight.blocked`. Metriche a cardinalità finita:
`current_anchor_expires_at`, `days_to_expiry`, `next_anchor_status`,
`last_coverage_check`, `last_successful_discovery`, `candidate_build_result`,
`review_required`, `promotion_success/failure`; anchor ID, act ID e URL
vanno nei log/traces auditati, non come label di metriche. Il report conserva
gli ID per la diagnostica senza raw bytes o dati cliente.

```mermaid
sequenceDiagram
    participant W as Platform daily worker
    participant C as Core rollover service
    participant O as Official source adapters
    participant R as Repository/CAS
    participant P as Projected source_preflight
    W->>C: refresh_regulatory_state(as_of, cursors, snapshots, reviews)
    C->>R: read current/staged/revision
    C->>O: recheck known sources + discover registries
    O-->>C: immutable snapshots + complete scan evidence
    C->>C: parse, map, validate, build/verify B if due
    C->>R: put-if-absent candidate; CAS stage B
    alt as_of >= B.valid_from and fresh scan complete
        C->>R: CAS promote A -> B + event
    end
    C-->>W: typed report, coverage, candidate and committable cursor updates
    W->>C: source_preflight(as_of, current_coverage)
    C-->>W: ready/reasons, offline
    W->>C: resolve_active(as_of, current_coverage)
    C-->>W: current anchor or None
    W->>P: source_preflight(as_of, catalog, GME, anchor, current_coverage)
    P-->>W: ready/reasons, offline
```

## 11. Test obbligatori e acceptance criteria

Fixture sintetiche riproducibili, nessuna rete nella suite ordinaria. Golden
indipendenti dai parser (raw workbook/indice/atto → facts → mapping → B),
replay con ordine e clock controllati, serializzazione canonica e digest,
provenance per ogni valore, unità/conversioni `Decimal`, source changes e
`carry_forward`, stato/transizioni, error injection per fase, idempotenza,
CAS/concorrenza, schema v1/v2, base wheel senza XLSX e confronto offline.
Smoke live ufficiali sono opzionali/separati e non certificano nuovi valori
senza copertura e interpretazione complete.

| Livello | Verifica principale |
| --- | --- |
| Unit/domain | Intervalli, facts/Decimal, parser versionati, derivazioni, failure code e ogni transizione. |
| Contract/schema | Manifest, envelope canonici, v1/v2, bytes vietati, digest e provenance; snapshot legacy invariato. |
| Integration offline | Gateway/repository finti ma realistici, daily workflow completo, source preflight e compare con rete disabilitata. |
| Golden/replay | Raw fixture sintetiche indipendenti, A→B 30/09–01/10, ordine/clock variati e stesso build key/anchor. |
| Failure/concurrency | Fault injection a ogni fase, scansione incompleta, review, stale evidence, CAS multipli e rerun dopo crash. |
| Platform/PostgreSQL | Adapter transazionale, unique constraints, isolamento tra worker, restart e gate catalogo+Core in repository separata. |

Scenario positivo sintetico: A `[2026-07-01, 2026-10-01)`; il 2026-09-30
resta current mentre fonti supportate permettono Candidate B
`[2026-10-01, 2027-01-01)`, verifica e stage; il 2026-10-01 discovery e
coverage del giorno confermano B, un solo CAS lo promuove,
`source_preflight.ready == true` con catalogo/GME sintetici e `compare`
termina senza rete. L'esempio richiede la nuova validità v2; non riscrive il
vecchio A mensile incluso nel package.

Scenari negativi obbligatori: atto nuovo senza parser il 30 settembre →
`REVIEW_REQUIRED`, nessuna promotion, il 1 ottobre A scaduto e preflight
falso; fonte temporaneamente indisponibile → `SOURCE_UNAVAILABLE`, non
`AMBIGUOUS_APPLICABILITY`; stesso build key/bytes diversi →
`DETERMINISM_VIOLATION`; due promotion concorrenti → un solo evento; rerun
post-successo → stesso B/current/ledger; nuovo atto dopo stage → revoca e
blocco; paginazione incompleta o Normattiva/ADM non raggiungibile → nessuna
copertura inventata; cambio fonte nota → non reinterpretare A in-place;
periodi adiacenti e confine `valid_until`; customer compare con network
monkeypatched a errore e risultato stabile.

Acceptance finale Core:

1. Tutte le fasi sono pure o hanno I/O esplicito; solo acquisition/discovery
   usa rete. Ogni failure è machine-readable e fail-closed.
2. Nessun atto nuovo pertinente **nel perimetro e nei registri monitorati**
   resta senza finding/decision; coverage richiede scansioni complete e non
   soltanto otto hash.
3. Candidate B deriva da facts/parser/mapping e fonti ufficiali verificati,
   con provenance per valore; stage/promotion sono CAS e idempotenti.
4. Selezione current per validità, evidenza datata e non revocata; nessun
   confronto dopo scadenza senza B; risultati futuri restano stime.
5. Vecchi envelope/anchor restano leggibili col digest originale; nuovi schemi
   e capability sono nel manifest, CLI precedente non cambia significato.
6. Test offline e gate AGENTS passano; smoke live e Platform hanno evidenza
   separata prima di dichiarare una release operativa.

## 12. Compatibilità, migrazione e release

Nuovi schema ID normativi registrati nel manifest:
`italian-energy/regulatory-anchor/v2`, `italian-energy/regulatory-candidate/v2`,
`italian-energy/regulatory-candidate-coverage-result/v1`,
`italian-energy/regulatory-anchor-coverage-evidence/v1`,
`italian-energy/regulatory-manual-review/v1`,
`italian-energy/regulatory-discovery-report/v2`,
`italian-energy/regulatory-discovery-snapshot/v2`,
`italian-energy/regulatory-registry-cursor/v1`,
`italian-energy/regulatory-rollover-attempt/v1`,
`italian-energy/regulatory-rollover-state/v1`,
`italian-energy/regulatory-rollover-event/v1`,
`italian-energy/regulatory-rollover-report/v2` e
`italian-energy/regulatory-source-preflight-result/v1`. Capability nuova
`regulatory_anchor_rollover`.
Gli schema v1 di discovery e rollover restano decodificabili per artefatti
persistiti; gli output correnti usano v2 per conservare le decisioni di
classificazione e la provenance del finding.
Non cambiare il significato di `contract_version=1`; introdurre un v2 del
singolo payload quando cambia la shape. L'artefatto Q3 esistente è importato
una volta nel registro come current legacy, con ID/digest originali, senza
estenderne il periodo. La nuova build v2 produce B distinto. Contract version
resta `1`; manifest e schema ID sono additivi. Non viene aggiunto `--rollover`
alla CLI finché adapter e repository durevoli non sono configurati. Confrontare
wheel/sdist e manifest installati, extra ARERA opzionale e lockfile; la release
additiva è candidata a `v0.13.0` solo dopo gate e autorizzazione separata.

La Platform richiede una propria migration per tabelle append-only, vincoli
unici e puntatore CAS, un job giornaliero e un adapter Core aggiornato. La
milestone P1 è implementata localmente in Spec Platform 013: lo storage privato
salva raw bytes per digest senza interpretarli o inserirli negli envelope;
persiste artefatti canonici, current/staged/history, evidenze/discovery/review,
generation e storico, senza logica di parsing/selezione normativa. Il vincolo
Platform ora è `>=0.13.0,<0.14.0`; il Core sorgente ha metadati 0.13.0 locali,
ma il wheel locale è stato buildato nel container Platform e ha superato il
contract smoke. PyPI espone ancora 0.12.0, quindi la release resta separata.

## 13. Milestone di implementazione e stato

Ogni milestone segue `spec → test → implementazione minima → verifica →
Memory Bank`. Dopo **ciascuna** eseguire, dalla root Core:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest --cov=italian_energy --cov-branch
git diff --check
```

Se un gate è bloccato dall'ambiente, registrarlo come non verificato; non
chiamare successo un test mirato. Nessun commit/tag/push/release implicito.

| Milestone | Obiettivo, file/moduli e API/data model | Test/acceptance, dipendenze e migration |
| --- | --- | --- |
| M1 — Contract/identity | `arera/projection.py`, nuovi `arera/rollover_models.py`, `integration/serialization.py`, `manifest.py`: anchor v2, timestamps, `RegulatoryFact`, build key e artifact digest; preservare v1. | Contract/golden canonical JSON, `Decimal`, intervalli, vecchio Q3 round-trip; nessuna migration DB; dipende dalla Spec 014. |
| M2 — Discovery verticale | `arera/discovery.py`, `integration/regulatory_acquisition.py`, fixture indice ARERA/ADM/GU/Normattiva in `tests/fixtures/regulatory_rollover/`, `tests/unit/test_regulatory_discovery.py`: adapter, completezza, cursor e finding. | Pagine mancanti, overlap, rettifiche, fonte indisponibile, nessun atto e atto non supportato; nessun cursor avanza su scan incompleto. Dipende da M1. La scansione live degli indici dei cinque canali è passata il 2026-10-04; la prova non attesta l'interpretazione dei documenti o la loro applicabilità. |
| M3 — Parser/facts | Implementati `arera/rollover_sources.py`, `arera/rollover_parsers.py` e l'estrazione token OOXML in `arera/importer.py`: registry esatto e parser ARERA Spec 005. Le estensioni VAT/ADM sono registrate nelle tranche M13–M14. | Fixture raw→facts per i due profili, schema ignoto, MIME e parse error; URL/digest/fetched_at/atto/parser/version/cella/token/derivazione conservati. Un PDF/layout senza parser supportato produce review. Gate storico M3: 387 test, 95,08% branch coverage, Ruff, format, mypy e diff check verdi. Nessuna migration. Dipende da M2. |
| M4 — Mapping/candidate | Implementati `arera/rollover_mapping.py`, `arera/rollover_validation.py` e i modelli candidate/decisione in `rollover_models.py`: 12 campi charge, accisa e VAT; copertura a partizioni half-open; build key e digest artifact separati. | Fixture Q4 sintetica, due profili/tre quote, validità adiacente, gap, conflitto, valori che cambiano nel periodo, mancanza imposte, provenance incoerente e rerun con tempi operativi diversi. Candidate `UNVERIFIED`, senza carry-forward implicito. Gate: 404 test, 95,04% branch coverage, Ruff, format, mypy e diff check verdi. Dipende da M3. |
| M5 — Coverage/review | Implementati `arera/rollover_coverage.py`, `integration/projected_service.py`, `tests/unit/test_regulatory_coverage.py`: discovery datata, review artifacts e digest, alias semantico `refresh_regulatory_coverage`; il vecchio nome resta compatibile. | Nuovo atto/incomplete scan/digest diverso bloccano; rete e incertezza sono distinte; gli artefatti review sono persistiti nella coverage result. Gate: 437 test, 95,13% branch coverage, Ruff, format, mypy e diff check verdi. Dipende da M2–M4. |
| M6 — Store/staging/promotion | Implementati `arera/rollover_repository.py` (Protocol + in-memory), `arera/rollover_state.py`, `tests/unit/test_regulatory_state.py`: attempt append-only, eventi, CAS `stage`/`promote`/`revoke_staged`, anchor history. | Transizioni, immutabilità, recovery/idempotenza, due worker concorrenti e un solo evento verificati; `promote` rifà coverage alla data di validità. Gate Core: 465 test, 95,30% branch coverage, Ruff, format, mypy e diff check verdi. Lo store PostgreSQL/Blob è nella milestone Platform P1. Dipende da M4–M5. |
| M7 — Workflow/Core gate — COMPLETA | `integration/regulatory_rollover_service.py`, `projected_service.py`, `projected.py`, `tests/unit/test_regulatory_rollover_service.py`, `test_projected_service.py`: `refresh_regulatory_state`, `source_preflight`, `resolve_active` e report typed. | Fixture A→B 30/09→01/10; rerun, promozione idempotente, review, fonte indisponibile/cambiata, preflight e compare offline. Gate complessivo finale M7–M8: 498 test, 95,09% branch coverage; Ruff, format, mypy e diff check. Dipende da M2–M6. |
| M8 — Contract/compatibilità — COMPLETA | `integration/{__init__,manifest,serialization}.py`, `projected_service.py`, README e test di manifest/envelope/compare. Capability e schema ID sono additivi; nuovi envelope sono serializzabili; compare accetta l'evidence nuova e resta offline. | CLI `--refresh-anchor` conserva il significato precedente. La working tree locale porta i metadati Core a 0.13.0, senza wheel verificato né release. Gate M7–M8 storico: 498 test, 95,09% branch coverage; Ruff, format, mypy e diff check. Dipende da M7. |
| P1 — Adapter Platform — IMPLEMENTATA LOCALMENTE | In Spec Platform 013: migration/ORM/store PostgreSQL/Blob per ledger/CAS; `adapters/energy_core/python_package.py`, nuovo `workers/regulatory.py`, catalog gate, config e test Postgres. | Worker regolatorio separato, archive current/staged/history, bytes privati content-addressed, CAS, recovery e gate offline. Sei test PostgreSQL 17 sono stati eseguiti in una sessione precedente; Docker socket non è accessibile nell'ambiente di verifica corrente per ripetere i test. Nessuna formula o parser in Platform. |
| M9 — Classificazione esatta degli atti Q4 — COMPLETATA LOCALMENTE 2026-10-05, stato 343 aggiornato da M15 | `arera/rollover_classification.py` contiene regole Core versionate per gli esatti metadati già osservati di ARERA `343/2026/R/com` e Gazzetta `26A04702`; M15 aggiunge parsing e mapping dell'effetto ARERA. | Test per identificazione esatta, metadati discordanti, atti ignoti e override esplicito. Nessuna migration o schema pubblico. La 343 non resta più in review per mancanza di parser; finding diversi o metadati discordanti restano fail-closed. |
| M10 — Classificazione tipizzata del decreto MEF 26A04766 — COMPLETATA LOCALMENTE 2026-10-05 | `arera/rollover_classification.py` riconosce i metadati esatti del decreto 4 settembre 2026; la decisione iniziale fail-closed era `REVIEW_REQUIRED` finché la portata del testo non fosse verificata. | Test offline per record esatto e lookalike con date/URL discordanti. Nessuna migration o schema pubblico. La tranche M11, dopo verifica del testo ufficiale, sostituisce l'esito generico con una regola di irrilevanza limitata a questo atto/prodotto/periodo. |
| M11 — Irrilevanza versionata del decreto diesel fuori periodo — COMPLETATA LOCALMENTE 2026-10-05 | La regola `gazzetta-diesel-excise-out-of-scope/v1.0.0` classifica l'esatto atto `26A04766` come irrilevante per l'anchor elettrico Q4: il decreto tratta il solo gasolio carburante dal 6 al 10 settembre, prima del Q4. | Test TDD per l'identità esatta e review generica per un record lookalike con ID uguale e date/URL discordanti. Nessuna migration o schema pubblico. È una decisione vincolata all'atto ufficiale verificato, non un parser general-purpose. Non produce facts e da sola non abilita candidate/preflight. Gate: 591 test, 95,05% branch coverage, Ruff check/format, mypy e diff check verdi. |
| M12 — Classificazione puntuale del D.Lgs. 148/2026 fuori dai tassi domestici elettrici — COMPLETATA LOCALMENTE 2026-10-05 | La regola `gazzetta-dl148-domestic-electricity-rates-out-of-scope/v1.0.0` riconosce solo il record ufficiale `26A04702`: l'art. 12 modifica tempi di detrazione IVA, non le aliquote applicate ai consumi; l'art. 32 modifica ambiti di gas e casi di accisa relativi a produttori/usi specifici, non i tassi dell'utenza domestica elettrica rappresentati dall'anchor. | Test TDD per record esatto e lookalike; nessun parser o valore prodotto, migration o schema nuovo. Una discovery live ha rivelato che il path Gazzetta effettivo usa `caricaDettaglioAtto` con maiuscole: classifier e test sono stati allineati ai metadati. La scansione completa successiva ha coperto tutti e cinque i canali (Normattiva 1/49) usando una risposta acquisita via SecureTransport con verifica TLS attiva (`tls_verify_result=0`) e poi validata dall'adapter Core. Gate: 591 test, 95,05% branch coverage, Ruff check/format, mypy e `git diff --check` verdi. Restano finding da interpretare, nessun candidate Q4 e `source_preflight` resta chiuso. |
| M13 — Parser PDF ADM per accisa elettrica domestica — COMPLETATA LOCALMENTE 2026-10-05 | `AdmDomesticExcisePdfParser` v1.0.0 legge la sola riga domestica del PDF ADM attuale; `OfficialRegulatoryDocumentAcquirer` la seleziona solo per record ADM con data, ID, basename e MIME coerenti. L'extra `arera` include `pypdf`. | Fixture PDF sintetiche, parser TDD, variazione numerica permessa solo con layout/coordinate identici, lookalike/layout e PDF malformato o senza coordinate in review. Replay end-to-end offline, acquirer→parser, del PDF privato: `0.0227 EUR/kWh`, digest uguale all'anchor Q3. Gate Core condiviso con M14: 626 test, 95,01% branch coverage, Ruff check/format, mypy e diff check verdi. Nessuna migration/schema API. Non produce candidate e non chiude il preflight. Dipende da M3/M9–M12. |
| M14 — Parser puntuali VAT Normattiva — COMPLETATA LOCALMENTE 2026-10-05 | `NormattivaVatTableAParser` e `NormattivaVatArt16Parser` acquisiscono le versioni AKN datate esatte del DPR 633/1972, separano classificazione domestica e aliquota e producono facts VAT con derivazione e provenienza. | Fixture sintetiche AKN, replay offline delle pagine acquisite in precedenza, layout/disposizione/date non supportati in review, mapping che richiede entrambi i facts. Gate Core condiviso con M13: 626 test, 95,01% branch coverage, Ruff check/format, mypy e diff check verdi. Nessuna migration. Non certifica gli altri atti fiscali né l'applicabilità per un anchor Q4. |
| M15 — Parser ARERA 343 e conferme esplicite Q4 — COMPLETATA LOCALMENTE 2026-10-07 | `arera/rollover_parsers.py`, `rollover_models.py`, `rollover_mapping.py`, `rollover_coverage.py` e `integration/regulatory_rollover_service.py`: parser PDF puntuale v1.0.0; `RegulatoryEffectAssertion`; mapping `confirm_value` verso anchor/fact/valore precedente; acquisizione che separa URL del record e URL dei bytes. | Replay offline del PDF privato e digest; test di layout/clausole, metadata, catena esplicita, copertura annuale e coverage successiva; fixture sintetica end-to-end stage 30/09 → promote 01/10 → preflight pronto senza rete. Nessuna migration o schema pubblico. Gate Core: 657 test, 95,01% branch coverage, Ruff check/format, mypy e `git diff --check` verdi. Il report live pre-M15 del 2026-10-05 contava 853 finding; non è stato ricalcolato dopo la classificazione locale della 343 e restano altri finding da risolvere prima di candidate, promozione e preflight reali. |
| M16 — Trasporto TLS, layout live e timestamp delle evidenze — COMPLETATA LOCALMENTE 2026-10-07 | `pyproject.toml`, `uv.lock`, `arera/official_registry_adapters.py`, `integration/regulatory_rollover_service.py` e test adapter/service. Usa il trust store nativo senza disabilitare verifica certificato/hostname; deduplica la stessa delibera ARERA ripetuta nel listino; riconosce il separatore ADM osservato; crea candidate, coverage e promotion dopo il completamento delle acquisizioni e dei controlli digest. | Test su TLS verificato, duplicati/conflitti ARERA, layout ADM e acquisizione precedente al candidate. Nessuna migration/schema pubblico. Gate mirato dopo il fix: 3 test rollover passati. Il run live completo del 2026-10-07 termina con review e coverage incompleta; vedere §23. |

File Core implementati/da tenere come riferimento sono quelli nelle righe M1–M8; aggiungere
`tests/unit/test_architecture.py`, `tests/unit/test_projection_anchor.py` e
fixture sintetiche per i vincoli architetturali e di retrocompatibilità.
`src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q3.json`
deve restare byte-identico; nuovi anchor versionati avranno nomi nuovi o
storage content-addressed. Aggiornare `specs/README.md`, ADR 0017 e Memory
Bank soltanto per decisioni/risultati reali, senza dichiarare implementazione
o verifica live prima che avvengano.

Inventario Core da aprire nella sessione successiva (nuovi file marcati `+`):

```text
src/italian_energy/arera/projection.py
src/italian_energy/arera/importer.py
+ src/italian_energy/arera/rollover_models.py
+ src/italian_energy/arera/discovery.py
+ src/italian_energy/arera/rollover_sources.py
+ src/italian_energy/arera/rollover_parsers.py
+ src/italian_energy/arera/rollover_mapping.py
+ src/italian_energy/arera/rollover_validation.py
+ src/italian_energy/arera/rollover_coverage.py
+ src/italian_energy/arera/rollover_repository.py
+ src/italian_energy/arera/rollover_state.py
src/italian_energy/integration/regulatory_acquisition.py
src/italian_energy/integration/projected.py
src/italian_energy/integration/projected_service.py
+ src/italian_energy/integration/regulatory_rollover_service.py
src/italian_energy/integration/errors.py
src/italian_energy/integration/manifest.py
src/italian_energy/integration/serialization.py
src/italian_energy/integration/__init__.py
src/italian_energy/integration/projection_cli.py
src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q3.json (solo lettura)
tests/unit/test_architecture.py
tests/unit/test_projection_anchor.py
tests/unit/test_projected_service.py
tests/unit/test_integration.py
tests/unit/test_projected_contract.py
tests/unit/test_projection_cli.py
+ tests/unit/test_regulatory_discovery.py
+ tests/unit/test_regulatory_parsers.py
+ tests/unit/test_regulatory_candidate.py
+ tests/unit/test_regulatory_coverage.py
+ tests/unit/test_regulatory_state.py
+ tests/unit/test_regulatory_rollover_service.py
+ tests/fixtures/regulatory_rollover/
README.md
pyproject.toml; uv.lock solo se cambiano dipendenze
memory-bank/active-context.md; memory-bank/progress.md
```

## 14. Decisioni differite non bloccanti e rischi

La scelta del backend Platform (PostgreSQL + blob privato già presenti) e del
cadence scheduler concreto appartiene alla sua spec, ma il protocollo CAS e la
semantica Core sono qui fissati. La disponibilità/forma degli endpoint ufficiali
e la prima fonte Q4 richiedono prova live; se non supportate, il job produce
review/blocco tipizzato. Nuove famiglie normative e altri profili sono fuori
scope e richiederanno spec/parser/versioni ulteriori. L'automatismo del caso
normale vale solo per fonti e layout esplicitamente supportati: non è una
promessa di interpretare qualunque nuovo provvedimento.

**Ready for live Q4: NO.** La persistenza Platform e il job locale sono
implementati e i contratti sono fissati, ma i parser fiscali/atti e la prova
live completa dei cinque registri mancano. L'operatività resta fail-closed fino
alla certificazione dei layout e delle derivazioni e alla promozione reale.

## 16. Verifica implementativa locale — 2026-10-04

Core: suite completa `582 passed`, branch coverage `95,00%`; Ruff check,
Ruff format, mypy, `uv lock --check --offline` e `git diff --check` verdi.
La verifica include i cinque adapter, acquisizione esatta dei bytes/digest,
layout ARERA effettivamente osservato e rifiuto fail-closed dei formati ignoti.

Scansione live Core del 2026-10-04: tutti i cinque indici sono terminati con
`complete=true`: ARERA atti 43 pagine/29 record, ARERA tariffe 1/1, ADM 1/1,
Gazzetta Serie Generale 1/840, Normattiva aggiornamenti 1/48. Digest snapshot:
ARERA atti `0ae9056bf8a0a9dfab21afff330844a39cb629195f6b91fa882d1ed178f8f37f`,
ARERA tariffe `4418d096c5f287f2e24e0a5be27e4de826f69b130a86a824913b637ce503cd84`,
ADM `ee77c9c853b1edf931fe057eae3acbb14a97dbe21bdd8e135abb9a655ad7e469`,
Gazzetta `922ee671c0157446f1c5265606b7ad8d9dae083ff4eb9bd629d1dd3ec94862b7`,
Normattiva `548ea04f2a58cb14602848c078119e205609bb792a32562d73c8f5451a790b66`.
Il report complessivo è `REVIEW_REQUIRED`, `candidate_id=null`, con 919 finding
e reason `current_anchor_expired`, `stale_coverage_evidence`,
`unsupported_regulatory_source`, `incomplete_coverage`. La completezza degli
indici non afferma che tutti gli atti siano interpretati né prova coverage.

La [delibera ARERA 343/2026/R/com](https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26)
è stata scoperta con efficacia dal 2026-10-01. Le pagine ufficiali ARERA
descrivono alcune componenti come confermate, ma manca il parser/mapping Core
certificato che emetta `RegulatoryEffect` e facts completi; ADM/Normattiva e gli
atti fiscali potenzialmente pertinenti richiedono anch'essi parser e verifiche
versionati. Non si riusano implicitamente valori precedenti. Nessun candidate
Q4 reale è stato costruito o promosso; l'anchor incluso è scaduto il 2026-10-01
e `source_preflight.ready` resta false.

Platform: suite non-integration `230 passed, 6 deselected`, coverage raw
90,05%; Ruff, format, strict mypy, architecture scan,
`docker compose config --quiet` e diff check passano. Sei test PostgreSQL 17
passano con Core source locale; migration upgrade/downgrade/upgrade verificata.
Container locale buildato con wheel Core 0.13.0 e contract smoke passato.
PyPI 0.12.0 resta incompatibile con il nuovo pin Platform; nessun wheel è
pubblicato. Il rilascio 0.13.0 rimane un gate separato.

## 18. Evidenza live aggiuntiva e gate Q4 — 2026-10-04

La verifica delle fonti primarie ha ristretto, ma non rimosso, la review:

- La [pagina ufficiale ARERA](https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26)
  registra la delibera 343/2026/R/com, pubblicata il 29 settembre ed efficace
  dal 1 ottobre 2026. La [pagina operatore](https://www.arera.it/en/area-operatori/prezzi-e-tariffe/oneri-generali-di-sistema-e-ulteriori-componenti)
  indica la
  conferma dal 1 ottobre dei valori A_SOS in vigore dal 1 luglio e riporta
  conferme per A_RIM e le componenti collegate. Questo è un atto di conferma
  individuato, non ancora una catena `RegulatoryEffect` per ogni valore,
  profilo e quota del modello Core. La pagina non fornisce in un unico payload
  canonico tutti i campi dell'anchor né costituisce il parser versionato
  richiesto.
- Il [PDF ADM raggiunto dalla pagina ufficiale aliquote](https://www.adm.gov.it/portale/aliquote-accisa-nazionali)
  aggiornato al 18 settembre 2026 è stato acquisito in sola lettura,
  hash SHA-256 `4bd14b283e63a3a6c7518795010f9e1ac2ff96c9c8d52deee99e03a5631c0d33`.
  Pagina 5 e controllo visivo mostrano la riga abitazioni a `0,0227 EUR/kWh`
  con riferimento al D.M. 30/12/2011. Il dato coincide con l'accisa
  dell'anchor Q3, ma il PDF da solo non dimostra la validità completa del fatto
  per il periodo candidato né l'assenza di altre modifiche pertinenti.
- Il [D.Lgs. 148/2026 in Gazzetta Ufficiale](https://www.gazzettaufficiale.it/eli/id/2026/09/04/26A04702/sg)
  è presente nella Serie Generale e contiene disposizioni
  fiscali che richiedono verifica di ambito e applicabilità. L'assenza di un
  match lessicale non è una classificazione negativa certificata. La discovery
  non ha una regola Core versionata che chiuda tutti i finding osservati;
  restano `REVIEW_REQUIRED`.

Di conseguenza il workflow resta fail-closed: nessun candidate Q4 reale, nessuna
promotion e `source_preflight.ready == false`. Il Core e la Platform possono
acquisire e persistere gli aggiornamenti degli indici, ma non dichiarano
l'anchor autonomamente aggiornato finché parser, classificazione, applicabilità
e copertura dei fatti non sono certificate. I gate locali verdi e la discovery
live completa non sostituiscono tale acceptance.

## 19. Verifica successiva della fonte ARERA 343 — 2026-10-05

La pagina ufficiale della delibera conferma pubblicazione 2026-09-29 ed
efficacia 2026-10-01. La pagina operatore ARERA aggiornata elenca la 343 per il
periodo Q4 e descrive conferme temporali per le componenti A_SOS e A_RIM; il
comunicato sul cliente tipo fornisce totali di bolletta, non il dettaglio dei
12 campi Core per profilo e quota. Il link documentale collegato alla scheda
della delibera non ha restituito un body acquisibile nell'ispezione corrente e
non è disponibile qui un digest dei bytes dell'allegato. La pagina riassuntiva
non è un sostituto del documento o di una disposizione esplicita per ciascun
fatto.

Conseguenza: `343/2026/R/com` resta `REVIEW_REQUIRED`; non si generano effetti
di conferma copiando i valori del Q3, aggregando i totali della bolletta o
deducendo da una pagina tematica che tutte le quote siano coperte. La prossima
implementazione deve acquisire e conservare l'allegato ufficiale esatto,
certificare layout/versione e legare ciascun fatto a disposizione, profilo,
quota e periodo. Nessun candidate Q4 reale è costruito o promosso; il preflight
resta chiuso.

## 20. Valutazione puntuale del D.Lgs. 148/2026 per l'anchor elettrico — 2026-10-05

La verifica del [testo ufficiale Gazzetta, art. 12](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A04702&art.dataPubblicazioneGazzetta=2026-09-04&art.flagTipoArticolo=0&art.idArticolo=12&art.idGruppo=9&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1)
mostra modifiche ai termini di esercizio della detrazione IVA nel DPR
633/1972 e nel testo unico IVA: non modifica l'aliquota sui consumi domestici
di elettricità che l'anchor riceve da Tabella A, parte III, n. 103 e art. 16.
L'[art. 32](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A04702&art.dataPubblicazioneGazzetta=2026-09-04&art.flagTipoArticolo=0&art.idArticolo=32&art.idGruppo=14&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1)
interviene su usi del gas naturale, soggetti obbligati e specifiche officine
elettriche/usi ausiliari e su altri prodotti sottoposti ad accisa; non
modifica il tasso di accisa elettrica applicato all'utenza domestica BT
modellata dal Core.

Decisione D17 in ADR 0017: l'identità esatta `26A04702` può essere classificata
`IRRELEVANT_BY_VERSIONED_RULE` per il solo perimetro dei valori fiscali
dell'anchor domestico elettrico con
`gazzetta-dl148-domestic-electricity-rates-out-of-scope/v1.0.0`. La regola
usa canale, codice redazionale, date e struttura dell'URL osservati; ogni
variante, atto collegato o rettifica resta review. Non emette facts e non
certifica altri atti fiscali.

Una scansione delimitata dal 04/09 al 05/10/2026 ha completato tutti i cinque
canali: ARERA atti (43 pagine, 29 record), ARERA tariffe (1), ADM (1), Gazzetta
(775) e Normattiva (1 pagina, 49 atti aggiornati). Il report contiene 853
finding ancora da classificare/review; discovery completa non significa che
gli effetti siano interpretati. Il body Normattiva era 44.680 byte, SHA-256
`3f580e212d8e5761dcb5bb6a8cafe93e1dc93fd67257a809e1a11b77fcd40142`, acquisito
con TLS verificato dal trasporto macOS SecureTransport (`http 200`, verifica
0) e validato dall'adapter Core; non è stato disabilitato il controllo TLS.
Il trasporto urllib Python locale continua a non fidarsi della catena e va
verificato nel runtime Platform.

I record Gazzetta live hanno il path maiuscolo `caricaDettaglioAtto`; il
matcher locale attendeva un path minuscolo e lasciava gli atti in review
generica. La correzione ora classifica il replay dei metadati esatti
`26A04702` e `26A04766` con le rispettive regole versionate.

La pagina ufficiale ARERA per oneri elenca A_SOS, A_RIM, UC3 e UC6 e registra
per Q4 la conferma dei valori in vigore dal 1 luglio (A_SOS/UC3/UC6) e dal
1 gennaio (A_RIM); la pagina gas elenca a sua volta le conferme GS/RS/UG1/RE/UG3.
Sono controlli ufficiali utili a circoscrivere l'effetto, ma restano pagine
tematiche e non forniscono il body dell'atto o una disposizione esatta per ogni
fact. In base al §19 non si trasformano da sole in effects/candidate: il PDF
343 ufficiale continua a rispondere HTTP 502.

La pagina menu ufficiale Gazzetta che collega l'atto è stata acquisita il
2026-10-05 13:57:34 UTC: 34.322 byte, SHA-256
`95d149e7e2302768e366621a908acf05d395ae9e3646a9cf70ae45bf9cbce012`. È un
indice dell'atto, non il body dei singoli articoli; i testi ufficiali degli
artt. 12 e 32 sono stati ispezionati separatamente e i loro body raw non sono
stati archiviati nel repository. Il PDF ARERA 343 ufficiale ha restituito
HTTP 502; gli altri finding fiscali non classificati restano review. Nessun
candidate Q4 reale è stato costruito/promosso e il preflight rimane chiuso.

## 17. Decisioni persistenti di discovery e checkpoint — 2026-10-04

`DiscoverySnapshot` v2 conserva una classificazione versionata per ogni atto
osservato, il `source_record` completo e `classification_complete`. Il report
v2 porta i finding attraverso le finestre di overlap: `REVIEW_REQUIRED` non
scompare quando un atto esce dalla finestra, mentre una decisione di irrilevanza
versionata non viene riaperta. Una rettifica di metadati genera review anche
quando i due snapshot non si sovrappongono. Il `source_record` incorporato
consente acquisition, coverage e audit del finding storico. Snapshot v1 si
caricano con classificazione incompleta e devono essere classificati di nuovo;
non vengono promossi a baseline normativa per effetto di default impliciti.

Il workflow considera un finding `SUPPORTED` come motivo per iniziare un nuovo
candidate solo quando i facts acquisiti coprono il prossimo `valid_from`;
un'acquisizione fallita continua invece a produrre reason code e retry. Questo
evita che, dopo la promozione di B, gli atti di Q4 generino un candidate spurio
per il trimestre successivo, senza nascondere outage, cambi o review.
Acquisizione e compare restano separati; l'integrazione Platform richiede i
report/schema v2 per nuovi run e mantiene la lettura degli envelope v1 già
persistiti. L'archivio seleziona come baseline l'ultimo snapshot **completo**
per canale; uno scan incompleto non sostituisce né cancella il checkpoint
precedente.

Gate Core rinnovato: `587 passed`, 95,06% branch coverage, Ruff check/format,
mypy, `uv lock --check --offline` e `git diff --check` verdi. Gate Platform
rinnovato: `233 passed` unitari con 90,10% coverage; Ruff, format, strict mypy,
architecture scan e Compose config verdi. I due test PostgreSQL 17 del
repository rollover passano sul database dedicato. La scansione live precedente
resta `REVIEW_REQUIRED` con 919 finding: nessun parser/mapping Q4 fiscale o
dell'effetto ARERA 343/2026/R/com è stato certificato; nessun candidate Q4 è
stato costruito o promosso e `source_preflight.ready` resta false. Non è stata
eseguita alcuna release.

## 15. Decisioni implementative aggiuntive — 2026-10-04

### Effetti regolatori espliciti

Ogni fatto numerico porta un `RegulatoryEffect` versionato: `set_value`,
`confirm_value`, `amend_value` o `terminate_value`. Una conferma/modifica/
cessazione deve indicare l'anchor precedente, il valore precedente e il fatto
precedente, oltre alla disposizione nel documento. Il mapping confronta tale
catena con il valore del current anchor e blocca riferimenti o importi incoerenti.
L'uguaglianza del digest di una fonte non costituisce conferma normativa.

### Recupero dopo `valid_from`

La costruzione tardiva non è ammessa dal mapper in generale. Il workflow può
abilitarla solo quando tutte le cinque scansioni sono complete e ciascuna
copre `[current.valid_until, as_of + 1 giorno)`, senza saltare il periodo
scaduto. Le fonti del candidate devono dimostrare la validità al giorno del
run; poi la stessa invocazione può stage e promuovere. `promoted_at` registra
l'istante effettivo e non viene retrodatato. Senza prova completa l'anchor
scaduto resta inutilizzabile e il preflight rimane chiuso.

### Job Platform e store

La Platform possiede job giornaliero e persistenza durevole, mentre Core
acquisisce e interpreta. L'archivio Platform memorizza bytes raw privati
content-addressed e artefatti Core canonici immutabili. Stage/promotion sono
protetti da transazione e CAS su generation. Il job catalogo non avvia più il
rollover e congela gli ID/digest dell'anchor e della coverage risolti dal Core.
Spec Platform 013 definisce lo store e il worker separato dalla pipeline
catalogo.

### Compatibilità schema

La catena di effetto è additiva e deve essere serializzata con uno schema
versionato del candidate. Le vecchie envelope/candidate già persistite restano
leggibili; la serializzazione corrente usa lo schema più recente. Nessun anchor
v1 incluso è riscritto. Il bump di versione Core e il pin Platform si
preparano, ma pubblicazione e live certification sono gate distinti.

## 21. Parser versionato della riga ADM domestica — 2026-10-05

È stato aggiunto `AdmDomesticExcisePdfParser` (layout
`adm-national-excise-pdf-v1`, parser `adm-national-domestic-electricity-excise`
v1.0.0). L'acquisitore Core assegna questa famiglia solo a record ADM con ID,
data del registro, basename URL e MIME coerenti; non classifica PDF diversi.
Il parser richiede il PDF non cifrato di 11 pagine, la pagina 5/11, intestazione
e data di aggiornamento esatte, riga domestica e importo univoco allineati nei
bounding coordinates della tabella, unità `EUR/kWh` e riferimento al D.M.
30/12/2011. Emette un `RegulatoryFact` `Decimal`, con token raw, atto, URL,
digest, `fetched_at`, parser/versione, locator e periodo half-open iniziato alla
data del listino. `date.max` significa solo “nessuna sostituzione nota nel
documento corrente”: la discovery ADM completa al cutoff e la verifica prima
della promotion restano obbligatorie.

Test offline coprono layout sintetico, valore mutato con struttura invariata,
identità/MIME/layout sconosciuti, riga non domestica e PDF malformato. Il replay
del PDF ADM conservato privatamente in `/private/tmp` ha prodotto `0.0227`
EUR/kWh per `[2026-09-18, 9999-12-31)`; il digest coincide con la fonte ADM
già fissata nell'anchor incluso (`4bd14b283e63a3a6c7518795010f9e1ac2ff96c9c8d52deee99e03a5631c0d33`).
Il file non viene copiato nelle fixture o distribuito. Questa verifica valida
il parser sullo snapshot disponibile, non certifica un'acquisizione live,
l'applicabilità del periodo Q4 o la promozione di un anchor.

Nota del 2026-10-07: il precedente replay ADM del 2026-10-05 non includeva
ancora il PDF 343 e questa conclusione è superata dalla sezione 22. La
disponibilità e il parsing locale della 343 non chiudono però gli altri finding
di discovery e non certificano un candidate o il preflight live.

## 22. Delibera ARERA 343/2026/R/com — conferme elettriche Q4 — 2026-10-07

Il PDF fornito dall'utente è identificato con il collegamento ufficiale ARERA
`https://www.arera.it/fileadmin/allegati/docs/26/343-2026-R-com.pdf`. Il
2026-10-07 il trasporto Core l'ha acquisito live con verifica TLS attiva:
427.425 byte, SHA-256
`685691673341be23f479823c61b18c37fe24360f629ff3f8b3c5c847888db30e`, uguale
al file fornito dall'utente.
Identità attesa: pubblicazione 2026-09-29, delibera `343/2026/R/com`, otto
pagine, efficacia dal 2026-10-01. Il file privato non viene aggiunto alle
fixture o al repository; il trasporto di produzione conserva i bytes raw nello
store privato Platform.

Il parser `arera-343-q4-confirmation` v1.0.0 riconosce solo il PDF, URL, atto,
data e layout esatti. Valida l'identità nel frontespizio, il dispositivo
elettrico completo dell'articolo 1 e l'entrata in vigore dell'articolo 4.2.
Produce quattro `RegulatoryEffectAssertion` non numeriche:

| Assertion | Fonte normativa | Profilo Core |
| --- | --- | --- |
| conferma `ASOS` dal 2026-07-01 | Art. 1.1, per utenze non intestate a imprese a forte consumo | entrambi i profili domestici; tutte le quote presenti nel current anchor |
| conferma `ARIM` dal 2026-01-01 | Art. 1.3 | entrambi i profili domestici; tutte le quote presenti nel current anchor |
| conferma `UC3` dal 2026-01-01 | Art. 1.4 | entrambi i profili domestici; tutte le quote presenti nel current anchor |
| conferma `UC6` dal 2026-01-01 | Art. 1.4 | entrambi i profili domestici; tutte le quote presenti nel current anchor |

Le assertion hanno validità target `[2026-10-01, 2027-01-01)`, locator,
testo-regola, URL, digest, documento, `fetched_at`, parser e versione. Gli
articoli 1.2 e 1.5 riguardano utenze energivore/regimi TIPPI fuori dai profili
Core; 1.6 riguarda la ripartizione fra conti e 1.7 la destinazione del gettito,
non una tariffa cliente. Gli articoli gas 2–4.1 non sono mappati nell'anchor
elettrico. Un cambiamento inatteso in una clausola classificata riporta il
documento a `UNSUPPORTED_REGULATORY_SOURCE`/`REVIEW_REQUIRED`.

Il documento non pubblica importi. Il mapping può quindi usare l'assertion
solo per una decisione `confirm_value` che contiene anchor ID, valore e fact ID
precedenti e ha valore identico a quello già pubblicato. Non crea un fatto
numerico dal testo `sono confermati`. `ASOS` deve corrispondere al periodo
iniziale della fonte precedente `arera_227`; `ARIM`, `UC3` e `UC6` al periodo
iniziale di `arera_588`. Per `network_total`, oltre a UC3/UC6 deve essere
presente il riferimento annuale `arera_575` con validità che copre tutto il
candidate period; per `system_total` servono ASOS e ARIM. Una tariffa che manca
dall'anchor corrente, un valore diverso, una fonte annuale non valida o una
assertion incompleta non viene costruita e blocca il candidate. Il rerun tardivo
al 2026-10-07 è ammesso solo con le cinque discovery complete da
`current.valid_until` a `as_of + 1 giorno`, fonti fiscali correnti e assenza di
altri finding non risolti. Un parser riuscito non equivale a una promozione.

Il classifier versionato risolve la copia della stessa delibera nell'indice
generale ARERA come duplicato della scansione tematica; solo il record esatto
dell'indice oneri è passato al parser. URL o metadata discordanti rimangono in
review. Il source gateway scarica l'URL ufficiale del PDF esatto, mantenendo
`record_url` e `acquired.url` distinti e controllando URL finale, MIME, digest,
size e orario; non disabilita la verifica TLS.

### Decisione D19 — le conferme normative non sono fatti numerici

- **Problema:** la 343 dichiara alcuni valori confermati ma non li riporta.
- **Alternative:** estrarre numeri per euristica; copiare l'anchor senza catena;
  modellare assertion normative non numeriche e legarle al valore precedente
  solo nel mapping Core.
- **Scelta:** parser PDF esatto produce assertion tipizzate; il mapper crea
  `confirm_value` solo se il link al current anchor e tutte le altre fonti
  applicabili sono verificabili. `as_of`, fonte e digest dell'atto restano
  provenienza del nuovo candidate; l'anchor precedente non viene modificato.
- **Motivo:** il contenuto non contiene importi e non autorizza una loro
  estrazione; il legame esplicito soddisfa il requisito anti-fallback.
- **Conseguenze:** il Core ora acquisisce la 343 dall'URL PDF ufficiale
  mantenendo distinti URL record e URL dei bytes, produce quattro assertion
  non numeriche e le propaga nel fingerprint/build del candidate. Coverage
  accetta l'assertion Q4 mentre non si sovrappone alla validità dell'anchor Q3;
  dopo una materializzazione `confirm_value` verificabile, resta coperta anche
  dall'anchor Q4. I test offline includono il replay privato del PDF, layout
  sintetici, catena esplicita dei valori, candidate 30/09 e promozione 01/10 con
  preflight senza rete. Gli altri finding live continuano a bloccare.
  **Differito:** candidate Q4 live, preflight live, certificazione degli altri
  finding e release Core 0.13.0.

## 23. Gate live Core dopo M16 — 2026-10-07

Il run ripetuto con il clock reale del servizio e trasporto Core standard ha
completato la scansione `[2026-09-01, 2026-10-08)` su tutti i cinque canali:
ARERA atti 43 pagine/29 record, ARERA tariffe 1/1, ADM 1/2, Gazzetta Serie
Generale 1/889 e Normattiva 1/49. Totale 970 record. Le classificazioni sono
un record `SUPPORTED` (`343/2026/R/com`), 966 `REVIEW_REQUIRED` e 3
`IRRELEVANT_BY_VERSIONED_RULE`; il report espone 967 finding perché omette le
tre decisioni di irrilevanza.

Il Core ha acquisito la 343 dall'URL ufficiale con verifica TLS attiva: 427.425
byte, digest `685691673341be23f479823c61b18c37fe24360f629ff3f8b3c5c847888db30e`,
uguale al PDF fornito dall'utente. Il parser ha prodotto quattro assertion
non numeriche. La correzione M16 ha eliminato il falso
`SOURCE_CHANGED_UNEXPECTEDLY` causato dal timestamp di creazione anteposto
all'acquisizione: il run aggiornato non riporta più tale reason. Ora l'esito
espone `INCOMPLETE_COVERAGE` e `UNSUPPORTED_REGULATORY_SOURCE`, senza creare
candidate, stage o promotion.

Il pacchetto Q3 rimane `[2026-09-01, 2026-10-01)` ed è scaduto. La coverage
current è `ready=false`; `source_preflight.ready=false` con
`CURRENT_ANCHOR_EXPIRED`, `UNSUPPORTED_REGULATORY_SOURCE` e
`NEXT_ANCHOR_MISSING`. Fra i finding ARERA non interpretati compare la
[delibera 338/2026/R/eel](https://www.arera.it/atti-e-provvedimenti/dettaglio/26/338-26),
oltre ad altri atti elettrici. Anche i due aggiornamenti ADM, 887 record della
Gazzetta e 49 aggiornamenti Normattiva restano in review. Non è sufficiente
classificarli via titolo o keyword; occorrono parser/regole versionati e prove
di applicabilità per i fatti dell'anchor. L'anchor Q4 non è quindi certificato.

Le suite Core locali e il build package sono gate distinti dalla certificazione
live. Il run usa un repository in-memory e non verifica il persist dello store
Platform, la ripartenza del worker o la promozione atomica in PostgreSQL. La
release 0.13.0 resta bloccata finché i finding pertinenti/non risolti non sono
classificati da policy verificate, il candidate Q4 non è verificato e promosso,
il preflight non è pronto e il gate Platform non è ripetuto end-to-end.

## 24. Piano di chiusura della certificazione e della 0.13.0 — 2026-10-07

Questo piano è una fotografia del 7 ottobre; gli avanzamenti verificati l'8
ottobre e i blocchi ancora presenti sono registrati nella sezione 25.

### Stato già verificato

- Core locale: 663 test, 95,01% branch coverage, Ruff, format, mypy, lock check
  e diff check passati; wheel e sdist locali costruite e wheel smoke isolato
  passato. La 343 è acquisita con TLS verificato e il parser produce quattro
  conferme esplicite. Questi risultati non equivalgono alla certificazione Q4.
- Platform locale: Ruff check/format, mypy su `src tests`, contratti di
  architettura, controllo licenze, `git diff --check` e 233 test non-integration
  con 90,10% coverage passati il 2026-10-07. La suite PostgreSQL non è stata
  eseguita: in questa sessione mancavano `ENERGY_PLATFORM_DATABASE_URL` e Docker.
- Certificazione live: 970 record acquisiti su cinque canali, ma nessun
  candidate Q4, stage o promotion; `source_preflight.ready=false`. Il Q3 è
  scaduto il 2026-10-01.

### Milestone residue

| Ordine | Obiettivo e file principali | Test e criterio di uscita |
| --- | --- | --- |
| R1 — Chiudere il perimetro delle fonti | In `arera/discovery.py`, `arera/rollover_classification.py` e negli adapter, definire una matrice versionata per ogni campo dell'anchor: fonte primaria, identità normativa, intervallo di applicabilità e canale ufficiale di aggiornamento. Conservare le scansioni complete, poi collegare i record ai fatti tramite identificatori ufficiali e relazioni normative. Un record si esclude solo con una regola puntuale e motivata; titolo, keyword e hash non bastano. Esaminare in particolare la 338/2026/R/eel sulla base dell'atto e del perimetro dei campi Core. | Fixture di record pertinenti, irrilevanti e ambigui per tutti i canali; replay della finestra completa. Ogni campo supportato ha una catena di fonti; ogni record non dimostrabilmente fuori perimetro resta review. Il numero 966 deve scendere solo per decisioni verificabili, non per filtri euristici. |
| R2 — Costruire e verificare Q4 | In `arera/rollover_parsers.py`, `arera/rollover_mapping.py`, `arera/rollover_validation.py` e `integration/regulatory_rollover_service.py`, completare i fatti per quote, profili, imposte e componenti Q4, inclusi gli effetti `confirm/amend/set` e la validità `[2026-10-01, 2027-01-01)`. Conservare documento, disposizione, locator, digest, parser e mapping versionati. | Golden privati da fonti ufficiali, replay deterministico e test di lacune/conflitti. Tutti i campi richiesti sono coperti senza carry-forward implicito; candidate id e digest sono stabili; `validation_result` è verificato. |
| R3 — Certificare il recupero tardivo Core | Eseguire di nuovo la scansione ufficiale completa e `refresh_regulatory_state(as_of=2026-10-07)`. Se la coverage dal 1° ottobre dimostra il candidate, stage e promote nello stesso run con timestamp reale. Salvare il report e gli artefatti raw per digest nello store di certificazione. | Nessun finding pertinente irrisolto; candidate Q4 promosso una sola volta; rerun idempotente; `source_preflight.ready == true`; `resolve_active(2026-10-07)` restituisce Q4; comparison sintetico non effettua richieste di rete. |
| R4 — Prova persistente Platform | In `Italian-Energy-Platform/specs/013-regulatory-anchor-rollover/spec.md` e nella migration/store/worker già implementati, avviare PostgreSQL 17 e ripetere migration up/down/up, CAS concorrente, restart, crash recovery, doppio job e replay con la build Core 0.13.0. Il job catalogo deve congelare ID e digest risolti dal Core. | Gate Platform completo, artefatti e cursori leggibili dopo restart, una sola promozione, nessun duplicato; test offline dimostra zero rete nel confronto. Richiede Docker e un database di test dedicato, assenti nella verifica del 2026-10-07. |
| R5 — Rilascio | Solo dopo R1–R4: ripetere tutti i gate Core e Platform, ricostruire wheel/sdist da tree pulita, installare la wheel in ambiente isolato, verificare il contratto Platform e pubblicare la 0.13.0 autorizzata dall'utente. | Versione, manifest/schema, dipendenza Platform e digest degli artefatti coincidono; smoke post-pubblicazione conferma il package distribuito. La certificazione live e il gate PostgreSQL sono prerequisiti, non sostituibili dal build locale. |

### Strategia per non revisionare indiscriminatamente 966 record

I 970 record sono una prova che gli adapter hanno letto i registri, non 970
modifiche all'anchor. La prossima implementazione deve costruire il grafo dalle
famiglie di fatti effettivamente modellate verso le fonti che possono
modificarle: provvedimenti e tabelle ARERA per gli oneri, riga domestica ADM per
l'accisa, disposizioni/versioni Normattiva per IVA e accisa, e atti in Gazzetta
collegati a quelle disposizioni. I collegamenti devono derivare da ID, URN,
relazioni di modifica e testi normativi ufficiali acquisiti; un record
sconosciuto o non collegabile rimane review. Le scansioni complete dei registri
si conservano come evidenza di discovery, ma non si trasformano in interpretazione
automatica del loro contenuto.

La [pagina ufficiale della 338/2026/R/eel](https://www.arera.it/atti-e-provvedimenti/dettaglio/26/338-26)
la descrive come aggiornamento Q4 delle condizioni del servizio di maggior
tutela, dei corrispettivi Ccm/Cpstg/Cpstgd/Cpstgm e di parti del TIV. R1 deve
confrontare le disposizioni e gli allegati effettivi con il modello dell'anchor;
fino a quel confronto, la 338 resta un finding aperto. Nessun valore del
comunicato stampa può sostituire il parser dell'atto o diventare un valore
regolatorio del candidate.

### Dipendenze e conclusione

Non resta una decisione architetturale da chiedere all'utente. Restano lavoro
Core verificabile sui record pertinenti e un prerequisito operativo per il gate
PostgreSQL 17. La 0.13.0 è pronta per proseguire l'implementazione, ma non è
pronta per la release finché R1–R4 non superano i rispettivi criteri.

## 25. Candidate Q4 da fonti live e stato di certificazione — 2026-10-08

Il run giornaliero Core del giorno 8 ottobre ha completato la discovery dei
cinque canali ufficiali. Le decisioni aggiunte in M19 sono versionate e
vincolate ai metadati ufficiali esatti: la 338/2026/R/eel e le relative
tabelle sono fuori dai campi del `DomesticProjectionAnchor` corrente; le due
edizioni ADM Q4 sono supportate dal parser della riga domestica; le edizioni
ADM storiche sono sostituite dalle due edizioni Q4; le due registrazioni della
Gazzetta per il D.Lgs. 148/2026 e il decreto sul gasolio hanno regole puntuali
già basate sull'esame ufficiale. Ogni record diverso resta in review. Queste
regole non escludono componenti di vendita protetta dal Core generale: valgono
solo per lo scope di questo anchor.

La discovery ha classificato 3 record `SUPPORTED`, 1003
`REVIEW_REQUIRED` e ulteriori record `IRRELEVANT_BY_VERSIONED_RULE` che non
entrano nel report dei finding. La scansione completa non equivale a coverage
completa. Il candidate non è verificabile finché i finding potenzialmente
pertinenti o non collegati in modo dimostrabile alle disposizioni modellate
restano irrisolti.

### Artefatto candidato

- File canonico: `src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q4-candidate.json`.
- Candidate ID: `regulatory-anchor-candidate:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`.
- SHA-256 dell'artefatto: `902354107ae452185c3a3a7d9d83dab9b2886c27a287378619b8debea0d107db`.
- Snapshot/as-of: `2026-10-08`; validità: `[2026-10-01, 2027-01-01)`.
- Mapping: validazione superata su 13 fatti e 11 decisioni. Le conferme Q4
  citano esplicitamente i fatti Q3; accisa e IVA hanno le rispettive fonti
  ufficiali acquisite l'8 ottobre.
- Stato anchor: `UNVERIFIED`; candidate non staged e non promosso. L'artefatto
  non è un anchor corrente utilizzabile nei confronti.

La riacquisizione delle due disposizioni Normattiva datate 2026-10-08 ha
prodotto IVA 10% e nuovi digest rispetto agli snapshot datati 2026-10-07 usati
dal precedente candidate. Il controllo dell'anchor Q3 segnala pertanto fonti
VAT cambiate, oltre alla scadenza già intervenuta. Il candidato aggiornato
include i digest acquisiti l'8 ottobre; questo non risolve i finding globali
della discovery.

La 338/2026/R/eel è stata esaminata nell'atto e nel workbook ufficiali. Le
modifiche trovate riguardano corrispettivi di vendita del servizio tutelato/STG
e fasce orarie, mentre questo anchor contiene totali rete/sistema, accisa
domestica e IVA. La regola d'ambito esatta elimina il finding per questo
anchor, senza affermare irrilevanza per altri prodotti Core.

### Esito e lavoro rimanente

- Il candidate Q4 è stato costruito; la sua verifica di coverage è fallita
  con `UNSUPPORTED_REGULATORY_SOURCE` a causa dei finding non risolti.
- Non sono state eseguite stage o promotion. L'anchor Q3 resta immutato e
  scaduto; `source_preflight.ready=false` e `resolve_active` non deve fornire
  un anchor utilizzabile per una data successiva al 2026-10-01.
- Il prossimo lavoro Core è collegare in modo completo e verificabile i finding
  Gazzetta/Normattiva e gli altri registri alle disposizioni che possono
  modificare i campi modellati. Non sono ammesse esclusioni globali per titolo,
  keyword, conteggio atteso o digest.
- Su richiesta dell'utente, Docker, PostgreSQL e il database di test sono
  esclusi da questa tranche. Ciò non cambia il risultato live Core: il gate
  Platform persistente resta separato.
- Gate Core dopo M19: 669 test passati, 95,02% di branch coverage, Ruff check
  e format, mypy su 104 file e `git diff --check` passati. Questi gate locali
  non certificano la coverage live: la 0.13.0 non è certificata né rilasciata.

### Diagnostica della coda review

Una scansione diagnostica completa ricostruita da zero il 2026-10-08, senza
riusare cursor o snapshot precedenti, ha letto 1011 record: 41 ARERA atti, 1
indice tariffe ARERA, 2 ADM, 917 Gazzetta Serie Generale e 50 Normattiva.
L'indice tariffe ARERA e i due record ADM sono `SUPPORTED`; 39 record ARERA,
915 record Gazzetta e 50 record Normattiva sono `REVIEW_REQUIRED`. Quattro
record risultano già esclusi da regole esatte. Questa scansione serve a
misurare la coda; non sostituisce il report del workflow né costituisce
evidenza di coverage pronta.

Il conteggio Gazzetta deriva dal parser del sommario di tutte le pubblicazioni
della Serie Generale, che conserva codice redazionale, data, titolo e URL ma
non il collegamento normativo dell'atto alle disposizioni dell'anchor. Non è
quindi un insieme di 915 modifiche regolatorie. La coda Normattiva include
codici redazionali di atti aggiornati, fra cui il TUA delle accise; non può
essere esclusa in blocco. La coda ARERA contiene anche determinazioni,
consultazioni e atti settoriali che richiedono un criterio di ambito basato su
metadati ufficiali e/o disposizioni, non su titolo.

Il prossimo lavoro è correggere il perimetro della discovery: dichiarare nel
Core le fonti/provisioni che alimentano ogni campo Q4; usare gli ID e le
relazioni ufficiali per collegare agli aggiornamenti i soli atti che possono
modificare tali fonti; acquisire e parsare quei testi con parser versionati.
La scansione completa resta evidenza di controllo, ma non ogni voce di indice
generale diventa una review manuale dell'anchor. Le fonti Normattiva ufficiali
offrono sia l'elenco degli atti aggiornati in un intervallo sia la lettura
articolo/versione tramite URN; questa è una base verificabile per la watchlist
di leggi e articoli, da certificare prima di cambiare il gate live.

### Verifica puntuale del collegamento TUA — 2026-10-08

La risposta live dell'API ufficiale Normattiva riporta per il TUA
`095G0523` l'ultimo aggiornamento del 2026-09-25 e il campo ufficiale
`ultimiAttiModificanti=26G00184`. La [Legge 166/2026 in Gazzetta]
(https://www.gazzettaufficiale.it/eli/id/2026/09/25/26G00184/sg) converte
misure temporanee per l'accisa sul gasolio; il [testo coordinato ufficiale del
DL 133/2026](https://www.normattiva.it/eli/id/2026/09/25/26A05124/ORIGINAL)
limita la rideterminazione al gasolio e a un periodo che termina il 5 settembre
2026. È dunque fuori dalla validità Q4 e dal campo `excise_rate` domestico
elettrico.

M21 conserva nel `OfficialRegistryRecord` l'ID ufficiale dell'ultimo atto
modificante restituito da Normattiva e aggiunge regole esatte/versionate per
questo collegamento TUA→Legge 166 e per il corrispondente record Gazzetta.
Layout, date o identificatori diversi restano review. I test mirati passano;
il nuovo adapter ha parsato con successo la risposta ufficiale completa dei 50
atti Normattiva (digest
`6f472940954b756cf413e0a8cf02a4133c3f51df48209c1a957bfc2f1b8d271a`).
Applicando le regole aggiornate alla scansione diagnostica indipendente dei
1011 record, l'esito è 3 `SUPPORTED`, 1002 `REVIEW_REQUIRED` e 6
`IRRELEVANT_BY_VERSIONED_RULE`: 39 ARERA atti, 914 Gazzetta e 49 Normattiva
rimangono in review. Questo replay diagnostico non è un nuovo run del workflow
e non sostituisce il report live certificato. Il candidate Q4 resta
`UNVERIFIED`, non staged e non promosso.

### Verifica della rubrica ufficiale Gazzetta — 2026-10-08

La pagina ufficiale della Serie Generale n. 226 del 29 settembre 2026 espone
ogni atto sotto un elemento HTML `span.rubrica`; il parser precedente scartava
questo dato e appiattiva le voci in ID/titolo/data/URL. L'adapter v2 deve
conservare la rubrica canonica su ciascun record Gazzetta. Una rubrica assente
o un layout non riconosciuto interrompe la scansione senza avanzare il cursore.

La prima policy automatica ammessa è limitata alla rubrica esatta
`ESTRATTI, SUNTI E COMUNICATI`: per i campi di questo anchor, queste voci
informative non sono atti che modificano le disposizioni normative o i valori
ARERA/ADM; questi ultimi restano sorvegliati dai registri ARERA e ADM e dalle
versioni normative Normattiva. La policy non cancella i record dalla discovery
né dichiara completa la scansione. Tutte le altre rubriche, inclusi leggi,
decreti, delibere e ordinanze, restano `REVIEW_REQUIRED` salvo regola puntuale
verificata. La decisione è legata al dato strutturato ufficiale, non a titolo,
parole chiave o ID.

La pagina verificata è
[Serie Generale n. 226 del 29 settembre 2026](https://www.gazzettaufficiale.it/gazzetta/serie_generale/caricaDettaglio/home?dataPubblicazioneGazzetta=2026-09-29&numeroGazzetta=226).
Il singolo controllo della struttura non è un nuovo replay completo: finché
non si esegue nuovamente `refresh_regulatory_state`, i conteggi M21, il
candidate `UNVERIFIED` e il preflight chiuso restano gli ultimi risultati del
workflow.

### M22 — replay dopo la rubrica ufficiale Gazzetta — 2026-10-08

L'adapter Gazzetta preserva `registry_section`, ottenuta dal `span.rubrica`
dell'indice ufficiale. Il classifier applica la policy versionata
`gazzetta-extracts-summaries-communications-out-of-scope/v1.0.0` soltanto alla
rubrica esatta `ESTRATTI, SUNTI E COMUNICATI`. Una rubrica assente, vuota o con
markup annidato non supportato rende la scansione incompleta e non avanza il
cursore. Tutte le altre rubriche restano review salvo regola puntuale.

Il workflow Core live è stato rieseguito il 2026-10-08 dopo questa modifica;
non si tratta più del replay diagnostico stateless precedente. I cinque canali
hanno prodotto 1011 record: 3 `SUPPORTED`, 364
`IRRELEVANT_BY_VERSIONED_RULE` e 644 `REVIEW_REQUIRED` (39 ARERA, 556
Gazzetta, 49 Normattiva). Rispetto al run M19 la review scende di 358. Le 644
review sono record non collegati dal classifier corrente, non 644 atti che
modificano i valori dell'anchor.

Il candidate Q4 è stato ricostruito con lo stesso ID/digest documentato in
§25. La validazione del mapping passa su 13 facts e 11 decisions; la coverage
del candidate fallisce ancora per `unsupported_regulatory_source`. Nessun
candidate è stato staged o promosso, `source_preflight.ready` rimane `false` e
il package Q3 è scaduto. Il confronto cliente non deve caricare il candidate e
resta offline.

Gate Core M22: 678 test passati, 95,00% branch coverage, Ruff check/format,
mypy su `src tests` e `git diff --check` passati. Docker/PostgreSQL/DB test
sono esclusi su richiesta; non è stata eseguita alcuna release.

### M23 — scope delle fonti e promozione Q4 locale

Il collo di bottiglia è ora esplicito: il gate applica la review a ogni atto
non riconosciuto dei registri generalisti, anche quando non è collegato a un
campo del `DomesticProjectionAnchor`. Non chiedere all'utente di classificarli
in blocco e non eliminarli per titolo o keyword. Aggiungere una matrice Core
versionata `anchor field → fonte/disposizione ufficiale → canali/relazioni di
aggiornamento`. Conservare tutti gli snapshot completi; usare gli identificatori
e i collegamenti normativi ufficiali per legare gli aggiornamenti alle fonti
monitorate. Solo le relazioni senza interpretazione supportata o con
applicabilità ambigua devono produrre `REVIEW_REQUIRED`; scansione, link o hash
da soli non sono prova di irrilevanza.

La matrice iniziale Q4 deve coprire le componenti ARERA confermate dalla
343/2026/R/com e le relative fonti tariffarie, la riga ADM dell'accisa
domestica elettrica con le disposizioni del TUA, e le due disposizioni
Normattiva DPR 633/1972 che formano il 10% IVA. Le fonti recenti che possono
toccare queste disposizioni vanno acquisite e valutate tramite ID/URN e testo
ufficiale delimitato; atti non supportati restano bloccanti. M23 non è completo
finché il replay live non produce candidate coverage pronta, stage/promotion
unica, preflight pronto e comparison offline. Il conteggio di record non è un
criterio di accettazione.

#### Decisione di ambito M23

Gli indici generali rimangono acquisiti integralmente e con scansione completa;
la presenza nell'indice non rende però ogni record una possibile modifica dei
valori del candidate. Per `DomesticProjectionAnchor` la matrice usa fonti
primarie con perimetro verificabile: indice ARERA delle componenti tariffarie
(e i relativi atti), indice ADM delle aliquote nazionali con riga domestica,
testi Normattiva delle disposizioni mirate del TUA e del DPR 633/1972. Il
codice redazionale Normattiva del DPR 633/1972 è `072U0633`; quello del TUA è
`095G0523`.

Un record ARERA del registro atti generico può essere escluso dal candidate solo
quando una scansione completa dell'indice ARERA tariffario mostra che non è una
fonte delle componenti modellate. Un record Gazzetta è collegato alla coverage
Q4 solo tramite un identificatore ufficiale di atto modificante riferito a una
disposizione sorvegliata, oppure tramite una relazione di fonte ARERA/ADM
registrata e versionata. Normattiva conserva l'intera scansione; solo gli
aggiornamenti del TUA e del DPR 633/1972, più gli atti ufficiali che li
modificano, entrano nel grafo Q4. La verifica usa il testo ufficiale delimitato
e la data di applicabilità, non il solo identificatore, titolo o digest.

Queste esclusioni di ambito si applicano solo dopo scansioni complete di tutti
i canali coinvolti e sono decisioni machine-readable con regola e versione.
Una scansione incompleta, una modifica non classificata, un nuovo collegamento
verso una disposizione sorvegliata o un testo non interpretabile restano
bloccanti. Gli snapshot e i record fuori ambito restano conservati come
provenance; non avanzano il cursore se la scansione non è completa.

#### Esito M23 — replay e promozione locale 2026-10-08

La matrice è implementata in `arera/rollover_scope.py` come policy Core
versionata `1.0.0`. Riutilizza lo snapshot live completo del giorno, mantenendo
tutti i cinque canali e i record originali; mette in scope le fonti tariffarie
ARERA, le relazioni ufficiali verso TUA/DPR 633/1972 e gli aggiornamenti ADM.
Scansioni incomplete, fonti sorvegliate e modifiche senza relazione certa
restano bloccanti. Il test copre paginazione completa, relazioni precedenti,
scansione tariffaria vuota, modifiche rilevanti e non rilevanti.

Il replay deterministico dello snapshot ufficiale acquisito il 2026-10-08 ha
verificato la coverage del candidate Q4; il repository Core in-memory ha
effettuato stage e una sola promotion, producendo l'anchor verificato
`regulatory-anchor:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`.
Validità `[2026-10-01, 2027-01-01)`, snapshot `2026-10-08`, digest canonico
`641c71a677d98cefe6ec562fd5665a54d3620059e61d70c6a00c397238073ddf`. Il
preflight Core è `ready=true` per il giorno verificato. L'anchor, l'evidenza
datata e l'evento di promotion sono conservati rispettivamente in
`data/billing/arera-domestic-bt-projection-anchor-2026-q4.json`,
`data/billing/arera-domestic-bt-coverage-2026-10-08.json` e
`data/billing/arera-domestic-bt-promotion-event-2026-10-08.json`.

La risoluzione dell'anchor packaged ora accetta `as_of` e sceglie l'unica
finestra half-open attiva; il CLI passa la data richiesta. Il confronto
sintetico Q4 ha prodotto tre scenari usando solo snapshot ed evidenza locale,
con acquisizione di rete disabilitata nel test. Le componenti proiettate
restano stime, non valori futuri garantiti.

M23 è completata localmente per la promozione Q4 su evidenza del 2026-10-08.
Questa prova non equivale a un refresh valido per date successive: coverage è
datata e va aggiornata dal job giornaliero. Store durevole Platform, restart,
concorrenza PostgreSQL e Docker restano verifiche Platform separate.

## 26. Decisione di release del package Core 0.13.0 — 2026-10-08

Su richiesta esplicita dell'utente, la release del package Core 0.13.0 è stata
pubblicata dopo la chiusura locale M23 e i gate Core completi. La release contiene il
candidate Q4 validato, l'anchor promosso, la coverage datata e l'evento di
promozione immutabile. Il preflight documentato è valido per `as_of=2026-10-08`;
non certifica automaticamente date successive.

Questa decisione separa la pubblicazione del package Core dal gate di
accettazione Platform. La prova PostgreSQL 17, il CAS persistente, il restart
del worker e il job giornaliero Platform non sono inclusi nella release Core e
restano da eseguire prima di dichiarare verificata l'integrazione Platform in
produzione. Docker e database di test sono stati esplicitamente esclusi
dall'utente da questo rilascio.

Il piano R1–R4/R5 della sezione 24 è superato per il solo rilascio del package:
R1–R3 sono chiusi localmente con la matrice versionata, il candidate validato
e il replay/promozione; R4 resta un gate Platform separato. R5 per Core richiede
la suite Core completa, build wheel/sdist, smoke installato isolato, commit,
tag e pubblicazione PyPI tramite Trusted Publishing. Il rilascio non attesta
che la Platform abbia già aggiornato il proprio vincolo o attivato il worker.

## 27. Evidenza effettiva del rilascio 0.13.0 — 2026-10-08

- Commit sorgente e tag `v0.13.0`:
  `e8306161d8b5056135a18f2c594cd56c1550bde9`.
- Correzione successiva del workflow dispatch sul branch `main`:
  `bc97423095b87610250f9e02e7d4ceea0bedee23`; il tag continua a identificare
  il commit sorgente immutabile precedente.
- GitHub CI del commit sorgente verde su Python 3.12, 3.13 e 3.14. Il workflow
  Trusted Publishing `37806544781` ha completato build, versione/tag check,
  upload degli asset, smoke wheel e publish PyPI. La GitHub Release è
  https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.0.
- L'API PyPI riporta `italian-energy` versione `0.13.0`. SHA-256 wheel
  `a3cc6c11e93b9d398aa8c2f8c83c65614765eb6ea447f84b06e05fa7b3ab8518`;
  SHA-256 sdist
  `b65c065572f8c8f6d883d04ef4f0cd88f03d08142c41c6ffb3b49290f8aee327`.
  Entrambi coincidono con gli asset della GitHub Release.
- Installazione isolata da PyPI verificata: import versione `0.13.0`, capability
  `regulatory_anchor_rollover`, anchor Q4 atteso e coverage `ready=true` per
  `as_of=2026-10-08`.
- Il rilascio non certifica PostgreSQL/Platform, scheduler giornaliero o la
  freschezza della coverage per date successive al 2026-10-08.
