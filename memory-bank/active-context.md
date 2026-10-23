# Active context

## Refresh ARERA con ID compatto — verificato localmente 2026-10-23

- **Scritto:** Spec 014 §28 documenta il record ufficiale `5-26dicu` del
  22 ottobre che interrompeva l'indice generale e i controlli di identità.
- **Implementato:** `AreraActsIndexAdapter` 1.2.0 riconosce il formato compatto
  preservando ID, data e URL esatti. Nessuna modifica a scope, fonti, valori
  economici o policy di promozione. Sette regressioni coprono ID e metadati
  discordanti, paginazione e mancato avanzamento del cursore su errore.
- **Verificato:** 910 test, branch coverage 95,07%, Ruff check/format, mypy
  `src tests` e diff check passano sul checkout completo. La regressione del
  formato fallisce sul codice originale e passa dopo la correzione. Replay
  del raw ufficiale SHA-256
  `2d9641c0ae0e498e8a9bad5a548e894bdb3a06586cea1828e4ad331cc1e2ba2f`
  passato: dieci righe nella prima pagina, totale 463 su 47 pagine.
- **Runtime Platform locale:** tutti i cinque canali completati, 47 pagine
  ARERA, coverage/preflight corrente ready con motivi vuoti. I 69 finding
  Gazzetta rimasti in review durante il guasto sono risolti dalle regole di
  scope già esistenti; non sono state aggiunte esclusioni per titolo.
  Anchor corrente e digest invariati. Successore futuro ancora separatamente
  bloccato per `incomplete_coverage`, senza promozione.
- **Accettazione locale:** catalogo 2026-10-23
  `1c5146b5-0b02-41d9-b7b4-3adfbc521131`, verified e confronti abilitati;
  GET preflight del profilo Torino salvato ready con 265 offerte ammissibili;
  browser senza avviso fonti, errori o mutazioni. La Platform usa un override
  Compose locale ignorato da Git che monta questo sorgente in sola lettura
  su API, comparison worker, regulatory worker e catalog worker.
- **Confini:** modifiche preesistenti conservate, nessun nuovo confronto,
  commit, push, wheel pubblicata o deployment di produzione. Il pin wheel
  0.13.5 resta distinto dall'esecuzione del sorgente locale corretto.

## Core 0.13.5 — pubblicata 2026-10-19

Il tag `v0.13.5` e il commit `6220db76f88085ae1e759774b985ce7b8f544c87` sono
pubblicati su GitHub; PyPI espone `italian-energy==0.13.5`. Il workflow release
`39289896115`, inclusi build e Trusted Publishing, è riuscito. I digest PyPI e
GitHub coincidono: wheel `33b20140e3e84c3f79be61eef6c192641da1f9c219c3acaf57845b4250d21ed5`,
sdist `a610f40aac3903055d0ff70eeb2db9129179a8717b84fdae40db945035c7620a`.
Suite locale: 895 test, 95,00% branch coverage, Ruff check/format, mypy, lock
check, build e smoke isolato passano. La pubblicazione non prova adozione o
deployment Platform. Evidenza: `docs/release-0.13.5-publication.md`.

## Core 0.13.5 — preparazione della durata economica, 2026-10-18

- **Scritto:** Spec 008 v0.8.4, Spec 013 e ADR 0012/0016 separano adesione
  inclusiva da decorrenza e durata economica. La beta attiva al primo giorno
  del proprio orizzonte annuale. Il DURATA diretto di DettaglioOfferta è la
  durata delle condizioni economiche; -1 significa indeterminata.
- **Implementato:** parser v6, mapping economic-validity-v2, nuovo contesto
  prospettico e metadati economic_terms. Prezzi predefiniti annualizzabili
  non diventano promesse di durata; condizioni note insufficienti restano
  escluse. Le finestre sconto contigue restano esatte; nodi Sconto non
  modellati sono conservati ed esclusi. Snapshot precedenti restano leggibili
  ma richiedono refresh per la nuova normalizzazione. Nessun ricalcolo storico.
- **Verificato:** 895 test Core, branch coverage 95,00%, Ruff check/format,
  mypy e lock check passano. Il replay ufficiale del 18 ottobre dopo hydration
  legge 4.550 record e seleziona 257 candidate annuali per Roma/non residente
  e modalità 01/01, anziché otto; 57 con durata oltre dodici mesi. Quote, IVA,
  ranking e sconti sono controllati con importi attesi indipendenti.
- **Platform:** piccolo delta source/DTO/UI per quattro metadati e badge,
  270 test non integration / 90,68%, 26 test web/build e controlli mirati
  passano. Il checkout ampio rimane sospeso/uncommitted; controlli statici
  globali e adozione HTTP/runtime non sono certificati da questa milestone.
