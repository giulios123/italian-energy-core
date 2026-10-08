# Active context

## Regulatory Anchor Rollover — Q4 promosso localmente, 2026-10-08

Il Core ha promosso l'anchor Q4 da un replay deterministico dello snapshot
ufficiale completo acquisito il 2026-10-08. La matrice Core versionata collega
i campi dell'anchor agli indici tariffari ARERA, ADM e alle disposizioni
Normattiva sorvegliate; non è stata richiesta classificazione manuale dei
record generalisti.

Anchor corrente packaged:
`src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q4.json`.
ID `regulatory-anchor:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`,
digest `641c71a677d98cefe6ec562fd5665a54d3620059e61d70c6a00c397238073ddf`,
snapshot `2026-10-08`, validità `[2026-10-01, 2027-01-01)`, status `VERIFIED`.
Il candidate immutabile d'origine resta in
`arera-domestic-bt-projection-anchor-2026-q4-candidate.json`.

La coverage datata è in
`arera-domestic-bt-coverage-2026-10-08.json`; l'evento append-only di
promozione è in `arera-domestic-bt-promotion-event-2026-10-08.json`. Il replay
ha dato candidate coverage pronta, stage riuscito, promozione singola,
coverage anchor pronta e `source_preflight.ready=true`. Il confronto sintetico
ha restituito tre scenari usando soltanto gli snapshot forniti; la rete è stata
disabilitata nel test. Gate Core finale: 689 test, 95,05% branch coverage,
Ruff check/format, mypy `src tests` e `git diff --check` tutti verdi.

Il loader packaged seleziona l'anchor con `as_of` usando intervalli half-open;
il CLI passa la data alla risoluzione. La coverage prova la data 2026-10-08 e
deve essere aggiornata prima di confronti in date successive. La 0.13.0 è
pubblicata su GitHub e PyPI dal tag `v0.13.0` sul commit
`e8306161d8b5056135a18f2c594cd56c1550bde9`. CI Python 3.12–3.14 e Trusted
Publishing sono verdi; l'installazione isolata da PyPI conferma capability e
anchor Q4. Archivio/job Platform, Docker e PostgreSQL restano un gate separato
e non sono inclusi nel rilascio.

### Snapshot storico M21 — collegamento TUA verificato (superato da M23)

L'API Normattiva attribuisce l'aggiornamento TUA del 25/09 alla Legge
26G00184; il testo Gazzetta e il testo coordinato ufficiale mostrano che la
misura riguarda il gasolio fino al 05/09, prima della validità Q4. Il Core ora
conserva `ultimiAttiModificanti` e ha regole/test esatti per i due record
collegati. Il workflow live completo non è ancora stato rieseguito, quindi
resta valido l'ultimo esito certificato: candidate `UNVERIFIED`, preflight
chiuso, nessuna promozione. Restano i finding ARERA/Gazzetta/Normattiva non
collegati o non interpretati; non vanno classificati tutti a mano.

Replay diagnostico (non workflow) con la risposta Normattiva live e le nuove
regole: 1011 record, 3 supportati, 1002 in review, 6 irrilevanti per regola
versionata; review residue 39 ARERA, 914 Gazzetta, 49 Normattiva.

### Snapshot storico — 2026-10-05 (superato da stato 2026-10-07)

Spec 014/ADR 0017 governano la pipeline `discovery → acquire → parse → map →
validate → candidate → verify → stage → promote`. M1–M14 Core e Platform Spec
013 P1 sono implementati localmente: il Core fornisce anchor v2, fatti
`Decimal`, parser/mapping esatti, coverage e review auditabili, workflow
`refresh_regulatory_state`, `source_preflight` e `resolve_active`; la Platform
fornisce il worker giornaliero, store PostgreSQL/Blob, CAS e gate del catalogo.
Il confronto cliente usa snapshot persistiti e resta offline.

