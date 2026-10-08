# ADR 0017 — Rollover automatico dei Regulatory Anchor

## Stato

Accettato come decisione architetturale della Spec 014. Implementati localmente
il contratto Core M1–M16, gli adapter ufficiali e l'archivio/job Platform P1.
Il PDF fornito dall'utente è stato acquisito live con TLS verificato e mappato
in quattro conferme esplicite. Il replay live post-M22 ha costruito il
candidate Q4 canonico e restituito 644 record ancora in review su 1011; gli
altri 358 finding non bloccanti sono stati risolti dalla rubrica ufficiale e
da regole versionate. Il candidate non è verificato, staged o promosso; il
package Q3 è scaduto e coverage e preflight restano chiusi. M23 deve collegare
i finding alle fonti effettive dei campi Q4, così le voci non collegate non
vengono confuse con modifiche dell'anchor. La certificazione Platform e la
release 0.13.0 non sono concluse. Nessuna decisione qui attesta valori
successivi all'anchor verificato.

## Contesto

La Spec 013/ADR 0016 e le modifiche locali permettono di verificare, con
copertura datata, l'anchor già incluso. Il suo `refresh_regulatory_anchor`
non scopre nuove pubblicazioni né costruisce un successore. Il loader usa un
solo artefatto Q3; il validator limita la validità al mese di `as_of`.
La Platform deve ricevere un esito economico Core senza implementare regole
normative proprie. Le decisioni seguenti fissano la semantica per la Spec 014.

## Decision log

### D1 — Proprietà dell'orchestrazione

- **Problema:** una routine giornaliera deve attraversare discovery, build e
  promotion senza spostare la semantica nella Platform.
- **Alternative:** scheduler e DB nel Core; fasi pubbliche indipendenti che la
  Platform compone; una façade Core con port di storage e source gateway.
- **Scelta:** `refresh_regulatory_state` è la façade Core; la Platform schedula
  e implementa solo gateway/persistenza transazionale. Le fasi restano moduli
  interni separati e testabili.
- **Motivo:** il Core decide candidate, validità, coverage e transizioni; il
  dominio resta indipendente dall'infrastruttura.
- **Conseguenze:** serve un repository Protocol con CAS, un adapter Platform
  e un report tipizzato. **Differito:** deployment/cadence concretamente usati.

### D2 — Discovery e fiducia

- **Problema:** i digest delle fonti note non rivelano atti nuovi.
- **Alternative:** controllare gli otto hash; cercare parole nei PDF; enumerare
  indici ufficiali con checkpoint e classificazione versionata.
- **Scelta:** scandire completamente i quattro canali ARERA, ADM, Gazzetta e
  Normattiva con sovrapposizione temporale, cross-check, cursor avanzato solo
  su run riuscito e finding per ogni atto potenzialmente pertinente. Fonte
  ufficiale/HTTPS e parser supportato sono necessari, mai sufficienti da soli.
- **Motivo:** l'assenza di un atto deve essere supportata dalla completezza
  della ricerca, non inferita da un documento invariato.
- **Conseguenze:** scan incompleto o atto non classificabile bloccano;
  registri/adapter versionati e snapshot auditabili. **Verificato localmente
  il 2026-10-04:** tutti e cinque gli adapter hanno prodotto snapshot completi;
  l'endpoint Open Data Normattiva di produzione ha risposto senza autenticazione
  con 48 atti in una pagina. Questo prova l'acquisizione dell'indice e la sua
  forma osservata, non la copertura normativa né i parser degli atti. **Differito:**
  certificazione dei documenti e del mapping Q4.

### D3 — Parser, mapping e continuità dei valori

- **Problema:** un nuovo allegato può cambiare layout, significato o periodo.
- **Alternative:** PDF/OCR/keyword generici; copia dei valori precedenti;
  parser e mapping specifici per famiglia/versione.
- **Scelta:** parser allowlisted → `RegulatoryFact` con locator/unità/periodo →
  mapping normativo versionato → candidate. `carry_forward` richiede regola
  esplicita, fonte di conferma quando necessaria e discovery completa.
- **Motivo:** preserva la distinzione source-faithful vs regola fatturabile
  delle ADR 0006/0009/0010 ed evita di inventare aliquote.
- **Conseguenze:** nuovo schema o atto ambiguo apre review auditata e impedisce
  stage/promotion. **Differito:** nuove famiglie dopo il primo supporto BT.

### D4 — Tempo e validità

- **Problema:** `as_of`, fetch, efficacia e promotion hanno ruoli diversi; il
  validator attuale forza il mese di `as_of`.
- **Alternative:** selezione per `anchor.as_of == today`; validità trimestrale
  hardcoded; finestra provata dai facts e dagli atti.
- **Scelta:** v2 usa `[valid_from, valid_until)`, derivata dai periodi provati.
  `snapshot_as_of` è la semantica del campo serializzato `as_of` e può precedere
  `valid_from` se le fonti per il periodo futuro sono già pubblicate; può
  cadere nel periodo per una build tardiva. La
  coverage per il confronto è separata e deve essere fresca per quella data.
  L'anchor v1 conserva la sua finestra originale.
- **Motivo:** consente stage anticipato e non estende l'efficacia di una fonte.
- **Conseguenze:** validator, selector e risultati v2 nuovi; date e timezone
  espliciti. **Differito:** nessuna estensione automatica a trimestri senza prove.

### D5 — Candidate e identità

- **Problema:** rerun e fetch ripetuti possono creare oggetti differenti con
  gli stessi valori, mentre l'anchor deve essere identificato esattamente.
- **Alternative:** ID timestamp/random; un solo hash del JSON con timestamp;
  build key semantico più digest dei bytes canonici congelati.
- **Scelta:** `build_key` content-addressed esclude tempi operativi; il primo
  snapshot selezionato è immutabile, e `artifact_sha256` identifica i bytes
  canonici completi, compresi i suoi timestamp. Rerun restituisce l'artefatto
  conservato; stesso key e bytes diversi è `DETERMINISM_VIOLATION`.
- **Motivo:** idempotenza senza perdere provenance o integrità.
- **Conseguenze:** doppio ID/versione e vincoli unici; il digest v1 resta
  verificato col suo algoritmo originale. **Differito:** nessuno.

### D6 — State machine e atomicità

- **Problema:** A deve restare attivo mentre B è staged; due worker possono
  promuovere nello stesso momento.
- **Alternative:** sovrascrivere il file package; lock applicativo globale;
  append-only più puntatore CAS transazionale.
- **Scelta:** candidate immutabili e ledger degli eventi; `PREPARING`,
  `VERIFIED`, `STAGED`, `PROMOTED` o review/rigetto. Current/staged/historical
  sono ruoli. La Platform implementa `put-if-absent` e CAS sulla generation;
  il Core verifica contiguità, freshness e precondizioni prima del CAS.
- **Motivo:** una sola transizione osservabile e storia auditabile.
- **Conseguenze:** la promotion equivalente ripetuta è no-op; conflitto reale
  è tipizzato. **Differito:** dialetto SQL della migration Platform.

