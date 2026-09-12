# Spec 008 — Portale Offerte Importer e integrazione frontend v0.8

## Stato

Specifica normativa v0.8.0. L'implementazione locale è autorizzata per il
milestone corrente; commit, tag, push e release restano operazioni separate.

## Contesto

La Spec 007 implementa il confronto deterministico di un contratto corrente
con offerte `Offer` già normalizzate e prequalificate. Non acquisisce il
catalogo commerciale dal Portale Offerte e non interpreta una pagina web o un
documento commerciale.

Il Portale Offerte è il comparatore pubblico gestito da Acquirente Unico per
le offerte retail di energia elettrica e gas. La disciplina ARERA prevede la
pubblicazione dei dati correnti e storici delle offerte in modalità open data.
La fonte ufficiale deve quindi essere acquisita come dataset verificabile e
trasformata in modelli canonici prima di invocare il Comparison Engine.

Il frontend raccoglierà i dati del contratto corrente e del profilo di consumo.
Non deve contenere formule economiche, scegliere il ruleset, calcolare il
totale o trasformare una stringa commerciale in una tariffa. Deve validare un
payload strutturato e passarlo alla libreria; la libreria resta indipendente da
web framework, browser, database, cloud e sistemi AI.

## Obiettivo

Fornire un flusso riproducibile:

```text
frontend → payload canonico → download open-data → snapshot/provenance
         → parsing e normalizzazione → filtri di applicabilità
         → Comparison Engine 007 → ranking e risparmi
```

La v0.8 deve scaricare, verificare e normalizzare le offerte elettriche
domestiche in bassa tensione pubblicate sul Portale Offerte e passarle al
motore 007. Ogni dato non rappresentabile senza assunzioni economiche deve
essere escluso con una motivazione stabile; non è ammesso completarlo con
valori inventati o con la spesa annua dichiarata dal portale.

## Perimetro v0.8

### Incluso

- energia elettrica, clienti domestici, bassa tensione;
- offerte pubbliche a prezzo fisso o variabile/indexed che il modello corrente
  può rappresentare senza perdita economica non dichiarata;
- download on-demand da endpoint HTTPS ufficiali allowlisted del Portale
  Offerte;
- file open-data nel formato ufficiale dichiarato dalla fonte, inizialmente
  con supporto a catalogo offerte e file ausiliari necessari alla
  normalizzazione;
- snapshot immutabile in memoria, digest SHA-256 e provenance fino al file e,
  quando il formato lo consente, all'elemento/campo sorgente;
- filtro per validità temporale, classificazione, territorio e requisiti di
  fornitura disponibili nel dataset;
- normalizzazione a `Offer`, `FixedTariff` o `IndexedTariff`;
- integrazione con `DeterministicComparisonEngine` e restituzione del ranking
  all-in della Spec 007;
- contratto JSON/Pydantic per il passaggio frontend → libreria;
- fixture locali source-faithful e uno smoke test live separato.

### Escluso

- scraping dell'interfaccia HTML, automazione del browser o reverse engineering
  di endpoint non documentati;
- gas, dual fuel, prosumer, comunità energetiche, MT/AT/AAT e clienti non
  domestici;
- offerte riservate, negoziate individualmente o non pubblicate nella fonte
  ufficiale;
- acquisizione automatica del contratto corrente da bollette PDF/OCR,
  immagini, Portale Consumi o credenziali SII;
- interpretazione semantica di condizioni commerciali testuali;
- raccomandazione soggettiva, marketing, ranking per qualità del venditore o
  selezione basata su preferenze non economiche;
- persistenza, scheduler, cache globale, API HTTP, autenticazione e UI;
- uso della spesa annua stimata dal Portale come sostituto del Pricing o del
  Billing Engine;
- fallback silenzioso a snapshot obsoleti, interpolazione, backfill o
  previsione di dati mancanti.

L'estensione a gas o ad altre classi di utenza richiederà una specifica
successiva con fonti, modelli, regole e test distinti.

## Fonti e confine di fiducia