Core gate 2026-10-05 dopo M14: 626 test, 95,01% branch coverage, Ruff
check/format, mypy su `src tests`, `uv lock --check --offline` e
`git diff --check` verdi. Una scansione live limitata
`2026-09-04`–`2026-10-05` ha completato tutti i canali: ARERA atti
(43 pagine/29 record), ARERA tariffe (1), ADM (1), Gazzetta (775) e Normattiva
(1 pagina/49 atti). Il report contiene 853 finding ancora da interpretare;
`scans_complete=true` non significa assenza di review. La scansione precedente
del 2026-10-04 aveva 919 finding su una finestra diversa. Il path ufficiale
Gazzetta usa `caricaDettaglioAtto`; classifier e test ora corrispondono ai
record live `26A04702` e `26A04766`, che ottengono le rispettive regole esatte.
Il client urllib locale non valida la catena Normattiva; la risposta è stata
acquisita in precedenza con macOS SecureTransport, TLS verificato, e validata
dall'adapter Core. Il registry parser ora supporta il workbook ARERA Spec 005,
le due disposizioni VAT AKN del DPR 633/1972 e la riga domestica del PDF ADM.
Il replay offline end-to-end del PDF ADM privato ha prodotto `0.0227 EUR/kWh`
con digest uguale alla fonte nell'anchor; nessun fetch live è stato eseguito
in questa tranche. `343/2026/R/com` è stato individuato, ma il PDF non è ancora
nel workspace: l'utente lo inserirà appena disponibile. Mancano la catena Core
di effetti per l'atto e l'interpretazione degli altri finding fiscali. L'URL
PDF estratto dalla pagina ufficiale è stato
richiesto via Core client, curl e browser: ha restituito HTTP 502 e non ha
prodotto bytes/hash. L'anchor packaged è scaduto il 2026-10-01 e
`source_preflight.ready` resta false.

La pagina ufficiale ARERA di riepilogo conferma i gruppi di componenti Q4, ma
Spec 014 §19 richiede ancora l'atto e la disposizione puntuale per ogni fact;
il PDF 343 rimane HTTP 502 nell'ultima verifica registrata. Il trasporto
urllib va allineato al trust store del runtime Platform prima che il worker usi
questa via localmente.

Il classifier Core predefinito assegna `known-q4-act-review/v1.0.0` all'esatto
record ARERA `343/2026/R/com`, ancora da interpretare. Dopo verifica degli
artt. 12 e 32 della Gazzetta ufficiale, `26A04702` riceve la regola puntuale
`gazzetta-dl148-domestic-electricity-rates-out-of-scope/v1.0.0`: non produce
facts e non cambia le aliquote domestiche elettriche modellate. La regola
`gazzetta-diesel-excise-out-of-scope/v1.0.0` continua a escludere l'esatto
`26A04766`, relativo al gasolio carburante dal 6 al 10 settembre. Non si usano
keyword/titoli o ID simili; altri finding e metadati discordanti restano review.
La discovery è completa, ma restano finding da interpretare, il preflight è
chiuso e non esiste un candidate Q4 reale.

Platform gate locale: 233 test unitari passati, coverage raw 90,10%,
Ruff check/format, strict mypy, architecture scan, Compose config e diff check
verdi. I due test PostgreSQL 17 sul repository rollover passano con il sorgente
Core locale; il baseline precedente riportava sei test PostgreSQL e migration
upgrade/downgrade/upgrade verdi. Il container locale è stato buildato con
wheel Core 0.13.0 e il contract smoke è passato; PyPI continua a fornire solo
0.12.0, quindi nessuna release né certificazione d'uso pubblicata.

Decisioni correnti: discovery/parsing/mapping versionati, nessun guessing di
PDF, `carry_forward` solo con prova normativa, candidate/anchor immutabili,
intervalli half-open, promotion CAS, refresh legacy compatibile. Le stime
regolatorie future restano ipotesi. Il rilascio 0.13.0 resta un gate separato;
nessun commit, tag, push o release.

Discovery snapshot/report e rollover report ora serializzano v2. Ogni snapshot
conserva decisione di classificazione e record sorgente; le review irrisolte
restano visibili fuori dalla finestra di overlap. Il repository Platform ignora
snapshot incompleti nella scelta del checkpoint, pur conservando le letture v1
storiche. Il gate resta chiuso: l'ultima discovery live ha 919 finding, nessun
candidate Q4 e nessuna promozione; la persistenza v2 non certifica
l'interpretazione di atti o imposte.