### D7 — Scadenza, incidenti e review

- **Problema:** network failure e incertezza normativa richiedono azioni
  diverse; dopo la scadenza A non è riutilizzabile.
- **Alternative:** fallback ad A/valori precedenti; eccezioni testuali;
  reason codes tipizzati e fail-closed.
- **Scelta:** errori infrastrutturali sono retriable, ambiguità/nuovo schema
  sono `REVIEW_REQUIRED`; un candidate incompleto non si promuove. Le review
  sono artefatti versionati con scope, digest, reviewer e motivazione.
- **Motivo:** rende recupero e diagnosi automatici dove possibile e la
  decisione umana visibile dove necessaria.
- **Conseguenze:** `source_preflight.ready=false` da `valid_until` se B manca;
  alert 7/1/0 giorni. **Differito:** canale operativo delle notifiche.

### D8 — Compatibilità e confine Platform

- **Problema:** v1/v2 e il refresh locale sono già consumabili o predisposti;
  rinominarli direttamente sarebbe breaking.
- **Alternative:** cambiare la semantica di `refresh_regulatory_anchor`;
  breaking contract v2 generale; API additiva con alias legacy.
- **Scelta:** mantenere il refresh legacy sui documenti noti, aggiungere
  `refresh_regulatory_coverage` e la façade rollover; nuovi schema/capability
  nel manifest, vecchi envelope leggibili. La Platform usa `resolve_active`
  Core e `source_preflight`, non `anchor.as_of == today`.
- **Motivo:** migration progressiva e nessuna duplicazione di logica normativa.
- **Conseguenze:** doppio percorso per un ciclo di compatibilità, test contract
  obbligatori e nuova versione candidata 0.13.0. **Differito:** data di rimozione
  dell'alias, da specificare in una futura deprecation policy.

### D9 — CLI e orchestrazione effettiva

- **Problema:** la pipeline richiede registry adapters, source port e repository
  durevole. Un comando CLI non può configurare in sicurezza lo store durevole
  Platform; il workflow operativo è gestito dal job separato.
- **Alternative:** aggiungere `--rollover` che restituisce errore senza i binding;
  aggiungere un formato CLI per cablare adapter/storage; lasciare la CLI di
  refresh intatta e invocare la façade Python dal worker Platform.
- **Scelta:** nessun `--rollover` CLI in questa milestone. Il CLI
  `--refresh-anchor` continua a verificare il package corrente. M7 espone
  `RegulatoryRolloverService.refresh_regulatory_state`; la factory Core registra
  i cinque adapter ufficiali e accetta la porta di persistenza; M8 registra
  capability, schema ed envelope additive. I callback/classifier e le policy sono
  configurazione Core e non devono diventare regole Platform.
- **Motivo:** evitare un comando non operativo e mantenere separati job/storage
  da semantica, parsing e mapping. Tutto il ciclo è esercitabile offline tramite
  repository e adapter sintetici iniettati.
- **Conseguenze:** P1 Platform configura il job e lo storage transazionale dopo
  la release Core compatibile; la CLI legacy rimane source-compatible.
  **Differito:** comando CLI solo se in futuro esiste una modalità d'uso locale
  con adapter e store supportati.

## Conseguenze generali

Il caso normale può procedere automaticamente soltanto per layout e regole
esplicitamente supportati. Staging anticipato non garantisce promotion:
discovery e coverage devono essere rifatti alla data di attivazione. Tutte le
stime future della Spec 013 rimangono etichettate come ipotesi. La Spec 014
definisce milestone e acceptance per l'implementazione; questo ADR non cambia
artefatti regolatori o release.

## Avanzamento implementativo — 2026-10-01

M1 è stata implementata localmente: schema anchor v2 ed envelope sono
additivi; validator e digest dell'anchor Q3 v1 restano invariati; i fatti
normalizzati rifiutano `float`, e build key e digest artefatto hanno semantiche
separate. M2 implementa scansione paginata, provenance e digest per pagina,
overlap, finding/review e cursori committabili solo a copertura completa su
cinque canali. La suite offline ha 381 test, 95,27% branch coverage e tutti i
gate AGENTS passano. Gli adapter live ufficiali restano da certificare; nessun
anchor successivo reale è stato prodotto.

M3 aggiunge un registry senza fallback selezionato dal tripletta canale/tipo
documento/layout e un parser che riusa il parser ARERA XLSX Spec 005. Token
OOXML, cella, digest, date e versione sono conservati nei fatti `Decimal`.
PDF fiscali e nuovi layout rimangono review finché parser e fixture dedicati
non sono approvati. Gate: 387 test, 95,08% branch coverage; nessun anchor reale.

M4 aggiunge mapping versionato e candidate immutabile. Ogni tariffa e aliquota
deve essere coperta in modo continuo e produrre un solo `Decimal`/unità sull'intero
intervallo half-open; cambi intra-periodo richiedono un periodo candidate più
breve. Il candidate resta `UNVERIFIED` fino a coverage/discovery M5. Gate:
404 test, 95,04% branch coverage; fixture fiscale sintetica, nessun valore reale.

## Decisioni aggiuntive — 2026-10-04

### D10 — Effetto normativo esplicito e collegato al valore precedente

- **Problema:** un numero nel nuovo fatto non distingue un valore nuovo da una
  conferma o cessazione e può far apparire `carry_forward` come copia implicita.
- **Alternative:** inferire la conferma dall'uguaglianza con A; lasciare al
  mapping il solo valore numerico; aggiungere un effetto versionato con link.
- **Scelta:** ogni `RegulatoryFact` include `RegulatoryEffect/v1`. Conferma,
  modifica e cessazione richiedono `previous_anchor_id`, `previous_value`,
  `previous_fact_id` e disposizione; il mapping confronta il legame con il
  valore esistente in A. Un hash invariato non soddisfa questa prova.
- **Motivo:** rende la continuità regolatoria un fatto dichiarato dalla fonte
  e verificato dal Core, preservando audit, `Decimal` e fail-closed.
- **Conseguenze:** il candidate usa un envelope/schema aggiornato; envelope
  storiche restano leggibili. Il parser può promuovere solo un effetto supportato
  in modo deterministico. **Differito:** codificare ciascun parser fiscale e
  interpretare provvedimenti nuovi non ancora supportati.

### D11 — Recovery tardivo con prova di discovery del gap

- **Problema:** il servizio impediva ogni build dopo `valid_from`, anche quando
  una scansione completa ricostruiva tutto il periodo di indisponibilità.
- **Alternative:** promuovere il primo candidate disponibile senza recupero;
  ampliare la validità di A; consentire recovery solo con scansioni complete.
- **Scelta:** Core ammette build tardiva solo se tutte le cinque scansioni
  coprono `[A.valid_until, as_of + 1 giorno)` e i facts provano B applicabile.
  Il job può stage e promuovere nello stesso run; `promoted_at` è il timestamp
  reale e preflight resta chiuso fino al successo.
