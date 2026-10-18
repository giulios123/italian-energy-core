# Changelog

## [0.13.4] - 2026-10-18

### Added

- Pricing del codice Portal domestico `TIPO_DISPACCIAMENTO=14` da CdispD
  verificato, mantenuto come componente aggregata unica con provenance.
- Acquisizione tipizzata del parametro `cdispd` dal CSV ufficiale giornaliero
  e sua proiezione esplicita a valore corrente nella stima annuale prospettica.

### Changed

- La proiezione CdispD conserva data, tariffa, digest, locator e snapshot dopo
  serializzazione; il valore resta identico nei tre scenari PUN e non riceve
  una seconda maggiorazione per le perdite.
- Parametro mancante, duplicato o non valido esclude le offerte dipendenti
  senza bloccare le altre. Il replay storico mantiene la copertura mensile
  esatta e non eredita il valore corrente.

### Verification

- 842 test passano con 95,05% di branch coverage; Ruff check/format, mypy,
  pre-commit, `uv lock --check` e `git diff --check` passano.
- Wheel e sdist 0.13.4 sono stati costruiti; lo smoke isolato del wheel
  conferma l'import e la versione `0.13.4`.

## [0.13.3] - 2026-10-18

### Added

- Spec 015: copertura esplicita delle perdite e dei costi aggregati di
  dispacciamento/capacità nel contratto corrente. Il preflight blocca copertura
  ignota, tariffa separata mancante e conflitti; le componenti dichiarate
  separate entrano una sola volta nella baseline.
- Le righe costo conservano semantica, trattamento, perdite incluse, finestre
  effettive e motivazione verificata dell'accisa zero mensile residente.
- Mapping versionato `portale-dispacciamento-v1`: il codice `99` usa solo
  `VALORE_DISP` esplicito come addebito separato; i codici `01`–`14` senza
  importo economico verificato restano riferimenti e non diventano zero o
  componenti ricostruite.

### Changed

- Il parser Portal conserva campi raw, validità, semantica e provenance delle
  voci `Dispacciamento` fino a `Bill.components[]`, evitando doppi conteggi di
  CdispD aggregato e addebiti separati.
- La quota fissa annuale ordinaria segue la tariffa solo con policy esplicita;
  promozioni e altre scadenze restano nelle rispettive finestre.
- Il refresh regolatorio riusa un'asserzione solo quando fonte, digest, atto,
  URL, validità e locator coincidono con l'anchor; lo scope incrementale
  conserva i finding tariffari supportati precedenti.

### Verification

- 801 test passano con 95,21% di copertura (branch inclusa); Ruff check e
  format, mypy, pre-commit, lock check e `git diff --check` passano.
- Golden privato verificato; wheel e sdist costruiti e smoke isolato del wheel
  conferma l'import di `italian-energy==0.13.3`.