La fonte primaria è il dataset [Open Data del Portale Offerte](https://www.ilportaleofferte.it/portaleOfferte/it/open-data.page)
pubblicato e raggiungibile dal dominio ufficiale del portale. Il mapping
economico è congelato sulla [versione 4.0 delle Regole per il calcolo della
spesa](https://www.ilportaleofferte.it/portaleOfferte/resources/cms/documents/7d0a872b48e9f98394310fdf03bc84aadac7b06785099416ae29e25400f.pdf).
In v0.8 i ruoli sono congelati
come segue: XML offerte Mercato Libero elettrico, CSV parametri Mercato Libero
elettrico, CSV offerte PLACET elettrico, CSV parametri PLACET elettrico e CSV
prezzi storici degli indici pubblici. Il namespace XML supportato è
`http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01`; i file CSV
sono UTF-8 quando dichiarato dalla fonte e Windows-1252 per il file storico
attualmente pubblicato. Un cambiamento di schema, intestazioni o namespace
produce `REVIEW_REQUIRED`.

L'importer deve distinguere tre livelli:

- `source_snapshot`: bytes e metadati ricevuti, senza interpretazione;
- `source_normalized`: campi del dataset mappati in un modello di importazione,
  con diagnostiche e provenance;
- `offer_eligible`: offerta normalizzata e applicabile al profilo della
  richiesta, pronta per il Comparison Engine.

Una fonte open-data valida non rende automaticamente ogni riga una tariffa
calcolabile. L'assenza di una componente, una validità ambigua, una formula
non supportata o un'applicabilità non dimostrabile producono un'esclusione
candidate, non un'approssimazione.

Il dataset ufficiale e la pagina di dettaglio del portale restano fonti
distinte. Se una pagina contiene una condizione non presente nel dataset, la
condizione viene conservata come testo/provenance e non modifica il costo,
salvo che sia già rappresentata da una regola economica strutturata.

## Contratto frontend → libreria

### Principi

- Il frontend invia JSON validabile con i modelli pubblici; non invia oggetti
  generici o formule eseguibili.
- Date e orari sono ISO 8601; gli importi, i tassi e le quantità economiche
  sono stringhe decimali per preservare `Decimal`.
- Campi sconosciuti, numeri binari `float`, `NaN`, `Infinity` e valori booleani
  in posizione economica sono rifiutati.
- Il frontend non invia al Portale Offerte POD, nome, indirizzo, codice fiscale,
  credenziali o altri dati personali. Il download usa solo i filtri di
  applicabilità necessari.
- Il frontend non replica Pricing, Billing, proratazioni, IVA, accisa o
  arrotondamenti. Visualizza il risultato restituito dalla libreria e le sue
  assunzioni, warning, provenance ed esclusioni.

### Input minimo

Il payload di confronto deve poter essere deserializzato in un
`ComparisonRequest` della Spec 007 e deve contenere:

- `current_contract`, già strutturato e coerente con `SupplyPoint`, tariffa e
  validità;
- `consumption`, un solo `ConsumptionProfile` per lo scenario;
- `period` e `as_of` espliciti;
- `classification`, `rule_set` e `coverage_matrix` verificati;
- `rounding_policy` monetaria e `percentage_rounding_policy` esplicite;
- `market_data` quando una candidata indexed lo richiede;
- eventuali `measurements` billing verificate;
- `external_items`, se presenti, separati dal calcolo come già definito in 007.

Il payload è incapsulato in `PortalComparisonRequest` (la precedente
`PortalOffersQuery` indicativa non è un secondo contratto) e contiene:

- commodity, inizialmente solo `electricity`;
- segmento cliente e classe di fornitura derivati dalla classificazione;
- territorio o zona necessaria a dimostrare l'applicabilità dell'offerta;
- modalità di attivazione richiesta, se il dataset la espone;
- data di riferimento `as_of`;
- ambito delle offerte richiesto, ad esempio `free_market` o un insieme
  esplicitamente supportato;
- politica di aggiornamento: nella v0.8 `on_demand`, senza fallback implicito.

La query non può allargare la copertura del ruleset o della matrice. Un filtro
non supportato dal dataset deve produrre un errore o un'esclusione esplicita,
mai essere ignorato senza evidenza.

### Output minimo

La libreria deve restituire un `PortalComparisonResult` serializzabile che
contenga:

- `snapshot` o il suo identificativo content-addressed;
- data di acquisizione, URL finale allowlisted, formato e digest SHA-256;
- versione del parser e, se disponibile, versione dichiarata del dataset;
- conteggi di righe ricevute, normalizzate, idonee ed escluse;
- offerte idonee eventualmente esposte per audit, senza dati personali;
- diagnostiche, warning e provenance aggregate;
- esclusioni di importazione ordinate in modo deterministico;
- il `ComparisonResult` della Spec 007, con baseline, ranking, risparmi,
  copertura ed eventuali partite esterne separate.

Se il download e il parsing riescono ma nessuna offerta è eleggibile, il
risultato è valido con ranking vuoto e tutte le esclusioni visibili. Se il
contratto corrente, la copertura globale, il dataset o lo schema sorgente non
sono verificabili, l'operazione fallisce senza un confronto parziale.

## Modelli pubblici richiesti

I nomi sono indicativi del contratto e possono essere raffinati durante la
pianificazione, senza cambiare la semantica.

### Profilo Portale in `PortalComparisonRequest`

`PortalComparisonRequest` è il modello Pydantic v2 frozen con `ComparisonContext`,
cataloghi espliciti, `PortalEligibilityProfile`, eventuali market data verificati
e politica `on_demand_exact`. I codici di territorio e di attivazione devono
essere quelli dichiarati dal dataset o da una tabella di mapping versionata; non
si confrontano stringhe libere con euristiche.

### `PortalFileSnapshot`

Rappresenta un file ricevuto:

- ruolo (`offers`, `supplier_registry`, `auxiliary` o altro ruolo verificato);
- URL originale e URL finale;
- `retrieved_at` timezone-aware;
- content type, dimensione, bytes e SHA-256;
- versione/schema dichiarati dalla fonte, se presenti.

Il modello è immutabile. I bytes possono restare in memoria o essere gestiti da
un consumer esterno; la libreria non persiste automaticamente materiale
scaricato.

### `PortalOffersSnapshot`

Raggruppa uno o più `PortalFileSnapshot`, dataset date/period dichiarati,
commodity, digest del manifest e provenance. L'identificativo è derivato dal
manifest canonico e dall'hash dei file, non dall'ordine di download.

### `PortalOfferRecord`

Rappresenta una riga source-normalized prima della conversione in `Offer`.
Conserva almeno:

- codice offerta del portale e identificativo venditore;
- nome e tipo dichiarati (`fixed` o `indexed`);
- periodo di pubblicazione/validità quando presente;
- ambito territoriale, profilo cliente e modalità di attivazione dichiarati;
- componenti economiche strutturate e unità originali;
- condizioni testuali non economiche;
- eventuale spesa annua dichiarata come evidenza separata, mai come risultato;
- provenance puntuale e diagnostiche di mapping.

Campi non necessari al calcolo non devono essere scartati se servono a
spiegare l'idoneità o l'esclusione.

### `NormalizedPortalOffer`

Contiene l'`Offer` canonica, la provenance del record sorgente, gli attributi
di applicabilità usati dal filtro e le assunzioni/warning residue. La tariffa
deve essere una `FixedTariff` o `IndexedTariff` valida per il periodo della
richiesta. Il codice offerta del portale diventa l'identificativo stabile
`offer_id`, salvo una collisione dimostrata dal dataset.

### `PortalOfferExclusion`

Modello immutabile con `offer_id` o riferimento sorgente, codice stabile,
messaggio deterministico e provenance. I codici minimi sono:

- `unsupported_commodity`;
- `not_current`;
- `period_not_covered`;
- `territory_not_covered`;
- `classification_not_covered`;
- `activation_not_covered`;
- `duplicate_offer_id`;
- `missing_provenance`;
- `source_malformed`;
- `tariff_not_representable`;
- `indexed_input_missing`;
- `not_verified`.

Le esclusioni di importazione sono distinte dalle esclusioni di confronto 007
(`pricing_failed` e `billing_failed` incluse). Devono essere ordinate per
codice offerta e poi per codice di esclusione.

### `PortalOffersImportResult`

Contiene snapshot, stato (`VERIFIED`, `REVIEW_REQUIRED` o `UNVERIFIED`), record
normalizzati, offerte idonee, esclusioni, diagnostiche e warning. Un risultato
`REVIEW_REQUIRED` non può essere usato per avviare automaticamente un confronto.

### `PortalComparisonResult`

Contiene `PortalOffersImportResult` e il `ComparisonResult` 007. Il suo ID deve
essere SHA-256 del payload canonico composto da query, snapshot, parser version,
`ComparisonRequest` e offerte normalizzate ordinate per `offer_id`.

## Acquisizione sicura

L'adapter HTTP concreto è un dettaglio sostituibile. Il core deve esporre un
protocollo minimale iniettabile nei test e nei consumer, come già avviene per
l'importer ARERA, senza importare SDK web.

L'acquisizione deve:

- consentire solo HTTPS e host allowlisted del Portale Offerte;
- seguire redirect soltanto se il nuovo URL resta allowlisted;
- limitare timeout a 60 secondi per file, massimo tre redirect, massimo cinque
  file, 64 MiB per XML, 8 MiB per CSV e 96 MiB complessivi;
- verificare status HTTP e content type dichiarato;
- rifiutare HTML, PDF o archivi non previsti dal manifest;
- calcolare il digest sui bytes ricevuti prima del parsing;
- non usare cookie, login, token, dati del contratto o header identificativi;
- non sostituire una risposta errata con una cache senza consenso esplicito;
- conservare gli header non personali utili all'audit senza fare affidamento su
  essi per la semantica economica.

Il parser XML deve usare una libreria hardened e parsing streaming quando la
dimensione lo richiede. CSV, encoding, delimitatori, namespace e schema devono
essere verificati contro fixture ufficiali; un cambiamento non riconosciuto
produce `source_malformed`/`REVIEW_REQUIRED`.

## Normalizzazione economica

Le basi `PER_YEAR` e `PER_KW_YEAR` sono supportate dal Pricing Engine. Il
pro-rata commerciale obbligatorio è `MONTHLY_TWELFTHS_PARTIAL_365`: ogni mese
solare completamente coperto vale 1/12 dell'importo annuo, mentre una frazione
vale giorni/365. Il fattore è calcolato in `Decimal`, senza arrotondamenti
intermedi, e viene applicato anche ai corrispettivi per kW/anno dopo la
moltiplicazione per la potenza contrattuale.

### Regole comuni

- Ogni tasso viene convertito a `Decimal` con unità esplicita e senza float.
- Ogni valore mantiene periodo, fonte, locator e stato di verifica.
- Le date del portale sono interpretate come periodi semiaperti
  `[start, end)` coerenti con il dominio.
- Una riga è corrente solo se il periodo dichiarato contiene `as_of`; l'assenza
  di una data non viene sostituita con la data di download.
- La validità della tariffa deve coprire interamente `ComparisonRequest.period`.
- La stessa fornitura del contratto corrente viene usata per creare il
  contratto candidato, come richiesto dalla 007.
- L'ID del contratto candidato resta derivato da offerta, fornitura, snapshot e
  payload canonico; non si usa un UUID casuale.

### Fixed

Un'offerta fixed può essere convertita solo quando il dataset espone tutte le
componenti necessarie in unità modellabili (`per_kWh`, `per_day`, `per_month`,
`per_kW_day`, `flat`, o altra unità già supportata dal Pricing Engine), con
bande coerenti e validità non ambigua. Componenti non riconducibili a una
`ChargeRule` restano non rappresentabili.

### Indexed

Un'offerta indexed può essere convertita solo se il dataset identifica
esplicitamente indice, banda, granularità, spread/componenti e periodo. La
formula viene costruita soltanto con gli operatori già supportati da
`PriceExpression`. Un valore forward o una stima annua del portale non è un
indice di mercato sufficiente per la 007: se `MarketData` manca o non copre il
periodo, l'offerta viene esclusa con `indexed_input_missing` oppure,
successivamente, con `pricing_failed` dal Comparison Engine.

### Bonus, sconti e condizioni

- Bonus numerici, non condizionati e con periodo/unità espliciti possono essere
  trasformati in `discounts` con provenance.
- Bonus condizionati a comportamento, canale, pagamento, durata minima,
  servizi abbinati o requisiti non modellati restano in `conditions` e in un
  warning; non vengono applicati al totale.
- Prodotti, servizi, canoni opzionali e voci non comparabili restano evidenza
  esterna dell'offerta. Non entrano nel `BillingResult` né nel ranking 007.
- La spesa annua stimata pubblicata dal Portale viene conservata, se presente,
  come osservazione source-faithful. Non sostituisce Pricing, Billing,
  arrotondamenti, IVA, accisa o regole del ruleset selezionato.

## Applicabilità e copertura

Il filtro di eleggibilità deve usare solo dati strutturati e mapping versionati:

1. commodity e classe di utenza;
2. livello di tensione e caratteristiche della fornitura;
3. territorio/zona coperto dall'offerta;
4. modalità di attivazione;
5. finestra `subscription_period` rispetto ad `as_of`;
6. copertura della tariffa rispetto al periodo;
7. compatibilità del tariff type con il Pricing Engine;
8. provenance e stato di verifica.

L'importer non amplia la `BillingCoverageMatrix`. Prima del download, il
servizio deve eseguire il preflight globale della 007: contratto corrente,
ruleset, classificazione, matrice, misure e rounding. Un errore globale deve
fallire senza ranking e, quando possibile, senza effettuare il download.

Un record del portale non può essere presentato come idoneo soltanto perché il
portale lo mostra in una ricerca generica. Il risultato deve spiegare quali
campi hanno dimostrato l'applicabilità alla fornitura del frontend.

## Orchestrazione end-to-end

Il servizio applicativo previsto dalla v0.8 esegue in ordine:

1. deserializzazione e validazione del payload frontend;
2. preflight della richiesta 007;
3. costruzione della query open-data senza dati personali;
4. acquisizione e verifica dello snapshot;
5. parsing source-faithful con diagnostiche deterministiche;
6. normalizzazione dei record e raccolta delle esclusioni;
7. filtro di validità/applicabilità;
8. invocazione di `DeterministicComparisonEngine` sulle sole offerte idonee;
9. aggregazione di provenance, assunzioni, warning ed esclusioni;
10. serializzazione del `PortalComparisonResult` per il frontend.

Il Comparison Engine non deve conoscere il trasporto, il formato del portale o
il frontend. L'orchestratore non deve duplicare formule di Pricing/Billing.
Una candidata che supera l'importer ma fallisce Pricing o Billing rimane
un'esclusione 007 isolata; non invalida le altre candidate.

## Determinismo e immutabilità

- Stesso payload, stesso snapshot, stessa versione parser e stesso ruleset
  producono lo stesso `snapshot_id`, `import_id`, `comparison_id`, offerte,
  esclusioni e ranking.
- L'ordine dei file, delle righe e delle offerte ricevute non modifica gli ID
  o il risultato.
- Snapshot e modelli pubblici sono Pydantic v2 frozen e serializzabili.
- Il JSON canonico ordina chiavi e collezioni semantiche prima dell'hash.
- Nessun timestamp di esecuzione, UUID casuale o hash dell'ordine di input entra
  in un identificativo economico.
- I bytes raw non vengono mutati dal parser; una fixture verificata conserva
  sempre il digest dichiarato.

## Errori e stati

### Errori globali

`PortalOffersError` deve fallire l'intero flusso per:

- URL non allowlisted, redirect non sicuro o risposta HTTP errata;
- content type, dimensione, encoding o archivio non validi;
- digest incoerente o manifest incompleto;
- schema/namespace/colonne non riconosciuti;
- snapshot senza data o provenance minima quando necessaria;
- stato `REVIEW_REQUIRED` usato per il confronto automatico;
- payload frontend, contratto corrente o copertura 007 non validi.

### Errori isolati

Una riga o un'offerta può essere esclusa singolarmente per codici
`PortalOfferExclusion` senza perdere le candidate valide. Il messaggio non deve
esporre dati personali e deve indicare il locator o il codice sorgente utile
alla diagnosi.

## Acceptance criteria

- Esiste una specifica e un ADR dedicati all'importer prima dell'implementazione.
- Il contratto frontend JSON viene validato senza float, campi extra o formule
  arbitrarie e supporta round-trip lossless dei `Decimal`.
- Un fixture ufficiale elettrico viene scaricato/rappresentato come snapshot
  immutabile con digest, provenance e parser version.
- Il parser riconosce il formato supportato, rileva schema modificato e fallisce
  chiuso su file corrotti, HTML, redirect non consentiti e digest errato.
- Fixed e indexed validi diventano tariffe canoniche con source locator e
  periodi corretti; i termini non rappresentabili vengono esclusi.
- Il filtro dimostra `as_of`, periodo, classificazione, territorio e modalità di
  attivazione; non usa euristiche su testo libero.
- La spesa annua dichiarata dal portale non modifica il totale calcolato dalla
  007. Bonus condizionati, servizi e voci esterne restano visibili ma esclusi.
- Il flusso end-to-end produce il ranking 007, risparmi e percentuali con lo
  stesso ordinamento e gli stessi ID della richiesta normalizzata equivalente.
- Un insieme senza offerte idonee produce un risultato valido con ranking vuoto;
  un errore globale non produce un confronto parziale.
- L'ordine dei file e delle righe non modifica snapshot, ID, esclusioni o
  ranking.
- Nessun dato del contratto corrente viene inviato al Portale Offerte e nessun
  documento personale viene scritto nel repository.
- Le offerte non correnti, duplicate, non verificabili, fuori territorio o non
  modellabili hanno esclusioni stabili e auditabili.
- Ruff, format check, mypy strict, pytest con branch coverage almeno 95%,
  pre-commit, build wheel/sdist e `git diff --check` passano; lo smoke live del
  Portale è separato dai test deterministici.

## Test richiesti

### Sorgente e trasporto

- URL e redirect allowlisted/non-allowlisted;
- timeout, status, content type, limite bytes e archivio malformato;
- encoding, namespace, delimitatore e colonne inattese;
- digest, snapshot ID e manifest con ordine permutato;
- fixture minime per fixed, indexed, bonus, servizi e record incompleti.

### Normalizzazione

- mapping `Decimal` e unità senza float;
- periodi semiaperti e confini di `as_of`;
- duplicate offer ID e supplier ID;
- fixed con bande e componenti duplicate;
- indexed senza indice, spread, granularità o punti di mercato;
- bonus applicabili/non applicabili e condizioni residue;
- offerte fuori territorio, classificazione, attivazione o periodo;
- provenance mancante e stato non verificato.

### Frontend e confronto

- JSON round-trip e immutabilità di tutti i modelli pubblici;
- preflight globale prima del download;
- confronto fixed/fixed e fixed/indexed tramite 007;
- isolamento di `pricing_failed`/`billing_failed` dopo import riuscito;
- partite esterne invarianti per ranking, risparmi e totale comparabile;
- nessuna candidata idonea con risultato valido e ranking vuoto;
- input riordinati con ID e ranking invarianti;
- assenza di dipendenze da framework web, browser, database, cloud, MCP o AI.

### Smoke live

Uno smoke test può interrogare il Portale reale e verificare raggiungibilità,
content type, digest e parsing di un dataset corrente. Non deve rendere la
suite unit/integration dipendente dalla rete né fissare in repository dati
personali o bytes che cambiano senza digest dichiarato.

## Evidenza e limiti dichiarati

Il risultato deve mostrare almeno:

- data e digest dello snapshot usato;
- fonte e versione del parser;
- livello di verifica dell'importazione;
- numero di offerte ricevute, idonee ed escluse;
- condizioni residue e bonus non applicati;
- copertura regolatoria 007 e market data richiesti;
- distinzione fra costo comparabile calcolato e stima dichiarata dal portale.

La v0.8 non può dichiarare "tutte le offerte disponibili" se il dataset,
l'ambito domestico BT o il mapping economico coprono soltanto un sottoinsieme.
Deve inoltre dichiarare che la convenienza è calcolata per lo scenario di
consumo fornito, il periodo e l'`as_of` indicati, non come previsione universale
del costo futuro.

## Decisioni di pianificazione congelate

- gli endpoint sono HTTPS allowlisted sul dominio ufficiale, con quattro file
  elettrici (Mercato Libero/PLACET), CSV storico indici quando richiesto, limiti
  di redirect/tempo/dimensione e nessun dato del contratto negli URL;
- il territorio commerciale resta nel `PortalEligibilityProfile`; `SupplyPoint`
  mantiene soltanto la zona elettrica;
- il mapping fixed/indexed usa soltanto `PriceExpression` e `MarketData` verificati;
  formule a scaglioni, canoni, dual fuel e condizioni obbligatorie non
  rappresentabili producono esclusioni;
- la v0.8 include entrambi i cataloghi e non usa fallback, forecast,
  interpolazione o persistenza; gas e ulteriori formati richiederanno una spec
  autonoma.

## Riferimenti normativi e di fonte

- [ARERA — Il Portale Offerte](https://www.arera.it/consumatori/il-portale-offerte)
- [ARERA — Delibera 51/2018/R/com e scheda tecnica](https://www.arera.it/schede-tecniche/dettaglio/it/schedetecniche/18/051-18st)
- [ARERA — Allegato A, contenuti minimi del Portale Offerte](https://www.arera.it/fileadmin/allegati/docs/18/51-18_Allegato_A__valido_dall_1_aprile_2026.pdf)
- [Acquirente Unico — Portale Offerte](https://www.acquirenteunico.it/attivita/portale-offerte)
