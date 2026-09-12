# Spec 007 — Comparison Engine v0.7

## Contesto

Pricing e Billing sono disponibili come motori separati e la Spec 006 rende
esplicita la copertura dei ruleset domestici BT. Manca un motore che calcoli il
costo comparabile di un contratto corrente e di offerte commerciali già
normalizzate. Il catalogo del Portale Offerte, le bollette PDF e la verifica
dell'idoneità commerciale non fanno parte di questo confine.

## Obiettivo

Confrontare in modo deterministico un contratto corrente con un insieme di
offerte già canoniche, applicando lo stesso scenario di consumo, mercato,
classificazione, ruleset e periodo. Il ranking deve usare il totale della
bolletta comparabile e deve rendere esplicite sia le esclusioni sia le partite
esterne che non partecipano al confronto.

## Requisiti

### MUST

- `ComparisonRequest` deve richiedere `as_of`, `SupplyClassification`,
  `RegulatoryRuleSet`, `BillingCoverageMatrix`, `RoundingPolicy` monetaria e
  una policy esplicita per le percentuali; mantiene consumo, periodo, offerte e
  `MarketData` condivisi.
- `as_of` deve appartenere alla validità del contratto corrente. Un'offerta è
  corrente quando `subscription_period.start <= as_of < subscription_period.end`.
- Il periodo richiesto deve essere coperto dalla matrice con livello minimo
  `ruleset_verified`, per la classificazione e lo stesso `ruleset_id` passato al
  Billing Engine. Gap, overlap, profilo ambiguo o livello insufficiente fanno
  fallire l'intero confronto.
- Il caller deve fornire offerte normalizzate e commercialmente prequalificate.
  Le condizioni testuali non vengono interpretate; i termini economici devono
  essere rappresentati nella tariffa e le condizioni residue restano assunzioni.
- Il motore deve valutare il contratto corrente e ogni candidata tramite il
  relativo Pricing Engine (`FixedPricingEngine` o `IndexedPricingEngine`) e poi
  tramite `RegulatoryBillingEngine` con `external_items=()`.
- Il totale comparabile è il totale della `Bill` risultante: componenti di
  vendita, rete, oneri, accisa e IVA inclusi quando presenti nel ruleset.
- Partite esterne (`ExternalBillItem`) possono essere ricevute, ma devono avere
  chiavi univoche, provenance, stato `VERIFIED` e periodo contenuto. Sono
  esposte separatamente e non entrano in Bill, differenze, percentuali o ranking.
- Gli ID delle offerte devono essere univoci. Un errore globale (contratto
  corrente, copertura o input condiviso) produce `ComparisonError`; un errore
  di una candidata produce un'esclusione con codice e dettaglio deterministici.
- I codici di esclusione sono `not_current`, `same_as_current`,
  `period_not_covered`, `pricing_failed` e `billing_failed`.
- Il risparmio è `current_total - alternative_total`; la percentuale è
  `savings / current_total * 100`, è quantizzata con la policy esplicita e vale
  `None` quando il totale corrente è non positivo, con warning deterministico.
- Alternative e `ranking` devono essere ordinati per totale comparabile
  crescente e poi per `offer_id`. Nessuna candidata valida produce comunque un
  risultato con ranking vuoto.
- `comparison_id` e gli ID dei contratti ipotetici devono essere SHA-256 di
  payload JSON canonici e non dipendere dall'ordine delle offerte.
- I modelli pubblici devono restare Pydantic v2 frozen, serializzabili e basati
  su `Decimal`; il modulo non può importare web framework, cloud SDK, database,
  MCP, Home Assistant, AI o l'extra XLSX.

### SHOULD

- Il risultato dovrebbe conservare il `BillingResult` completo per il corrente
  e per ogni alternativa, così da rendere auditabile il totale all-in.
- Le esclusioni dovrebbero essere ordinate per `offer_id` e non esporre dati
  personali o contenuti di documenti privati.
