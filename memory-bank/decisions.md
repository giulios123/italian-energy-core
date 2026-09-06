# Decisions

- Pydantic v2 frozen è il formato canonico dei modelli.
- Decimal è obbligatorio per valori economici.
- I periodi sono semiaperti; gli intervalli di mercato sono timezone-aware.
- L’indicizzazione usa un AST tipizzato senza `eval`.
- `SupplyPoint` è il nome canonico al posto di `Supply`.
- Pricing, Billing, Comparison e Recommendation sono confini distinti.
- La v0.1 modella ma non calcola prezzi o bollette.
- La Spec 002 usa un `FixedPricingEngine` stateless, fail-closed e senza conversione EUR/MWh.
- `PricingRequest` richiede una `RoundingPolicy`; ogni componente viene arrotondata prima della somma del totale.
- Il `pricing_id` fixed è uno SHA-256 del JSON canonico della request; `FLAT` scatta una sola volta all'inizio della validità effettiva.
- La Spec 003 usa un `IndexedPricingEngine` separato, con `IndexedPricingError`,
  e restituisce il `PricingResult` comune senza trace aggiuntivo.
- L'evaluator indicizzato richiede `MarketData` e metadati per tutti gli indici
  citati; per profili vuoti o a energia zero non richiede punti temporali.
- Le granularità indicizzate supportate sono quarter-hour, hour, day e month.
  Il bucket deve essere uguale o più fine dell'indice e interamente contenuto in
  un solo punto; consumo più aggregato, gap, overlap e stime sono rifiutati.
- L'AST indicizzato valuta più indici coerenti in `Decimal`, senza rounding
  intermedi. EUR/MWh viene convertito in EUR/kWh soltanto a valutazione
  completata tramite divisione esatta per 1000.
- Il pricing indicizzato aggrega una componente energia per fascia applicata,
  usa un tasso medio ponderato esatto e arrotonda una sola volta la componente.
- Provenance di indice e punti effettivamente usati viene propagata con warning
  deterministici quando manca, senza inventare origine o stato di verifica.
- La Spec 004 usa `RegulatoryBillingEngine` separato dagli evaluator pricing:
  riceve `PricingResult`, classificazione, ruleset e una sola `RoundingPolicy`.
- Billing è fail-closed: ogni regola, parametro, misura e pass-through usato deve
  essere `VERIFIED` e avere provenance; il primo profilo dichiarabile è
  `domestic_bt_resident`, senza aliquote hard-coded.
- `Bill` e `ObservedBill` restano modelli distinti. La riconciliazione usa chiavi
  esplicite, tolleranza fissa di un centesimo e non modifica `bill_id` o componenti.