- **Motivo:** recupera automaticamente un ritardo del worker senza inventare
  continuità o riattivare l'anchor scaduto.
- **Conseguenze:** cursori che iniziano dopo la scadenza non sono sufficienti;
  outage, review o intervallo non coperto restano `BLOCKED`. Test fixture
  includono run 2026-10-04 e incomplete scan.

### D12 — Persistenza e scheduling nel Platform

- **Problema:** il repository Core è solo in-memory e il job catalogo non può
  essere il proprietario della continuità regolatoria.
- **Alternative:** storage cloud/Core-native; Platform DB/Blob e job dedicato;
  tenere tutto nel singolo worker catalogo.
- **Scelta:** Platform fornisce store transazionale e raw archive privato, e
  schedula un worker regolatorio separato. Core mantiene endpoint e semantica;
  worker catalogo consuma l'anchor risolto e i digest congelati.
- **Motivo:** rispetta i confini esistenti e riusa Postgres/Blob, rendendo il
  CAS verificabile e i confronti offline.
- **Conseguenze:** richiede spec/migration/worker Platform e Core `0.13.x`;
  nessun cambio economics in Platform. **Differito:** release e certificazione
  live rimangono gate espliciti dopo i test di integrazione.

## M5 — coverage e review — 2026-10-01

`verify_regulatory_candidate_coverage` ora richiede scansioni complete e fresche
per tutti i cinque registri e verifica il digest di ogni fonte del candidate.
Le review manuali sono artefatti immutabili con decision ID, scope, reviewer,
rationale, regola/parser/mapping versionati e digest del documento; la coverage
result conserva sia artefatti sia source checks. La review di un atto modificato
deve riferirsi al digest osservato. Errori di rete, mutazioni, scansioni
incomplete, evidenza stale e atti non supportati producono reason code distinti.
`refresh_regulatory_coverage` è il nome esplicito per la verifica dell'anchor
corrente; l'API `refresh_regulatory_anchor` resta alias compatibile, senza
costruire il prossimo anchor. Gate: 437 test, 95,13% branch coverage, Ruff,
format, mypy e `git diff --check` verdi. Nessun anchor successivo reale e
nessun adapter live sono verificati.

## M6 — repository e transizioni atomiche — 2026-10-01

`RegulatoryRepository` definisce il contratto storage e
`InMemoryRegulatoryRepository` ne è il riferimento concorrente per i test. Il
current, i candidate, gli anchor storici, le coverage, i tentativi e gli eventi
append-only coesistono senza sovrascrivere artefatti. `put_candidate_if_absent`
è idempotente per build key e segnala `DETERMINISM_VIOLATION` se lo stesso
identificatore semantico produce output differenti. `stage`, `promote` e
`revoke_staged` usano generation/current ID attesi; la promozione pubblica una
copia VERIFIED immutabile e conserva A come historical. I test concorrenti
provano una sola transizione osservabile per staging e promotion. Gate: 465
test, 95,30% branch coverage, Ruff, format, mypy e `git diff --check` verdi.
È implementato soltanto il repository di riferimento: nessun anchor reale è
stato promosso e la persistenza Platform resta P1.

## M7 — orchestrazione e gate offline — 2026-10-01

`RegulatoryRolloverService.refresh_regulatory_state` ora separa internamente
discovery/acquisizione, parsing/mapping, candidate, coverage, stage e promotion.
Il report conserva finding, cursor updates, coverage e codici di errore; il
service `source_preflight` e `resolve_active` non accedono alla rete. Il
confronto accetta l'evidence nuova senza cambiare il contratto storico e resta
offline. Fixture sintetiche verificano A `[2026-07-01, 2026-10-01)` → B
`[2026-10-01, 2027-01-01)`, rerun, outage transitorio, fonte mutata, review e
confini temporali. Nessun adapter live è certificato.

## M8 — manifest, envelope e compatibilità — 2026-10-01

La capability `regulatory_anchor_rollover` e gli schema ID nuovi sono
nell'integration manifest e nel serializer canonico. `refresh_regulatory_anchor`
e `--refresh-anchor` non cambiano significato; non viene introdotto `--rollover`
perché non c'è un adapter live o repository durevole su cui eseguire il job.
Gate complessivo M7–M8: 498 test, 95,09% branch coverage, Ruff/format/mypy e
`git diff --check` verdi. Nessun bump, build, commit, tag, push o release.
Platform P1, prove live degli endpoint/layout e parser fiscali restano da fare;
nessun anchor successivo reale è stato prodotto o promosso.

## Stato implementativo — 2026-10-04

Il follow-through locale ha aggiunto il worker regolatorio Platform indipendente
dal catalogo, repository PostgreSQL/Blob, migration, archivio raw privato,
append-only per artefatti/evidenze/eventi e CAS per stage/promotion. Il gateway
Platform invoca la factory Core senza token Normattiva e congela gli
identificativi e i digest usati dal job cliente. Core conserva parser, mapping,
semantica e selezione.

Gates locali Core: 582 test, 95,00% branch coverage, Ruff/format/mypy, lock
check e `git diff --check` verdi. La scansione live degli indici dei cinque
registri è completa: ARERA atti 43 pagine/29 record, ARERA tariffe 1/1, ADM
1/1, Gazzetta 1/840, Normattiva 1/48. Il report ha 919 finding, è
`REVIEW_REQUIRED` e non produce candidate perché gli atti/layout non supportati
non possono essere classificati o mappati automaticamente. La delibera ARERA
343/2026/R/com è stata individuata ma non trasformata in facts Q4 verificati.

Platform: 230 test unitari, coverage raw 90,05%, Ruff/format/mypy, architecture
scan e `docker compose config --quiet` verdi. Sei test PostgreSQL 17 passano con
il Core source locale e migration upgrade/downgrade/upgrade è verificata. Il
container locale è stato buildato con wheel Core 0.13.0 e il contract smoke è
passato. PyPI continua a fornire 0.12.0; il rilascio 0.13.0 non è avvenuto.

Il parser numerico ufficiale disponibile resta ARERA XLSX Spec 005. I parser
fiscali ADM/Normattiva e l'effetto Q4 non sono certificati; l'anchor incluso è
scaduto il 2026-10-01 e `source_preflight.ready` resta false. Nessun valore
precedente è riutilizzato implicitamente. La capability locale e la discovery
live non equivalgono a un anchor reale promosso o a una release.

## Decisione addizionale D12 — Discovery decisions are durable per observed act

- **Problema:** uno snapshot completo conservava record e hash d'indice, ma le
  decisioni di classificazione erano solo nel report giornaliero. Quando un
  atto usciva dalla finestra di overlap, un finding `REVIEW_REQUIRED` poteva
  sparire; inoltre un report precedente non conteneva necessariamente i
  metadati necessari a riacquisire il documento. Un worker dopo la promotion
  poteva anche riaprire fatti già rappresentati dall'anchor appena attivato.
