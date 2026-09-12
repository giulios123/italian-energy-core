# Spec 006 — Billing Coverage Expansion v0.6

## Contesto

Il `RegulatoryBillingEngine` della Spec 004 è data-driven e può selezionare
profili regolatori distinti, ma la copertura oggi dimostrata è limitata a un
ruleset BT domestico residente, al periodo 2026-05-01/2026-07-01 e a un solo
golden privato riconciliato.

La Spec 005 importa dal workbook elettrico domestico ARERA 2026 valori
source-faithful per residenza anagrafica e diversa da residenza anagrafica. Il
bundle importato non è però un `RegulatoryRuleSet`: non decide fiscalità,
proratazione, selezione del CDISPD o relazione fra componenti atomiche e totali.

La futura Spec 007 confronterà offerte già disponibili come modelli canonici.
Non acquisisce né normalizza automaticamente tutte le offerte commerciali del
Portale Offerte e non trasforma una bolletta PDF in input strutturati. Questi
confini restano separati dalla copertura regolatoria definita qui.

## Obiettivo

Estendere in modo auditabile la copertura di calcolo delle bollette elettriche,
partendo dai due segmenti domestici presenti nella fonte ARERA 2026, e rendere
esplicito il livello di evidenza raggiunto per ogni combinazione di profilo,
ruleset e periodo.

La v0.6 deve:

1. rinumerare la bozza precedente da 007 a 006 e congelare il digest dello
   snapshot ARERA 2026 verificato all'avvio;
2. preservare il caso BT domestico residente già riconciliato;
3. aggiungere il profilo BT domestico non residente con ruleset distinto e senza
   fallback;
4. coprire con ruleset verificati tutti e soli i mesi contigui dello snapshot;
5. impedire che una copertura normativa o sintetica venga presentata come
   riconciliazione reale;
6. predisporre una matrice estensibile per successive classi di utenza
   elettrica, senza inventarne parametri o dichiararle supportate in anticipo.

## Livelli di copertura

Ogni voce della matrice di copertura ha uno e un solo livello:

- `unsupported`: mancano fonti, regole o input necessari al calcolo;
- `source_normalized`: i dati sorgente sono acquisiti e normalizzati, ma non
  esiste ancora un ruleset fatturabile verificato;
- `ruleset_verified`: il ruleset e i test sintetici sono verificati per profilo
  e periodo, ma manca un oracle reale riconciliato;
- `golden_reconciled`: almeno un oracle reale privato e sanitizzato passa per
  tutte le voci e per il totale entro la tolleranza prescritta.

Il livello appartiene alla combinazione completa di profilo, ruleset e periodo;
non si propaga automaticamente ad altri mesi, classi di utenza o versioni.

## Requisiti

### MUST

- Deve esistere una matrice pubblica, versionata e validata automaticamente che
  elenchi almeno: codice profilo, classificazione della fornitura, periodo,
  `ruleset_id`, fonti normative, livello di copertura ed evidenze disponibili.
- La matrice non contiene documenti privati, importi osservati, POD, dati
  anagrafici o altri identificativi del cliente.
- I profili minimi della v0.6 sono `domestic_bt_resident` e
  `domestic_bt_non_resident`, entrambi in bassa tensione e distinti tramite
  `SupplyClassification`; un profilo non può fare fallback sull'altro.
- Per entrambi i profili devono essere prodotti ruleset pubblici versionati per
  tutti e soli i periodi 2026 coperti integralmente dalle fonti verificate.
- La trasformazione da `AreraRegulatoryBundle` a `RegulatoryRuleSet` deve essere
  esplicita, deterministica e auditabile. Deve conservare la provenance fino a
  foglio/cella e documentare ogni decisione semantica, inclusi componenti
  atomici, totali dichiarati, CDISPD, proratazione e basi di calcolo.
- Il composer deve eseguire soltanto `network_total` e `system_total`; i valori
  atomici restano evidenza di controllo e `CDISPD` resta fuori dal ruleset come
  componente commerciale da modellare nel Pricing.
- Le regole economiche devono essere mensili e usare
  `MONTHLY_TWELFTHS_PARTIAL_365`: mesi interi per dodicesimi con arrotondamento
  commerciale del tasso mensile, mesi parziali per giorni/365 e poi rounding
  monetario della componente.
- IVA, accisa e ogni altro parametro non presente nel workbook della Spec 005
  richiedono una fonte normativa ufficiale distinta, periodo di efficacia,
  digest e stato `VERIFIED`. Nessun valore può essere dedotto da una bolletta o
  copiato dal ruleset residente per analogia.
