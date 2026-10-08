# Progress

## M22 — rubrica ufficiale Gazzetta e replay live — 2026-10-08

- L'adapter Gazzetta ora conserva la rubrica canonica letta dal markup
  `span.rubrica`. Rubrica mancante, vuota o con struttura annidata non
  supportata genera errore Core e non produce una scansione completa.
- Aggiunta una regola versionata solo per la rubrica esatta
  `ESTRATTI, SUNTI E COMUNICATI`; le altre rubriche restano review salvo policy
  puntuali. Nessun filtro per titolo o keyword.
- Rieseguito `refresh_regulatory_state` live al 2026-10-08 con tutti i cinque
  canali. Risultato: 1011 record, 3 `SUPPORTED`, 364
  `IRRELEVANT_BY_VERSIONED_RULE`, 644 `REVIEW_REQUIRED` (39 ARERA, 556
  Gazzetta, 49 Normattiva). La policy riduce di 358 i finding Gazzetta; il
  numero residuo descrive record d'indice non collegati, non altrettante
  modifiche ai valori Q4.
- Candidate Q4 ricostruito con ID
  `regulatory-anchor-candidate:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`
  e SHA-256
  `902354107ae452185c3a3a7d9d83dab9b2886c27a287378619b8debea0d107db`;
  validazione 13 fatti/11 decisioni superata. Coverage non pronta per
  `unsupported_regulatory_source`; nessuno stage o promotion e
  `source_preflight.ready=false`.
- Conclusione M22: il candidato esiste e i valori sono validati dal parser,
  ma Q4 non è attivo. Non serve classificare i 644 record a mano. M23 deve
  implementare il grafo versionato delle fonti per campo e collegare gli atti
  modificanti con identificatori ufficiali; record nuovi o ambigui restano
  fail-closed. Poi servono replay live, coverage, stage/promotion e comparison
  offline.
- Gate Core: 678 test, 95,00% branch coverage, Ruff check/format, mypy su
  `src tests` e `git diff --check` passati. Docker/PostgreSQL/DB test esclusi
  su richiesta. Nessun commit/tag/push/release.

## M21 — relazione Normattiva→atto modificante verificata — 2026-10-08

- Interrogata in sola lettura l'API ufficiale Normattiva con TLS verificato.
  La risposta attribuisce l'aggiornamento del TUA `095G0523` del 2026-09-25
  all'atto modificante `26G00184`.
- Verificati la Legge 166/2026 in Gazzetta e il testo coordinato ufficiale del
  DL 133/2026: la misura modifica temporaneamente l'accisa del gasolio e scade
  il 2026-09-05, quindi non cambia l'accisa domestica elettrica del Q4.
- Aggiunto `latest_amending_act_ids` al record Core; l'adapter Normattiva ora
  preserva gli identificatori ufficiali. Classifier e test riconoscono solo la
  relazione esatta TUA→26G00184 e il corrispondente record Gazzetta.
- Test mirati: 4 passati. Il report live completo non è stato rieseguito; il
  precedente conteggio review resta l'ultimo report certificato e Q4 rimane
  `UNVERIFIED`, non staged/promosso. M21 chiude un caso preciso, non l'intera
  certificazione.
- Replay diagnostico dei record completi della scansione stateless, aggiornati
  con la risposta Normattiva live e le nuove regole: 1011 record, 3
  `SUPPORTED`, 1002 `REVIEW_REQUIRED`, 6 `IRRELEVANT_BY_VERSIONED_RULE`.
  Review residue: 39 ARERA, 914 Gazzetta, 49 Normattiva. Non è un report del
  workflow né prova di coverage pronta.
- Non sono state usate euristiche su titolo/keyword. Docker/PostgreSQL/DB test,
  commit, tag, push e release restano esclusi.
- Gate Core M21: 674 test passati con 95,00% di branch coverage, Ruff check e
  format, mypy su `src tests` e `git diff --check` passati.

## M20 — Scomposizione live della coda review — 2026-10-08

- Ricostruita da zero, con fonti ufficiali e TLS verificato, una scansione
  diagnostica completa dal 2026-09-01 all'08/10. I cinque canali hanno
  restituito 1011 record: ARERA atti 41, ARERA tariffe 1, ADM 2, Gazzetta 917,
  Normattiva 50. La scansione non ha riusato cursori o snapshot precedenti e
  non sostituisce il report del workflow usato per il candidate.
- Disposizioni nella scansione diagnostica: 3 `SUPPORTED`, 1004
  `REVIEW_REQUIRED`, 4 `IRRELEVANT_BY_VERSIONED_RULE`. Review per canale:
  ARERA atti 39, Gazzetta 915, Normattiva 50. Il singolo record di differenza
  rispetto al report M19 va riconciliato confrontando i report e i relativi
  input prima di trattare i due totali come equivalenti.
- Identificato il problema strutturale: l'adapter Gazzetta appiattisce ogni
  sommario di Serie Generale a codice/titolo/data/URL; non registra il legame
  dell'atto alle disposizioni dell'anchor. La coda da 915 non significa 915
  modifiche tariffarie. La lista Normattiva contiene anche il TUA delle
  accise e non può essere ignorata in blocco. Gli atti ARERA richiedono scope
  legato ai settori/campi, non alle parole del titolo.
- Prossimo lavoro Core: fonti e disposizioni esplicite per campo Q4; relazioni
  ufficiali fra atti e fonti monitorate; parser solo per gli atti che toccano
  tali disposizioni; replay completo, coverage, stage, promotion e preflight.
  Nessuna review massiva manuale. Fino al completamento il Q4 resta non attivo.

## M19 — Candidate Q4 aggiornato e classificazioni esatte — 2026-10-08

- Eseguita la discovery live completa dei cinque canali. Il Core ha acquisito
  nuovamente le due disposizioni IVA Normattiva con vigenza `2026-10-08` e
  verificato il 10% IVA. I due digest sono `3131100857ef19810e425b0330d2521fb698391419c5c5068ba72dd4b8cf148c`
  e `8aa066590d1e5e86e6a539367743a3563ec97e73b5c8047e72d74da2215b361e`.
- Esaminati PDF e workbook ufficiali ARERA 338/2026/R/eel. Aggiunta la regola
  puntuale `arera-338-sale-terms-out-of-projection-anchor` v1.0.0: i campi
  aggiornati (vendita maggior tutela/STG e fasce orarie) non appartengono allo
  scope del `DomesticProjectionAnchor` corrente. La regola non dichiara quei
  dati irrilevanti per altri prodotti Core.
- Aggiunte regole esatte/versionate per le due pubblicazioni ADM Q4 e per le
  due edizioni ADM storiche supersedute. Gli atti diversi o con metadati
  discordanti restano review; non sono usati filtri per titolo o keyword.