- **Alternative:** riclassificare ogni finding ogni giorno senza stato; non
  conservare decisioni e riaprire tutti gli atti storici; salvare nel nuovo
  snapshot la decisione versionata con il record sorgente e separare le review
  ancora aperte dai facts già incorporati.
- **Scelta:** `DiscoverySnapshot` v2 conserva finding, regola/versione,
  `source_record` e `classification_complete`; finding unresolved attraversano
  le finestre senza overlap. Una variazione dei metadati genera review anche
  fuori dal range condiviso. La preparation parte per un fatto supportato solo
  se la sua validità copre il prossimo `valid_from`; i failure di acquisizione
  conservano il retry. Platform legge come baseline solo snapshot completi.
- **Motivo:** lo stato di review non è perdita-dato implicita, mentre un atto
  supportato già usato in B non deve produrre un candidato spurio dopo la
  promotion. La selezione dei fatti futuri resta vincolata da validità e parser
  Core, non dai digest soli.
- **Conseguenze:** nuovi schema `regulatory-discovery-report/v2`,
  `regulatory-discovery-snapshot/v2` e `regulatory-rollover-report/v2`; i
  payload v1 restano leggibili e gli snapshot v1 sono marcati come
  classification incompleta. Il gateway Platform richiede v2 per output nuovi,
  legge run v1 storici e non promuove snapshot incompleti a baseline.
  **Differito:** certificazione parser/mapping fiscali Q4, costruzione e
  promozione di un anchor Q4 reale, wheel pubblicato e release 0.13.0.

## Decisione addizionale D13 — evidenza live non equivale a mapping Q4 — 2026-10-04

- **Problema:** la discovery completa trova atti e aggiornamenti recenti, ma il
  Core non può promuovere un anchor sulla base di soli indici, hash uguali o
  descrizioni web aggregate.
- **Alternative:** copiare i valori Q3 e trattare la conferma descrittiva ARERA
  come conferma di tutti i campi; oppure mantenere il blocco finché la
  disposizione e la provenance non sono mappate per ogni fatto.
- **Scelta:** il PDF ADM 2026 è stato acquisito e la riga domestica
  `0,0227 EUR/kWh` verificata testualmente e visivamente, ma non viene
  trasformata in fatto Q4 senza validità temporale e classificazione completa.
  La conferma ARERA 343/2026/R/com e le indicazioni ufficiali su A_SOS/A_RIM
  sono evidenze da mappare, non `RegulatoryEffect` già prodotti. Il D.Lgs.
  148/2026 resta finding aperto finché non è provata la sua applicabilità o
  irrilevanza per il profilo Core.
- **Motivo:** il valore costante non prova continuità normativa. La review
  impedisce di inventare un periodo valido o di supporre che un atto fiscale
  non incida sui campi dell'anchor.
- **Conseguenze:** nessun candidate Q4 viene stageato/promosso e il preflight
  resta chiuso. I gate locali certificano il software, non la disponibilità di
  un anchor reale. La Platform conserva gli artefatti e applica il blocco senza
  classificare fonti. **Differito:** parser ARERA 343/2026, parser/regole
  fiscali ADM/Normattiva/Gazzetta e decisioni auditate sui finding pertinenti.

## Decisione addizionale D14 — classificazione predefinita esatta e fail-closed — 2026-10-05

Nota di stato: la parte D14 che manteneva `343/2026/R/com` in review è
superata dalla decisione D19, dopo il replay dell'atto completo fornito il
2026-10-07. Le altre regole D14 conservano la propria semantica.

- **Problema:** l'invocazione discovery senza classifier trasformava ogni
  record in review generica, inclusi due atti Q4 già identificati con metadati
  ufficiali; ciò rendeva meno chiaro quali blocker noti avessero già un esito
  deliberato e lasciava il comportamento predefinito senza un punto versionato
  di policy.
- **Alternative:** lasciare tutta la classificazione al chiamante; dedurre
  rilevanza da titolo/keyword; oppure riconoscere soltanto identità ufficiali
  esatte e mantenerle bloccate finché interpretazione e mapping mancano.
- **Scelta:** `rollover_classification.py` registra una regola Core
  `known-q4-act-review/v1.0.0` per ARERA `343/2026/R/com` con canale, URL,
  data di pubblicazione, data di efficacia dove disponibile e document ID
  attesi, e per Gazzetta `26A04702` con canale, codice redazionale, date e
  struttura dell'URL attesi. Il risultato è `REVIEW_REQUIRED`, mai
  `SUPPORTED` o irrilevanza. Metadati diversi e ID ignoti restano review
  generica; un classifier esplicitamente fornito conserva precedenza.
- **Motivo:** la regola rende il blocco noto tracciabile e verificabile senza
  attribuire effetti economici sulla base di un indice o di una somiglianza.
  Discovery resta completa ma non equivale a interpretazione.
- **Conseguenze:** i record sono auditabili con rule ID/version già previsti
  dallo schema discovery v2; nessuna migration o schema pubblico nuovo. Test
  offline coprono identità esatte, varianti e override. La readiness rimane
  falsa e non viene prodotto un candidate reale.
- **Differito:** parser esatti, catene `RegulatoryEffect`, applicabilità
  fiscale e decisioni di review firmate/auditate. La regola non sostituisce
  questi gate e non abilita promozione.

## Decisione addizionale D15 — decreto accise 26A04766 tipizzato ma fail-closed — 2026-10-05

Stato: scelta iniziale superata dalla D16 dopo l'ispezione del testo ufficiale
completo. La regola review rimane la scelta per record simili o metadati non
esatti.

- **Problema:** la discovery Gazzetta include il decreto MEF `26A04766`, ma il
  classifier lo lasciava in review generica. Il solo titolo “Rideterminazione
  temporanea delle aliquote di accisa” non dimostra quale prodotto o periodo
  sia coinvolto e non autorizza una conclusione sull'accisa elettrica.
- **Alternative:** dedurne l'irrilevanza dal titolo; interpretare genericamente
  il testo; oppure riconoscere l'identità ufficiale esatta e mantenere review
  fino a un mapping Core versionato del contenuto acquisito.
- **Scelta:** la regola `known-q4-excise-act-review/v1.0.0` richiede canale
  Gazzetta, codice redazionale e document ID `26A04766`, date 2026-09-04 e URL
  ufficiale con parametri corrispondenti. Assegna sempre
  `REVIEW_REQUIRED`. L'atto pubblicato ridetermina l'accisa sul gasolio usato
  come carburante dal 6 al 10 settembre 2026; questa lettura ufficiale non è
  implementata come interpretazione automatica, perché discovery/classifier
  qui riceve solo metadati d'indice e il parser/mapping fiscale non è
  certificato. Fonte: [testo ufficiale Gazzetta, atto 26A04766](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticoloDefault/originario?atto.codiceRedazionale=26A04766&atto.dataPubblicazioneGazzetta=2026-09-04&atto.tipoProvvedimento=DECRETO).
