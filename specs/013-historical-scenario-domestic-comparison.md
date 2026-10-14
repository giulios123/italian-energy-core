# Spec 013 — Confronto beta domestico con scenari storici

**Stato:** base implementata e rilasciata in Core `v0.12.0` il 2026-09-28;
addendum GME implementato in Core `v0.13.1` il 2026-10-14.

## Stato e scopo

Specifica normativa per la beta Core, successiva alla Spec 011. Il risultato è
un confronto deterministico con costi e risparmi **stimati**, non un forecast e
non una verifica della futura bolletta. Il replay storico della Spec 010 e i
payload già rilasciati restano invariati.

Il confronto riguarda offerte elettriche domestiche BT, residenti e non
residenti. L’orizzonte è il primo periodo di dodici mesi civili completi dopo
il mese di `as_of`. Per `as_of = 2026-09-27`, il periodo è
`[2026-10-01, 2027-10-01)` e lo storico è settembre 2025–agosto 2026.

## Metodo normativo

- Richiedere i dodici mesi civili consecutivi immediatamente precedenti il mese
  di `as_of`; rifiutare gap, duplicati, copertura parziale e dati arretrati.
- Ripetere per ogni mese futuro il consumo e l’indice del medesimo mese
  dell’anno osservato. Non scalare la quantità mensile per la diversa durata
  del mese.
- Calcolare tre scenari sugli indici energetici storici: 0,80, 1,00 e 1,20.
  Applicare il moltiplicatore al solo valore dell’indice prima di spread e
  componenti commerciali. Non applicarlo a prezzi fissi, quote o bolletta
  complessiva. Usare `Decimal` senza introdurre arrotondamenti intermedi.
- Usare lo snapshot catalogo ufficiale acquisito a `as_of`. Verificare la
  sottoscrivibilità a tale data separatamente dalla decorrenza e durata delle
  condizioni economiche. Escludere condizioni note che non coprono i dodici
  mesi. La finestra di sottoscrizione del catalogo non prova la durata del prezzo:
  se la durata economica è assente, non estendere il prezzo e riportare
  l'esclusione; esporre le assunzioni commerciali applicate.
- Selezionare componenti regolatorie e fiscali ufficiali valide a `as_of`, con
  profilo residente/non residente, unità, periodi, digest e riferimenti di
  fonte. Applicarle uniformemente agli scenari come assunzione futura. La
  proiezione non è `VERIFIED` e non allunga la validità attestata delle fonti.
- Ricalcolare le imposte sulle basi imponibili di ciascuna stima con sole
  regole ufficiali verificate. Un valore o una regola necessaria mancanti
  rendono il confronto non pronto; non usare zero o valori inventati.
- Classificare spese, risparmi e ranking futuri come stime. Il ranking e la
  recommendation usano solo lo scenario base. Conservare filtri hard, soglie
  inclusive e ordinamento definiti dalla Spec 009/011.
- Ripetere il costo del contratto corrente solo se il caller dichiara
  l’assunzione di continuità richiesta dalla Spec 011. Voci occasionali di
  bolletta non diventano costi ricorrenti.

## Fonti e indici supportati

Il catalogo e gli indici pubblicati dal Portale Offerte mantengono i contratti
della Spec 008. Un nuovo importer GME acquisisce i report mensili ufficiali
scaricabili per il valore aggregato e i report per fasce per i valori F1/F2/F3.
Il catalogo dei report, le righe interpretate, il periodo, l’istante di
acquisizione e il digest SHA-256 restano tracciabili; i bytes grezzi non
attraversano il confine Core–Platform.

Ogni mapping commerciale documenta codice d’origine, definizione ufficiale,
unità e granularità. PUN Index GME, PE, prezzo di picco/fuori-picco e prezzi
per fascia sono indici distinti. Si supporta solo un mapping provato dalle
specifiche del Portale e dalle fonti ufficiali. Un indice senza mapping o
serie completa non è calcolato: l’offerta interessata è esclusa con motivo
esplicito; se manca un indice necessario alla baseline, il preflight fallisce.

### Acquisizione del PUN mensile GME

Il report statistico mensile PDF resta la fonte primaria del PUN mensile. Il
Core può ricavare lo stesso valore dallo ZIP annuale ufficiale «Dati storici»
GME MGP solo se la richiesta del PDF del mese termina con una risposta HTTP
404 esplicita. Un errore di rete, timeout, redirect non ammesso, altra risposta
HTTP, integrità, struttura o parsing del PDF non attiva il fallback. Il
fallback non maschera un errore di acquisizione o un layout non supportato.