- Rigenerato attraverso `refresh_regulatory_state` il candidate canonico Q4
  in `src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q4-candidate.json`.
  ID `regulatory-anchor-candidate:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`,
  SHA-256 `902354107ae452185c3a3a7d9d83dab9b2886c27a287378619b8debea0d107db`;
  snapshot 2026-10-08, validità `[2026-10-01, 2027-01-01)`, 13 fatti e 11
  decisioni con mapping validato. Non è un anchor attivo: è `UNVERIFIED`.
- La discovery è completa ma riporta 3 `SUPPORTED`, 1003
  `REVIEW_REQUIRED` e record ulteriori risolti da regole di irrilevanza
  versionate. Coverage fallita con `UNSUPPORTED_REGULATORY_SOURCE`; nessuno
  stage/promotion, `source_preflight.ready=false`. Q3 resta scaduto e immutato.
- Modificati i classifier e i test di discovery/candidate; test mirati: 45
  passati. Gate Core completo: 669 test, 95,02% branch coverage, Ruff check e
  format, mypy su 104 file e `git diff --check` passano.
- Docker, PostgreSQL e DB di test saltati su richiesta. La 0.13.0 non è
  certificata né rilasciata. Nessun commit/tag/push.

## M18 — candidate anchor Q4 da fonti ufficiali live — 2026-10-07

- Acquisiti e parsati da Core ARERA 343, i PDF ADM aggiornati il 26/09 e
  06/10/2026 e le due versioni Normattiva DPR 633/1972 datate 07/10/2026.
  Il parser ADM produce `0.0227 EUR/kWh` in entrambe le edizioni; Normattiva
  produce IVA `10%`; ARERA 343 genera quattro conferme esplicite per ASOS,
  ARIM, UC3 e UC6.
- Riacquisito il workbook annuale ARERA 575: digest SHA-256 identico a quello
  nel Q3; supporta la validità annuale dei componenti di rete già riferiti
  dall'anchor precedente.
- Creato il candidate canonico Q4
  `src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q4-candidate.json`,
  ID `regulatory-anchor-candidate:bf9c64b03f7ac59c2ba30c3f4532841cadc8cedb533c77d60cd6b0aee4abd0dc`.
  Contiene 9 oneri, accisa e IVA; validità `[2026-10-01, 2027-01-01)` e
  snapshot `2026-10-07`. Canonical round-trip e validation mapping passano.
- Il candidate resta `UNVERIFIED`: la discovery completa non è stata risolta
  e non sono stati eseguiti coverage verification, stage o promotion. Il
  preflight rimane chiuso; il Q3 storico resta immutato.
- Esaminate la delibera ARERA 338/2026/R/eel e le sue tabelle ufficiali
  (digest `d97489dac8a3c5e0682a5f9fc462d647e43adcd08549cab059c8e0ad2f61bc4a`
  e `3edb84c7e1f8f779167f906e5b8cceca19090ae1f183e2e866a05269dda53736`).
  I corrispettivi PE/PD/PED/PPE, CCM/CPSTG e fasce TIV non sono campi del
  modello anchor corrente; il finding resta aperto finché non viene registrata
  una decisione d'ambito versionata o aggiunto il mapping pertinente.
- Test contrattuale offline aggiunto per il candidate. Gate Core: 664 test,
  95,01% branch coverage, Ruff check/format, mypy e `git diff --check` verdi.
  Docker/PostgreSQL e test DB saltati su richiesta. Nessun commit/tag/push/
  release; la 0.13.0 resta distinta dal candidate e non è certificata.

## M16 — TLS, adapter live e timestamp del rollover — 2026-10-07

- Il trasporto Core usa il trust store nativo con verifica certificato e
  hostname attiva. I test verificano i flag TLS; le richieste live ai cinque
  registri e al PDF ARERA 343 sono riuscite senza bypass TLS.
- Gli adapter deduplicano la stessa delibera ARERA quando ID/data/URL
  coincidono e accettano il separatore con spazio osservato nel nome del PDF
  ADM; conflitti di metadati restano errori tipizzati.
- Regression test TDD: il candidate era timestampato all'avvio, prima dei byte
  acquisiti. Il Core ora registra candidate, digest evidence, stage e promotion
  dopo le operazioni che attestano. Il test mirato passa e il nuovo run non
  restituisce più il falso `SOURCE_CHANGED_UNEXPECTEDLY`.
- Certificazione live aggiornata: tutti i cinque canali completi il 2026-10-07,
  970 record; 1 `SUPPORTED`, 966 `REVIEW_REQUIRED`, 3 irrilevanze versionate.
  Candidate non costruito per `INCOMPLETE_COVERAGE`/atti non risolti; l'anchor
  Q3 è scaduto il 2026-10-01; `source_preflight.ready=false`. La 338/2026/R/eel
  e gli update ADM/Gazzetta/Normattiva non hanno ancora mapping/prove Core
  sufficienti. Il run è in-memory e non certifica store e worker Platform.
- Gate Core dopo M16: 663 test passati, 95,01% branch coverage, Ruff check e
  format, mypy su 103 file, `uv lock --check --offline` e `git diff --check`
  passano. Wheel e sdist 0.13.0 costruite; smoke in ambiente isolato conferma
  versione, import della factory e TLS `CERT_REQUIRED`/hostname attivi.

## M17 — Piano residuo e gate Platform ripetuto — 2026-10-07

- Spec 014 §24 ora elenca i cinque passaggi residui con file, gate e criteri
  d'uscita. La risoluzione dei 966 finding è impostata come chiusura del
  perimetro tramite relazioni normative ufficiali/versionate; non come review
  manuale indiscriminata né classificazione euristica.
- Verifica non-integration Platform ripetuta: Ruff check/format, mypy su
  `src tests`, lint architetturale, controllo licenze, `git diff --check` e
  233 test passano, coverage 90,10%.
- La suite PostgreSQL 17 non è stata eseguita: l'ambiente non ha
  `ENERGY_PLATFORM_DATABASE_URL` configurato e Docker non è disponibile.
- Nessun nuovo candidate live, promozione o release: il preflight resta chiuso
  finché la coverage fiscale/regolatoria del Q4 non è verificata.
- La release 0.13.0 resta bloccata dal gate live e dall'end-to-end Platform;
  non sono stati creati commit, tag o push.

## Parser e mapping della delibera ARERA 343 — 2026-10-07

- L'utente ha fornito il PDF ufficiale ARERA 343 nel path locale privato. Replay
  offline: 427.425 byte, SHA-256
  `685691673341be23f479823c61b18c37fe24360f629ff3f8b3c5c847888db30e`; il
  documento non è stato copiato nel repository o nelle fixture.