Verifica fonti del 2026-10-05: sono state acquisite le pagine tariffarie
ufficiali ARERA, con digest `8510582e29e18c908ccc030729c0db6fab5c785ae3f41cc78d6126e6c98ad8a7`
(oneri) e `69edbde3f83dee3bee3ea2fc1b90ded7229a237cd63d752851143742bf14c0f8`
(tariffe gas). Indicano conferme per A_SOS/A_RIM e componenti GS/RE/RS/UG1/UG3,
ma non bastano da sole secondo Spec 014 §19 a formare tutti i fatti profilo/quota.
Il workbook ARERA 227/Q3 di 50.308 byte è stato riacquisito e il suo digest
coincide con quello congelato nell'anchor. Il PDF 343 collegato continua a
restituire HTTP 502. I testi ufficiali del D.Lgs. 148/2026 hanno chiuso solo il
finding esatto per i tassi domestici elettrici con la regola M12; gli altri atti
fiscali e il mapping Q4 restano da verificare. Nessun candidate Q4 reale è
costruito o promosso; `source_preflight.ready` resta false.

## Snapshot storico — implementazione locale 2026-10-01

Spec 014 e ADR 0017 governano la pipeline `discovery → acquire → parse → map →
validate → candidate → verify → stage → promote`. M1–M8 sono complete
localmente; Platform P1 resta separata. Anchor v2, facts `Decimal`, build key,
digest artefatto, parser/mapping versionati, coverage e review auditabili,
repository append-only in-memory e CAS sono implementati. M7 aggiunge
`RegulatoryRolloverService.refresh_regulatory_state`, report tipizzato,
`source_preflight` e `resolve_active`; test sintetici coprono staging il
30/09/2026, promozione il 01/10/2026, rerun, outage, review, digest cambiato e
compare offline. M8 aggiunge capability e schema ID al manifest, envelope
canonici e compatibilità del confronto con la nuova evidence. Il CLI mantiene
`--refresh-anchor` per il significato precedente; non esiste `--rollover`.
Gate finale Core: 498 test, 95,09% branch coverage, Ruff, format, mypy e
`git diff --check` verdi. Nessun adapter ufficiale live è certificato, i
parser fiscali non sono supportati e nessun anchor successivo reale è stato
prodotto o promosso. Nessun commit, tag, push o release.

La working tree contiene modifiche locali preesistenti su Spec 013/ADR 0016,
`RegulatoryCoverageEvidence`, `refresh_regulatory_anchor`, CLI e test, oltre
alle aggiunte Spec 014/M1–M8; tutte sono state preservate e i gate sono stati
eseguiti. Il package incluso ha un solo anchor `as_of=2026-09-27`, valido
`[2026-09-01, 2026-10-01)`. Il validator v1 resta mensile; `refresh_regulatory_anchor`
verifica ancora solo gli otto documenti noti e non scopre atti né costruisce B.
Al 2026-10-01 l'anchor packaged ha raggiunto `valid_until` e il suo preflight
resta fail-closed; la fixture A→B trimestrale della Spec 014 resta sintetica
e distinta.

Decisioni principali: lead time configurabile con default 30 giorni; discovery
completa ARERA/ADM/Gazzetta/Normattiva con cursor e cross-check; parser e
mapping versionati, nessun guessing di PDF; `carry_forward` solo con prova;
candidate e anchor immutabili, build key distinto da artifact digest; validity
half-open e `snapshot_as_of` potenzialmente precedente a `valid_from` nel v2;
stage/promotion CAS transazionali nel repository Platform, selezione Core per
validità e coverage fresca. Il vecchio refresh mantiene la semantica e gli
envelope v1 restano leggibili. Il confronto rimane offline e le applicazioni
regolatorie future della beta restano stime/ipotesi.

La lettura in sola lettura della Platform ha confermato il worker che acquisisce
solo l'anchor packaged, `anchor.as_of == today` nel gate locale e il pin
`>=0.12.0,<0.13.0`. P1 dovrà salvare current/staged/history/evidenze e
invocare `resolve_active`/`source_preflight` Core, senza duplicare logica
normativa. La consultazione web di indici ufficiali ha informato la strategia
di discovery, ma non è una scansione live certificata dei registri né una
verifica di valori successivi. P1 deve implementare persistenza di
current/staged/history, snapshot/cursori, evidenze, eventi e CAS, poi invocare
`regulatory_anchor_rollover`, `source_preflight` Core e il gate catalogo
Platform. Parser e policy fiscali restano in Core. Lead time default 30 giorni,
coverage freshness default un giorno civile. Nessun `--rollover` CLI finché
non esistono adapter live certificati e repository durevole; layout o atti
ignoti restano in review. Rischi live: fonti ufficiali e API Normattiva di
produzione non certificate.