- **Separato:** pubblicazione 0.13.5, pin/digest Platform, immagini, refresh
  catalogo v6, worker/browser HTTP e deployment. Nessun commit, push o tag
  è incluso. Evidenze: `docs/offer-economic-validity-0.13.5.md`.

## Release Core 0.13.4 — pubblicata 2026-10-18

La release GitHub [v0.13.4](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.4)
punta al commit `b4de15af1561eb3cef33910bca7e60bc4ead1bdb`; il tag `v0.13.4`
è pubblicato e la CI su `main` (`39145299869`) e sul tag (`39145469387`) è
verde per Python 3.12, 3.13 e 3.14. Trusted Publishing (`39145646425`) è
riuscito e [PyPI](https://pypi.org/project/italian-energy/0.13.4/) espone
`0.13.4`.

I digest PyPI coincidono con gli asset GitHub: wheel
`b353a9510d1d216d27d36b1f23deb79028fcb1513fd5d59f9f26bd80b914deca`, sdist
`3f656573fff136f948c99eff46c5eaf2431885db3ab333edc02240a143f945b9`. Suite
locale: 842 test, 95,05% branch coverage; Ruff, format, mypy, pre-commit,
lock check, build wheel/sdist e smoke isolati passano. La copertura economica
annuale delle offerte resta un gate aperto; l'adozione Platform è separata.

## Release Core 0.13.3 — pubblicata 2026-10-18

La release GitHub [v0.13.3](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.3) punta al commit `e2226e63c4ae3e7ab8431409c1fbba2c9e1cd05e`. CI su `main` (`39119112136`) e sul tag (`39119175159`) è verde per Python 3.12, 3.13 e 3.14. Trusted Publishing (`39119298409`) è riuscito e [PyPI](https://pypi.org/project/italian-energy/0.13.3/) espone la versione `0.13.3`.

I digest PyPI coincidono con gli asset della GitHub Release: wheel `3df0bee7a3519dc739591e78bf10b6590db055c078f079c17b1198cd7863cd5c`, sdist `0eb59d4d86d7c4f89ed2f62d0f4a9730e978d160789274cd027544078b82bc7c`. Suite locale: 801 test, 95,21% branch coverage; Ruff, format, mypy, pre-commit, lock check, golden privato, build wheel/sdist e smoke isolato passano. L'adozione Platform resta una milestone separata.

## Portale Offerte — CdispD corrente per la stima annuale, 2026-10-18

- **Scritto:** Spec 008 addendum v0.8.3, Spec 013 e ADR 0012/0016 applicano
  la regola ufficiale Portale v4.2: per codice 14 domestico, CdispD del trimestre
  corrente moltiplicato per il consumo annuo. Non occorrono dodici osservazioni
  mensili future; il precedente limite v0.8.2 vale per il replay mensile esatto.
- **Implementato:** il parser v4 conserva il parametro ufficiale giornaliero
  nello snapshot con data, tariffa EUR/kWh, digest e locator. Il dato tipizzato
  sopravvive all'hydration senza raw bytes. Il percorso prospettico espone
  `PortalCdispDProjection` tra le assunzioni, con policy a valore costante e
  `future_values_verified=false`. Aggregato unico, nessun secondo fattore per
  le perdite e nessuna variazione tra gli scenari PUN. La nuova capability è
  `portal_cdispd_parameter_projection`; il riferimento mensile ARERA resta
  rigoroso e il codice 99 rimane invariato.
- **Fonte live verificata:** CSV del 2026-10-18, riga 52, CdispD EUR 0,016776/kWh,
  SHA-256 `801bb798d551656be3e7e9db45431d81fc0bb5df147dfb4f94b722e577e639d0`.
  Su 4.550 record ufficiali, a parità di profilo non residente Roma e modalità
  01/01, la normalizzazione passa da 0 a 369 offerte. Otto superano il filtro
  annuale attuale, ma l'audit successivo ha trovato un errore: la finestra di
  sottoscrizione viene usata come fine tariffa e la durata parte da `as_of`
  invece che dall'attivazione simulata. Il numero 8 non attesta la reale
  copertura economica. Verifica effettuata dopo envelope/hydration.
- **Verifiche automatiche:** 842 test, branch coverage 95,05%, Ruff check e
  format, mypy `src tests` passano. Le regressioni economiche indipendenti controllano anche IVA, entrambi i
  profili, dati mancanti/errati, periodi, digest e invarianti di provenienza.
- **Adozione aperta:** la correzione è inclusa in Core `v0.13.4` e pubblicata
  su PyPI; il runtime Platform non è stato aggiornato. Servono adozione del
  nuovo artefatto e refresh catalogo; i vecchi snapshot privi del campo non
  vengono riscritti in lettura. L'audit della validità tariffaria ha trovato
  che il filtro annuale corrente non prova la copertura di dodici mesi: le
  otto offerte candidate non sono confermate come economicamente annuali.
  Dettagli e fonti in `docs/cdispd-current-parameter-2026-10-18.md`.

## Refresh Core 2026-10-17 — correzione coverage rollover

Corretto il refresh giornaliero in `rollover_coverage.py` e
`rollover_scope.py`. La coverage ora riconosce una conferma ARERA già
incorporata solo se coincidono ID e digest della fonte, atto, URL, validità e
locator conservato nei riferimenti dell'anchor. Lo scope tariffario mantiene
anche finding `SUPPORTED` correnti e precedenti quando lo snapshot incrementale
non contiene righe indicizzate.

La causa era una perdita di contesto tra run: il parser della 343 produceva
assertion senza facts, mentre la coverage del giorno successivo le trattava
come non risolte; inoltre l'indice vuoto poteva far perdere il legame con gli
atti tariffari e bloccare la coverage per finding non correlati. Refresh
operativo locale del 2026-10-17: snapshot `89b8a00c-2b3a-407a-98da-49bac1752d64`,
`comparisons_enabled=true`, nessun `reason_code`. La preparazione di un anchor
successore Q1 2027 resta separatamente bloccata da `incomplete_coverage`.

`git diff --check` e parsing AST dei due moduli sono stati verificati; non è
stata eseguita la suite automatizzata. Il push del sorgente su `main` non
pubblica una nuova wheel né aggiorna da solo immagini/worker Platform: per
rendere la correzione disponibile ai refresh standard serve una successiva
release Core e adozione Platform.

## Portale Offerte — esclusione temporanea tipo `04`, 2026-10-16

Su richiesta dell'utente, il parser Mercato Libero v2 conserva
`TIPO_OFFERTA=04` come record `unsupported` e il normalizzatore lo esclude
con `unsupported_offer_type`, codice originale e locator. Non interpreta le
componenti economiche del tipo `04`, non lo converte in fixed/indexed e non
interrompe la lettura delle altre offerte. La decisione temporanea è
registrata in Spec 008, ADR 0012 e `memory-bank/decisions.md`.

Regressione prima della correzione: i due casi con tipo `04` fallivano nel
parser. Dopo la correzione: 29 test importer e 770 test Core passati, branch
coverage 95,04%; Ruff check/format e mypy `src tests` passati. Il replay
offline dei byte ufficiali del 14 ottobre, SHA-256
`7de4c0df3fc0dcc22589a4d28e43ac09dd75ed088bdad3da2af1e3f27f627dee`, legge
tutti i 3.540 record: 646 fixed, 2.893 indexed e un `unsupported` (Alperia
Power Eco Neves, codice `000368ESVML01XX5015672X261011XVE`). Il file resta
invariato; questa prova non è un nuovo download né un confronto economico.

Release Core `0.13.2` pubblicata su [GitHub](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.2)
e PyPI il 2026-10-16. Il tag punta al commit
`d8ac5c0bacf04f607e962571133ea72a751b76e8`; CI GitHub è verde su Python 3.12,
3.13 e 3.14 (`38883696900`, `38883695969`). Trusted Publishing
`38883880466` ha pubblicato wheel e sdist. SHA-256 wheel
`bbdc5b429ea367c9159ca5830b240c3b28cead124e5a73574565bef0fce40dbe`, sdist
`3a15585851aea318558be7f714f45fd0044e822a73d6a700ea198905df2d4a6e`; entrambi
corrispondono a GitHub `SHA256SUMS` e PyPI. L'installazione isolata da PyPI
conferma `0.13.2`. La wheel Platform resta alla `0.13.1`; l'adozione è una
milestone separata. Nessun controllo normativo è stato modificato.

## Core 0.13.1 — fallback storico mensile PUN GME, pubblicata 2026-10-14

Spec 013 e ADR 0016 ora vincolano PDF mensile primario e fallback al solo HTTP
404 esplicito. Il fallback usa `_15`, intervalli consecutivi a 15 minuti in
`Europe/Rome`, token `Decimal` e provenance ZIP con digest e locator OOXML.
`_60` non è una sostituzione automatica; rete, integrità e parsing falliscono
chiusi.

La ripetizione live dello ZIP ufficiale `Anno2026.zip` del 2026-10-08 ha
registrato SHA-256
`55a8e0fc7efe71ab4830a42991802415e0b03bc11fa434e444a59a9385a686a0`.
Settembre copre le 2.880 celle `D23326:D26205` e dà
`207.54221705555555556979166666666666666666666666667 EUR/MWh`. L'acquisizione
live `as_of=2026-10-08` ha restituito i dodici mesi ottobre 2025–settembre
2026. Medie _15 per ottobre 2025, giugno, luglio e agosto 2026 concordano con
i PDF GME alla precisione pubblicata.

Release Core `0.13.1` pubblicata su GitHub Releases e PyPI dal workflow
Trusted Publishing. Commit `4f507ae28775e96b19ff3d2e67334abb8f2d2012`, tag
`v0.13.1`; CI verde su Python 3.12, 3.13 e 3.14, workflow release
`38526766297` completato. PyPI mostra entrambi gli artefatti e l'attestazione
Trusted Publishing. SHA-256 wheel
`3796f74fce84d3e121b00c235abf86eb50f25cdd3085d32b2e24f58fbd53edf8`, sdist
`d2e7f30d0e5cd5dd93cd2797eceee8e76fc617caaf57615669a4361882659a90`; gli
hash coincidono con gli asset della GitHub Release. Verifiche Core: 764 test,
95,04% branch coverage, Ruff, mypy, pre-commit, lock check, build wheel/sdist
e smoke wheel isolato verdi. Capability, schema ID e contratto invariati.
Nessuna modifica Platform: mantenere `>=0.13.0,<0.14.0` e aggiornare il pin
puntuale/hash e i verificatori dell'artefatto nella milestone Platform.

## Dependabot virtualenv — fix locale, 2026-10-08

GitHub ha quattro alert aperti sul `virtualenv` bloccato in `uv.lock` alla
versione 21.7.8: GHSA-p58f-9548-mpm2, GHSA-x78j-v8h9-3j2q,
GHSA-94p9-xgh2-xp45 e GHSA-9h9j-4vrj-gf7g. Il pacchetto arriva solo dal gruppo
`dev`, tramite `pre-commit`; non è un requisito runtime pubblicato su PyPI.
`uv.lock` ora blocca `virtualenv` 21.14.6 e `python-discovery` 1.6.1, con
hash PyPI. La versione supera la minima correttiva indicata in tutti e quattro
gli advisory. Suite Core completa: 689 test, 95,05% branch coverage; Ruff,
mypy, lock check offline e diff check verdi. Modifica ancora locale: gli alert
GitHub verranno ricalcolati quando il lockfile aggiornato arriverà sul branch
predefinito. Nessun bump o rilascio di versione applicativa.

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


## Componenti attuali e motivazione accise — 2026-10-17

- **Scritto:** Spec 013 documenta la continuità della quota fissa annuale e le
  finestre `applied_periods`; la nuova Spec 015 definisce la dichiarazione
  `current_component_coverage`, i codici fail-closed, la semantica pubblica e la
  motivazione verificata per accise zero.
- **Implementato:** Core estende soltanto le quote annuali ordinarie marcate
  `follow_tariff`; mantiene autonome scadenze di promo; aggiunge componenti
  correnti separate per perdite e dispacciamento/capacità solo con tariffa
  esplicita; conserva periodo effettivo, significato e trattamento in
  `CostComponent`. L'output proiettato congela `current_component_coverage`.
  `monthly_resident_exemption` è emesso soltanto da regola residente verificata,
  aliquota e consumo imponibili nulli ma consumo mensile positivo.
- **Verificato:** 55 test mirati in `test_projected_service.py`,
  `test_projected_contract.py` e `test_billing_artifacts.py`; Ruff e mypy
  mirati passano. Nessuna suite completa, API HTTP Platform o artefatto Core
  aggiornato verificati.
- **Limite aperto al momento della verifica:** il passaggio dei metadati dei
  componenti Portal importati a `Bill.components` è un slice distinto assegnato
  a `core_offer_charges`; CdispD senza tariffa verificata non è un importo e
  non deve essere proiettato.
- Nessun commit, release o deployment.


### Chiusura integrazione Portal → Bill — 2026-10-17

- Il slice importer completato propaga i metadati supportati (`meaning`,
  `pricing_treatment`, `losses_included`, `included_semantics`, `validity` e
  provenance) da `PortalEconomicComponent` attraverso `ChargeRule` fino a
  `Bill.components`. Il test mirato conferma code 99 → bolletta, 31,68 EUR su
  3.600 kWh con metadati. Verificati 34/34 test mirati del slice.
- CdispD, codice 14, resta un riferimento aggregato senza importo diretto nel
  dataset e blocca la completezza del confronto; nessuna ripartizione o tariffa
  è stata inventata.
- Nessun rilascio Core.