- Aggiunto `arera-343-q4-confirmation` v1.0.0, vincolato a documento, URL, atto,
  date, otto pagine e clausole attese. Emette solo quattro assertion
  non numeriche per ASOS, ARIM, UC3 e UC6; clausole o layout inattesi producono
  review. Il mapper le lega ai valori/fact dell'anchor precedente attraverso
  `confirm_value`, valida periodi e fonti precedenti e richiede la fonte
  annuale `arera_575` per `network_total`. Nessun importo è estratto o copiato
  implicitamente.
- Acquisition conserva distinti URL del record ARERA e URL del PDF effettivo.
  Coverage ammette l'assertion futura fuori dalla validità Q3 e richiede la
  materializzazione esplicita quando il periodo si sovrappone. Il workflow
  sintetico verifica staging il 30/09, promozione il 01/10, preflight pronto e
  nessuna rete durante il confronto.
- Test aggiunti per replay, parser malformato/layout/clausole variate, mapping,
  provenienza e validazione del modello assertion. Gate Core: 657 test,
  95,01% branch coverage, Ruff check/format, mypy `src tests` e
  `git diff --check` verdi.
- Non è stato eseguito un nuovo job live. Il report della discovery live del
  2026-10-05 contava 853 finding prima dell'aggiunta del parser; il conteggio
  non è stato ricalcolato dopo la classificazione locale della 343. Nessun candidate Q4 reale è stato
  costruito o promosso, l'anchor incluso è scaduto e il preflight reale resta
  false. Il parser della 343 non chiude gli altri finding o certifica il job
  Platform end-to-end. Nessuna release 0.13.0, commit, tag o push.

## Parser ufficiali ADM e Normattiva per il rollover — 2026-10-05

- Aggiunto `AdmDomesticExcisePdfParser` v1.0.0 per il layout ADM nazionale
  esatto: pagina 5/11, data italiana verificata contro il record ADM, riga
  domestica associata al token con coordinate del PDF, unità EUR/kWh e
  riferimento D.M. 30/12/2011. L'acquisitore assegna layout e `source_id`
  solo per record ufficiali con ID/data/path coerenti. Il parser fail-closed
  su PDF cifrato/malformato, layout inatteso, riga o importo ambiguo e richiede
  `pypdf` nell'extra `arera`.
- Replay offline end-to-end `OfficialRegulatoryDocumentAcquirer` → registry sul
  PDF ADM conservato privatamente: un fatto `0.0227 EUR/kWh`, con digest
  `4bd14b283e63a3a6c7518795010f9e1ac2ff96c9c8d52deee99e03a5631c0d33`, uguale
  alla fonte nell'anchor incluso. Il file non è stato copiato nel repository e
  questa tranche non ha fatto un nuovo fetch live. Il `date.max` usato come
  estremo tecnico “fino a sostituzione” resta subordinato a discovery ADM
  completa e ricontrollo al cutoff; non attesta da solo validità futura.
- Registrati i parser VAT esatti per Tabella A Parte III n. 103 e DPR 633/1972
  art. 16 AKN datato. Test sintetici provano valori/fatti/provenance, layout
  alterati, date invalide/non applicabili, clausole diverse, MIME/identità
  sconosciuti e parsing PDF non disponibile. README, Spec 014, ADR 0017 e
  `active-context.md` allineati; manifest, schema API e anchor pubblicato non
  cambiano.
- Gate Core: 626 test, 95,01% branch coverage, Ruff check/format, mypy su
  `src tests`, `uv lock --check --offline` e `git diff --check` verdi. Il
  confronto resta offline. Nessun candidate Q4 è stato costruito o promosso e
  `source_preflight.ready` resta false: la delibera ARERA 343 e la catena dei
  suoi effetti non sono verificabili senza il PDF, che l'utente aggiungerà
  appena disponibile; restano inoltre finding fiscali da interpretare.
  Nessun commit, tag, push o release.

## Verifica live dei cinque registri e classifier Gazzetta — 2026-10-05

- Discovery delimitata `2026-09-04`–`2026-10-05`: cinque canali completi —
  ARERA atti 43 pagine/29 record, ARERA tariffe 1, ADM 1, Gazzetta 775,
  Normattiva 1 pagina/49 atti. Il report ha `scans_complete=true` e 853 finding
  da interpretare/classificare; questo prova la lettura degli indici, non
  l'assenza di atti pertinenti o la loro applicabilità.
- Il client urllib Python locale non valida la catena Normattiva. La stessa
  richiesta è riuscita via macOS SecureTransport mantenendo TLS attivo
  (`http 200`, verifica 0); i byte JSON (44.680) digest
  `3f580e212d8e5761dcb5bb6a8cafe93e1dc93fd67257a809e1a11b77fcd40142` sono stati
  passati all'adapter Core e validati. Non si è ignorato o disabilitato TLS.
- Il registro Gazzetta usa il path case-sensitive
  `/atto/serie_generale/caricaDettaglioAtto/originario`. Il classifier
  attendeva il path minuscolo e lasciava `26A04702` e `26A04766` in review
  generica. Allineati i matcher e i test ai metadati ufficiali osservati;
  replay offline dei due record ora restituisce le rispettive regole
  `IRRELEVANT_BY_VERSIONED_RULE`. Gli atti non generano facts.
- Le pagine ufficiali ARERA di riepilogo indicano conferme Q4 per le famiglie
  A_SOS/A_RIM/UC3/UC6 e GS/RS/UG1/RE/UG3, ma non sostituiscono il body 343 e la
  disposizione puntuale per ogni fact richiesta da Spec 014 §19. Non sono stati
  trasformati in effects o candidate.
- TDD: i due test con URL live fallivano prima della correzione; dopo passano
  con il test dei lookalike (3/3). Gate Core completo: Ruff check/format, mypy
  su 103 file, 591 test, 95,05% branch coverage e `git diff --check` verdi.
  `343/2026/R/com` resta review; PDF ufficiale ancora HTTP 502. Nessun candidate
  Q4 reale, promozione o preflight ready. Nessun commit/tag/push/release.

## Classificazione puntuale del D.Lgs. 148/2026 — 2026-10-05

- Il testo ufficiale Gazzetta degli [artt. 12](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A04702&art.dataPubblicazioneGazzetta=2026-09-04&art.flagTipoArticolo=0&art.idArticolo=12&art.idGruppo=9&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1) e [32](https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A04702&art.dataPubblicazioneGazzetta=2026-09-04&art.flagTipoArticolo=0&art.idArticolo=32&art.idGruppo=14&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1) è stato verificato rispetto ai soli tassi fiscali dell'anchor elettrico domestico: il primo riguarda termini di detrazione IVA, il secondo gas e casi specifici relativi a produttori/usi; non cambia le aliquote modellate.
- Spec 014 §20 e ADR D17 registrano la regola Core esatta `gazzetta-dl148-domestic-electricity-rates-out-of-scope/v1.0.0`. Solo il record `26A04702` con canale/date/URL attesi è irrilevante per questo perimetro; non produce facts, mentre lookalike e altri atti restano review.
- TDD: il test della regola falliva prima del classifier; dopo l'implementazione la suite discovery passa (39 test). Gate Core: 591 test, 95,05% branch coverage, Ruff check/format, mypy `src tests` e `git diff --check` verdi. Nessuna migration o variazione API/schema; la scansione live limitata e incompleta successiva è documentata sopra, candidate Q4 e preflight ancora bloccati. Nessun commit/tag/push/release.