## Refresh esplicito dell’anchor — 2026-09-29

Implementato localmente il contratto `REGULATORY_ANCHOR_REFRESH` e lo schema
`italian-energy/regulatory-anchor-refresh-result/v1`. L’API
`ProjectedDomesticEnergyService.refresh_regulatory_anchor(as_of,
registry_reviews)` e la CLI `projection_cli --refresh-anchor` riscaricano gli
otto documenti dell’anchor incluso, ne confrontano gli SHA-256, conservano
`anchor.as_of` e producono un envelope riusabile offline. Non acquisiscono
catalogo o GME. Anchor scaduto, fonte mutata, revisione assente, atto incerto o
applicabile bloccano il risultato.

Limite esplicito: il refresh non scopre né interpreta da solo nuove
pubblicazioni e non genera un anchor aggiornato per periodi non coperti. La
revisione dei registri è ancora un input datato; per automatizzare nuovi valori
servono parser/mapping versionati delle nuove fonti e una milestone separata.
La Platform non è stata modificata; deve usare la nuova capability di refresh
per ottenere l’evidenza e `source_preflight(...).ready` per il gate. Nessun
commit, tag, push o release.
Gate locali 2026-09-29: 326 test, 95,27% branch coverage, Ruff check/format,
mypy e `git diff --check` verdi. I controlli usano fixture, senza refresh live
dei registri in questa sessione.

## Correzione riuso anchor — 2026-09-29

Implementata localmente la correzione Spec 013/ADR 0016 per l’anchor incluso:
`as_of=2026-09-27` resta la data dello snapshot; validità half-open
`[2026-09-01, 2026-10-01)` consente il confronto del 29 settembre solo con
evidenza specifica per quella data. Il pacchetto non va riscaricato ogni
giorno. Dal 1° ottobre serve un anchor applicabile.

`RegulatoryCoverageEvidence` lega digest canonico e ID dell’anchor, data del
confronto, verifica degli otto documenti e revisione datata delle fonti
ufficiali successive (responsabile, ricerche, atti e decisioni di applicabilità).
Hash invariati da soli non attestano assenza di nuovi atti. Il gate Core
`ProjectedDomesticEnergyService.source_preflight(...).ready` e il preflight
cliente sono offline e fail-closed; la CLI distingue acquisizione/verifica live
dal replay deterministico di `ProjectedSourceBundle`. I valori futuri restano
stime (`future_values_verified=false`).

Verifica locale 2026-09-29: 321 test, branch coverage 95,42%, Ruff check e
format, mypy, `git diff --check` verdi. Non è stata eseguita né attestata una
nuova revisione live dei quattro registri il 29 settembre; le fixture dei test
sono sintetiche. La Platform non è stata modificata: deve sostituire il
controllo locale `anchor.as_of == today` con `source_preflight(...).ready`,
insieme alla propria regola di freschezza catalogo, e invocare
`preflight(request, ...).ready` prima di `compare`. Nessun commit o nuova
pubblicazione.

Release Core `v0.12.0` del 2026-09-28: Spec 013, importer GME, anchor
ARERA/fiscale, envelope e CLI di verifica sono inclusi nel package. La release
GitHub allega wheel, sdist e checksum; PyPI viene pubblicato dal workflow OIDC.
La Platform non è stata modificata e il suo vincolo `<0.12.0` richiede
allineamento prima di consumare questa versione. Nessun envelope cliente è
stato fornito per il confronto personalizzato.

Milestone completata localmente (2026-09-27): Spec 013 `Confronto beta
domestico con scenari storici`, ADR 0016 e capability additiva in Core. Il
metodo congelato è: 12 mesi civili recenti e consecutivi, proiezione sul
medesimo mese dell'anno, indici 0,80/1,00/1,20 e recommendation solo sul base;
i valori futuri sono stime. La precedente proposta forward/robust è ora Spec
012 differita; Spec 011 resta il Current Domestic Advisor rilasciato. La
working tree contiene anche le modifiche catalog CLI preesistenti: preservate.