- **Motivo:** identifica un blocco noto senza applicare guessing a titolo o
  keyword, senza inventare fatti e senza dichiarare l'atto irrilevante per
  l'anchor elettrico prima che la policy possa verificare documento, prodotto
  e finestra.
- **Conseguenze:** la forma v2 `DiscoveryActFinding` resta invariata; testano
  l'identità esatta e un record lookalike, senza migration. Candidate Q4 e
  `source_preflight.ready` non cambiano.
- **Differito:** un parser o una regola d'ambito che consumi acquisizione e
  digest canonico, dimostri la non-applicabilità ai facts elettrici del periodo
  target, e produca un esito auditabile. Fino ad allora l'atto rimane review.

## Decisione addizionale D16 — decreto diesel fuori perimetro Q4 elettrico — 2026-10-05

- **Problema:** dopo la verifica del testo integrale ufficiale, la D15 lasciava
  in review un atto che prescrive una sola rideterminazione su gasolio usato
  come carburante dal 6 al 10 settembre 2026. Il Q4 elettrico candidato inizia
  il 1° ottobre e i facts fiscali dell'anchor riguardano l'elettricità.
- **Alternative:** lasciare ogni atto fiscale in review; dedurre l'ambito dal
  titolo/keyword; oppure registrare una regola versionata solo per l'identità
  ufficiale esatta, con motivazione basata sul testo dell'atto.
- **Scelta:** per il solo canale Gazzetta, atto/documento `26A04766`, date
  `2026-09-04` e URL ufficiale atteso, il classifier assegna
  `IRRELEVANT_BY_VERSIONED_RULE` con `gazzetta-diesel-excise-out-of-scope/v1.0.0`.
  La motivazione registra prodotto e periodo espressi nell'art. 1 del [testo
  ufficiale](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticoloDefault/originario?atto.codiceRedazionale=26A04766&atto.dataPubblicazioneGazzetta=2026-09-04&atto.tipoProvvedimento=DECRETO): gasolio usato come carburante, 6–10 settembre 2026. La policy non
  classifica altri atti di accisa e non usa matching testuale generico.
- **Motivo:** la regola non cambia né deriva alcun valore elettrico; elimina
  soltanto un falso blocco dimostrato fuori finestra e fuori prodotto dal testo
  ufficiale versionato.
- **Conseguenze:** il finding porta rule ID/version, record e provenance nel
  discovery snapshot v2. Un ID uguale con metadati discordanti, un diverso atto
  o un'errata corrige rimangono review. La policy non genera facts e non chiude
  gli altri finding fiscali; candidate e preflight restano indipendenti. Nessuna
  migration o modifica all'API pubblica.
- **Differito:** estendere l'elenco di atti irrilevanti solo con decisioni
  versionate e riferimenti ufficiali specifici; ogni nuova disposizione fiscale
  continua a richiedere review finché la sua applicabilità non è provata.

## Decisione addizionale D17 — D.Lgs. 148/2026 fuori dai tassi domestici elettrici — 2026-10-05

- **Problema:** la regola D14 lasciava in review il record Gazzetta `26A04702`,
  un decreto correttivo che menziona IVA e accise. Il titolo da solo non prova
  se le modifiche cambino i due valori fiscali dell'anchor domestico BT.
- **Alternative:** mantenere review generica finché la pipeline non dispone di
  un parser completo; interpretare il decreto a runtime con euristiche sul
  testo; oppure verificare le disposizioni fiscali pertinenti e registrare una
  policy versionata per il solo record esatto.
- **Scelta:** dopo verifica del testo ufficiale, il Core classifica l'esatto
  record `26A04702` come `IRRELEVANT_BY_VERSIONED_RULE` per i tassi di accisa e
  IVA della fornitura domestica elettrica. L'art. 12 modifica i termini di
  detrazione IVA (DPR 633/1972 artt. 19 e 25), non l'aliquota applicabile ai
  consumi; l'art. 32 modifica ambiti di gas, soggetti obbligati e specifiche
  officine/usi ausiliari, non il tasso di accisa elettrica domestica. Fonti:
  [art. 12 Gazzetta](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A04702&art.dataPubblicazioneGazzetta=2026-09-04&art.flagTipoArticolo=0&art.idArticolo=12&art.idGruppo=9&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1),
  [art. 32 Gazzetta](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A04702&art.dataPubblicazioneGazzetta=2026-09-04&art.flagTipoArticolo=0&art.idArticolo=32&art.idGruppo=14&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1).
  Il classifier richiede canale Gazzetta, codice `26A04702`, date osservate e
  URL ufficiale con il medesimo codice. Rule ID/version:
  `gazzetta-dl148-domestic-electricity-rates-out-of-scope/v1.0.0`.
- **Motivo:** il contenuto normativo esaminato non modifica i due campi fiscali
  numerici dell'anchor. La decisione puntuale evita un parser generico e non
  deduce valori o periodi per analogia; il testo non è interpretato a runtime.
- **Conseguenze:** la regola non produce `RegulatoryFact`, non cambia aliquote
  e non chiude altri atti fiscali. Metadati discordanti, atti collegati e
  finding nuovi restano review. Nessuna migration o modifica API/schema; i
  test devono provare la regola esatta e lasciare in review i lookalike. Candidate
  Q4 e `source_preflight.ready` restano indipendenti e bloccati dagli altri
  finding e dalla mancata acquisizione del documento ARERA 343.
- **Verifica live successiva:** la scansione Gazzetta del 2026-10-05 ha
  restituito l'URL ufficiale con path case-sensitive
  `/atto/serie_generale/caricaDettaglioAtto/originario`. Il classifier locale
  attendeva un path minuscolo e non applicava la regola ai record reali. Il
  matcher e i test sono stati allineati ai metadati osservati; il replay esatto
  classifica `26A04702` e `26A04766` con le rispettive regole versionate.
  Una successiva scansione limitata 2026-09-04/2026-10-05 ha completato tutti
  i cinque canali e prodotto 853 finding da interpretare. Normattiva: 49 atti,
  risposta JSON di 44.680 byte con SHA-256
  `3f580e212d8e5761dcb5bb6a8cafe93e1dc93fd67257a809e1a11b77fcd40142`; la
  risposta è stata ottenuta con macOS SecureTransport, TLS verificato
  (`http 200`, verifica 0), e validata dall'adapter Core. Non è stato bypassato
  TLS. L'HTTP client urllib locale ha ancora un trust-store incompatibile e va
  verificato nel runtime Platform. Discovery completa non equivale a
  interpretazione completa o candidate pronto.
- **Differito:** eventuale parser per le modifiche normative a profili non
  domestici, impianti di produzione, altre imposte e altri periodi; nessuna
  generalizzazione della regola oltre l'anchor corrente.

## Decisione addizionale D18 — parser ADM per l'accisa elettrica domestica — 2026-10-05

- **Problema:** il listino ADM è un PDF ufficiale necessario per il fatto
  dell'accisa, ma un estrattore PDF generico o una ricerca del token `0,0227`
  non dimostrano che l'importo appartenga alla riga abitazioni.