- Release `v0.13.3` pubblicata su [GitHub](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.3) e [PyPI](https://pypi.org/project/italian-energy/0.13.3/). CI su `main` e sul tag passa per Python 3.12, 3.13 e 3.14 (run `39119112136` e `39119175159`); Trusted Publishing `39119298409` è riuscito. I digest PyPI corrispondono agli asset GitHub: wheel `3df0bee7a3519dc739591e78bf10b6590db055c078f079c17b1198cd7863cd5c`, sdist `0eb59d4d86d7c4f89ed2f62d0f4a9730e978d160789274cd027544078b82bc7c`.

## [0.13.2] - 2026-10-16

### Changed

- Il catalogo Mercato Libero conserva `TIPO_OFFERTA=04` come record non
  supportato ed esclude la singola offerta con `unsupported_offer_type`, senza
  interpretarne le componenti economiche o interrompere le altre righe.
- Il parser distingue la policy temporanea per il valore esatto `04` dagli
  altri tipi sconosciuti, che continuano a richiedere revisione.

### Verification

- 770 test passano con 95,04% di branch coverage; Ruff check/format, mypy,
  pre-commit, lock check offline e `git diff --check` passano.
- Wheel e sdist costruiti; lo smoke test isolato importa `italian_energy`
  dal wheel e verifica la versione `0.13.2`.
- CI GitHub verde su Python 3.12, 3.13 e 3.14 per `main` e tag
  (`38883696900`, `38883695969`). Release pubblicata su
  [GitHub](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.2);
  il workflow Trusted Publishing `38883880466` è riuscito e l'installazione
  isolata da PyPI conferma `0.13.2`.
- I digest pubblicati su PyPI corrispondono agli asset GitHub:
  wheel `bbdc5b429ea367c9159ca5830b240c3b28cead124e5a73574565bef0fce40dbe`,
  sdist `3a15585851aea318558be7f714f45fd0044e822a73d6a700ea198905df2d4a6e`.

## [0.13.1] - 2026-10-14

### Added

- Fallback dello storico mensile PUN allo ZIP annuale ufficiale GME soltanto
  dopo HTTP 404 del PDF, con serie `_15`, controlli Europe/Rome, media
  `Decimal` a precisione 50 e provenance digest/locator.
- Parser OOXML hardened basato su `defusedxml` già incluso nel runtime; ZIP
  annuale riusato per più mesi della stessa acquisizione e contratto
  Core–Platform invariato.

### Verification

- 764 test passano con 95,04% branch coverage; Ruff, format, mypy,
  pre-commit, lock check, build wheel/sdist e smoke del wheel passano.
- La finestra GME live `as_of=2026-10-08` copre ottobre 2025–settembre 2026.
  Lo ZIP 2026 verificato ha digest
  `55a8e0fc7efe71ab4830a42991802415e0b03bc11fa434e444a59a9385a686a0`;
  settembre contiene 2.880 intervalli e media `_15`
  `207.54221705555555556979166666666666666666666666667 EUR/MWh`.
- La Platform non fa parte di questa release Core; il suo vincolo SemVer resta
  `>=0.13.0,<0.14.0` e l'accettazione PostgreSQL/worker è separata.

## [0.13.0] - 2026-10-08

### Added

- Regulatory Anchor Rollover: versioned effects, five-channel discovery,
  typed parser/review outcomes, immutable candidate workflow, late recovery,
  and Core offline preflight/anchor resolution.
- Production Core factory for official-source adapters and durable storage ports.
- Audit timestamps are recorded after completed source fetches and digest checks,
  so a freshly acquired regulatory assertion is not rejected as newer than its
  candidate.
- Q4 2026 domestic-BT anchor, its dated coverage evidence, and promotion event,
  with explicit confirmations linked back to the Q3 facts.

### Verification boundary

- The official ARERA 343 PDF was fetched live on 2026-10-07 with TLS
  verification enabled. Its 427,425 bytes and SHA-256
  `685691673341be23f479823c61b18c37fe24360f629ff3f8b3c5c847888db30e` match
  the user-supplied file; the versioned parser produced four non-numeric
- The complete five-channel official snapshot acquired on 2026-10-08 was
  replayed through the versioned field-to-source scope policy. The candidate
  passed validation for 13 facts and 11 mapping decisions; stage and one
  promotion succeeded. The packaged anchor is
  `regulatory-anchor:8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e`,
  valid on `[2026-10-01, 2027-01-01)`, with dated evidence ready for
  `as_of=2026-10-08`. That evidence must be refreshed for later comparison dates.
- Core tests: 689 passed with 95.05% branch coverage. Ruff check/format, mypy,
  `git diff --check`, wheel/sdist build, and isolated wheel import/capability
  smoke pass. PostgreSQL/Platform restart and concurrency tests are outside
  this Core package release and were not run.

## [0.12.0] - 2026-09-28

### Added

- Comando `python -m italian_energy.integration.catalog_cli --date YYYY-MM-DD`
  per il catalogo reale, riepilogo delle cinque fonti e copertura degli indici,
  con errori espliciti e senza fallback a un'altra data.
- Spec 013: confronto prospettico additivo su dodici mesi storici consecutivi,
  scenari d'indice 0,80/1,00/1,20, anchor regolatoria e fiscale puntuale,
  costi stimati, nuovi envelope e capability Core.
- Importer GME per report mensili PUN e medie F1/F2/F3, con mapping e unità
  distinti; comando `projection_cli --verify-sources` per verifica live di
  catalogo, storico, definizione d'indice e fonti ARERA/ADM/Normattiva.
- La Spec 012 prospettica con forward e recommendation robusta resta differita;
  gli envelope storici e il Current Domestic Advisor restano compatibili.

### Verification

- 311 test passano con 95,22% di branch coverage; Ruff, format, mypy,
  `git diff --check`, golden privati e smoke degli extra `gme`/`arera` passano.
- La verifica live del 2026-09-27 ha validato catalogo, dodici mesi GME
  consecutivi e anchor ARERA/fiscale. Non è stato fornito un envelope cliente,
  quindi non è stata eseguita una comparazione personalizzata.
- GitHub Release e PyPI pubblicati tramite Trusted Publishing; wheel, sdist e
  `SHA256SUMS` sono allegati alla release GitHub.

## [0.11.1] - 2026-09-22

### Added

- Typed `CurrentDomesticEnergyService.preflight` and
  `CurrentPreflightResult`, sharing contract, continuation, index and
  regulatory-coverage checks with `compare()`.
- Manifest capability `current_portal_preflight` and schema
  `italian-energy/current-preflight-result/v1`.

### Verification boundary

- 235 tests pass with 95.16% branch coverage; Ruff, format, mypy,
  pre-commit, private golden, `git diff --check`, and wheel import smoke pass.
- GitHub release assets include the wheel, sdist and `SHA256SUMS`. Trusted
  Publishing OIDC run `35788003178` succeeded; PyPI hashes match the GitHub
  artifacts and an isolated PyPI install/import smoke passed.
- Platform staging acceptance remains a separate release gate.

## [0.11.0] - 2026-09-13

### Added

- Current Domestic Advisor per confronti domestici BT negli scenari
  deterministici `low_index`, `base` e `high_index`.
- Acquisizione di snapshot verificati Portale Offerte e proiezione esplicita
  dei dodici mesi storici di consumo e indice sul prossimo orizzonte.
- Soglia percentuale nella recommendation corrente e nuovi aggregati/envelope
  JSON del contratto d'integrazione Core–Platform.
- Artefatti installabili `italian_energy-0.11.0-py3-none-any.whl` e
  `italian_energy-0.11.0.tar.gz`.
- Pubblicazione completata su GitHub e PyPI tramite Trusted Publishing OIDC.

### Verification boundary

- 232 test passano con 95,29% di branch coverage; Ruff, format, mypy e
  `git diff --check` passano.
- Gli scenari prospettici non sono forecast: il Core richiede dati storici e
  copertura regolatoria verificata, e fallisce chiuso quando mancano.

## [0.10.0] - 2026-09-09 (locale, non pubblicata)

### Added

- Contratto Core–Platform v1 in `italian_energy.integration`, con manifest,
  capability e schema ID deterministici.
- Façade sincrona per confronti storici domestici BT elettrici e recommendation
  separata sul risultato già calcolato.
- Envelope JSON canonici fail-closed per gli aggregati pubblici e codici errore
  stabili privi di dettagli sensibili.
- `defusedxml` nella dipendenza base; `openpyxl` resta nell'extra `arera`.

### Verification boundary

- La v0.10.0 è locale e non pubblicata. Nessuna modifica alla Platform,
  commit, tag, push o release è inclusa.
- Confronti correnti/futuri, forecast, gas, persistenza e migrazioni automatiche
  restano fuori contratto.

## [0.9.0] - 2026-09-09 (locale, non pubblicata)

### Added

- `DeterministicRecommendationEngine` per interpretare risultati Comparison
  senza ricalcolare Pricing o Billing.
- Preferenze strutturate su tipo tariffa, rischio indicizzato, durata, sconti e
  soglia minima di risparmio in EUR.
- Evidenza candidata verificata, shortlist, decisione `switch`/`stay_current`,
  esclusioni stabili e `PortalRecommendationAdapter`.

### Not included

- Scoring pesato, forecast, AI, testo commerciale, persistenza o API web.

## Unreleased

### Added

- Implementata localmente la Spec 008 Portale Offerte Importer v0.8.0: modelli
  frontend `ComparisonContext`/`PortalComparisonRequest`, snapshot content-addressed,
  trasporto HTTPS allowlisted, parser XML/CSV source-faithful e market data storici.
- Normalizzazione deterministica delle offerte elettriche domestiche BT Mercato
  Libero e PLACET verso Pricing/Billing/Comparison 007, con validità relativa,
  corrispettivi annuali, provenance, applicabilità e ledger completo delle esclusioni.
- Aggiunte fixture e test di sicurezza, schema drift, duplicati, replay indexed
  multi-indice, ranking end-to-end e invarianti di ordine; branch coverage locale 95%+.

### Verification boundary

- La milestone è locale e non pubblicata: commit, tag, push e release richiedono
  autorizzazione separata. Lo smoke live del Portale resta separato dalla suite offline.

### Documentation

- Implementata localmente la Spec 007 Comparison Engine v0.7.0: confronto
  all-in di offerte normalizzate, ranking deterministico, esclusioni motivate,
  matrice di copertura obbligatoria e partite esterne escluse dal ranking.
- Implementata localmente la Spec 006 Billing Coverage Expansion v0.6.0:
  ruleset BT domestici residente/non residente, matrice di copertura, composer
  deterministico, fiscalità ufficiale versionata e snapshot ARERA 2026 congelato.
- Il golden non residente è stato riconciliato sul bimestre 2026-03-01/2026-05-01
  dal documento privato disponibile; il mapping sanitizzato delle righe impedisce
  riusi e target canonici ambigui.
- Riallineato lo stato documentale: `v0.4.0` è pubblicata come release GitHub;
  `v0.5.0` resta locale e non pubblicata.
- Chiarito che il Comparison Engine opera su offerte già normalizzate e non
  sostituisce un importer del catalogo commerciale del Portale Offerte.

## [0.5.0] - 2026-09-07 (locale, non pubblicata)

### Added

- Spec 005 e importer ARERA per il workbook elettrico domestico 2026.
- Raw snapshot immutabili content-addressed, parsing XLSX con `Decimal`,
  provenance per cella e bundle normalizzati per residenti e non residenti.
- Stati `VERIFIED`, `UNVERIFIED` e `REVIEW_REQUIRED` con controlli fail-closed
  del layout e dei totali; parser disponibile nell'extra `arera`.
- Smoke test live `scripts/verify_arera_import.py` senza persistenza del raw.

### Verification boundary

- Il bundle ARERA è source-faithful e non è un `RegulatoryRuleSet` fatturabile:
  IVA, accisa, proratazione, selezione CDISPD e assemblaggio restano esclusi.
- Test, coverage, Ruff, format, mypy, pre-commit, build e smoke install devono
  essere verificati localmente prima di qualsiasi release separata.

## [0.6.0] - 2026-09-08 (locale, non pubblicata)

### Added

- Composer deterministico ARERA → ruleset mensili per i segmenti domestici BT.
- Matrice di copertura e loader JSON caricabili senza l'extra XLSX.
- Proratazione TIT mensile con dodicesimi, giorni/365 e rounding commerciale.
- Provenance con locator foglio/cella/sezione e confini di potenza inclusivi o
  esclusivi.

### Verification boundary

- Snapshot ARERA 2026 VERIFIED congelato al digest
  `b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`.
- I golden privati residente e non residente passano entro 0,01 EUR; la matrice
  dichiara `golden_reconciled` soltanto per i rispettivi periodi riconciliati.
- Il documento privato e i JSON sanitizzati restano fuori dal repository; commit,
  tag, push e release della v0.6.0 richiedono autorizzazione separata.

## [0.4.0] - 2026-09-06

### Added

- Spec 004 e `RegulatoryBillingEngine` data-driven per profili, regole lineari,
  soglie, percentuali, proration e pass-through verificati.
- Modelli immutabili per classificazione, misure, ruleset versionati, AST
  quantitativo, observed bill, riconciliazione e `BillingResult`.
- `bill_id` deterministico indipendente dall'oracle e tolleranza esplicita di
  `0,01 EUR` per voce e totale.
- Fixture sintetiche, ruleset pubblico domestico BT residente Q2 2026 e test
  fail-closed per pricing, unità, provenance, arrotondamento, dipendenze
  percentuali e riconciliazione.
- Verificatore end-to-end privato `scripts/verify_private_golden.py` e scenario
  tecnico sanitizzato in `private/`.

### Verification boundary

- Test, branch coverage, Ruff, format e mypy passano localmente.
- Il verificatore del golden privato passa usando la pagina collegata di elementi
  di dettaglio, mantenuta fuori dal repository. La riconciliazione è esatta sulle
  chiavi e resta entro `0,01 EUR` per voce e totale.
- La chiusura tecnica del golden è stata consolidata nella release GitHub
  `v0.4.0`; documento, input e importi osservati restano privati. La
  disponibilità del package su PyPI non è stata richiesta né verificata.

## [0.3.0] - 2026-09-06 (locale, non pubblicata)

### Added

- `IndexedPricingEngine` per indici market-data versionati, AST Decimal e
  conversione EUR/MWh senza arrotondamenti intermedi.
- Validazione di granularità, copertura temporale, gap/overlap e provenance.

## [0.2.0] - 2026-09-06 (locale, non pubblicata)

### Added

- Spec 002 e `FixedPricingEngine` stateless per tariffe fisse.
- Calcolo deterministico di energia, addebiti per kWh/giorno/kW-giorno e `FLAT`.
- Rounding esplicito per componente, provenance, assumptions e pricing ID SHA-256.
- Validazione fail-closed di fasce, validità, unità e basi non supportate.

### Not included

- Billing, fiscalità, importer ARERA e confronto offerte.

## [0.1.0] - 2026-09-06

### Added

- Domain core immutabile e validato con Pydantic v2.
- Modelli per denaro, periodi, consumi, tariffe fisse/indicizzate, mercato, provenance, cost breakdown e risultati.
- AST tipizzato per formule indicizzate, senza esecuzione arbitraria.
- Protocolli separati per pricing, billing, comparison e recommendation.
- Test unitari e property-based per invarianti del domain core.

### Not included

- Calcolo pricing, billing reale, importer ARERA e golden bill; sono coperti dalle spec successive.
