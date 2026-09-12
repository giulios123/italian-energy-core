# Spec 011 — Confronto prospettico e raccomandazione robusta v0.11

## Stato

Specifica normativa v0.11.0 preparata. La scrittura della spec non autorizza
l'implementazione, il bump della versione del package o modifiche alla
repository Platform. Commit, tag, push, release e pubblicazione restano
operazioni separate.

## Contesto

La Spec 010 espone un contratto Core–Platform tipizzato e serializzabile per il
replay di un confronto storico concluso. Il servizio storico deriva
`as_of` dal periodo, usa gli indici storici pubblicati e richiede copertura
regolatoria verificata per l'intero periodo.

Il Portale Offerte pubblica i parametri delle offerte e gli indici storici, ma
non pubblica le quotazioni forward utilizzate per la propria spesa annua
stimata. La disciplina del Portale calcola inoltre la spesa su quattro
trimestri a partire dal trimestre di consultazione e usa i valori regolatori e
fiscali vigenti alla consultazione. Questi dati non possono essere ricostruiti
dal Core con un fallback o con una previsione implicita.

Il confronto attuale/futuro richiede quindi una semantica separata: un
orizzonte di attivazione esplicito, input prospettici tracciati, una proiezione
regolatoria dichiarata e più scenari deterministici. Il risultato non è una
certificazione della bolletta futura.

## Obiettivo

Definire un confronto all-in prospettico per i primi dodici mesi dalla data di
attivazione e una recommendation consultiva robusta rispetto agli scenari
forniti dal caller, mantenendo separati:

- fatti verificati e loro provenance;
- assunzioni sulla baseline, sui consumi e sul mercato futuro;
- costi stimati prodotti da uno scenario;
- decisione `switch` o `stay_current`.

Il Core non acquisisce curve forward, non genera previsioni e non modifica la
semantica del replay storico.

## Perimetro v0.11

Incluso:

- elettricità domestica in bassa tensione, con residenza esplicita;
- catalogo Portale Offerte acquisito alla `quote_date` e usato per tutti gli
  scenari;
- orizzonte `[activation_date, activation_date + 12 mesi)` con mesi civili e
  clamp di calendario;
- profilo di consumo futuro fornito dal caller;
- schedule completa del contratto corrente, eventualmente diversa per
  scenario;
- offerte fixed e indexed rappresentabili dal modello corrente;
- un solo scenario `base` e almeno uno scenario `stress`;
- congelamento esplicito delle componenti regolatorie e fiscali osservate alla
  `quote_date`;
- ranking prospettico e recommendation che richiede il superamento della
  soglia in ogni scenario.

Escluso:

- forecast generati dal Core o provider forward integrati;
- uso della spesa annua stimata dal Portale come sostituto del calcolo;
- gas, dual fuel, classi non domestiche, MT/AT/AAT e prosumer;
- scraping, PDF/OCR, persistenza, scheduler, API web, UI, cloud, MCP e AI;
- modifica, migrazione o reinterpretazione dei payload storici v0.10;
- modifica alla repository Platform.

## Modelli pubblici e contratto d'integrazione

La superficie stabile resta `italian_energy.integration`. Sono aggiunti i
seguenti modelli Pydantic v2 frozen, con `Decimal`, date ISO-8601 e provenance
serializzabile.

### Richiesta prospettica

`ProspectivePortalComparisonRequest` contiene:

- `quote_date`, data di riferimento del catalogo e della consultazione;
- `activation_date`, non precedente a `quote_date`;
- `projected_consumption`, un `ProjectedConsumptionProfile` fornito dal caller;
- classificazione e profilo di eleggibilità domestica BT;
- `scenarios`, una tupla di `ProspectiveScenario`;
- misure billing ed elementi esterni verificati opzionali.

