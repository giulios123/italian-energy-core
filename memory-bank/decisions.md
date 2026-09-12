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
- La Spec 005 separa il bundle ARERA source-faithful dal `RegulatoryRuleSet`
  fatturabile: soltanto il fetch ufficiale allowlisted può produrre dati
  `VERIFIED`, mentre il parsing offline resta `UNVERIFIED`.
- La Spec 006 distingue quattro livelli di copertura (`unsupported`,
  `source_normalized`, `ruleset_verified`, `golden_reconciled`) per la
  combinazione esplicita di profilo, ruleset e periodo.
- Il primo ampliamento della copertura è il segmento BT domestico non residente;
  nessun profilo può ereditare ruleset o stato di verifica per analogia.
- Il composer v0.6 usa esclusivamente `network_total` e `system_total` come
  componenti eseguibili, conserva atomici e locator come evidenza, esclude
  `CDISPD` e applica regole mensili con `MONTHLY_TWELFTHS_PARTIAL_365`.
- Lo snapshot ARERA 2026 VERIFIED è congelato al digest
  `b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`; ruleset
  e matrice sono JSON package e il loader base non importa XLSX.
- La Spec 008 mantiene il Comparison Engine indipendente dal trasporto e dal
  formato Portale: `portal_offers/` acquisisce snapshot HTTPS esatti, conserva
  provenance/esclusioni e invoca la 007 solo sulle offerte normalizzate.
- La Spec 007 usa `as_of` esplicito, richiede la matrice a livello minimo
  `ruleset_verified`, confronta i totali `Bill` all-in e isola le candidate non
  calcolabili con codici di esclusione stabili.
- `savings` è `current_total - alternative_total`, la percentuale è positiva
  per un'alternativa più economica e le partite esterne non partecipano mai al
  ranking.
- La Spec 009 usa filtri hard e minor costo, non scoring: `low` ammette solo
  fixed, `medium` anche indexed capped, `high` ogni rischio supportato; la
  soglia EUR è inclusiva e assente significa `stay_current` compatibile con il
  payload legacy.
- Recommendation richiede evidenza strutturata verificata solo quando la
  policy la usa; mancanze escludono la singola candidata. L'adapter Portale
  deriva i fatti da tariffa, sconti e durata senza interpretare testo libero.
- Il contratto Core–Platform v0.10 mantiene l'identità `italian-energy` /
  `italian_energy` e pubblica la superficie stabile `italian_energy.integration`;
  il root riesporta solo le costanti di discovery senza rimuovere gli import
  pubblici precedenti.
- Il manifest espone soltanto capability realmente disponibili, ordinate in
  modo deterministico, e non dichiara confronto corrente, forecast o costo
  futuro.
- `CORE_SCHEMA_IDS`, come `CORE_CAPABILITIES`, è derivata dal manifest per la
  discovery senza importare o interpretare payload.
- La façade v0.10 è sincrona e storica: deriva `as_of` dal periodo, seleziona
  internamente ruleset/matrice packaged, usa entrambi i cataloghi e applica
  rounding EUR/percentuali a due decimali `ROUND_HALF_UP`.
- Gli aggregati d'integrazione usano envelope JSON con `contract_version`,
  `schema_id` e payload canonico; versione/schema sconosciuti, extra e float
  economici falliscono chiusi senza migrazioni automatiche.
- `defusedxml` è dipendenza base per il percorso Portale; `openpyxl` resta
  esclusivamente nell'extra `arera`, con import ARERA lazy per mantenere il base
  installabile senza XLSX.