- Ogni regola e parametro utilizzati devono coprire integralmente il periodo
  richiesto. Gap, overlap, fonte scaduta, mapping ambiguo o dato non verificato
  producono `BillingError` senza risultato parziale.
- Il caso residente esistente deve restare un regression gate. Il profilo non
  residente deve avere almeno un test end-to-end sintetico indipendente e un
  golden reale privato sanitizzato prima di raggiungere
  `golden_reconciled`.
- Ogni golden deve ricostruire il `PricingResult` dai dati strutturati
  dell'offerta, applicare il ruleset pertinente e riconciliare chiavi esplicite
  e totale entro `0,01 EUR`, senza modificare input o parametri per far passare
  il test.
- L'assenza di un golden non blocca la pubblicazione di una voce
  `ruleset_verified`, ma deve impedirne la descrizione come bolletta reale
  certificata o riconciliata.
- Una richiesta con profilo o periodo non presente nella matrice come almeno
  `ruleset_verified` deve fallire in modo esplicito; non sono ammessi fallback,
  interpolazione, carry-forward o riuso implicito di un altro profilo.
- Il Billing Engine continua a ricevere un `PricingResult` già calcolato. Questa
  spec non importa offerte commerciali, non sceglie offerte e non duplica la
  logica del Pricing o del futuro Comparison Engine.
- I nuovi modelli pubblici, se necessari, devono essere Pydantic v2 frozen e
  serializzabili; importi, tariffe, percentuali e quantità economiche usano
  `Decimal`, mai `float`.
- Ogni difetto economico scoperto durante una nuova riconciliazione richiede un
  regression test prima della correzione.

### SHOULD

- I periodi 2026 dovrebbero essere suddivisi secondo le finestre effettive delle
  fonti e non aggregati se ciò altera l'ordine di arrotondamento osservabile.
- La matrice dovrebbe distinguere il numero di golden indipendenti dal livello
  normativo, così che nuova evidenza possa essere aggiunta senza cambiare il
  significato del ruleset.
- Il verificatore dovrebbe poter eseguire tutti i golden privati presenti
  localmente senza conoscere i loro nomi nel codice pubblico e produrre soltanto
  identificativi tecnici, esito e scarti non personali.
- Le nuove classi di utenza elettrica dovrebbero essere ordinate per
  disponibilità congiunta di fonte ufficiale, ruleset completo e oracle
  sanitizzabile, non per somiglianza nominale con un profilo esistente.

### MAY

- Più golden indipendenti possono aumentare l'evidenza di una stessa voce senza
  ampliare automaticamente il periodo o il profilo dichiarato.
- La matrice può includere voci `unsupported` o `source_normalized` per rendere
  visibili i blocchi, purché non siano esposte come calcolabili ai consumer.
- Un consumer può mostrare il livello di copertura all'utente prima di avviare
  il calcolo o il confronto.

## Casi d'uso

1. Calcolo e riconciliazione di una bolletta BT domestica residente nel periodo
   coperto dal golden esistente.
2. Calcolo di una bolletta BT domestica non residente con ruleset verificato e
   nessun fallback sul profilo residente.
3. Riconciliazione di un golden non residente privato, con dettaglio degli
   scarti per chiave senza pubblicarne i dati.
4. Rifiuto di una richiesta per un mese non interamente coperto dalle fonti.
5. Rifiuto di un profilo BT non domestico o MT ancora registrato come
   `unsupported`.
6. Consultazione della matrice da parte del futuro Comparison Engine prima di
   valutare offerte già normalizzate.

## Domain model coinvolto

`BillingRequest`, `RegulatoryBillingEngine`, `BillingResult`,
`SupplyClassification`, `RegulatoryRuleSet`, `RegulatoryProfile`,
`RegulatoryParameter`, `VerificationStatus`, `AreraRegulatoryBundle`,
`ObservedBill`, `BillReconciliation`, `PricingResult`, `Provenance` e una
eventuale rappresentazione tipizzata della matrice di copertura.

## Invarianti

- Copertura normativa, copertura temporale e riconciliazione reale sono assi
  distinti e non vengono dedotti l'uno dall'altro.
- Un golden prova soltanto la combinazione esplicita di profilo, ruleset,
  periodo e struttura osservata che ha riconciliato.
- I due segmenti domestici non condividono regole o parametri per assunzione.
- Il bundle ARERA resta separato dal ruleset fatturabile e dal catalogo delle
  offerte commerciali.
- Nessun documento privato o dato personale entra nel repository pubblico.
- La somma della Bill deriva esclusivamente da componenti arrotondate secondo la
  policy dichiarata; l'oracle non modifica mai il risultato calcolato.
- Una voce priva di fonte ufficiale e provenance completa non può raggiungere
  `ruleset_verified`.

