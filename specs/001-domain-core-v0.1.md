# Spec 001 — Domain Core v0.1

## Contesto

Il progetto deve offrire un nucleo Python locale, deterministico e riusabile per offerte di energia elettrica in Italia. Il dominio non deve conoscere applicazioni, provider cloud, persistenza, trasporto HTTP, autenticazione o sistemi AI.

## Obiettivo

Definire e implementare un modello canonico immutabile per rappresentare fornitura, consumi, contratti, offerte, tariffe fisse e indicizzate, dati di mercato, provenance, breakdown dei costi e risultati dei motori futuri.

La v0.1 non calcola ancora prezzi, bollette o ranking: prepara contratti e invarianti testati per le Spec 002–006.

## Requisiti

### MUST

- I modelli pubblici devono essere Pydantic v2 frozen, con campi extra vietati e collezioni immutabili.
- Gli importi e i valori economici devono usare `Decimal`; input `float`, NaN e infinito sono rifiutati.
- La valuta deve essere esplicita e la v0.1 deve accettare EUR.
- I periodi civili sono semiaperti `[start, end)`; gli intervalli di mercato sono timezone-aware.
- `FixedTariff` deve rappresentare prezzi monorari o per fascia, validità, quote fisse, componenti aggiuntive e sconti.
- `IndexedTariff` deve rappresentare indice, formula AST, granularità, formule per fascia, validità, floor, cap, componenti, condizioni e coefficienti/perdite nominati.
- `ALL` non può coesistere con fasce specifiche nella stessa struttura tariffaria.
- La formula indicizzata non può essere una stringa eseguita o valutata dinamicamente.
- Dati esterni rilevanti devono poter conservare provenance con origine, identificatore, timestamp, efficacia, versione dataset e hash.
- Pricing, billing, comparison e recommendation devono avere confini e protocolli distinti.
- Una recommendation non può mutare risultati economici.
- Il core non può importare web framework, SDK cloud, database, MCP, Home Assistant o AI.

### SHOULD

- Gli aggregate root devono includere `schema_version`.
- La serializzazione canonica deve usare stringhe per Decimal e timestamp ISO-8601.
- Le fasce devono essere codici estensibili, non un enum chiuso alle sole F1/F2/F3.
- Le condizioni commerciali non valutate devono rimanere esplicite come condizioni/assunzioni.

### MAY

- I consumer possono convertire i modelli in JSON Schema, database o DTO propri.
- Un adapter futuro può normalizzare dati ARERA verso il modello canonico mantenendo il raw snapshot.

## Casi d’uso

1. Costruire una tariffa fissa monoraria immutabile.
2. Costruire una tariffa fissa per fasce senza mescolare `ALL` e fasce nominate.
3. Rappresentare una tariffa indicizzata come AST, ad esempio indice × coefficiente + spread con clamp.
4. Associare un profilo di consumi a un punto di fornitura e a un contratto.
5. Conservare dati indice e provenance senza incorporarli in un provider.
6. Passare request/result immutabili ai quattro motori futuri.

## Domain model coinvolto

`Money`, `EnergyQuantity`, `Power`, `UnitRate`, `Currency`, `RoundingPolicy`, `DatePeriod`, `TimeInterval`, `SupplyPoint`, `ConsumptionProfile`, `FixedTariff`, `IndexedTariff`, `Offer`, `Contract`, `MarketIndex`, `MarketData`, `Provenance`, `ChargeRule`, `CostComponent`, `CostBreakdown`, `Bill`, `PricingResult`, `ComparisonResult` e `Recommendation`.

`SupplyPoint` è il nome canonico che sostituisce il termine generico `Supply`.

## Invarianti

- Gli importi non contengono float e le operazioni di somma rispettano la valuta.
- Un periodo ha `end > start`; intervalli adiacenti non si sovrappongono.
- Un profilo non contiene bucket sovrapposti nella stessa fascia e non mescola `ALL` con fasce specifiche.
- Una struttura tariffaria non contiene fasce duplicate.
- Un AST somma soltanto prezzi con unità compatibili; moltiplica un prezzo soltanto per uno scalare; floor non supera cap.
- Un `CostBreakdown` ha totale uguale alla somma delle componenti.
- Provenance e timestamp sono strutturalmente validi; l’hash, quando presente, è SHA-256.

## Acceptance criteria

- I modelli possono essere costruiti, serializzati e ricostruiti senza perdita di informazione.
- I casi invalidi producono errori Pydantic deterministici.
- Fixed e indexed tariff sono distinguibili tramite discriminatore e conservano i rispettivi termini economici.
- Un AST non permette formule dimensionalmente incoerenti o valutazione arbitraria.
- I quattro protocolli sono importabili senza dipendenze applicative.
- Test unitari e property-based coprono gli invarianti e la coverage di branch del package è almeno 95%.
- Ruff, mypy strict, pytest e build del package terminano senza errori.

## Casi limite

- Cambio ora legale in `Europe/Rome`.
- Bucket adiacenti, profilo vuoto e consumo pari a zero.
- Decimal con scala diversa e importi negativi usati per sconti.
- Tariffe con validità non coincidente con il periodo contrattuale.
- Indice con granularità incompatibile con un futuro profilo.
- Provenance senza URL ma con identificatore e hash.

## Test richiesti

- Precisione Decimal e rifiuto float/NaN/infinito.
- Periodi, intervalli timezone-aware e DST.
- Provenance, formato hash e round-trip JSON.
- Bucket negativi, sovrapposti, duplicati e fasce miste.
- AST, unità, coefficienti, floor/cap e discriminatori.
- Tariffe fixed/indexed, offer/contract e cost breakdown.
- Property-based test per partizionamento e serializzazione.
- Test architetturali sugli import vietati.

## Questioni aperte

- La Spec 002 definirà l’arrotondamento per componente e il primo evaluator fixed.
- La Spec 003 definirà l’ordine semantico completo dell’AST e la gestione dei dati mancanti.
- La Spec 004 definirà golden bill, privacy, tolleranza e componenti normative verificate.
- La Spec 005 definirà formato/versioning degli snapshot ARERA e warning di parsing.
- La Spec 007 definirà ranking e percentuali di confronto.