- **Alternative:** lasciare il listino in review; cercare parole/importi in
  tutto il PDF; oppure supportare un solo layout esplicito, controllandone
  struttura, coordinate, data, riferimento normativo e record ufficiale.
- **Scelta:** `AdmDomesticExcisePdfParser` v1.0.0 accetta solo layout
  `adm-national-excise-pdf-v1`: PDF non cifrato di 11 pagine, pagina 5/11,
  titolo elettrico e update date in italiano coerente col record ADM; associa
  l'importo EUR/kWh alla riga «per qualsiasi applicazione nelle abitazioni»
  mediante coordinate di testo e richiede il riferimento D.M. 30/12/2011.
  L'acquisitore assegna `adm_excise_YYYYMMDD` solo quando data, ID e basename
  URL corrispondono al finding ADM ufficiale. Emette un `RegulatoryFact`
  versionato con il digest e tutti i locator/provenance necessari. La data
  indicata dal listino inizia il periodo osservato; `date.max` è solo il
  sentinel tecnico “fino a sostituzione” e non sostituisce discovery ADM
  completa, refresh coverage o ricontrollo prima della promozione.
- **Motivo:** evita guessing e consente al Core di aggiornare un importo solo
  quando la stessa riga ufficiale e la sua unità restano riconoscibili.
- **Conseguenze:** l'extra Core `arera`, già necessario per il parser ARERA
  workbook, include ora `pypdf` per il parser ADM; layout non
  riconosciuto, righe ambigue o PDF malformato producono review tipizzata.
  Fixture sintetiche provano sia la resistenza alle variazioni di importo sia
  il fail-closed sui cambi di struttura. Un replay privato del PDF ADM
  disponibile localmente ha prodotto 0,0227 EUR/kWh e digest uguale alla fonte
  Q3. Nessun anchor Q4 è stato costruito o promosso da questa decisione.
- **Differito:** parser delle altre righe ADM e conferma giuridica dell'ambito
  oltre la data di aggiornamento; la finestra del candidato deve restare
  limitata dall'intersezione con i fatti ARERA verificati e dalla discovery
  completa al cutoff.

## Decisione addizionale D19 — materializzare le conferme della delibera ARERA 343 — 2026-10-07

- **Problema:** il PDF ARERA 343/2026/R/com conferma ASOS, ARIM, UC3 e UC6 dal
  rispettivo periodo precedente senza ristampare gli importi; il Core non
  poteva costruire il Q4 senza inventare numeri o copiare implicitamente i
  valori Q3.
- **Alternative:** lasciare la delibera in review finché ARERA non pubblica
  un'altra tabella; estrarre euristicamente importi dal PDF; oppure parsare
  solo clausole esatte e rappresentarle come effetti non numerici legati al
  valore precedente nel mapping Core.
- **Scelta:** il parser `arera-343-q4-confirmation` v1.0.0 è vincolato a otto
  pagine, URL e atto attesi, date esatte, articolo elettrico 1 completo e
  dispositivo 4.2. Ha riprodotto il PDF locale di 427.425 byte, digest
  `685691673341be23f479823c61b18c37fe24360f629ff3f8b3c5c847888db30e`; il
  file resta privato e non è una fixture di distribuzione. Emette quattro
  assertion senza importi. Il mapper richiede la corrispondenza con le fonti
  precedenti: ASOS con l'inizio periodo `arera_227`, ARIM/UC3/UC6 con
  `arera_588`, e `arera_575` annuale ancora valido per ogni `network_total`.
  I facts risultanti portano `confirm_value`, valore e fact ID precedenti,
  nonché PDF, digest, parser, clausole e derivazione. Fingerprint e periodo del
  candidate includono le assertion; la coverage futura le accetta solo fuori
  sovrapposizione, oppure dopo una materializzazione esplicita corrispondente.
- **Motivo:** l'atto non contiene importi, ma la sua disposizione conferma
  puntualmente i valori per il nuovo periodo. Il mapping deve rendere il
  legame verificabile e impedire fallback impliciti.
- **Conseguenze:** il record tariffario esatto ARERA è `SUPPORTED`; la copia
  nell'indice generale è un duplicato versionato. Il test sintetico verifica
  staging il 30/09, promozione il 01/10 e preflight senza rete. Il replay PDF
  reale certifica il parser soltanto. Il report live del 2026-10-05 contava
  853 finding prima di M15 e non è stato ricalcolato; non è stato costruito né
  promosso un anchor Q4 reale e
  `source_preflight.ready` reale resta false. Nessuna migration o schema
  pubblico nuovo; non è avvenuto il rilascio 0.13.0.
- **Differito:** interpretazione dei finding live rimanenti, candidate e
  promotion Q4 live, verifiche Platform end-to-end e decisione separata sul
  rilascio 0.13.0.

## Decisione addizionale D20 — timestamp successivi alle acquisizioni — 2026-10-07

- **Problema:** il workflow catturava `created_at` all'avvio del job, prima
  delle richieste HTTP. Un'assertion acquisita pochi secondi dopo risultava
  falsamente successiva al candidate e generava `SOURCE_CHANGED_UNEXPECTEDLY`.
- **Alternative:** accettare un timestamp incoerente; usare il tempo del
  trasporto come tempo del candidate; oppure registrare l'istante dopo ciascuna
  acquisizione/verifica e prima di costruire o promuovere l'artefatto.
- **Scelta:** Core rilegge il clock dopo parsing, controlli digest e verifica
  candidate; `checked_at`, `created_at`, `staged_at` e `promoted_at` non
  precedono l'operazione che attestano. Il clock resta iniettabile per replay.
- **Motivo:** una fonte verificata non deve essere rifiutata per l'ordine delle
  operazioni, e l'audit deve rappresentare quando i controlli sono avvenuti.
- **Conseguenze:** test di regressione simula byte acquisiti dopo l'avvio; il
  live run non riporta più `SOURCE_CHANGED_UNEXPECTEDLY`. Resta bloccato per
  `UNSUPPORTED_REGULATORY_SOURCE` e `INCOMPLETE_COVERAGE`.
- **Differito:** gestione esplicita di una scansione che attraversa la
  mezzanotte civile `Europe/Rome`.

## Decisione addizionale D21 — trust store di sistema con TLS verificato — 2026-10-07

- **Problema:** urllib usava il bundle CA del runtime e Normattiva presentava
  una catena non riconosciuta nel runtime locale.
- **Alternative:** disabilitare verifica certificato/hostname; richiedere un
  bundle CA privato; usare il trust store nativo del sistema operativo.
- **Scelta:** la porta HTTP usa `truststore.SSLContext`, mantenendo
  `CERT_REQUIRED` e la verifica hostname. La dipendenza Core è versionata nel
  lockfile. Non si usa un trasporto insicuro.
- **Motivo:** allineare il client al trust store già configurato dal runtime,
  senza accettare certificati non attendibili.