## Acceptance criteria

- La matrice di copertura è pubblica, versionata, validata nei test e riporta
  senza ambiguità lo stato di ogni profilo/periodo incluso.
- `domestic_bt_resident` conserva il golden esistente in stato
  `golden_reconciled` per 2026-05-01/2026-07-01.
- `domestic_bt_non_resident` dispone di ruleset verificato, test sintetico
  end-to-end e almeno un golden privato riconciliato prima della chiusura della
  milestone.
- Per entrambi i segmenti, ogni ulteriore periodo 2026 dichiarato
  `ruleset_verified` ha copertura completa delle fonti regolatorie e fiscali,
  provenance e test dei confini temporali.
- Una suite negativa dimostra il rifiuto di profilo errato, periodo scoperto,
  fonte non verificata, mapping ambiguo e golden con voci mancanti o eccedenti.
- La documentazione pubblica non usa espressioni come "tutte le bollette" o
  "copertura certificata" senza riportare la matrice effettiva e il relativo
  livello di evidenza.
- Nessuna regressione su pricing fixed/indexed, Billing v0.4, importer ARERA
  v0.5 e import base/extra.
- Ruff, format check, mypy strict, pytest con branch coverage almeno 95%,
  pre-commit, build wheel/sdist, smoke install base/extra, verificatori privati e
  `git diff --check` passano.

## Casi limite

- Bolletta che attraversa due mesi con parametri o arrotondamenti distinti.
- Cambio di residenza o classificazione durante il periodo di fatturazione.
- Fonte ARERA disponibile ma fonte fiscale mancante o con efficacia diversa.
- Workbook aggiornato allo stesso URL con digest nuovo e layout invariato o
  modificato.
- Componenti aggregate nella bolletta osservata ma atomiche nel ruleset, o
  viceversa, senza chiave di riconciliazione univoca.
- Conguaglio, ricalcolo, bonus, canone TV e prodotti o servizi esterni.
- Golden valido per un fornitore ma struttura di dettaglio differente per un
  altro fornitore.
- Profilo elettrico non domestico, tensione diversa da BT o settore gas.

## Test richiesti

- Test di schema, ordinamento deterministico e coerenza della matrice di
  copertura.
- Test del mapping esplicito bundle ARERA → ruleset per entrambi i segmenti,
  con provenance per ogni valore utilizzato.
- Test di separazione resident/non-resident e di selezione univoca del profilo.
- Test temporali per ogni finestra dichiarata, inclusi gap, overlap e periodi a
  cavallo di un cambio parametro.
- Test sintetici end-to-end indipendenti per entrambi i profili domestici.
- Regression test del golden residente e nuovo golden non residente, entrambi
  privati, con chiavi e tolleranza di `0,01 EUR`.
- Test fail-closed per fonti fiscali mancanti, dati non verificati,
  classificazioni non supportate e richiesta oltre la copertura dichiarata.
- Test che il Comparison Engine e l'importer Portale Offerte non siano dipendenze
  del Billing Engine o della matrice.

## Fuori perimetro

- Download, parsing o normalizzazione del catalogo commerciale del Portale
  Offerte.
- Estrazione automatica di bollette o offerte da PDF/OCR.
- Confronto, ranking o raccomandazione fra offerte: Spec 007 e milestone
  successive.
- Gas, dual fuel, prosumer, scambio sul posto, ritiro dedicato e comunità
  energetiche.
- Profili elettrici non domestici o tensioni diverse da BT finché non esistono
  fonti ufficiali, mapping e golden dedicati accettati in un'estensione
  normativa.
- Persistenza, API web, scheduler, cloud e interfacce utente.

## Stato di congelamento

Lo snapshot VERIFIED usato dalla milestone ha digest SHA-256
`b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`, contiene
256 valori per entrambi i segmenti e copre 2026-01-01/2026-09-01. Il raw XLSX
non è distribuito né salvato nel repository; gli artefatti JSON del package ne
conservano solo digest, provenance e regole derivate.

## Questioni aperte

- Il golden BT domestico non residente disponibile in `private/nonresident.pdf`
  è completo degli elementi necessari; il relativo JSON sanitizzato resta fuori
  dal repository e riconcilia il periodo 2026-03-01/2026-05-01.
- Quali fonti ufficiali fiscali coprono integralmente ciascun periodo 2026 dei
  due segmenti senza ricavare aliquote dalle bollette?
- La matrice di copertura deve essere un modello runtime pubblico o un artefatto
  di verifica distribuito con il package?
- Quale classe di utenza elettrica deve seguire i due segmenti domestici, una
  volta disponibili fonte normativa e oracle indipendente?
