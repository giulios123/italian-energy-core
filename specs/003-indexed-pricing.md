# Spec 003 — Indexed Pricing v0.3

## Contesto

La Spec 001 ha definito `IndexedTariff`, l'AST tipizzato delle formule e i
modelli immutabili per indici e dati di mercato. La Spec 002 calcola il costo
commerciale delle tariffe fisse, ma rifiuta dati di mercato e formule
indicizzate. Questa specifica definisce il primo evaluator indicizzato senza
introdurre import, interpolazioni o regole normative non verificate.

L'evaluator resta domain-first, deterministico, stateless e indipendente da
provider, database, web framework, billing, fiscalità e fonti ARERA.

## Obiettivo

Definire `IndexedPricingEngine`, che valuta un'`IndexedTariff` su un profilo di
consumo e su dati indice compatibili, restituendo lo stesso `PricingResult`
immutabile usato dal pricing fixed. Il risultato deve essere riproducibile,
auditabile tramite input e provenance, e deve fallire in modo esplicito quando
la copertura temporale o le unità non sono sufficienti.

## Requisiti

### MUST

- L'API pubblica deve esporre `IndexedPricingEngine.price(PricingRequest) -> PricingResult`
  e `IndexedPricingError`. Non sono introdotti result, trace o DTO aggiuntivi.
- La request deve contenere `MarketData`; il campo resta opzionale nel modello
  condiviso `PricingRequest` per compatibilità con il fixed, ma l'evaluator
  indicizzato deve rifiutare `market_data=None`.
- Ogni `BandFormula` deve contenere almeno un `IndexReference`. Più riferimenti
  indice nella stessa formula sono ammessi, anche con codici diversi, se tutti
  hanno la granularità della tariffa.
- Ogni `IndexReference` deve trovare un `MarketIndex` con lo stesso codice,
  unità e granularità. La granularità dell'indice e quella della tariffa devono
  coincidere per tutti i riferimenti usati.
- Sono supportate soltanto le granularità `QUARTER_HOUR`, `HOUR`, `DAY` e
  `MONTH`. `BILLING_PERIOD` e `YEAR` producono `IndexedPricingError`.
- Un punto `QUARTER_HOUR` o `HOUR` deve iniziare su un confine locale valido
  nel timezone dell'indice e avere durata effettiva, rispettivamente, di 15 o
  60 minuti. Un punto `DAY` deve coprire da mezzanotte locale alla mezzanotte
  civile successiva; un punto `MONTH` dal primo giorno del mese alla mezzanotte
  del mese successivo. Il confronto della copertura usa gli istanti assoluti,
  anche se il punto è serializzato in un timezone diverso.
- La gerarchia di granularità è `QUARTER_HOUR < HOUR < DAY < MONTH`. Un bucket
  positivo deve avere granularità uguale o più fine di quella dell'indice e
  deve essere interamente contenuto in un solo `MarketDataPoint` per ogni
  riferimento usato dalla formula.
- I bucket completamente esterni al periodo richiesto sono ignorati; un bucket
  che attraversa un confine del periodo produce errore. Nessuna interpolazione,
  media, carry-forward, backfill o ripartizione di un bucket aggregato è
  ammessa. Un consumo più aggregato dell'indice produce errore.
- Per un bucket positivo deve esistere esattamente un punto che lo contiene per
  ogni indice riferito. Un gap, una copertura ambigua o punti sovrapposti nella
  copertura usata producono errore. I punti non necessari al calcolo possono
  essere presenti in `MarketData` e sono ignorati.
- `MarketData` deve definire tutti gli indici citati anche quando il profilo è
  vuoto o contiene soltanto energia zero. In questi ultimi casi non sono
  richiesti punti temporali, perché nessun costo energia viene valutato.
- L'AST deve essere valutato ricorsivamente in `Decimal`, senza rounding
  intermedi: `IndexReference` legge il valore del punto selezionato,
  `PriceConstant` legge il proprio rate, `ScalarConstant` e `NamedCoefficient`
  forniscono lo scalare, `AddPrice` somma e `MultiplyPrice` moltiplica il prezzo
  per lo scalare. `ClampPrice` applica floor e cap nel punto esatto dell'albero.