- **Conseguenze:** i test verificano i flag TLS; Normattiva ha risposto HTTP
  200 con i byte JSON validati dall'adapter. La verifica certificato è rimasta
  attiva durante il run live.
- **Differito:** smoke del worker Platform nel suo container e host di
  produzione, che non sono certificati dal run in-memory Core.

## Decisione addizionale D22 — layout osservati negli indici ARERA e ADM — 2026-10-07

- **Problema:** l'indice ARERA tariffario ripete la stessa delibera per più
  famiglie di componenti; l'indice ADM usa talvolta un trattino lungo seguito
  da spazio nel nome PDF.
- **Alternative:** scaricare duplicati o scegliere una riga arbitraria;
  fallire chiuso sui conflitti, deduplicando solo identità/date/URL coincidenti.
- **Scelta:** ARERA unisce i titoli e scarica una sola volta i record con ID,
  data e URL uguali; metadati discordanti diventano
  `SOURCE_CHANGED_UNEXPECTEDLY`. Il parser del registro ADM ammette lo spazio
  osservato nel layout, senza allargare l'identità del PDF oltre ID/data/path.
- **Motivo:** tollerare varianti di presentazione prive di effetto semantico e
  conservare i conflitti come review.
- **Conseguenze:** fixture provano deduplica, conflitto e separatore ADM.
- **Differito:** nuovi layout devono avere nuove versioni e fixture.

## Decisione addizionale D23 — certificazione live resta fail-closed — 2026-10-07

- **Problema:** il run completo ha osservato 970 record ma 966 non hanno una
  policy Core esatta; tra questi compaiono atti ARERA del Q4, due update ADM,
  887 record Gazzetta e 49 aggiornamenti Normattiva.
- **Alternative:** promuovere in base a una lista di hash, ignorare i record per
  titolo/keyword o richiedere interpretazione versionata e prova di ambito.
- **Scelta:** discovery completa significa solo che le scansioni sono
  complete. I record non classificati restano `REVIEW_REQUIRED`; nessun
  candidate incompleto viene staged o promosso e il preflight rimane chiuso.
- **Motivo:** il Core non deve indovinare interpretazioni legali o riutilizzare
  valori senza una derivazione verificabile. La delibera 343 copre quattro
  conferme, non tutti gli effetti Q4.
- **Conseguenze:** il gate live 0.13.0 non è superato. La 338/2026/R/eel e gli
  altri finding pertinenti devono essere mappati oppure esclusi da regole
  versionate fondate su documenti ufficiali; poi servono candidate, promotion,
  preflight e gate Platform persistente.
- **Differito:** chiudere ogni review necessaria e ripetere la certificazione
  end-to-end. Nessun tag, push o release in questa sessione.

## Decisione addizionale D24 — copertura legata ai fatti modellati — 2026-10-07

- **Problema:** la scansione completa di cinque registri ha restituito 970
  record, di cui 966 senza interpretazione esatta. Trattare ogni record come
  applicabile produce un carico di review non proporzionato; ignorarlo per
  titolo, keyword o hash non prova la completezza dell'anchor.
- **Alternative:** revisionare manualmente ogni risultato ad ogni run;
  restringere le scansioni e presumere che gli atti non trovati siano
  irrilevanti; conservare la scansione completa e legare gli atti ai campi
  modellati tramite identità e relazioni normative ufficiali.
- **Scelta:** mantenere i cinque canali come evidenza di discovery, ma costruire
  il perimetro di copertura dalle famiglie supportate (`CHARGE`, `EXCISE_RATE`,
  `VAT_RATE`) e dalle rispettive fonti ufficiali. Un finding si risolve solo
  con parser/mapping o regola di irrilevanza esatta, versionata e motivata,
  sostenuta da ID/URN, disposizioni e contenuto ufficiale acquisito. Record
  ambigui o senza collegamento verificabile restano `REVIEW_REQUIRED`.
- **Motivo:** consente discovery ampia e incrementale senza interpretare
  genericamente normative e senza trasformare ogni atto pubblicato in input
  economico dell'anchor.
- **Conseguenze:** R1–R2 di Spec 014 §24 devono materializzare la matrice campo-
  fonte e le relazioni di modifica; solo dopo si ricalcola l'esito della
  finestra Q4. La 338/2026/R/eel è un finding aperto finché atto/allegati non
  sono confrontati col modello Core.
- **Differito:** elenco certificato di tutte le disposizioni/URN e degli
  identificatori ARERA/ADM applicabili alle famiglie del modello; va completato
  usando le fonti ufficiali prima di chiudere la certificazione live.

## Decisione addizionale D25 — classificazione puntuale delle fonti Q4 — 2026-10-08

- **Problema:** il run live ha individuato la 338/2026/R/eel, gli aggiornamenti
  ADM Q4 e registrazioni storiche/tributarie; applicare una policy generica a
  questi documenti rischierebbe di includere componenti fuori dal modello o di
  ignorare variazioni fiscali pertinenti.
- **Alternative:** filtri per titolo o keyword; ignorare interi canali; tenere
  ogni record in review; oppure valutare i documenti ufficiali e registrare
  regole esatte per identità, data, URL e layout.
- **Scelta:** versione `1.0.0` delle regole puntuali per (a) classificare la
  338 e le sue tabelle fuori dai campi di questo specifico anchor, (b)
  supportare gli esatti documenti ADM del 26 settembre e 6 ottobre 2026,
  (c) trattare le due edizioni ADM precedenti come supersedute per il Q4, e
  (d) mantenere le regole esatte già esaminate per i due atti Gazzetta. Il
  parser ADM continua a dover confermare data, riga domestica e valore.
- **Motivo:** la decisione usa evidenza ufficiale e non allarga la semantica
  dell'anchor a corrispettivi di vendita o fasce orarie non modellate.
- **Conseguenze:** i record elencati non richiedono più review per questo
  anchor; qualunque metadato discordante o documento diverso resta review.
  Restano 1003 finding `REVIEW_REQUIRED`: la discovery completa non prova da
  sola la coverage e non autorizza stage/promotion.
- **Differito:** relazione completa tra i rimanenti record Gazzetta/Normattiva
  e le disposizioni che possono modificare i campi del modello, più la
  certificazione live di coverage e promotion. Nessuna esclusione ampia è
  consentita come scorciatoia.

## Decisione addizionale D26 — candidate Q4 visibile ma non attivo — 2026-10-08

- **Problema:** i parser possono produrre valori Q4 verificabili localmente
  anche quando la completezza della discovery generale non è dimostrata.
- **Alternative:** scartare il candidate parziale; promuoverlo nonostante le
  review; oppure conservare il candidate come artefatto `UNVERIFIED` senza
  renderlo risolvibile come anchor corrente.
- **Scelta:** conservare il candidate canonico con fatti, decisioni,
  provenienza e digest; vietare staging e promotion finché la coverage non è
  pronta.
- **Motivo:** rende il lavoro verificabile e ripetibile senza indebolire il
  comportamento fail-closed.