L'orizzonte è derivato, non passato separatamente. `activation_date` con giorno
non presente nel mese di destinazione usa il clamp del dominio (ad esempio 29
febbraio → 28 febbraio dell'anno successivo).

`ProjectedConsumptionProfile` avvolge un `ConsumptionProfile` futuro e
dichiara `method` (`user_declared`, `historical_shifted` o `external_model`),
assunzioni e provenance. Il Core valida contenimento nell'orizzonte, assenza
di overlap, timezone civile `Europe/Rome`, granularità compatibile con le
tariffe e valori `Decimal`; non costruisce o trasla il profilo.

### Scenari e baseline

`ProspectiveScenario` contiene:

- `scenario_id` univoco;
- `role`, esattamente `base` o `stress`;
- `current_contract_schedule`, schedule di segmenti che partiziona senza gap o
  overlap l'orizzonte;
- `projected_market_data`, dati di mercato per gli indici usati.

Ogni segmento della baseline identifica tariffa, periodo, provenance e
`basis` (`contractual`, `seller_notice` o `explicit_assumption`). Le
assunzioni sono ammesse e devono essere esposte; non possono essere create
implicitamente dal Core. Tutti i segmenti conservano la stessa fornitura e
l'identità del contratto corrente.

Il market scenario base richiede dati completi per ogni indice e intervallo,
data di osservazione, provenance e stato `source_verified`. Ogni stress deve
avere dati completi, `methodology` e assunzioni esplicite; può essere una curva
verificata o una trasformazione dichiarata dal caller. Gap, overlap,
interpolazione, carry-forward e backfill sono rifiutati. Il Core non scarica e
non genera alcuna curva.

La richiesta deve contenere esattamente una base e almeno uno stress. Gli ID,
gli indici e i punti duplicati sono errori globali.

### Risultato prospettico

`ProspectivePortalComparisonResult` contiene:

- ID content-addressed della richiesta e dello snapshot Portale;
- `quote_date`, `activation_date` e orizzonte derivato;
- evidenza dell'anchor regolatorio verificato e della policy di congelamento;
- import result Portale condiviso dagli scenari;
- una `ProspectiveComparisonEstimate` per ogni scenario, con baseline,
  alternative, stime all-in, risparmi, ranking, esclusioni, assunzioni e
  warning;
- ranking base come ordinamento esposto al consumer;
- distinzione esplicita fra valori `estimated` e dati sorgente `verified`.

Il totale e il risparmio di ogni scenario sono stime del relativo scenario:
non possono essere presentati come valori `VERIFIED`, previsione universale o
certificazione della bolletta futura. Le partite esterne restano evidenza
separata e non entrano in totale, risparmio o ranking.

### Recommendation prospettica

`ProspectiveRecommendationRequest` riceve un
`ProspectivePortalComparisonResult` già calcolato e `RecommendationPreferences`.
`ProspectiveRecommendation` contiene decisione, candidata selezionata,
shortlist, risparmi per scenario, esclusioni, codici motivazione, risk notes e
assunzioni.

La recommendation:

1. applica gli stessi filtri hard tipizzati della Spec 009;
2. considera una candidata solo se calcolabile in base e in ogni stress;
3. richiede `savings >= minimum_savings` in ogni scenario, con soglia
   inclusiva;
4. ordina la shortlist secondo il costo stimato della base e poi `offer_id`;
5. restituisce `stay_current` se la soglia è assente, se una candidata non è
   robusta o se nessuna candidata è ammissibile.

Una durata economica assente può essere assunta a dodici mesi per fixed e
indexed, secondo la decisione di prodotto; l'assunzione è sempre riportata e
può essere usata dalla recommendation. Una durata nota inferiore a dodici
mesi esclude la candidata.

La recommendation non ricalcola Pricing o Billing e non modifica nessun
risultato di scenario. Le assunzioni ammesse non bloccano da sole lo switch:
la condizione necessaria è la robustezza della stessa candidata su tutti gli
scenari dichiarati.

### Schema e capability

Il contratto JSON v1 resta compatibile e viene esteso additivamente con:

- `italian-energy/prospective-portal-comparison-request/v1`;
- `italian-energy/prospective-portal-comparison-result/v1`;
- `italian-energy/prospective-recommendation-request/v1`;
- `italian-energy/prospective-recommendation/v1`.

Il manifest aggiunge soltanto le capability realmente implementate:
`prospective_portal_comparison` e `robust_prospective_recommendation`. Non viene
aggiunta una capability `forecast`. Gli envelope mantengono UTF-8 canonico,
chiavi ordinate, `Decimal` come stringa e comportamento fail-closed per float,
extra, schema o versione sconosciuti.

## Semantica economica

### Catalogo e condizioni commerciali

- La finestra di sottoscrizione dell'offerta deve contenere `quote_date`.
- La tariffa economica decorre da `activation_date`; la finestra di
  sottoscrizione non è la durata delle condizioni.
- Durata nota `< 12` mesi: esclusione `economic_terms_too_short`.
- Durata assente: assunzione `economic_terms_duration_assumed_12_months`, con
  warning e provenance del record sorgente.
- Componenti, sconti, servizi, canoni e condizioni non modellabili seguono le
  esclusioni della Spec 008; il testo libero non viene interpretato.
- L'annual estimate del Portale resta osservazione source-faithful e non entra
  nel calcolo.

### Regolazione, imposte e copertura

Il servizio seleziona l'anchor `RegulatoryRuleSet` verificato per profilo e
`quote_date`. I valori attivi alla data di riferimento vengono proiettati
sull'intero orizzonte e applicati ugualmente a tutti gli scenari, mantenendo
provenance dell'origine e stato distinto dall'applicabilità futura.

Se manca un anchor verificato, il servizio fallisce con
`coverage_unavailable`; non usa l'ultimo snapshot disponibile, valori zero o
aliquote inventate. L'anchor deve coprire esattamente il profilo domestico BT
e i parametri necessari al Billing. La proiezione non diventa
`VerificationStatus.VERIFIED`.

### Calcolo e determinismo

Ogni scenario valuta la baseline segmentata e le offerte candidate con gli
evaluator Pricing esistenti e con un percorso Billing prospettico esplicito,
senza indebolire i controlli del percorso storico. Usa lo stesso profilo di
consumo, snapshot Portale, regole congelate e policy di rounding.

Le candidate fixed non richiedono market data propri; le indexed richiedono
copertura esatta per ogni punto usato. Un errore condiviso di richiesta,
anchor, schedule o scenario invalida il confronto; un errore candidato viene
isolato nello scenario con codice e dettaglio deterministici. ID e ranking sono
invarianti rispetto all'ordine di input.

## Errori ed esclusioni

La façade usa gli errori stabili esistenti e aggiunge, se necessari al confine
pubblico, `prospective_input_invalid`, `prospective_coverage_unavailable`,
`prospective_scenario_invalid`, `prospective_comparison_failed` e
`prospective_recommendation_failed`. Nessun dettaglio contiene dati personali,
bytes sorgente o URL non necessari.

Le esclusioni candidate prospettiche includono almeno:

- `economic_terms_too_short`;
- `projected_market_data_missing`;
- `scenario_evaluation_failed`;
- `not_robust` nella recommendation.

Le esclusioni già definite dalle Spec 007–008 restano valide quando applicabili.

## Acceptance criteria

- La Spec 010 e tutti i payload storici restano semanticamente invariati.
- Una richiesta prospettica valida produce un orizzonte di dodici mesi da
  attivazione e un risultato per ogni scenario.
- Sottoscrizione, durata economica e validità della tariffa sono concetti
  distinti e testati.
- Consumo, schedule, anchor regolatorio e market data hanno validazione
  fail-closed e provenance sufficiente.
- La proiezione regolatoria è deterministica, esplicita e mai marcata come
  verificata per il futuro.
- Fixed/fixed, fixed/indexed, baseline multi-segmento e candidati esclusi
  producono ledger e ranking stabili.
- La recommendation seleziona soltanto candidate che superano la soglia in
  tutti gli scenari; soglia assente o scenario mancante produce
  `stay_current`.
- Gli ID canonici, gli envelope e gli errori sono stabili e non dipendono
  dall'ordine dei dati.
- Il manifest dichiara solo le due capability prospettiche, senza `forecast`.

## Test richiesti per l'implementazione futura

- Modelli frozen, Decimal, provenance, JSON round-trip e rifiuto dei float.
- Confini di `quote_date`, `activation_date`, periodi semiaperti e clamp del 29
  febbraio.
- Offerta sottoscrivibile alla data di riferimento, durata nota breve,
  durata mancante assunta a dodici mesi e separazione dalla tariff validity.
- Profilo futuro fuori orizzonte, overlap, timezone, granularità e profilo
  vuoto o a consumo nullo.
- Schedule con gap/overlap, segmenti assunti e schedule diverse per scenario.
- Anchor regolatorio assente, congelamento a `quote_date`, profilo errato e
  copertura futura non verificata.
- Base/stress mancanti o duplicati, market data incompleti, gap, overlap,
  indice non disponibile e indexed fallibile in un solo scenario.
- Calcolo fixed/fixed, fixed/indexed, baseline segmentata, rounding, warning,
  ranking, tie-break e ID invarianti alla permutazione.
- Recommendation con soglia esatta, risparmio insufficiente in uno stress,
  candidata assente in uno scenario, durata assunta e `stay_current` senza
  soglia.
- Regressione completa delle Spec 001–010, manifest, schema discovery,
  envelope fail-closed, smoke base/extra e `git diff --check`.

## Riferimenti

- [Portale Offerte — Open Data](https://www.ilportaleofferte.it/portaleOfferte/it/open-data.page)
- [ARERA — Regolamento di funzionamento del Portale Offerte, valido dall'1 aprile 2026](https://www.arera.it/fileadmin/allegati/docs/18/51-18_Allegato_A__valido_dall_1_aprile_2026.pdf)
- `specs/007-comparison-engine.md`
- `specs/008-portale-offerte-importer.md`
- `specs/009-recommendation-engine.md`
- `specs/010-platform-integration-contract.md`