- Il risultato dell'espressione deve essere `EUR/kWh` o `EUR/MWh`. Un risultato
  `EUR/MWh` viene convertito esattamente in `EUR/kWh` dividendo per 1000 solo
  dopo la valutazione completa e prima del prodotto per i kWh. Non sono
  ammesse altre conversioni automatiche. I valori negativi sono validi se non
  sono esclusi da floor/cap o da una validazione dell'input.
- Il matching tariffa/profilo deve seguire la Spec 002: una formula `ALL` può
  applicarsi a un profilo `ALL` o già ripartito per fasce; formule nominate
  richiedono un profilo per fasce e una formula per ogni fascia consumata. Non
  è ammesso mescolare `ALL` e fasce nominate.
- Le componenti energia devono essere aggregate per fascia della formula
  applicata. Per ogni fascia, `quantity` è il totale kWh, `unit_rate` è il
  tasso medio ponderato esatto normalizzato in `EUR/kWh`, e `amount` è il
  risultato arrotondato una sola volta della somma non arrotondata dei prodotti
  bucket-per-rate. Il codice deve essere `energy:<band>` e la formula simbolica
  deve essere stabile, ad esempio
  `sum(quantity_kwh_i * evaluated_rate_eur_per_kwh_i)`.
- Gli addebiti `fixed_charges`, `additional_charges` e `discounts` devono
  seguire validità, basi, segni, rounding e applicazione della Spec 002.
  Sono supportate soltanto `PER_KWH`, `PER_DAY`, `PER_KW_DAY` e `FLAT`; basi,
  unità o parametri non supportati producono errore senza totali parziali.
  `IndexedTariff` deve applicare la stessa validazione dei gruppi addebito/
  sconto di `FixedTariff`.
- `PricingRequest.regulatory_parameters` deve essere vuoto. La presenza di
  parametri regolatori produce errore esplicito; questa spec non calcola
  fiscalità o componenti normative.
- Ogni componente, inclusi gli addebiti commerciali, deve essere arrotondata
  con la `RoundingPolicy` richiesta. Il totale deve essere la somma delle
  componenti già arrotondate e non deve essere arrotondato una seconda volta.
- Il `pricing_id` deve essere `indexed:` seguito dallo SHA-256 del JSON canonico
  della request, con chiavi ordinate, separatori compatti, Decimal come stringhe
  e codifica UTF-8.
- La provenance del risultato deve includere soltanto contratto, tariffa,
  indici e punti effettivamente usati e regole applicate, con deduplicazione
  stabile. La provenance di una componente energia deve includere tariffa,
  `MarketIndex` e punti usati per quella fascia.
- Se un indice o un punto usato non ha provenance, il calcolo resta valido ma
  deve produrre un warning deterministico. Gli stessi warning devono comparire
  sia in `PricingResult.warnings` sia in `CostBreakdown.warnings`; non si
  devono inventare stato di verifica o origine mancanti.
- L'evaluator non deve mutare request, tariffa, profilo, dati indice o altre
  collezioni frozen. In caso di errore deve restituire nessun `PricingResult`.

### SHOULD

- L'implementazione dovrebbe condividere con `FixedPricingEngine` le funzioni
  interne per validità, selezione dei bucket, charge window, rounding,
  provenance e identificatore, senza duplicare contratti pubblici.
- I messaggi di errore dovrebbero identificare codice indice, fascia, intervallo
  e motivo del rifiuto quando disponibili.
- I warning di provenance mancante dovrebbero essere deduplicati per codice
  indice e mantenere l'ordine di prima osservazione dei dati usati.

### MAY

- I consumer possono fornire dati sintetici senza provenance per simulazioni e
  test, purché il risultato esponga i warning previsti.
- I consumer possono conservare o serializzare request e result per cache,
  audit e riproduzione esterna.

## Casi d'uso

1. Prezzo indicizzato orario con indice `EUR/MWh` e profilo quartorario.
2. Prezzo indicizzato mensile con profilo giornaliero o orario interamente
   contenuto nei punti mensili.
3. Formula con indice, coefficiente nominato, spread, somma e clamp.
4. Formula con più codici indice della stessa granularità.
5. Tariffa `ALL` su profilo ripartito per fasce e tariffa nominata su profilo
   per fasce.
6. Addebito giornaliero, capacità, flat e sconto applicati insieme al costo
   indicizzato.
7. Ricalcolo identico a partire dallo stesso JSON canonico della request.