- La verifica dovrebbe dimostrare l'invarianza rispetto alla permutazione delle
  offerte e che l'aggiunta di partite esterne non cambia il ranking.

### MAY

- Un consumer può presentare il livello della matrice e le esclusioni prima di
  mostrare il ranking.
- Una futura estensione può aggiungere importi o periodi candidati specifici,
  senza modificare la semantica del confronto corrente.

## Casi d'uso

1. Confronto fixed/fixed su una bolletta comparabile all-in.
2. Confronto fixed/indexed con `MarketData` completo e verificato.
3. Esclusione isolata di un'offerta non corrente o non calcolabile.
4. Rifiuto globale di periodo scoperto, ruleset non verificato o matrice ambigua.
5. Esposizione di canone TV, bonus e servizi esterni senza alterare il ranking.
6. Risultato vuoto di alternative ma con baseline corrente verificata.

## Domain model coinvolto

`ComparisonRequest`, `ComparisonResult`, `AlternativePricing`,
`ComparisonEngine`, `DeterministicComparisonEngine`, `ComparisonError`,
`OfferExclusion`, `OfferExclusionCode`, `PricingResult`, `BillingResult`,
`BillingCoverageDecision`, `ExternalBillItem`, `RegulatoryRuleSet`,
`SupplyClassification`, `ConsumptionProfile`, `MarketData` e `RoundingPolicy`.

## Invarianti

- La matrice è obbligatoria e non viene sostituita da fallback sul profilo o sul
  ruleset residente.
- Pricing determina il subtotal commerciale; Billing determina il totale
  comparabile; Comparison non duplica le formule economiche.
- Le partite esterne non vengono passate al Billing Engine e non modificano
  alcun importo usato per il ranking.
- Il contratto corrente è un errore globale; le candidate sono isolate.
- Il risultato e tutti i modelli nidificati restano immutabili.

## Acceptance criteria

- La spec, l'ADR e gli export pubblici documentano il contratto v0.7.
- Fixed/fixed e fixed/indexed producono totali all-in, risparmi, percentuali e
  ranking deterministici.
- Sono coperti i confini semiaperti di `as_of`, validità, duplicati, zero/negativo,
  tie-break, input riordinati e assenza di candidate.
- Gap, livello insufficiente, ruleset/profilo non corrispondente, pricing o
  billing non calcolabile sono dimostrati con test fail-closed appropriati.
- Le partite esterne verificate sono visibili ma escluse da Bill e ranking.
- Non esiste dipendenza da importer Portale Offerte, PDF/OCR o Recommendation.
- Ruff, format check, mypy strict, pytest con branch coverage almeno 95%,
  pre-commit, build, smoke base/extra, verificatori privati, smoke ARERA e
  `git diff --check` passano.

## Casi limite

- Offerta disponibile esattamente al confine iniziale o finale di `as_of`.
- Periodo che attraversa una finestra mensile del ruleset o un gap della matrice.
- Candidato indexed con punto di mercato mancante o ambiguo.
- Totale corrente nullo o negativo.
- Due candidate con stesso totale o una candidata uguale all'offerta corrente.
- Bonus, TV fee o servizio con segno negativo, provenance assente o periodo fuori
  dalla richiesta.

## Test richiesti

- Schema, immutabilità, Decimal e round-trip JSON dei nuovi modelli.
- Fixed/fixed, fixed/indexed, billing all-in, differenze, percentuali e warning.
- Validità di `as_of`, contratto, tariffa, offerta e copertura della matrice.
- Errori globali e isolamento delle esclusioni candidate.
- Ranking con tie-break, ordine input, ID canonici e ranking vuoto.
- Separazione delle partite esterne e assenza di regressioni sulle Spec 001–006.

## Fuori perimetro

- Importazione o scraping del Portale Offerte.
- Estrazione di PDF/OCR, eligibility strutturata, forecast o backfill di mercato.
- Recommendation, persistenza, API web, cloud, UI, gas e nuove classi di utenza.
- Commit, tag, push, release e pubblicazione PyPI.
