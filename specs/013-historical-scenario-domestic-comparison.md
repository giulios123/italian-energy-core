# Spec 013 — Confronto beta domestico con scenari storici

**Stato:** implementata e rilasciata in Core `v0.12.0` il 2026-09-28.

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

La finestra richiesta è una regola del servizio, non un fallback del provider:
deve contenere esattamente i dodici mesi attesi, senza mesi futuri, buchi,
duplicati o sovrapposizioni. Uno storico più vecchio non è sostituto valido.

L’ancora tariffaria ARERA deriva dagli atti e dataset ufficiali applicabili
alla data richiesta, integrando il workbook quando il suo periodo non arriva
ad `as_of`. La composizione mantiene separati oneri, rete e componenti
commerciali, senza sommare totali e componenti elementari insieme.

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

Il preflight distingue richiesta valida, catalogo verificato, finestra indice
completa e fresca, ancora regolatoria/fiscale verificata ad `as_of`,
modellabilità della baseline e copertura contrattuale. Espone periodi e fonti
effettivi. È non pronto se manca un dato economico necessario.

Il risultato contiene snapshot, periodo, osservazioni storiche con finestre
originarie, periodi futuri con valori stimati, moltiplicatori e assunzioni,
ancore e provenance senza periodi riscritti, tre confronti tipizzati
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
- Dodici mesi esatti; rifiuto di gap, duplicati, buchi interni, copertura
  incompleta, dataset arretrato e unità/granularità incompatibili.
- Abbinamento stagionale, anche con cambio anno, febbraio e bisestili; fattori
  `Decimal` 0,80/1,00/1,20.
- Invarianza di spread e quote al variare dello scenario dell’indice.
- Composizione e validità ARERA per entrambi i profili, quote, basi fiscali,
  soglie e arrotondamento mensile; fixture separate dalla prova live.
- Ancora puntuale e proiezione futura non verificata; il billing storico
  continua a rifiutare regole non valide per il suo periodo.
- Scadenza offerte, sottoscrivibilità ad `as_of`, continuità esplicita,
  durata insufficiente e tariffa non modellabile.
- Recommendation invariata sul solo base; scenari stress non cambiano soglie,
  ranking o selezione. Envelope e golden storici invariati.
- Verifica live separata di endpoint ufficiali, mesi effettivamente letti,
  digest e motivo dei gate incompleti. Le fixture non attestano dati reali.
- Gate AGENTS: Ruff, format check, mypy, pytest con branch coverage almeno 95%,
  golden privati, smoke base/extra e `git diff --check`.

## Confini

In scope: Core, fonti pubbliche, calcolo, serializzazione, test e CLI di
verifica. Fuori scope: persistenza, scheduler, autenticazione, API HTTP, UI,
Platform, forward quote, forecast, robust recommendation su stress, commit,
release e pubblicazione.

## Fonti normative

- [GME — PUN Index GME, DTF 25 MPE](https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20250101DTF25MPE.pdf)
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
