# ADR 0016 — Confronto beta su scenari storici

## Stato

Accettato per la Spec 013. La recommendation della beta è autorizzata sul
solo scenario base.

## Decisione

La beta confronta i prossimi dodici mesi completi con i dodici mesi storici
più recenti e consecutivi, ripetendo ogni mese sul medesimo mese futuro
dell’anno. I tre scenari cambiano il solo indice energetico applicando 0,80,
1,00 e 1,20. Consumo, spread, prezzi fissi, quote, regolazione e policy
fiscale rimangono uguali, salvo il ricalcolo delle imposte sulle basi
imponibili risultanti.

Gli indici derivano da dataset ufficiali con mapping e provenance. Il mapping
esplicita definizione, unità, granularità e fascia; PUN, PE, picco/fuori-picco
e prezzi F1/F2/F3 non sono equivalenti. Una finestra incompleta o arretrata non
è sostituita in silenzio.

L’anchor regolatorio e fiscale conserva `as_of` come data del suo snapshot
verificato e `validity` come intervallo di applicabilità half-open. Un confronto
in un’altra data interna a tale intervallo richiede un’evidenza separata che
lega l’anchor immutato alla data richiesta, verifica tutti i digest versionati
e documenta la revisione degli atti successivi applicabili. Hash corrispondenti
non provano da soli l’assenza di nuovi provvedimenti. Un digest modificato, una
revisione assente/incompleta o un nuovo atto applicabile bloccano l’uso; per
recepire l’atto serve un nuovo anchor verificato.

Acquisizione e verifica delle fonti sono operazioni esplicite separate dal
preflight e dal confronto deterministici, che consumano snapshot ed evidenza
persistibili senza rete. Il package immutabile dell’anchor non richiede un
refresh giornaliero: può essere riutilizzato entro la validità dopo una
conferma di copertura riferita alla data del confronto. I risultati mantengono
la data originale dell’anchor distinta dalla data del confronto. Applicare
l’anchor ai dodici mesi futuri è un’assunzione esplicita, mai `VERIFIED`. Il
billing storico conserva i propri controlli e non riceve ruleset con periodi
alterati per apparire verificato.

L’API Core `refresh_regulatory_anchor` e la CLI `--refresh-anchor` scaricano e
verificano tutti i documenti dell’anchor corrente e producono un envelope con
esito e digest, senza richiedere un nuovo download del package. La revisione
datata degli atti successivi resta un input esplicito: un atto applicabile o
incerto blocca l’uso, e il Core non ne deduce l’irrilevanza da hash o parole
chiave. Generare un anchor per un periodo ulteriore richiede nuovi parser e
mapping versionati. Acquisizione e discovery restano fuori dal percorso offline
di calcolo.

Per il PUN mensile, il report PDF è la fonte primaria. Il Core usa il file
annuale ufficiale GME MGP soltanto dopo un HTTP 404 esplicito del relativo PDF;
timeout, errori di rete, altri status HTTP, contenuto corrotto e parsing
fallito restano errori e non attivano il fallback. Dal 1° ottobre 2025 il
fallback usa `PUN INDEX GME` a 15 minuti nel foglio `Prezzi-Prices` del
workbook `_15`; `_60` non è un sostituto automatico. La media mensile è la
media aritmetica dei periodi consecutivi e di pari durata in `Europe/Rome`,
validati giorno per giorno (92, 96 o 100 quarti d’ora). I token numerici XML
restano `Decimal`, con precisione interna 50 e conversione EUR/MWh→EUR/kWh
dividendo per 1.000. Il PDF è confrontato soltanto alla sua precisione
pubblicata.

La provenance dello ZIP lega mese, URL ufficiale, digest dei byte scaricati,
workbook, foglio e celle. Un unico ZIP annuale può servire più mesi della
stessa acquisizione. Il lettore OOXML usa la libreria ZIP standard e
`defusedxml`; limiti di byte, righe, parti e redirect, allowlist HTTPS e
controlli dei percorsi ZIP fanno parte della validazione della fonte. Layout
diverso, copertura incompleta o contenuto ambiguo falliscono chiusi. Restano
invariati i modelli economici, gli schema ID e le capability pubbliche.

Si aggiungono un servizio e schema ID/capability d’integrazione; i contratti
correnti restano compatibili. La recommendation riusa policy e soglie esistenti
sullo scenario base senza rivalutare i costi. Il percorso forward della
proposta Spec 012 rimane differito.

Per il CdispD delle offerte domestiche con codice Portal 14, la stima usa il
parametro ufficiale del trimestre corrente secondo Regole Portale v4.2
§3.4.3.1 e Spec 008 addendum v0.8.3. Lo snapshot giornaliero conserva il dato
tipizzato e la provenienza anche dopo serializzazione. L'applicazione sui
dodici mesi futuri è un'assunzione tracciata, uniforme nei tre scenari; non
richiede che siano già pubblicati i consuntivi futuri, non estende le righe
storiche e non aggiunge nuovamente perdite o mercato capacità.

## Conseguenze

- L’output è una stima condizionata alle assunzioni esposte.
- Un indice essenziale, un’ancora o una regola fiscale non provati rendono il
  preflight non pronto.
- Un mapping commerciale assente esclude l’offerta interessata; non viene
  trasformato in un sinonimo di un altro indice.
- La Platform potrà consumare il nuovo contratto in una milestone distinta;
  persistenza e interfaccia restano fuori dalla Core.
