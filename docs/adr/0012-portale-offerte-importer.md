# ADR 0012 — Portale Offerte open data come catalogo commerciale verificabile

## Stato

Accettata per la Spec 008 v0.8.0.

## Decisione

Il catalogo commerciale viene acquisito esclusivamente dagli open data
ufficiali del Portale Offerte e resta separato dall'importer ARERA e dal
`RegulatoryRuleSet`. Un'esecuzione usa la data esatta `as_of == period.start`,
scarica i cataloghi elettrici Mercato Libero e PLACET e conserva snapshot,
digest, provenance e diagnostiche prima della normalizzazione.

Il parser produce record source-faithful e un ledger completo di esclusioni.
Solo tariffe fixed o indexed esprimibili con i modelli canonici entrano nel
`DeterministicComparisonEngine`; la stima annua del Portale, i forward, le
condizioni testuali non modellate, gli scaglioni e i canoni non sono sostituti
di Pricing o Billing.

I corrispettivi commerciali annui usano il pro-rata mensile a dodicesimi con
frazioni giorni/365. Le offerte indexed richiedono market data verificati e
copertura esatta, senza interpolazione o carry-forward.

### Decisione temporanea — 2026-10-16

Su richiesta dell'utente, il valore esatto `TIPO_OFFERTA=04` del catalogo
Mercato Libero viene escluso economicamente senza interrompere il resto
dell'importazione. Il parser v2 conserva il record come `unsupported`,
con raw fields e provenance, senza interpretarne i prezzi. Il normalizzatore
produce `unsupported_offer_type`, codice `04` e locator nel dettaglio e
contabilizza il record tra ricevuti ed esclusi.

Questa decisione non assegna un significato economico generale al codice
`04`, non lo converte in fixed/indexed e non accetta altri tipi sconosciuti.
Identificativi e date obbligatori, namespace e controlli d'integrità restano
vincolanti. Il supporto economico del tipo `04` richiederà una decisione
successiva basata sul mapping ufficiale.

### Decisione v0.8.1 — componenti `Dispacciamento`

Dal parser `008-portal-offers-v3`, ogni nodo `Dispacciamento` viene conservato
con il codice originale, i campi raw, la semantica versionata, la validità e
provenance puntuale. I codici `01`–`14` descrivono riferimenti regolatori e non
forniscono da soli un prezzo: senza un importo verificato l'offerta resta
esclusa dal confronto. Il codice `14` resta un solo aggregato CdispD e non viene
ripartito. Il codice `99` può entrare nella bolletta soltanto con
`VALORE_DISP`, unità e validità espliciti, come addebito separato; non modifica
il prezzo energia. I dettagli normativi del mapping `portale-dispacciamento-v1`
e la proiezione fino a `Bill.components[]` sono definiti nell'addendum v0.8.1
della Spec 008.

### Decisione v0.8.3 — parametro CdispD per la stima annuale

Le [Regole Portale v4.2 del 5 ottobre 2026](https://www.ilportaleofferte.it/portaleOfferte/resources/cms/documents/6bc502553cb0ea45958840b2de20078d.pdf),
§3.3, §3.4.3.1 e appendice, definiscono per il codice 14 domestico il CdispD
del trimestre corrente moltiplicato per il consumo annuo totale, senza altra
maggiorazione perdite. Il CSV giornaliero dei parametri Mercato Libero, già
acquisito, ne pubblica il valore. Richiedere osservazioni mensili verificate
di tutti i dodici mesi futuri impedirebbe questa stima ufficiale.

Durante l'acquisizione si conserva il parametro tipizzato nello snapshot
catalogo. Il solo percorso prospettico lo applica mediante un'assunzione
esplicita a valore costante, separata dai dati storici e non classificata come
tariffa futura verificata. Il replay storico conserva il requisito di
copertura mensile esatta. Parametro assente o non valido esclude le sole
offerte dipendenti; fonte/data/digest, aggregato unico e assenza di doppi
conteggi restano vincolanti. Dettagli in Spec 008 addendum v0.8.3.

### Decisione v0.8.4 — sottoscrizione e condizioni economiche

Nel percorso prospettico, le date di `ValiditaOfferta` delimitano l'adesione:
`DATA_FINE` è inclusiva e non è la scadenza del prezzo dopo l'attivazione.
Il confronto verifica l'adesione a `as_of` e attiva economicamente l'offerta
all'inizio del suo orizzonte futuro. Il replay storico conserva il percorso
originario e non ricalcola risultati già congelati.

Le Specifiche SII del Processo di Trasmissione Offerte Mercato Retail v5.0,
p. 53, definiscono il `DURATA` diretto di `DettaglioOfferta` come durata delle
condizioni economiche in mesi; `-1` significa indeterminata. I periodi dei
prezzi sono nodi distinti, descritti dalle Regole Portale v4.2 pp. 25–26:
primi N mesi, mese finale `MM/AAAA`, mese di calendario o prezzo predefinito.
La lettura ricorsiva di un qualunque `DURATA` non è quindi ammessa.

Il parser v6 conserva questi dati strutturati e il normalizzatore espone
ambito e base della durata. Prezzi predefiniti consentono la stima annuale
senza una garanzia numerica di durata. Nessuna promozione, scadenza autonoma
o cambiamento di prezzo viene esteso o eliminato per rendere l'offerta
calcolabile. Snapshot precedenti restano leggibili ma richiedono un nuovo
refresh per accedere a questa semantica, senza deduzioni da campi mancanti.

## Conseguenze

- Il dominio rimane indipendente da web framework, browser, database, cloud e
  AI; il trasporto HTTP è iniettabile.
- Il catalogo può cambiare quotidianamente senza compromettere il
  determinismo: gli identificativi dipendono da URL, digest, parser e payload
  canonici, non dall'ordine o dall'orario di acquisizione.
- Un cambiamento strutturale della fonte blocca il confronto automatico con
  `REVIEW_REQUIRED`; un singolo record non rappresentabile viene escluso con
  codice stabile e provenance.
- Il supporto a gas, dual fuel, OCR/PDF, persistenza e scheduler richiede ADR e
  specifiche autonome.