Per i periodi dal 1° ottobre 2025 il fallback usa la serie ufficiale
`PUN INDEX GME` del foglio `Prezzi-Prices` del workbook annuale `_15`. La serie
è riferita all’intervallo minimo MGP a 15 minuti; `_60` è una serie distinta
ammessa come controllo di coerenza della selezione, mai come sostituzione
automatica. Risolvere il foglio per nome e tramite le relazioni OOXML. Un nome,
insieme di colonne o definizione diverso da quello supportato rende
l’acquisizione non valida.

Leggere dalla tabella soltanto data, ora, periodo e la colonna esatta
`PUN INDEX GME`. Convertire i token numerici XML direttamente in `Decimal`,
senza passaggi `float` e senza arrotondamento alla precisione del PDF. La media
mensile aritmetica usa precisione decimale interna di 50 cifre: ogni periodo
atteso ha durata uguale di 15 minuti. Convertire da EUR/MWh a EUR/kWh mediante
divisione esatta per 1.000. Un confronto con il PDF usa soltanto le cifre
pubblicate dal PDF; non implica una regola GME di arrotondamento oltre la
precisione esposta.

Ogni mese deve contenere tutti i giorni civili e tutti i periodi consecutivi
attesi nel fuso `Europe/Rome`: 96 periodi nei giorni ordinari, 92 nel giorno
primaverile di cambio d’ora e 100 nel giorno autunnale. Rifiutare duplicati,
intervalli mancanti o fuori mese, periodi non consecutivi, formule, celle
mancanti, valori non finiti, workbook non leggibile, nomi o colonne ambigui e
archivi incompleti. I periodi devono corrispondere alle etichette locali di
data, ora e quarto d’ora del workbook, incluso il trattamento esplicito della
seconda occorrenza nell’ora autunnale.

Scaricare lo ZIP al massimo una volta per anno durante una singola acquisizione
della finestra e riutilizzare il workbook per i mesi mancanti. Conservare nella
provenance il mese, l’URL esatto dello ZIP, SHA-256 dei byte ZIP scaricati, nome
del workbook, foglio e intervallo delle celle usate. I validator accettano la
provenance ufficiale PDF o ZIP; identificatore mensile, digest, periodo e
valore della serie devono restare legati senza cambiare schema ID,
capability o contratto economico.

La lettura OOXML usa `defusedxml` e la libreria ZIP standard, senza introdurre
una dipendenza runtime XLSX. Applicare allowlist di URL HTTPS per PDF e ZIP,
verifica dell’host ufficiale a ogni redirect e massimo tre redirect. Limiti:
64 MB per download, 48 MB per workbook, 320 MB complessivi per le parti OOXML,
64 MB per singola parte e 40.000 righe. Rifiutare percorsi ZIP assoluti,
parent traversal, duplicati e parti cifrate o sospette prima dell’estrazione.

La finestra richiesta è una regola del servizio, non un fallback del provider:
deve contenere esattamente i dodici mesi attesi, senza mesi futuri, buchi,
duplicati o sovrapposizioni. Uno storico più vecchio non è sostituto valido.

L’ancora tariffaria ARERA deriva dagli atti e dataset ufficiali applicabili
alla data richiesta, integrando il workbook quando il suo periodo non arriva
ad `as_of`. `anchor.as_of` identifica la data dello snapshot verificato e non
deve essere riscritta per coincidere con la data del confronto. L’anchor è
applicabile soltanto nell’intervallo half-open `validity`; il suo riuso in una
data diversa da `anchor.as_of` richiede un’evidenza di copertura specifica per
la data richiesta. Il package dell’anchor non deve essere acquisito ogni
giorno: lo stesso snapshot resta utilizzabile mentre la sua validità copre la
data, anche se i documenti sono già stati pubblicati in precedenza.

L’evidenza lega l’identificativo e il digest canonico dell’anchor, la data del
confronto, l’istante della verifica e l’esito dei digest di tutte le fonti
versionate. Include una revisione attestata degli atti successivi presso i
registri ufficiali pertinenti di ARERA, ADM e Gazzetta Ufficiale e della
normativa vigente su Normattiva. La revisione registra responsabile, URL e
data controllata, ricerche, atti trovati e valutazione della loro applicabilità.
Esito incompleto, fonte alterata o atto applicabile rendono la copertura non
pronta; un atto applicabile richiede un nuovo anchor verificato. La verifica
può avvenire in un processo separato e il relativo risultato può essere
persistito: preflight e confronto deterministico non acquisiscono fonti dalla
rete.

