# Spec 015 — Copertura delle componenti attuali e motivazioni fiscali

## Stato

Scritta e implementata nel Core; inclusa nella release Core `v0.13.3` del
2026-10-18. L'adozione e il collaudo Platform sono milestone separate.

## Contesto

Il confronto prospettico calcola la baseline corrente da un contratto inserito
nella Platform. Il modello tariffario non può dedurre se le perdite di rete e il
corrispettivo aggregato di dispacciamento/capacità siano già inclusi nei prezzi,
addebitati separatamente o ancora sconosciuti. Un valore mancante non è uno zero.

Il risultato aggregato espone inoltre le componenti fiscali. Uno zero sulle
accise domestiche residenti può essere l'esito della franchigia mensile, mentre
l'assenza di una componente o l'impossibilità di calcolarla indica un problema
diverso. La distribuzione mensile conta anche quando il consumo annuo è uguale.

## Obiettivo

Definire il contratto Core–Platform per dichiarare la copertura dei costi del
contratto corrente, evitare conteggi doppi, conservare la semantica delle righe
pubbliche e spiegare soltanto gli importi zero verificati dal Core.

## Requisiti

### Richiesta e preflight

`ProjectedDomesticComparisonRequest.current_component_coverage` contiene le
voci `network_losses` e `dispatching_capacity`. Ogni voce dichiara `treatment`
(`included`, `separate` o `unknown`) e può contenere `unit_rate` soltanto quando
il trattamento è `separate`; l'unità ammessa è `EUR/kWh`. Campo assente,
componente assente o trattamento `unknown` bloccano il preflight. Un trattamento
`separate` senza tariffa blocca il preflight. Il Core non converte mai uno stato
mancante in zero.

Il risultato `ProjectedDomesticComparisonResult` conserva lo snapshot
`current_component_coverage`; il digest del risultato include lo stesso
snapshot. La lettura di risultati storici che non contengono il campo resta
compatibile.

Codici di errore stabili:

- `current_network_losses_coverage_unknown`;
- `current_dispatching_capacity_coverage_unknown`;
- `current_network_losses_rate_missing`;
- `current_dispatching_capacity_rate_missing`;
- `current_component_charge_conflict`.

### Applicazione economica

Il trattamento `included` non crea una nuova riga. Se esiste già una regola
separata in conflitto, il confronto è bloccato. Il trattamento `separate` con
una tariffa valida aggiunge una sola regola `EUR/kWh` alla bolletta corrente;
se una regola tariffaria corrispondente è già presente, non la duplica. Un
conflitto fra dati dichiarati e tariffa salvata blocca il confronto. Le regole
aggiunte alla baseline non sono applicate alle offerte alternative. I costi,
risparmi e IVA sono ricalcolati sulla baseline aggiornata.

### Semantica pubblica delle righe

`CostComponent` espone additivamente:

- `applied_periods`, con le finestre di applicazione effettive; le finestre
  contigue aggregate possono essere unite, i periodi con lacune restano
  distinti;
- `meaning`, con valori tipizzati come `network_losses` e
  `dispatching_capacity_aggregate`;
- `pricing_treatment`, per esempio `separate`;
- `losses_included`, quando la dichiarazione è applicabile;
- `included_semantics`, che per un corrispettivo aggregato di dispacciamento e
  capacità identifica le semantiche `dispatching` e `capacity_market` senza
  inventare una ripartizione monetaria;
- `zero_reason`, solo per importi zero con motivazione verificata.

I nuovi campi sono additivi e nullable o vuoti quando il significato non è noto.
La deserializzazione di payload precedenti rimane supportata. Su una
componente non aggregata, `applied_periods` assume il periodo originario; su
componenti aggregate riflette le finestre delle righe che hanno contribuito,
non l'orizzonte per convenzione.

### Accise zero

Il Core emette `zero_reason=monthly_resident_exemption` soltanto quando una
regola verificata di accisa mensile residente, esplicitamente marcata con tale
codice di motivazione, ha aliquota positiva, quantità imponibile zero e consumo
mensile positivo; la fornitura deve essere classificata residente. Non
attribuisce questa causa a consumo mensile nullo, utenze non residenti, regole
non verificate, componenti assenti o componenti non valutabili. L'input mensile
resta necessario per applicare le soglie mensili.

## Invarianti

- `unknown` e `separate` senza tariffa non producono una stima presentata come
  completa.
- Un importo dichiarato separatamente entra una sola volta nel totale attuale.
- Le componenti aggiunte alla baseline corrente non modificano prezzi o bollette
  delle offerte alternative; risparmi e graduatoria sono ricalcolati rispetto
  alla baseline.
- Un `zero_reason` può accompagnare solo un importo pari a zero.
- Le inclusioni semantiche di CdispD descrivono una voce aggregata e non
  implicano uno split di dispacciamento e mercato capacità.

## Acceptance criteria

- Il preflight distingue stato sconosciuto e tariffa mancante per entrambe le
  componenti.
- Le tariffe separate di perdite e dispacciamento/capacità compaiono una volta
  nel prezzo e nella bolletta attuale, con IVA e totale aggiornati.
- L'output espone lo snapshot di copertura e serializza unità ed enum in modo
  stabile.
- Il prezzo e la bolletta delle offerte alternative restano invariati; il
  ranking resta deterministico.
- L'accisa zero residente espone la motivazione verificata solo a consumo
  positivo ed esente; consumo nullo e regole non verificate non la espongono.
  L'accisa non residente non la espone. Due distribuzioni mensili a pari
  consumo annuo
  possono generare accise diverse.
- I confini mensili di consumo sono verificati a 1,5 kW, 3 kW e oltre 3 kW,
  sotto, sulle e sopra le soglie di 150 e 220 kWh.

## Verifica eseguita

- `tests/unit/test_projected_service.py`: preflight della copertura, applicazione
  economica, IVA/totale, alternative e motivazione delle accise.
- `tests/unit/test_billing_artifacts.py`: confini delle soglie residenti per
  potenza e consumo mensile.
- Suite Core completa: 801 test passati, copertura con branch 95,21%, Ruff,
  format, mypy, pre-commit, lock check e `git diff --check` verdi. Golden privato
  verificato; wheel e sdist buildati, smoke isolato del wheel 0.13.3 passato.
- Il contratto HTTP e l'accettazione Platform restano fuori da questa release.