## Domain model coinvolto

`PricingRequest`, `IndexedPricingEngine`, `IndexedPricingError`, `IndexedTariff`,
`BandFormula`, `IndexReference`, `PriceConstant`, `ScalarConstant`,
`NamedCoefficient`, `AddPrice`, `MultiplyPrice`, `ClampPrice`, `MarketIndex`,
`MarketData`, `MarketDataPoint`, `ConsumptionProfile`, `ConsumptionBucket`,
`ChargeRule`, `CostComponent`, `CostBreakdown` e `PricingResult`.

## Invarianti

- Una formula indicizzata contiene almeno un riferimento indice e tutti i
  riferimenti sono coerenti con la granularità della tariffa e con `MarketData`.
- Gli intervalli usati sono timezone-aware, canonici per la granularità e
  confrontati come istanti assoluti; i bucket selezionati non attraversano i
  confini della request o del punto indice assegnato.
- Ogni bucket positivo ha una sola copertura per indice; non esistono gap o
  sovrapposizioni nella copertura effettivamente usata.
- L'AST non esegue stringhe, non usa `eval` e non arrotonda nodi intermedi.
- La somma del breakdown coincide con la somma delle componenti arrotondate.
- Un risultato con la stessa request canonica ha lo stesso `pricing_id` e gli
  stessi importi, componenti, assumptions, warning e provenance.
- Una provenance mancante è esplicita tramite warning e non viene sostituita da
  dati inventati.

## Acceptance criteria

- I casi validi per tutte le granularità supportate restituiscono costi
  `Decimal` riproducibili, componenti aggregate e unit rate verificabili.
- I casi invalidi restituiscono `IndexedPricingError` o `ValidationError`
  deterministici e non producono risultati parziali.
- AST, unità, conversione EUR/MWh, clamp, coefficienti, fasce, copertura,
  validità, DST e arrotondamento sono verificati prima o durante il calcolo in
  modo fail-closed.
- Profilo vuoto/zero, dati inutilizzati, più indici, provenance completa o
  mancante, warning, JSON round-trip, immutabilità e ID deterministico sono
  coperti.
- Gli addebiti commerciali indicizzati hanno la stessa semantica verificata
  della Spec 002.
- La futura implementazione mantiene almeno il 95% di branch coverage e passa
  Ruff, format check, mypy strict, pytest, pre-commit, build del package e
  `git diff --check`.

## Casi limite

- Passaggio all'ora legale o solare in `Europe/Rome` per bucket e punti orari.
- Punti serializzati in UTC o in un timezone diverso dal `MarketIndex`.
- Confini del mese, bucket adiacenti, bucket che attraversano un punto indice e
  consumo più aggregato della serie.
- Valori indice, coefficienti, spread e risultati formula negativi.
- Formula con più indici, indice mancante, unità o granularità discordante,
  punto duplicato, gap o overlap.
- Profilo vuoto, energia zero, punti temporali inutilizzati e provenance
  assente soltanto su alcuni punti.
- Differenza tra somma non arrotondata e rounding della sola componente finale.

## Test richiesti

- Test unitari per ogni nodo AST, formule annidate, ordine semantico, più
  indici, clamp, unità, conversione EUR/MWh e valori negativi.
- Test di matching `ALL`/fasce, granularità, intervalli canonici, timezone,
  DST, validità e selezione dei bucket.
- Test di gap, overlap, copertura ambigua, bucket oltre il periodo, consumo
  aggregato, market data mancante e basi non supportate.
- Test di aggregazione ponderata, assenza di rounding intermedi, rounding per
  componente, breakdown totale e addebiti commerciali equivalenti alla Spec 002.
- Test di provenance usata, warning deduplicati, assumptions, immutabilità,
  JSON round-trip e `indexed:` pricing ID.
- Property-based test sulla suddivisione di bucket contenuti nello stesso punto
  indice e sulla stabilità della valutazione `Decimal`.
- Verifica finale con coverage branch almeno 95%, Ruff, format check, mypy
  strict, pytest, pre-commit, build e `git diff --check`.

## Questioni aperte

- La Spec 004 definirà tolleranza, componenti normative e golden bill.
- La Spec 005 definirà raw snapshot, versioning ARERA, normalizzazione e warning
  di parsing.
- La Spec 007 definirà ranking, percentuali e confronto tra risultati.