L’acquisizione dell’anchor è un’operazione Core esplicita e distinta dal
confronto. `refresh_regulatory_anchor(as_of, registry_reviews)` scarica e
verifica tutti i documenti versionati già elencati nell’anchor, conserva SHA-256
osservati e restituisce `RegulatoryAnchorRefreshResult` serializzabile. Se i
digest coincidono, riusa i valori e `anchor.as_of` senza riscriverli; se un
digest cambia o l’intervallo non copre la data, restituisce `review_required`.
Il refresh richiede inoltre revisioni datate dei registri ufficiali pertinenti
e blocca atti applicabili o incerti. Non deduce l’irrilevanza giuridica da un
hash o da parole chiave e non genera valori nuovi da layout non supportati.
Preflight e confronto consumano il risultato persistito senza rete. L’API
acquisisce i documenti collegati al package corrente; la discovery di nuove
pubblicazioni e la produzione di un nuovo anchor richiedono parser versionati
per i nuovi atti e non vengono simulate come aggiornamento automatico del
package.

La composizione mantiene separati oneri, rete e componenti commerciali, senza
sommarne totali e componenti elementari insieme.

Accise e IVA seguono fonti ufficiali fiscali indipendenti dal workbook ARERA.
Aliquote, soglie, trattamento residente/non residente e basi imponibili sono
verificati e versionati con provenance propria; atti successivi al set fiscale
esistente devono essere valutati prima del suo riuso.

## Contratto d’integrazione additivo

`ProjectedDomesticEnergyService` offre acquisizione del catalogo, degli indici
e dell’ancora regolatoria, `preflight`, `compare` e `recommend`. La richiesta
usa contratto corrente, profilo storico degli ultimi dodici mesi, `as_of`,
classificazione, eleggibilità, misure billing indispensabili e dichiarazione
esplicita sulla continuità del contratto. Fonti e input del calcolo sono
espliciti per consentire replay deterministici.

`ProjectedDomesticEnergyService.source_preflight(as_of, catalog,
market_history, anchor, coverage_evidence)` espone il gate tipizzato delle
fonti per i consumer che non dispongono ancora di una richiesta cliente. Il
preflight cliente e `compare` riusano gli stessi controlli. La copertura deve
riferirsi esattamente alla data richiesta; `anchor.as_of` resta la data
originale dello snapshot. Il preflight cliente distingue richiesta valida,
catalogo verificato, finestra indice completa e fresca, anchor applicabile con
copertura confermata, modellabilità della baseline e copertura contrattuale.
Espone periodi, fonti e codici di blocco. È non pronto se manca un dato
economico necessario.

Il risultato contiene snapshot, periodo, osservazioni storiche con finestre
originarie, periodi futuri con valori stimati, moltiplicatori e assunzioni,
data originale, validità e id dell’evidenza dell’anchor con provenance senza
periodi riscritti, tre confronti tipizzati
`low_index`, `base`, `high_index`, warning/esclusioni e recommendation
separata. La distinzione fra stato della fonte e stima è verificabile dal
consumer e non dipende da testo libero. La recommendation riusa solo il
risultato base e le soglie configurate.

Aggiungere nuovi schema ID e capability al manifest, mantenendo gli ID, i
modelli e la semantica degli envelope correnti. Envelope canonici rifiutano
float economici, chiavi duplicate, schema sconosciuti e bytes sorgente.
Le regole e i modelli di dominio non dipendono da framework web, cloud, DB, MCP
o AI.

## Test e criteri di accettazione

- Provenance, acquisizione verificata vs parsing offline, digest, layout,
  unità, mapping indice e fonti malformate.
- PDF mensile primario; fallback al solo HTTP 404; errori di rete, integrità e
  parsing non devono attivarlo. Coprire riuso dello ZIP annuale, valori
  `Decimal`, digest e locator OOXML, layout anomali e limiti di sicurezza.
- Serie `_15` completa in `Europe/Rome`, compresi i giorni a 92 e 100 periodi;
  duplicati, gap, formule, celle mancanti e archivi incompleti devono fallire
  chiusi. Confrontare la media con la precisione esposta dai PDF ufficiali.
- Envelope di storico che round-trippa entrambe le provenance senza cambiare
  manifest, schema ID o capability.