- **Conseguenze:** il candidate Q4 generato il 2026-10-08 non sostituisce il
  Q3 scaduto. `source_preflight.ready` rimane false e compare non può usarlo.
- **Differito:** completare le relazioni normative di discovery e ripetere
  coverage, stage, promotion e preflight. Docker/PostgreSQL e il DB test non
  fanno parte della tranche esclusa su richiesta dell'utente.

## Decisione addizionale D27 — conservare i collegamenti ufficiali di modifica Normattiva — 2026-10-08

- **Problema:** l'API Normattiva identifica il TUA come aggiornato il
  2026-09-25, ma l'adapter Core conservava solo codice, titolo e date. Senza
  `ultimiAttiModificanti`, il Core non poteva collegare quell'aggiornamento al
  relativo atto pubblicato in Gazzetta.
- **Alternative:** lasciare il record in review senza usare i metadati ufficiali;
  collegarlo con titolo/keyword; oppure conservare l'ID modificante restituito
  dall'API e applicare solo una regola esatta con data, URL, atto e disposizione
  verificati.
- **Scelta:** `OfficialRegistryRecord.latest_amending_act_ids` preserva in forma
  canonica gli ID Normattiva; l'esatta relazione TUA `095G0523`→Legge
  `26G00184` riceve regole Core versionate. La Gazzetta ufficiale e il testo
  coordinato provano che la misura collegata riguarda il gasolio e termina il
  2026-09-05, prima del Q4; non modifica il tasso domestico elettrico.
- **Motivo:** si usa il collegamento normativo ufficiale, senza dedurre
  applicabilità dal solo titolo. Il campo entra nel digest discovery e quindi
  nell'evidenza auditabile.
- **Conseguenze:** al prossimo run completo, i due record esatti (Gazzetta
  `26G00184` e aggiornamento Normattiva del TUA con quel solo modificante)
  potranno essere esclusi dallo scope con una regola versionata. Varianti,
  modificanti ulteriori o nuove date restano `REVIEW_REQUIRED`. La coda
  restante e il gate Q4 non sono ancora certificati.
- **Differito:** aggiornare il report live, quantificare i finding residui,
  risolvere quelli collegati alle disposizioni modellate e completare coverage,
  stage, promotion e preflight.

## Decisione addizionale D28 — preservare la rubrica ufficiale Gazzetta — 2026-10-08

- **Problema:** l'adapter Gazzetta enumerava ogni atto ma eliminava il legame
  strutturato alla rubrica mostrata nell'indice ufficiale. Questo rendeva
  indistinguibili gli atti normativi dagli estratti, sunti e comunicati.
- **Alternative:** classificare per titolo o parole chiave; trattare ogni voce
  come review manuale; oppure acquisire la rubrica strutturata e usare una
  policy esatta solo per la categoria informativa fuori perimetro.
- **Scelta:** l'adapter versione successiva conserva `registry_section` per
  ogni record. La rubrica esatta `ESTRATTI, SUNTI E COMUNICATI` può essere
  classificata fuori scope Q4 con regola versionata; tutte le rubriche
  normative/ignote e ogni record senza rubrica restano review o errore di
  parsing.
- **Motivo:** la rubrica deriva da `span.rubrica` nel markup ufficiale e viene
  inclusa nel digest del record. L'elenco continua a essere acquisito per
  intero; ARERA, ADM e Normattiva restano fonti indipendenti per i valori e le
  disposizioni sorvegliate dall'anchor.
- **Conseguenze:** l'esclusione è auditabile e circoscritta al metadata ufficiale;
  la verifica del solo layout non equivale a un replay live completo e non
  sblocca Q4. Titoli, keyword e identificatori non sono usati come filtro.
- **Differito:** eseguire il replay completo con il nuovo adapter, misurare il
  collegare le rubriche normative alle disposizioni dell'anchor e completare
  coverage, stage, promotion e preflight.

## Decisione addizionale D29 — scope del candidate tramite fonti primarie — 2026-10-08

- **Problema:** i registri ARERA, Gazzetta e Normattiva sono più ampi dei campi
  del `DomesticProjectionAnchor`; il gate corrente trasforma ogni voce senza
  classificazione puntuale in un blocco, anche quando non esiste una relazione
  con le fonti del candidate.
- **Alternative:** chiedere una decisione manuale per ogni voce; ignorare interi
  registri; oppure mantenere scansioni complete e legare gli atti ai campi del
  candidate tramite gli indici primari e identificatori ufficiali di fonte.
- **Scelta:** introdurre scope Core versionato per `DomesticProjectionAnchor`.
  Le componenti di rete/oneri sono sorvegliate dall'indice tariffario ARERA e
  dai suoi atti; l'accisa domestica elettrica dall'indice ADM e dal TUA
  Normattiva (`095G0523`); l'IVA domestica dalle disposizioni del DPR 633/1972
  (`072U0633`). Il registro generale Gazzetta fornisce documenti di supporto
  quando il grafo ufficiale collega una sua voce alle disposizioni sorvegliate.
- **Motivo:** fonti primarie complete e parser delimitati provano valori e
  applicabilità; la sola presenza nell'indice, l'uguaglianza di digest, il
  titolo o una parola chiave non bastano. L'assenza di collegamenti si può
  usare solo con scansioni complete e controlli correnti delle fonti primarie.
- **Conseguenze:** tutti i record e gli snapshot restano archiviati. Le regole
  di esclusione sono esplicite e versionate; una scansione incompleta, un nuovo
  collegamento a una disposizione monitorata, una fonte cambiata o un parser
  incerto mantengono il gate chiuso. Nessuna modifica automatica agli anchor
  pubblicati.
- **Esito 2026-10-08:** il replay dello snapshot live completo ha prodotto
  candidate coverage pronta. Il repository Core ha stageato e promosso una
  volta il candidate Q4; il preflight è pronto e il confronto sintetico Q4 è
  passato senza rete. Anchor, coverage datata ed evento di promozione sono
  artefatti immutabili distinti. L'evidenza vale per il cutoff 2026-10-08 e
  richiede refresh prima di usare date successive; la persistenza Platform e
  PostgreSQL rimangono fuori dal gate locale.

## Avanzamento M22 — replay live post-rubrica — 2026-10-08

Il replay completo ha letto 1011 record: 3 supportati, 364 irrilevanti per
regole esatte e 644 ancora in review (39 ARERA, 556 Gazzetta, 49 Normattiva).
Il candidate Q4 supera la validazione su 13 facts e 11 decisions, ma la
coverage resta bloccata da `unsupported_regulatory_source`; non c'è stage o
promotion e `source_preflight.ready=false`. La regola della rubrica ha rimosso
358 record informativi senza dichiarare irrilevanti le altre rubriche.

La review generale continua a includere voci non correlate perché manca il
grafo versionato dei campi Q4 verso le fonti primarie e gli atti modificanti.
Questo è il prossimo lavoro Core; non è una richiesta che l'utente classifichi
644 record. La promozione richiede di completare M23 e ripetere il replay live.