## Verifica del materiale ARERA 343 per il parser — 2026-10-05

- La [scheda ufficiale ARERA 343/2026/R/com](https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26)
  conferma pubblicazione il 29/09 ed efficacia dal 01/10. La [pagina operatore
  delle componenti](https://www.arera.it/en/area-operatori/prezzi-e-tariffe/oneri-generali-di-sistema-e-ulteriori-componenti)
  conferma alcune serie precedenti; il [comunicato Q4](https://www.arera.it/comunicati-stampa/dettaglio/elettricita-maggior-tutela-373-nel-iv-trimestre-2026-per-i-clienti-vulnerabili)
  contiene totali bolletta aggregati, non i 12 fatti Core per profilo/quota.
- Dal sorgente HTML della scheda è stato estratto l'URL esatto
  `https://www.arera.it/fileadmin/allegati/docs/26/343-2026-R-com.pdf`; il
  fetch via client Core, curl con retry e browser ha restituito HTTP 502
  (`nginx/1.28.0`). Non è stato acquisito né hashato il PDF.
- Acquisite le pagine tariffarie ufficiali: oneri, 183.257 byte,
  SHA-256 `8510582e29e18c908ccc030729c0db6fab5c785ae3f41cc78d6126e6c98ad8a7`
  (A_SOS conferma valori dal 01/07/2026; A_RIM dal 01/01/2026); tariffe gas,
  169.407 byte, SHA-256
  `69edbde3f83dee3bee3ea2fc1b90ded7229a237cd63d752851143742bf14c0f8`
  (GS/RS/UG1 da Q1 2026, RE da Q3 2025, UG3 da Q2 2024). Sono conferme
  ufficiali circoscritte ma non producono da sole tutti i facts profilo/quota.
- Riacquisito il workbook ARERA 227/Q3 esatto: 50.308 byte, digest uguale a
  quello congelato nell'anchor. Questo verifica i byte del predecessore, non
  prova l'effetto normativo Q4. La discovery live non è stata ripetuta e il
  finding 343 resta `REVIEW_REQUIRED`; nessun candidate reale e
  `source_preflight.ready == false`.

## Irrilevanza versionata del decreto diesel fuori Q4 — 2026-10-05

- Dopo la consultazione del testo ufficiale integrale, `26A04766` è stato
  classificato dal Core con `gazzetta-diesel-excise-out-of-scope/v1.0.0` e
  `IRRELEVANT_BY_VERSIONED_RULE`. L'art. 1 riguarda gasolio carburante dal 6
  al 10 settembre 2026, prima del Q4 elettrico che inizia il 1° ottobre.
- La regola richiede Gazzetta, ID atto/documento, date e URL esatti; un
  lookalike o metadati discordanti restano review generica. Non estrae né cambia
  valori e non si estende ad altre disposizioni fiscali. ADR D16 registra
  decisione, alternative, motivazione e conseguenze; D15 rimane come scelta
  iniziale esplicitamente superata per questo solo atto.
- Test TDD: l'atteso esito `IRRELEVANT_BY_VERSIONED_RULE` falliva prima della
  regola; dopo l'implementazione la suite discovery mirata passa (39 test).
  Gate Core dopo la modifica: 591 test, 95,05% branch coverage, Ruff check e
  format, mypy `src tests` e `git diff --check` verdi. Nessuna migration,
  release, commit, tag o push.
- La regola elimina un falso blocker noto ma non crea facts, candidate o
  promotion. `source_preflight.ready` rimane false per i restanti blocker; non
  è stata ripetuta la scansione live.

## Classificazione del decreto accise 26A04766 — 2026-10-05

- Discovery predefinita ora assegna ai metadati Gazzetta esatti del decreto
  MEF `26A04766` la regola Core `known-q4-excise-act-review/v1.0.0`. L'esito
  resta `REVIEW_REQUIRED`; un ID uguale con data o URL discordanti resta review
  generica. Non viene estratto né applicato alcun valore.
- Il testo ufficiale consultato riguarda gasolio usato come carburante dal 6 al
  10 settembre 2026. Poiché il classifier vede solo metadati e manca un parser/
  mapping fiscale che leghi contenuto, prodotto e validità ai facts elettrici,
  non deduce né variazione né irrilevanza per l'anchor.
- Test regression aggiunto prima della modifica: la regola falliva perché
  mancava; dopo l'implementazione `tests/unit/test_regulatory_discovery.py`
  passa (39 test). Gate Core completo: 591 test, 95,05% branch coverage, Ruff
  check/format, mypy su `src tests` e `git diff --check` verdi.
- Nessuna migration o modifica all'API pubblica. Q4 resta senza candidate reale
  o promozione e `source_preflight.ready` resta false. Decisione registrata in
  Spec 014 e ADR 0017 D15.

## Classificazione predefinita esatta degli atti noti — 2026-10-05

- Aggiunto `arera/rollover_classification.py`. In assenza di un classifier
  esplicito, discovery riconosce soltanto i metadati esatti già osservati per
  ARERA `343/2026/R/com` e Gazzetta `26A04702`, applicando
  `known-q4-act-review/v1.0.0`; l'esito resta `REVIEW_REQUIRED` finché non sono
  certificati parser, mapping ed effetto applicabile.
- Un ID identico con canale/URL/date/document ID diversi non prende la regola;
  qualsiasi record sconosciuto continua a richiedere review. Il classifier
  iniettato da test/replay conserva precedenza. Nessuna euristica, valore o
  fallback è stato introdotto.
- Aggiunti test per i due record esatti, metadati discordanti, record ignoti e
  override. Test discovery + rollover service: 73 passati. Gate Core completo:
  590 passati, 95,06% branch coverage, Ruff check/format, mypy `src tests`,
  `uv lock --check --offline` e `git diff --check` verdi. Il lock check ha usato
  una cache locale temporanea per rispettare il sandbox.
- Gate regolatorio invariato: nessun candidate Q4 reale né promozione;
  `source_preflight.ready == false`. Questa tranche migliora la decisione
  auditabile dei finding, non chiude la review.

## Regulatory rollover implementation locale e gate — 2026-10-04

- Verifica documentale live aggiuntiva: il PDF ADM ufficiale del 18 settembre
  (digest `4bd14b283e63a3a6c7518795010f9e1ac2ff96c9c8d52deee99e03a5631c0d33`)
  mostra a pagina 5, verificata visivamente, l'accisa domestica `0,0227
  EUR/kWh`. La pagina ARERA indica l'efficacia Q4 della delibera
  343/2026/R/com e conferme per componenti, ma il Core non emette ancora
  effects/facts completi con intervalli, profili e catene di provenance. Il
  D.Lgs. 148/2026 e gli altri finding fiscali restano da classificare. Il dato
  ADM uguale al Q3 non prova da solo validità futura; nessun candidate/promozione
  Q4, preflight ancora false.
- Non è stato aggiunto un fallback né un parser euristico: l'esito corretto per
  le fonti documentali non completamente mappate rimane `REVIEW_REQUIRED`.

- Core M1–M8 e Platform Spec 013 P1 sono presenti localmente. Core gate:
  `587 passed`, 95,06% branch coverage, Ruff check/format, mypy,
  `uv lock --check --offline` e `git diff --check` verdi.
- I cinque adapter ufficiali hanno completato una scansione live degli indici
  il 2026-10-04 e prodotto snapshot completi: ARERA atti 29 record/43 pagine;
  ARERA tariffe 1/1; ADM 1/1; Gazzetta 840/1; Normattiva 48/1. Il report Core
  risulta `REVIEW_REQUIRED`, 919 finding, nessun candidate e codici
  `current_anchor_expired`, `stale_coverage_evidence`,
  `unsupported_regulatory_source`, `incomplete_coverage`. Discovery completa
  non equivale a interpretazione regolatoria completa.
- ARERA ha pubblicato `343/2026/R/com` con effetto 2026-10-01 e la pagina
  ufficiale descrive conferme di componenti. Il Core non ha ancora un parser e
  mapping certificati per quegli effetti; il parser ufficiale disponibile resta
  il workbook ARERA Spec 005. I documenti fiscali nuovi e l'applicabilità del
  D.Lgs. 148/2026 restano in review. Nessun valore è stato copiato o inventato;
  nessun anchor Q4 è stato promosso e il preflight rimane false.
- Platform: 233 test unitari passati, coverage 90,10%;
  Ruff, format, strict mypy, architecture scan, Compose config e diff check
  passano. I sei test PostgreSQL 17 passano con `PYTHONPATH` sul sorgente Core
  locale; migration up/down/up verificata. Container locale costruito con
  wheel Core 0.13.0 e contract smoke passato. PyPI 0.12.0 resta incompatibile
  col pin Platform `>=0.13.0,<0.14.0`.
- Regressione PostgreSQL Platform v2 rieseguita sul database PostgreSQL 17
  dedicato: 2 test del repository passano. La suite verifica che il run v2 sia
  idempotente e che uno snapshot di discovery incompleto non sostituisca
  l'ultimo checkpoint completo; le letture storiche v1 restano supportate.
- `pyproject.toml` Core riporta 0.13.0 localmente. I risultati locali non
  certificano un wheel pubblicato, dati Q4, deploy o release. Nessun commit,
  tag, push o release.

## Follow-through discovery v2 e checkpoint — 2026-10-04

- Core: `DiscoverySnapshot` persiste decisione versionata, record ufficiale e
  completezza della classificazione. I finding di review seguono gli atti oltre
  la finestra di overlap; cambi dei metadati attivano review anche senza
  sovrapposizione. Acquisition può usare la provenance del finding storico.
  Snapshot v1 si caricano come non completamente classificati.
- Il worker non apre un candidato solo perché ripete finding `SUPPORTED`:
  verifica che i facts coprano il prossimo `valid_from`; i failure di
  acquisition restano retryabili. La regressione A→B prova che, dopo la
  promotion, i facts già attivi non generano un candidate futuro spurio.
- Platform produce il report rollover v2, richiede discovery/report v2 per il
  contratto corrente, continua a leggere run v1 persistiti e seleziona come
  cursore soltanto l'ultimo snapshot completo per canale.
- Gate Core completo: 587 test, 95,06% branch coverage, Ruff, format, mypy,
  lock offline e diff check verdi. Gate Platform: 233 unit test, 90,10%
  coverage, Ruff/format/mypy/architecture/Compose verdi; i due test PostgreSQL
  17 rilevanti passano.
- La discovery live resta `REVIEW_REQUIRED` con 919 finding. Mancano i parser e
  mapping fiscali Q4 e la conferma ARERA verificata; anchor Q4 non costruito né
  promosso, preflight false. Nessuna release, commit, tag o push.

## Completato

- Spec 014 / M8 — compatibilità e contract integration: aggiunta la capability
  `regulatory_anchor_rollover` e registrati schema IDs per candidate, coverage,
  discovery, attempt, state, event, report e preflight. Envelope canonici,
  façade Python e compare con `RegulatoryAnchorCoverageEvidence` verificati;
  il contratto legacy `refresh_regulatory_anchor` e il CLI `--refresh-anchor`
  restano invariati. ADR D9 registra perché non c'è `--rollover` CLI senza
  adapter live e repository durevole. Nessun version bump, build o release.
- Spec 014 / M7 — orchestrazione Core: `RegulatoryRolloverService` esegue
  refresh coverage, discovery, parsing/mapping esatti, candidate, verifica,
  staging e promotion; `source_preflight` e `resolve_active` sono offline.
  Test sintetici A→B 30/09→01/10 verificano anche rerun, outage temporaneo,
  digest mutato, atti/layout ignoti, review e compare senza rete. Gate finale
  M7–M8: 498 test, 95,09% branch coverage, Ruff, format, mypy e
  `git diff --check` verdi. Adapter live, parser fiscali, repository durevole e
  promozione reale non sono verificati; Platform P1 è la milestone residua.
- Spec 014 / M6 — repository/stage/promotion: aggiunti Protocol e store in-memory thread-safe con current/staged/history; put-if-absent verifica identità semantica e conserva il primo snapshot; attempt snapshots e audit ledger append-only. `stage`, `promote` e `revoke_staged` usano CAS sulla generation, richiedono adiacenza e coverage fresca alla data, e sono idempotenti; due worker concorrenti producono un solo effetto. Test: 28 casi state/repository; gate completo 465 test, 95,30% branch coverage, Ruff/format/mypy/`git diff --check` verdi. DB Platform differito a P1; nessun anchor reale promosso.
- Spec 014 / M5 — verification coverage e manual review auditabile: `RegulatoryCandidateCoverageResult` richiede scansioni complete per tutti i canali, source-check freschi per ogni documento del candidate e controlli digest per gli artefatti review. Differenzia `SOURCE_UNAVAILABLE`, digest mutato, coverage incompleta/stale e atto non supportato; le review di atti cambiati sono bound al digest osservato. Aggiunto `refresh_regulatory_coverage`; `refresh_regulatory_anchor` resta source-compatible e non costruisce un successore. Test: 33 casi dedicati; gate completo 437 test, 95,13% branch coverage, Ruff/format/mypy/`git diff --check` verdi. M6–M8 restavano da completare al gate M5; nessuna review live o anchor successivo reale.
- Spec 014 / M4 — mapping e candidate immutabile: composizione versionata delle
  12 charge richieste (due profili, network/system, tre quote), accisa e VAT;
  tutte le partizioni half-open devono avere copertura continua, stessa unità
  e unico valore `Decimal`. Candidate v2 rimane `UNVERIFIED`, contiene facts,
  provenance, decisioni di mapping, validazione e build key. Rifiuta valori
  mensili diversi nel periodo, gap, fonti fiscali mancanti, non contiguità con
  A, provenance incoerente e fatto duplicato con payload diverso. Rerun cambia
  artifact digest solo per tempi operativi, non build key/ID semantico. Test:
  17 casi candidate; gate completo 404 test, 95,04% branch coverage,
  Ruff/format/mypy/`git diff --check` verdi. M5–M8 restavano da completare al gate M4;
  nessun anchor reale è verificato.
- Spec 014 / M3 — parser/facts normalizzati: registry seleziona solo il tuple
  esatto canale/tipo documento/layout e non fa fallback; aggiunto il parser
  ARERA XLSX Spec 005, con verifica MIME e digest, `Decimal`, due profili,
  validità mensile, URL, fetched_at, pubblicazione, atto, parser/versione,
  cella e token OOXML originale. Formati fiscali PDF e layout non certificati
  sono `UNSUPPORTED_REGULATORY_SOURCE` o `PARSER_FAILURE` e non emettono fatti
  parziali. Test: 6 parser dedicati; gate completo 387 test, 95,08% branch
  coverage, Ruff/format/mypy/`git diff --check` verdi. Nessun anchor reale
  generato; M4–M8 erano ancora da completare al gate M3.
- Spec 014 / M2 — motore di discovery regolatoria implementato localmente:
  adapter versionati per ARERA atti, ARERA tariffe, ADM, Gazzetta Serie
  Generale e Normattiva; scan multipagina, periodi sovrapposti, provenance per
  URL/fetched_at/digest di ogni pagina, digest composito verificabile, cursori
  solo su scansioni complete e finding/review tipizzati. Test offline: 33 test
  discovery/acquisition; gate completo 381 test, 95,27% branch coverage,
  Ruff/format/mypy/`git diff --check` verdi. Non esistono ancora adapter live
  certificati; i canali non configurati falliscono chiuso. M3–M8 restano da
  completare e nessun anchor successivo reale è stato prodotto.
- Spec 014 / M1 — contratto e identità Regulatory Anchor Rollover:
  implementato localmente `RegulatoryFact`, `RolloverPolicy`, reason codes,
  canonicalizzazione/build key, digest artefatto, anchor schema v2 con snapshot
  anticipabile, schema/envelope v2. Il digest Q3 v1 resta fissato dal golden
  `13d106…dc9a9`; nessun valore o anchor successivo reale è stato costruito.
  Gate: 349 test, 95,32% branch coverage, Ruff check/format, mypy e
  `git diff --check` verdi. M2–M8 restano da implementare; nessun commit, tag,
  push o release.
- Refresh esplicito dell’anchor prospettico: aggiunti API/Core capability,
  envelope `RegulatoryAnchorRefreshResult` e CLI `--refresh-anchor` per
  riscaricare/controllare i digest degli otto documenti del package senza
  acquisire catalogo o GME. Le date `anchor.as_of` e del refresh restano
  separate; fonti mutate, anchor fuori validità, revisione mancante/ambigua e
  atti applicabili falliscono chiusi. Il confronto resta offline.
- Correzione locale della copertura anchor prospettica 2026-09-29: Spec 013 e
  ADR 0016 distinguono data snapshot, validità e copertura attestata per la data
  di confronto. Aggiunti `RegulatoryCoverageEvidence`, source preflight
  riusabile offline, bundle fonti e modalità CLI live/offline; envelope
  prospettici scritti in v2 e v1 mantenuti leggibili. Il 27 e il 29 settembre
  sono coperti da test con evidenza; il 1° ottobre scade questo anchor. Fonti
  alterate, revisione mancante/incerta o atto applicabile bloccano il gate.
  Nessuna revisione live dei registri è stata eseguita in questa milestone e la
  Platform resta da allineare. Gate locali: 321 test, branch coverage 95,42%,
  Ruff, format, mypy e `git diff --check` verdi; nessuna nuova release.
- Release Core `v0.12.0` del 2026-09-28: Spec 013 beta storica, importer GME,
  anchor regolatoria/fiscale, servizio e envelope prospettici inclusi. GitHub
  Release con wheel/sdist/`SHA256SUMS`; PyPI pubblicato tramite Trusted
  Publishing OIDC. La Platform non è stata modificata.
- Struttura repository, packaging e CI definiti.
- Spec 001 e ADR iniziali scritti.
- Domain core, test unitari e property-based implementati localmente.
- Spec 002, `FixedPricingEngine` e test fixed implementati localmente.
- Spec 003, `IndexedPricingEngine` e test di validazione implementati localmente.
- Spec 004, `RegulatoryBillingEngine`, modelli ruleset, riconciliazione e fixture
  sintetiche implementati localmente.
- Ruleset pubblico domestico BT residente per il periodo 2026-05-01/2026-07-01,
  con provenance ufficiale, fixture di test sintetica e scenario tecnico privato
  sanitizzato preparati.
- `scripts/verify_private_golden.py` esegue il percorso completo
  `PricingRequest → FixedPricingEngine → RegulatoryBillingEngine` e verifica
  stabilità di `bill_id`, chiavi, provenance e riconciliazione.
- Spec 005, ADR 0009 e importer ARERA domestico 2026 implementati localmente:
  raw snapshot immutabili, fetch allowlisted, parser XLSX sicuro, Decimal da
  token OOXML, bundle source-faithful e diagnostiche fail-closed.
- Spec 006 Billing Coverage Expansion v0.6.0 implementata localmente: composer
  deterministico per i due segmenti BT domestici, fiscalità ufficiale versionata,
  proratazione TIT mensile, locator di provenance, ruleset/matrice JSON e loader
  senza dipendenza XLSX.
- Spec 007 Comparison Engine v0.7.0 implementata localmente: confronto all-in,
  `as_of` esplicito, matrice obbligatoria, ranking stabile, esclusioni candidate
  motivate e partite esterne visibili ma escluse.
- Spec 008 Portale Offerte Importer e integrazione frontend specificata come
  milestone locale v0.8.0 implementata: download open-data ufficiale allowlisted,
  snapshot/provenance, parser XML/CSV, indici storici, normalizzazione elettrica
  domestica BT, validità relativa/corrispettivi annuali e orchestrazione verso la
  007 con ledger completo delle esclusioni.
- Documentazione riallineata allo stato reale delle release: `v0.4.0` è una
  release GitHub pubblicata, il golden residente storico è riconciliato e
  `v0.6.0` resta locale e non pubblicata.
- Spec 009 Recommendation Engine v0.9.0 implementata localmente: policy hard,
  evidenze verificate, shortlist/decisione `switch` o `stay_current`, ID
  content-addressed e adapter dal risultato Portale 008.
- Spec 010 Contratto d'integrazione Core–Platform v0.10.0 implementata
  localmente: manifest/capability, façade storica domestica BT, envelope JSON
  versionati e `CoreContractError` con codici stabili; nessuna modifica alla
  repository Platform.
- Release Core `v0.11.1` completata: preflight tipizzato specificato, testato e
  pubblicato; 235 test passano con 95,16% branch coverage e tutti i gate locali
  sono verdi. Tag e release GitHub pubblicati, wheel/sdist/`SHA256SUMS` allegati,
  Trusted Publishing OIDC riuscito, hash PyPI riconciliati e installazione
  isolata verificata. L'accettazione staging Platform resta separata.
- Corretto il setup CI/dev della suite ARERA: `openpyxl` è dichiarato nel
  gruppo `dev` oltre che nell'extra opzionale `arera`, senza aggiungerlo alle
  dipendenze della wheel base.
- Preparata la Spec 011 v0.11.0 e ADR 0015 per il confronto prospettico:
  orizzonte da attivazione, input futuri tracciati, scenari base/stress,
  congelamento regolatorio esplicito e recommendation robusta; milestone
  documentale senza codice o bump di versione.

## Verificato

- Gate della sessione documentale 2026-09-30: Ruff check, Ruff format check,
  mypy `src tests`, 326 test e branch coverage 95,27% passano sullo stato locale
  preesistente; `git diff --check` è pulito. Questi gate non implementano la
  Spec 014 e non attestano discovery o anchor successivi live.
- Refresh anchor/API: 326 test passano con branch coverage 95,27%; Ruff check,
  format-check, mypy src/tests e `git diff --check` passano su Python 3.12.
  I test usano fetcher sintetici; la rete non è stata usata per attestare una
  copertura regolatoria reale.
- Il baseline della v0.4.0 aveva 91 test; la milestone 006 aggiunge test per
  composer, proratazione, matrice, artefatti e due profili sintetici.
- La suite corrente conta 138 test con branch coverage package 95,36% e
  `fail-under=95`.
- Ruff check/format, mypy strict e pre-commit passano localmente.
- Wheel, sdist, smoke install base/extra e smoke live del workbook ufficiale 2026
  passano localmente.
- `git diff --check` è pulito.
- La verifica privata passa per entrambi i golden reali: il percorso completo
  produce Bill stabili e riconcilia tutte le chiavi entro 0,01 EUR per voce e
  totale; la matrice espone il bimestre non residente come `golden_reconciled`.
- Il parser ARERA ha
  fixture sintetiche per residenti/non residenti, fiducia, layout, sicurezza
  ZIP, precisione e failure mode.
- La suite corrente conta 152 test con branch coverage package 95,56%; i test
  Comparison coprono fixed/indexed, baseline globale, esclusioni, percentuali,
  stabilità degli ID, matrice e partite esterne.
- La suite corrente conta 179 test con branch coverage package 95,11%; i test
  Portal coprono acquisizione allowlisted, schema drift, digest, BOM/encoding,
  validità relativa, applicabilità, duplicati, multi-indice e confronto end-to-end.
- Smoke live Portale eseguito separatamente con data esplicita `2026-09-08`:
  snapshot VERIFIED, 4.472 record e 156 punti indice; digest snapshot
  `67577e044c0b257e3b11cbf1ce3f346218c6e932279e9845098b35ea2bb0d23d`.
- La suite corrente conta 188 test; i 9 test Recommendation coprono soglie,
  rischio, durata, sconti, compatibilità legacy, invarianti d'ordine e adapter
  Portale.
- La suite corrente conta 218 test e branch coverage package 95,36%; i test
  d'integrazione coprono manifest, nove aggregati JSON, errori fail-closed,
  selezione degli artefatti residente/non residente, orizzonte storico e
  recommendation senza ricalcolo.
- Wheel e sdist `0.10.0` costruite; metadata, `__version__`, manifest e
  `CORE_SCHEMA_IDS` coincidono. Smoke in ambienti puliti: base con Portale e
  import ARERA lazy senza `openpyxl`, extra `arera` con importer XLSX.
- Dopo la correzione CI, `uv sync --locked --dev` installa `openpyxl==3.1.5`;
  la suite completa passa su Python 3.12.13 e 3.13.12 con 218 test e branch
  coverage 95,36%. Ruff check/format, mypy strict e `git diff --check` passano;
  Python 3.14 resta affidato alla matrice GitHub perché non è installato
  localmente.
- Smoke live separati verificati: ARERA snapshot
  `b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`;
  Portale dataset `2026-09-08`, 4.472 record, 156 punti indice, snapshot
  `67577e044c0b257e3b11cbf1ce3f346218c6e932279e9845098b35ea2bb0d23d`.

## Da completare

- Certificare parser/mapping Core per le fonti Q4 conservate, includendo gli
  effetti ARERA e l'applicabilità fiscale; costruire facts completi, verificare
  coverage, produrre il candidate Q4 e promuoverlo solo con il job Platform.
  Conservare intatto l'anchor Q3 legacy e l'esito fail-closed fino a quel gate.
- Il job e l'archivio Platform esistono localmente e il job chiama il workflow
  Core. Restano da verificare il replay end-to-end dei raw bytes dal Blob,
  l'esito `source_preflight.ready` con un anchor reale e l'uso di un wheel Core
  pubblicato compatibile; nessuna release è stata eseguita.
- Nessuna azione tecnica residua nella Spec 005; commit, tag, push e release
  restano esclusi e richiedono autorizzazione separata.
- Commit, tag, push e release della v0.6.0 restano esclusi e richiedono
  autorizzazione separata.
- Commit, tag, push e release della v0.7.0 restano esclusi e richiedono
  autorizzazione separata.
- Commit, tag, push e release della v0.8.0 restano esclusi e richiedono
  autorizzazione separata; lo smoke live del Portale non blocca la suite offline.
- Commit, tag, push e release della v0.9.0 restano esclusi e richiedono
  autorizzazione separata.
- Commit, tag, push e release della v0.10.0 restano esclusi e richiedono
  autorizzazione separata; l'allineamento della Platform è fuori milestone.
- L'implementazione della Spec 011, il rinnovo dell'anchor ARERA alla
  `quote_date`, i nuovi envelope/capability e l'allineamento della Platform
  restano milestone successive con autorizzazione separata.
- Verifica locale 2026-09-13: aggiunti test per acquisizione catalogo, scenari
  low/base/high, validazioni fail-closed, copertura billing e recommendation;
  232 test Core passano con 95,29% di branch coverage. Ruff check/format, mypy
  strict e `git diff --check` passano; nessun valore regolatorio è stato
  inventato.
- Preparato il workflow dedicato `.github/workflows/release.yml` per Trusted
  Publishing su PyPI: build wheel/sdist, smoke import, artifact condiviso e
  publish OIDC nell'environment GitHub `pypi`, con dispatch manuale per `v0.11.0`.
- Workflow `Publish to PyPI` eseguito con successo per `v0.11.0`: wheel e sdist
  sono presenti su PyPI; API metadata 200 e smoke import isolato da PyPI
  restituisce `italian_energy.__version__ == 0.11.0`.

## Catalogo reale — 2026-09-27

- Comando di acquisizione esatta con riepilogo JSON e errori Core espliciti,
  specificato nell'addendum operativo della Spec 008.
- Live Portale: 4.478 record, 156 punti indice, cinque file ufficiali; PUN e PE
  coprono gennaio 2020–giugno 2026. Persistenza nella Platform verificata tramite
  rilettura dei cinque file e validazione dei digest.
- Live ARERA: VERIFIED, stesso digest congelato, periodo 2026-01-01/2026-09-01.
- Scelta utente: beta con scenari storici base/-20%/+20%; acquisizione del
  catalogo e copertura economica restano verifiche separate.
- Verifica finale: 240 test passano, branch coverage 95,21%; Ruff check,
  format-check, mypy src/tests e git diff --check passano. Il nuovo comando è
  stato eseguito anche sul catalogo live 2026-09-27. Nessun commit, cambio di
  versione o pubblicazione.

## Specifica beta storica — 2026-09-27

- Risolto il doppio uso di 011: il Current Domestic Advisor rilasciato resta
  Spec 011; proposta forward e robusta rinumerata Spec 012 e differita.
- Aggiunte Spec 013 e ADR 0016 con confronto dei 12 mesi recenti e consecutivi,
  ripetizione sullo stesso mese, indici x0,80/x1,00/x1,20, anchor ARERA/fiscale
  puntuale e recommendation solo base.
- Il lavoro comprende importer GME e fonti regolatorie/fiscali correnti,
  output stimato additivo, CLI live, test dedicati e gate Core; è incluso nella
  release Core `v0.12.0`.
- Verifica live ufficiale: `projection_cli --date 2026-09-27 --verify-sources`
  ha restituito `verified`. Catalogo Portale: 4.478 offerte e 156 punti indice;
  snapshot `portal-snapshot:d425ff802cf6233ff1e86711718e91848b6d4664f1ddd129446376324e351d86`.
- GME: PUN Index GME mensile MGP Baseload, unità EUR/MWh convertita con
  `Decimal` in EUR/kWh, esattamente settembre 2025–agosto 2026; dodici mesi
  consecutivi senza buchi o duplicati. Prezzi medi GME per fascia di luglio e
  agosto 2026 acquisiti e verificati come serie distinta, senza auto-mapping
  alle offerte.
- Anchor: fonti 575/2025, 588/2025 e 227/2026 ARERA, ADM 18 settembre 2026,
  TUA D.Lgs. 43/2025 e decreto 26A01335, DPR 633/1972 Tabella A e art. 16
  Normattiva fissati al 27 settembre 2026. Otto digest live corrispondono;
  validità dell'anchor 2026-09-01/2026-10-01, usata in futuro solo come
  assunzione. L'aliquota IVA domestica del 10% è supportata separatamente da
  Tabella A n. 103 e art. 16.
- Verifica sintetica e gate: 311 test passano, branch coverage 95,22%, Ruff
  check/format, mypy e `git diff --check` verdi. Entrambi i golden privati e
  smoke dipendenze opzionali (`openpyxl` 3.1.5, `pypdf` 6.19.0) passano.
- La CLI live ha verificato le fonti, non una bolletta personale: nessun
  `ProjectedDomesticComparisonRequest` con dati utente è stato fornito. La
  Platform non è stata modificata.

## Regulatory Anchor Rollover — M23: anchor Q4 creato e promosso localmente — 2026-10-08

- La matrice Core `scope_domestic_projection_discovery` v1.0.0 correla i campi
  modellati agli indici ufficiali completi ARERA, ADM e alle relazioni Normattiva
  verso TUA `095G0523` e DPR 633/1972 `072U0633`. Le scansioni incomplete e i
  finding rimasti collegati o incerti continuano a bloccare la coverage.
- Replay deterministico del rapporto live completo acquisito il 2026-10-08;
  candidate coverage pronta. Repository Core in-memory: stage riuscito, una
  promotion da Q3 a Q4, anchor coverage pronta e `source_preflight.ready=true`.
- Anchor verificato: `regulatory-anchor:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`,
  digest `641c71a677d98cefe6ec562fd5665a54d3620059e61d70c6a00c397238073ddf`,
  snapshot 2026-10-08, validità `[2026-10-01, 2027-01-01)`. Artefatto:
  `src/italian_energy/data/billing/arera-domestic-bt-projection-anchor-2026-q4.json`.
- Copertura datata ed evento di promozione sono persistiti in JSON versionati
  accanto all'anchor. Il loader e il CLI risolvono l'anchor con `as_of` e
  selezione half-open, preservando il loader no-argument Q3 per compatibilità.
- Confronto sintetico Q4 completato con tre scenari e rete disabilitata; stime
  future restano esplicitamente stime. I test dedicati Q4 verificano anchor,
  digest coverage, evento di promozione e confronto offline.
- Gate Core finale: 689 test, 95,05% branch coverage; Ruff check, Ruff format
  check, mypy `src tests` e `git diff --check` tutti verdi.
- Docker/PostgreSQL e DB di test esclusi su richiesta. L'evidenza è per
  `as_of=2026-10-08` e va rinnovata per date successive. Nessun commit, tag,
  push o release; la 0.13.0 non è pubblicata.

## Release Core 0.13.0 — preparazione locale 2026-10-08

- Aggiornati changelog, README, Spec 014 §26 e stato roadmap per separare il
  rilascio del package Core dal gate persistente Platform, escluso su richiesta.
- Gate locale Core: 689 test passati, 95,05% branch coverage, Ruff check e
  format, mypy `src tests`, lock check e `git diff --check` passati.
- Wheel e sdist 0.13.0 costruite; smoke isolato della wheel conferma versione,
  capability `regulatory_anchor_rollover`, anchor Q4 e coverage pronta al
  2026-10-08. PyPI risponde 404 per 0.13.0 e il tag/release GitHub non esistono.
- Pubblicazione autorizzata dall'utente; commit, push, tag e Trusted Publishing
  sono in corso. Nessuna verifica PostgreSQL/Platform è inclusa.
