# Spec 004 — Billing / Golden Bill v0.4

## Contesto

Il core calcola già il prezzo commerciale fisso e indicizzato, ma non ricostruisce
una bolletta completa. La bolletta deve mantenere separati il risultato commerciale,
le componenti di rete/oneri e le imposte, senza introdurre nel core parser di fonti
esterne o valori normativi non verificati.

La struttura delle componenti segue la logica corrente dello Scontrino dell'energia:
quota consumi, quota fissa e quota potenza, con separazione fra vendita, rete/oneri,
accisa, IVA e partite esterne. La specifica non implementa l'importer ARERA della
Spec 005.

Le fonti di riferimento per i futuri ruleset sono lo [Scontrino dell'energia
ARERA](https://www.arera.it/bolletta/bolletta-dellelettricita/lo-scontrino-dellenergia),
il [quadro regolatorio ARERA](https://www.arera.it/fileadmin/allegati/docs/22/449-22.pdf)
e l'[articolo 52 del Testo Unico Accise](https://www.normattiva.it/uri-res/N2Ls?urn%3Anir%3Astato%3Adecreto.legislativo%3A1995-10-26%3B504~art52-com3-leta=).
Le aliquote e i parametri non sono copiati nel core senza una verifica esplicita.

## Obiettivo

Definire un Billing Engine generale, deterministico e data-driven che riceva un
`PricingResult` già calcolato, applichi un `RegulatoryRuleSet` versionato e
restituisca una `Bill` immutabile. Un metodo dettagliato restituisce inoltre una
`BillingResult` con riconciliazione opzionale verso un oracle osservato.

La struttura supporta tutte le classi di utenza rappresentabili tramite profili di
applicabilità. La v0.4 dichiara copertura verificata soltanto per la combinazione
esplicita di profilo, versione del ruleset, periodo di efficacia e fixture oracle:
non è una certificazione generale di tutte le bollette dello stesso profilo. Il
primo profilo candidato è `domestic_bt_resident`.

Il golden end-to-end può partire da una `PricingRequest` con tariffa fissa e deve
costruire il `PricingResult` tramite `FixedPricingEngine` prima di invocare il
Billing Engine. Il verificatore privato è uno strumento di sviluppo separato e
non fa parte dell'API runtime.

## Requisiti MUST

- `Bill`, `BillingRequest` e `BillingEngine` esistenti restano compatibili in modo
  additivo.
- `RegulatoryBillingEngine.bill(request)` restituisce `Bill`; `evaluate(request)`
  restituisce `BillingResult` con `Bill` e riconciliazione opzionale.
- Il nuovo engine richiede `PricingResult`, `SupplyClassification`,
  `RegulatoryRuleSet` e `RoundingPolicy`; i payload legacy possono essere costruiti,
  ma una request incompleta fallisce prima del calcolo.
- `PricingResult.contract_id` e periodo devono coincidere con contratto e request.
  Billing non invoca evaluator fixed/indexed e non duplica pricing.
- I modelli pubblici sono Pydantic v2 frozen, `extra="forbid"`, con collezioni
  immutabili e `Decimal`; float, NaN e infinito sono rifiutati.
- La classificazione deve poter esprimere codice contrattuale, livello di tensione
  `BT`, `MT`, `AT` o `AAT`, uso, residenza, profilo fiscale e codici di eleggibilità.
  I codici di uso e contratto restano estensibili.
- `BillingMeasure` deve conservare valore, unità (`kWh`, `kvarh`, `kW`), periodo,
  stato di verifica e provenance per misure non ricavabili da consumo o contratto.
- Un `RegulatoryRuleSet` contiene identificatore, versione, validità, provenance,
  parametri `RegulatoryParameter` e profili di applicabilità. Deve essere selezionato
  esattamente un profilo; nessun profilo o più profili compatibili è errore.
- Ogni parametro e regola utilizzati devono essere `VERIFIED`, avere provenance e
  coprire interamente il periodo richiesto. Dati `UNVERIFIED` o `REVIEW_REQUIRED`,
  gap, overlap, unità incompatibili o regole mancanti producono `BillingError` senza
  risultato parziale.
- Le regole sono una union discriminata di regole lineari, regole a soglia e regole
  percentuali. Le formule quantitative usano un AST tipizzato con riferimenti a
  misure, costanti, addizione, sottrazione, prodotto scalare, minimo, massimo e
  clamp; non sono ammesse stringhe eseguibili o `eval`.
- Sono supportate basi per kWh, kvarh, giorno, mese, anno, kW-giorno, kW-mese,
  kW-anno, flat e percentuale. Ogni regola temporale dichiara la propria
  `ProrationPolicy` fra giorni effettivi, frazione del mese civile, frazione
  dell'anno civile e intero periodo.
- Il calcolo procede in ordine: componenti commerciali già calcolate, regole lineari,
  regole a soglia, regole percentuali in ordine topologico, poi partite esterne
  verificate. Le basi di una percentuale selezionano codici o categorie già prodotti;
  riferimenti mancanti, duplicati o ciclici sono errore.
- Ogni nuova componente viene arrotondata una sola volta con la `RoundingPolicy`
  della request. L'IVA usa le basi già arrotondate; il totale è la somma delle
  componenti arrotondate e non viene arrotondato una seconda volta.
- `ExternalBillItem` può rappresentare bonus, canone TV, prodotti/servizi e altre
  partite, ma richiede codice, categoria, quota, periodo, segno, stato `VERIFIED` e
  provenance. Il core non li inventa né li calcola implicitamente.
- `bill_id` è `bill:` seguito dallo SHA-256 del JSON canonico degli input di calcolo,
  escluso l'oracle osservato. L'osservato non modifica mai la Bill calcolata.
- La riconciliazione usa una `reconciliation_key` esplicita e univoca, senza fuzzy
  matching. Passa soltanto quando ogni voce e il totale differiscono al massimo di
  `0,01 EUR` e non esistono voci non abbinate. Una differenza produce stato `FAILED`
  con dettaglio; un osservato malformato produce `BillingError`.

## Modelli coinvolti

`BillingRequest`, `BillingEngine`, `Bill`, `CostComponent`, `CostBreakdown`,
`PricingResult`, `RegulatoryParameter`, `SupplyClassification`, `BillingMeasure`,
`RegulatoryRuleSet`, `LinearRegulatoryRule`, `ThresholdRegulatoryRule`,
`PercentageRegulatoryRule`, `ExternalBillItem`, `ObservedBill`,
`ObservedBillComponent`, `ComponentDifference`, `BillReconciliation` e
`BillingResult`.

## Casi limite e invarianti

- Le finestre seguono periodi civili `[start, end)` e i cambi mese/anno devono
  produrre segmenti non sovrapposti.
- Una misura richiesta da una regola ma assente, non verificata o fuori periodo è
  errore; non è ammessa stima o carry-forward.
- Un profilo domestico residente deve poter applicare un'esenzione e un recupero a
  soglia mediante l'AST quantitativo, senza codificare aliquote nell'engine.
- Le regole percentuali devono avere un ordine aciclico verificabile.
- Crediti e pass-through negativi sono ammessi soltanto quando dichiarati come tali.
- La riconciliazione a `0,01 EUR` per voce e totale è stabile rispetto all'ordine degli
  input e non muta gli oggetti frozen.
- Se l'oracle documenta righe mensili già arrotondate, il ruleset può esprimere
  la stessa regola con finestre mensili distinte; ogni finestra resta una componente
  autonoma e non si introducono correzioni manuali al parametro.
- Il golden oracle reale è privato e sanitizzato; nessun POD, PDF o dato personale
  entra nel repository pubblico. Un PDF sorgente non sanitizzato può essere
  conservato soltanto localmente in `private/` e non è un fixture accettabile.

## Acceptance criteria

- Il caso sintetico pubblico produce una Bill riproducibile con componenti vendita,
  rete/oneri, accisa, IVA e pass-through.
- Il golden privato `domestic_bt_resident` passa per tutte le voci e per il
  totale entro `0,01 EUR`, oppure la release resta bloccata con un dettaglio
  riproducibile dello scarto; non sono ammesse aliquote o importi corretti a mano
  per forzare il passaggio.
- Il golden end-to-end ricostruisce il prezzo commerciale dai dati dell'offerta,
  applica un ruleset pubblico con provenance ufficiale e confronta una `ObservedBill`
  privata senza pubblicare documento, importi osservati o identificativi.
- Sono coperti selezione profilo, validità, verifica, unità, soglie, percentuali,
  proration, arrotondamento, provenance, ID, immutabilità e riconciliazione.
- L'engine non importa o dipende da evaluator pricing concreti, framework, database,
  cloud, AI o parser ARERA.
- Branch coverage package ≥95%, Ruff, format check, mypy strict, pytest, pre-commit,
  build wheel/sdist, smoke install e `git diff --check` passano.

## Fuori perimetro

- Download, parsing, raw snapshot e normalizzazione delle fonti ARERA: Spec 005.
- Estrazione automatica di bollette PDF.
- Matrice numerica completa di tutte le utenze senza ruleset e fonte verificati.
- Persistenza, API web, cloud, comparison engine e recommendation.