Aggiornamento 2026-09-27: autorizzato e implementato un comando operativo
`italian_energy.integration.catalog_cli` per l'acquisizione esatta del catalogo
reale con diagnostica delle fonti/indici. Il catalogo live 2026-09-27 è VERIFIED:
4.478 record, 156 punti indice, snapshot
`d425ff802cf6233ff1e86711718e91848b6d4664f1ddd129446376324e351d86`.
I due indici arrivano a giugno 2026; il workbook ARERA live conserva il digest
congelato e la copertura termina il 2026-09-01. La Platform ha persistito i
cinque file (20.992.193 bytes), verificato i digest in lettura e riporta il
catalogo disponibile. Questo non chiude la copertura economica prospettica.
L'utente ha scelto per la beta scenari sullo storico: base, -20%, +20%; Entra
External ID è rimandata alla versione finale. Il contratto prospettico forward
è stato rinumerato Spec 012 e resta differito; Spec 013 governa la beta storica.
Nessun cambio di versione o pubblicazione.

Baseline pubblicata: Spec 011 Current Domestic Advisor v0.11.1. Il preflight
tipizzato `CurrentDomesticEnergyService.preflight` resta compatibile; la Spec
013 è stata poi rilasciata in v0.12.0. L'accettazione staging della Platform
resta separata.
Il digest ARERA 2026 VERIFIED congelato per il replay storico è
`b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b` e copre
2026-01-01/2026-09-01; il nuovo anchor prospettico di settembre è separato.

Verifica finale Spec 013: 311 test passano con 95,22% di branch coverage; Ruff
check/format, mypy, `git diff --check`, entrambi i golden privati e smoke extra
`gme`/`arera` sono verdi. La verifica live `projection_cli --date 2026-09-27
--verify-sources` è `verified`: catalogo 4.478 offerte, storico PUN completo
settembre 2025–agosto 2026, report GME F1/F2/F3 verificati separatamente per
luglio/agosto 2026 e anchor ARERA/fiscale completo, valido 2026-09-01/2026-10-01.
L'anchor include le versioni Normattiva di Tabella A e art. 16 fissate al
2026-09-27; tutte le otto fonti hanno digest corrispondenti. I valori dei mesi
futuri restano stime sotto l'ipotesi di congelamento dell'anchor. Non è stato
fornito un envelope con consumi e contratto di un cliente, quindi la verifica
live non ha eseguito una comparazione personalizzata. La Platform non è stata
modificata.

Sono presenti composer deterministico, ruleset JSON residente/non residente,
matrice di copertura e loader indipendente dall'extra XLSX. Il checkpoint
non residente usa il PDF privato `private/nonresident.pdf`, che contiene già
riepilogo, letture mensili, dettaglio fiscale e Box dell'offerta; non è richiesto
un nome file specifico. Il JSON sanitizzato e il mapping privato sono presenti.

Il ruleset pubblico `arera-domestic-bt-resident-2026-05-06`, i test sintetici
indipendenti, il verificatore end-to-end e i due scenari JSON tecnici
sanitizzati sono presenti. Il golden residente e quello non residente passano
con bill stabile, chiavi abbinate e differenze entro 0,01 EUR. Nessun importo o
aliquota è stato adattato per forzare il risultato. La Spec 005 aggiunge un importer per il workbook elettrico
domestico ARERA 2026: il raw snapshot è content-addressed e conservato in
memoria, il parsing offline resta `UNVERIFIED`, mentre il fetch ufficiale può
produrre valori `VERIFIED` soltanto con layout e controlli completi. Il risultato
è un bundle source-faithful, non un `RegulatoryRuleSet` fatturabile.

La repository è pubblica su GitHub e la CI della release `v0.4.0` è verde su
Python 3.12, 3.13 e 3.14. Le release GitHub `v0.1.0` e `v0.4.0` sono pubblicate;
la working tree contiene la milestone 005 locale da preservare.

Il Comparison Engine opera su offerte già normalizzate e prequalificate, usa il
totale Billing all-in, consulta obbligatoriamente la matrice e isola candidate
non calcolabili con esclusioni motivate. Le partite esterne sono restituite come
evidenza ma escluse da Bill e ranking. La Spec 008 fornisce ora l'adapter
allowlisted che porta i cataloghi commerciali elettrici domestici BT alla 007;
non promette che ogni formula commerciale sorgente sia calcolabile.

