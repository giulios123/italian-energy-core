# Spec 002 — Fixed Pricing v0.2

## Contesto

La v0.1.0 definisce i modelli canonici per offerte e consumi, ma non produce ancora
un costo. Questa specifica introduce il primo evaluator deterministico per tariffe
fisse, mantenendo il dominio indipendente da provider, database, web framework,
fiscalità e fonti normative non verificate.

## Obiettivo

Calcolare il costo commerciale di una `Contract` con `FixedTariff` per il periodo
richiesto e il sottoinsieme di bucket fornito dal `ConsumptionProfile`, restituendo
un `PricingResult` immutabile, auditabile e riproducibile.

## Requisiti

### MUST

- `PricingRequest.rounding_policy` deve essere esplicita.
- `FixedPricingEngine` deve accettare soltanto contratti con tariffa `FixedTariff`.
- Il periodo richiesto deve essere contenuto sia nella validità del contratto sia
  nella validità della tariffa.
- I bucket completamente esterni al periodo sono ignorati; un bucket che attraversa
  un confine del periodo produce `FixedPricingError`.
- Per i confini civili si usa `Europe/Rome`; i bucket restano intervalli semiaperti.
- Una tariffa `ALL` può applicarsi a profili `ALL` o a profili già ripartiti per fascia.
  Una tariffa per fasce richiede un profilo per fasce e un prezzo per ogni fascia
  effettivamente consumata.
- Prezzi energia e regole `PER_KWH` richiedono `EUR/kWh`; non è ammessa conversione
  automatica da `EUR/MWh`.
- Sono supportate le basi `PER_KWH`, `PER_DAY`, `PER_KW_DAY` e `FLAT`.
  `PER_DAY` richiede `EUR/day`, `PER_KW_DAY` richiede `EUR/kW/day` e potenza
  contrattuale, `FLAT` richiede `Money`.
- `PER_MONTH`, `PER_PERIOD` e `PERCENTAGE`, oltre a unità incompatibili, dati indice
  e parametri regolatori non vuoti, devono produrre un errore esplicito; non sono
  ammessi totali parziali.
- Una fascia nominata nelle regole commerciali è ammessa soltanto per `PER_KWH`;
  le basi giornaliere, kW-giorno e `FLAT` sono globali.
- Una regola con validità usa l'intersezione tra la propria validità, quella di
  contratto, quella di tariffa e il periodo richiesto. In assenza di validità propria
  si usa la validità effettiva contratto/tariffa.
- `PER_KWH` moltiplica i kWh applicabili; `PER_DAY` conta i giorni civili; `PER_KW_DAY`
  moltiplica kW contrattuali per giorni civili.
- `FLAT` si applica una sola volta soltanto alla richiesta che contiene l'inizio della
  validità effettiva della regola.
- Le regole in `discounts` devono avere `discount=true` e valore non positivo; le
  altre regole devono avere `discount=false` e valore non negativo. Il segno non viene
  mai invertito dall'evaluator.
- Ogni componente viene arrotondata con la policy richiesta; il totale è la somma
  dei componenti arrotondati e non viene arrotondato una seconda volta.
- Il `pricing_id` è `fixed:` seguito dallo SHA-256 del JSON canonico della request
  (chiavi ordinate, separatori compatti, Decimal come stringhe, UTF-8).
- Le condizioni non valutate di contratto, tariffa e regole applicate sono riportate
  nelle `assumptions`. La provenance della tariffa precede quella delle regole,
  con deduplicazione stabile.

### SHOULD

- Le formule delle componenti devono essere stringhe simboliche stabili:
  `quantity_kwh * rate_eur_per_kwh`, `days * rate_eur_per_day`,
  `kw_days * rate_eur_per_kw_day` e `flat_amount`.
- Le componenti energia devono essere aggregate per fascia applicata; le regole
  commerciali devono conservare il proprio codice nel codice della componente.
- L'evaluator deve essere stateless e non deve mutare request, contratto, tariffa o
  profilo.

### MAY

- I consumer possono serializzare request e risultato per cache o audit esterno.

## Casi d'uso

1. Prezzo monorario su profilo `ALL`.
2. Prezzo monorario su profilo già ripartito per fasce.
3. Prezzi distinti per fasce con addebiti per kWh, giorno e kW-giorno.
4. Sconto negativo e addebito una tantum stabile rispetto alla suddivisione del periodo.
5. Ricalcolo identico a partire dallo stesso JSON della request.

## Domain model coinvolto

`PricingRequest`, `FixedPricingEngine`, `FixedPricingError`, `FixedTariff`, `ChargeRule`,
`Contract`, `ConsumptionProfile`, `CostComponent`, `CostBreakdown` e `PricingResult`.

## Invarianti

- Nessun dato esterno o condizione non supportata viene silenziosamente ignorato.
- La somma del breakdown coincide con la somma delle componenti già arrotondate.
- Una richiesta divisa in periodi adiacenti conserva la somma per componenti variabili;
  una regola `FLAT` compare in una sola delle parti.
- L'ID del risultato è stabile per input canonico identico.
- L'esecuzione non altera oggetti frozen o collezioni immutabili.

## Acceptance criteria

- I casi validi restituiscono costi Decimal riproducibili e componenti auditabili.
- I casi invalidi restituiscono `FixedPricingError` o `ValidationError` deterministici.
- Il periodo, le fasce, le unità, le basi e la potenza sono verificati prima del calcolo.
- Rounding, DST, provenance, assumptions, JSON round-trip e immutabilità sono coperti.
- Ruff, mypy strict, pytest con branch coverage almeno 95%, pre-commit e build package
  terminano senza errori.

## Casi limite

- Profilo vuoto o con bucket completamente esterni.
- Bucket adiacenti, bucket che attraversano mezzanotte o il confine della request.
- Validità che attraversa un cambio dell'ora legale in `Europe/Rome`.
- Potenza contrattuale assente con regola `PER_KW_DAY`.
- Tariffa per fasce con fascia consumata priva di prezzo.
- Arrotondamenti negativi per sconti e differenza tra somma arrotondata e rounding finale.

## Test richiesti

- Test unitari per ogni base supportata e per ogni rifiuto fail-closed.
- Test di matching `ALL`/fasce, validità e selezione del sotto-periodo.
- Test di rounding per componente, ID deterministico e serializzazione.
- Test di provenance, assumptions, DST e immutabilità.
- Property-based test per partizionamento dei periodi e stabilità del calcolo.

## Questioni aperte

- La Spec 003 definirà la valutazione delle formule indicizzate.
- La Spec 004 definirà arrotondamenti e componenti fiscali/regolatorie di bolletta.
- La Spec 005 definirà snapshot e import ARERA.