- Dodici mesi esatti; rifiuto di gap, duplicati, buchi interni, copertura
  incompleta, dataset arretrato e unità/granularità incompatibili.
- Abbinamento stagionale, anche con cambio anno, febbraio e bisestili; fattori
  `Decimal` 0,80/1,00/1,20.
- Invarianza di spread e quote al variare dello scenario dell’indice.
- Composizione e validità ARERA per entrambi i profili, quote, basi fiscali,
  soglie e arrotondamento mensile; fixture separate dalla prova live.
- Anchor applicabile all’inizio, all’interno e nell’ultimo giorno valido del
  suo intervallo; la data di fine è esclusa. L’evidenza deve preservare
  separatamente la data originale dell’anchor e la data della verifica.
- Fonti alterate, digest mancanti, revisione atti assente/incompleta e nuovo
  atto applicabile bloccano il riuso; l’evidenza valida viene serializzata e
  ricaricata senza rete.
- Proiezione futura non verificata; il billing storico continua a rifiutare
  regole non valide per il suo periodo.
- Scadenza offerte, sottoscrivibilità ad `as_of`, continuità esplicita,
  durata insufficiente e tariffa non modellabile.
- Recommendation invariata sul solo base; scenari stress non cambiano soglie,
  ranking o selezione. Envelope e golden storici invariati.
- CLI/API di refresh separata dal confronto offline; verifica di ogni documento
  versionato dell’anchor e blocco fail-closed per fonti cambiate o revisioni
  normative non classificate.
- Copertura incompleta se gli hash coincidono ma manca la revisione ufficiale
  datata o la valutazione di un atto candidato. Le fixture non attestano dati
  reali.
- Gate AGENTS: Ruff, format check, mypy, pytest con branch coverage almeno 95%,
  golden privati, smoke base/extra e `git diff --check`.

## Confini

In scope: Core, fonti pubbliche, calcolo, serializzazione, test e CLI di
acquisizione/refresh. Fuori scope: persistenza, scheduler, autenticazione, API
HTTP, UI, Platform, forward quote, forecast, robust recommendation su stress,
commit, release e pubblicazione. La classificazione giuridica di atti nuovi o
ambigui resta una decisione esplicita e tracciata; il Core non la deduce da
somiglianza testuale.

## Fonti normative

- [GME — PUN Index GME, DTF 25 MPE](https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20250101DTF25MPE.pdf)
- [GME — Avvio prodotti MGP a 15 minuti dal 1° ottobre 2025](https://gme.mercatoelettrico.org/it-it/Home/AvvisieComunicati/AvvisieComunicatiME?id=7113)
- [GME — Dati storici MGP](https://gme.mercatoelettrico.org/Home/Esiti/Elettricita/MGP/Statistiche/DatiStorici)
- GME — PDF mensili: ottobre 2025, giugno–settembre 2026; usare i documenti ufficiali del rispettivo mese per il controllo alla precisione pubblicata.
- [GME — Prezzi medi per fasce](https://gme.mercatoelettrico.org/it-it/Home/Pubblicazioni/PrezzoMedioFasce)
- [Portale Offerte — Open Data](https://www.ilportaleofferte.it/portaleOfferte/it/open-data.page)
- [ARERA — Delibera 575/2025/R/eel](https://www.arera.it/atti-e-provvedimenti/dettaglio/25/575-25)
- [ARERA — Delibera 588/2025/R/com](https://www.arera.it/atti-e-provvedimenti/dettaglio/25/588-25)
- [ARERA — Delibera 227/2026/R/com](https://www.arera.it/fileadmin/allegati/docs/26/227-2026-R-com.pdf)
- [ADM — Aliquote accisa nazionali](https://www.adm.gov.it/portale/aliquote-accisa-nazionali)
- [Gazzetta Ufficiale — D.Lgs. 43/2025, testo unico delle accise](https://www.gazzettaufficiale.it/eli/id/2025/04/04/25G00052/sg)
- [Gazzetta Ufficiale — MEF, decreto 10 marzo 2026](https://www.gazzettaufficiale.it/eli/id/2026/03/20/26A01335/sg)
- [Normattiva — DPR 633/1972, Tabella A vigente al 27 settembre 2026](https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.presidente.della.repubblica:1972-10-26;633:1~art1!vig=2026-09-27)
- [Normattiva — DPR 633/1972, art. 16 vigente al 27 settembre 2026](https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.presidente.della.repubblica:1972-10-26;633~art16!vig=2026-09-27)
- Spec 007–011; ADR 0001–0014; ADR 0016.