La Spec 008 Portale Offerte Importer v0.8.0 è implementata localmente senza
commit/tag/push/release: `ComparisonContext`/`PortalComparisonRequest`, snapshot
content-addressed, acquisizione HTTPS allowlisted, parser XML/CSV, indici storici,
normalizzazione fixed/indexed e orchestrazione verso la 007 sono presenti. La
validità relativa usa mesi calendario con clamp e i corrispettivi annuali usano
1/12 per i mesi completi e giorni/365 per le frazioni. Ogni record termina come
offerta idonea o esclusione motivata; duplicati nello stesso catalogo escludono
tutte le occorrenze. Gas, PDF/OCR, persistenza, scheduler e UI restano fuori
perimetro; lo smoke live Portale è separato dalla suite offline.
Lo smoke live esplicito del 2026-09-08 ha acquisito 4.472 record e 156 punti
indice, producendo snapshot VERIFIED
`portal-snapshot:67577e044c0b257e3b11cbf1ce3f346218c6e932279e9845098b35ea2bb0d23d`.

La Spec 009 aggiunge RecommendationPreferences tipizzate, evidenze candidate
verificate, `DeterministicRecommendationEngine` e `PortalRecommendationAdapter`.
La decisione usa filtri hard e il minor totale comparabile; la soglia minima in
EUR è inclusiva e, se assente, il risultato resta `stay_current` per compatibilità
legacy. Nessun costo viene ricalcolato e nessun testo commerciale viene
interpretato.

La Spec 010 espone `italian_energy.integration` come contratto stabile: manifest
con capability/schema ID ordinati (anche tramite `CORE_SCHEMA_IDS`), richieste tipizzate per replay storico e
recommendation separata, envelope JSON canonici fail-closed e
`CoreContractError` con codici stabili. La façade seleziona ruleset e matrice
packaged per residente/non residente, richiede elettricità domestica BT e usa
rounding EUR/percentuali a due decimali HALF_UP. `defusedxml` è nella dipendenza
base; `openpyxl` resta nell'extra ARERA. L'allineamento della Platform e la
pubblicazione v0.10.0 restano milestone successive.

La CI della milestone locale include ora `openpyxl` anche nel gruppo `dev`,
perché la suite ARERA costruisce workbook XLSX sintetici. La dipendenza resta
comunque opzionale nel pacchetto distribuito: la wheel base non richiede
`openpyxl`, mentre l'extra `arera` continua ad abilitarlo per gli utenti.

La Spec 011 v0.11.0 è stata preparata come milestone documentale separata dal
replay storico: definisce dodici mesi da `activation_date`, catalogo alla
`quote_date`, profilo di consumo futuro fornito dal caller, schedule della
baseline e scenari `base`/`stress` con curve forward tracciate. La regolazione
e le imposte vengono congelate dai valori verificati attivi alla quotazione, ma
la loro applicazione futura resta una proiezione non `VERIFIED`; senza anchor
verificato il confronto fallisce chiuso. La recommendation può emettere
`switch` soltanto quando la stessa candidata supera la soglia in tutti gli
scenari. Sono stati aggiunti la spec e ADR 0015; questa milestone non ha
modificato codice, test, versione, Platform o pubblicazione. La working tree
contiene però modifiche concorrenti al percorso `Current Domestic Advisor`,
che devono essere preservate e consolidate separatamente.

Nel lavoro Platform del 2026-09-12 il percorso corrente è stato implementato
localmente: contratti `CurrentDomesticEnergyService`, scenari low/base/high,
capability/schema ID v1 e soglia percentuale sono ora presenti e coperti. La
suite è stata riallineata ai rami del current advisor (232 test, 95,29% branch
coverage); la release v0.11.0 include gli artefatti wheel/sdist installabili.
Il workflow `.github/workflows/release.yml` prepara e pubblica wheel/sdist su
PyPI tramite Trusted Publishing OIDC nell'environment GitHub `pypi`; il dispatch
manuale ha pubblicato il tag già esistente `v0.11.0` su PyPI.
