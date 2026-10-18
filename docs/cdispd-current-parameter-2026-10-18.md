# CdispD corrente per la stima annuale — 18 ottobre 2026

## Problema e criterio corretto

Il codice `TIPO_DISPACCIAMENTO=14` identifica la componente aggregata CdispD.
Le offerte interessate non sono prive del prezzo energia: la riga commerciale
rinvia a un parametro regolato pubblicato separatamente. La sola integrazione
con le righe mensili del workbook ARERA non risolveva la stima futura, perché
pretendeva osservazioni verificate per mesi non ancora trascorsi.

Le [Regole per il calcolo della spesa annua stimata, v4.2 del 5 ottobre
2026](https://www.ilportaleofferte.it/portaleOfferte/resources/cms/documents/6bc502553cb0ea45958840b2de20078d.pdf),
§3.3, §3.4.3.1 e appendice, indicano per i clienti domestici il CdispD del
trimestre in corso e la formula `CdispD × consumo annuo totale`, in EUR/kWh.
La formula non prevede un ulteriore fattore per le perdite e non distingue
residenti e non residenti per questa singola componente.

Il [CSV ufficiale giornaliero dei parametri Mercato Libero del
18/10/2026](https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/parametriML/2026_10/PO_Parametri_Mercato_Libero_E_20261018.csv)
contiene alla riga 52 `cdispd=0.016776`. È un unico aggregato di capacità e
corrispettivi di dispacciamento Terna. Su 1.645 kWh il prodotto non arrotondato
è EUR 27,596520, circa EUR 27,60 prima delle imposte.

## Scritto e implementato

Spec 008 addendum v0.8.3 e Spec 013/ADR 0012/0016 distinguono ora osservazione
corrente e periodo futuro di applicazione. Il parser v4 conserva un parametro
tipizzato nel catalogo durante l'acquisizione; il dato sopravvive all'envelope
senza i bytes grezzi. Il percorso prospettico genera un'assunzione esplicita a
valore costante, conservando tariffa, data, periodo, snapshot, digest e
provenienza. La nuova capability è `portal_cdispd_parameter_projection`.

L'importo resta identico nei tre scenari PUN ed entra una sola volta nella
materia energia, nell'imponibile IVA e nei totali. Non si modificano la validità
mensile ARERA, il replay storico, i prezzi del codice 99 o i risultati salvati.
Un parametro mancante, duplicato, errato o proveniente da altra data non viene
sostituito con zero o con un dato precedente. Le sole offerte dipendenti dal
parametro restano escluse; altre offerte complete possono essere confrontate.

## Prova sul catalogo ufficiale

Acquisizione HTTP Core dei cinque file ufficiali del 18 ottobre, seguita da
serializzazione/hydration e normalizzazione offline dello stesso snapshot.
Profilo: domestico non residente, Roma (`12/058/058091`), modalità `01/01`.
Periodo economico: `[2026-11-01, 2027-11-01)`.

- Record acquisiti: **4.550**.
- Snapshot: `portal-snapshot:1360d71b92cc45cc8f8b6c1f8ec6fe18c7bbda53d9f21d2b4b02fc5027ca0412`.
- CSV parametro SHA-256: `801bb798d551656be3e7e9db45431d81fc0bb5df147dfb4f94b722e577e639d0`.
- Senza parametro proiettato: **0** offerte normalizzate, **429** escluse per
  componente economica mancante.
- Con parametro corrente: **369** offerte normalizzate; **8** superano il filtro temporale attuale
  del Core. Il conteggio 8 non attesta la reale copertura economica: vedere
  la rettifica seguente. Restano 4 componenti
  mancanti e 56 tariffe non rappresentabili, oltre alle esclusioni ordinarie.

La prova dimostra il recupero del dato e l'esito del filtro attuale; non equivale a un confronto economico HTTP della Platform. Gli
artefatti diagnostici temporanei sono sotto `/tmp/energy-cdispd-live-*` e non
contengono dati personali.

## Verifiche e adozione

Le nuove regressioni economiche sono state eseguite prima della correzione e
fallivano per CdispD mancante. Dopo la correzione verificano entrambi i profili,
settembre e ottobre, serializzazione senza raw bytes, applicazione annuale,
importi e IVA indipendenti: 3.600 kWh × EUR 0,02 = EUR 72,00, più EUR 7,20 di
IVA al 10%. Verificano anche scenari invariati, periodi/dati incongruenti,
valori mancanti/duplicati/malformati, nessun doppio conteggio e digest del
risultato sensibile al parametro. Suite finale: **842 test passati**, branch
coverage **95,05%** con soglia 95% superata; Ruff check/format e mypy
`src tests` passano. Il Memory Bank registra la milestone.

La correzione è inclusa nella release Core
[v0.13.4](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.4)
e pubblicata su [PyPI](https://pypi.org/project/italian-energy/0.13.4/).
Trusted Publishing (run `39145646425`) e CI su `main`/tag (`39145299869`,
`39145469387`) sono riusciti; i digest SHA-256 PyPI coincidono con gli asset
GitHub. Wheel: `b353a9510d1d216d27d36b1f23deb79028fcb1513fd5d59f9f26bd80b914deca`;
sdist: `3f656573fff136f948c99eff46c5eaf2431885db3ab333edc02240a143f945b9`.

La copertura tariffaria effettiva per tutti i dodici mesi resta un gate aperto:
la finestra di sottoscrizione è riutilizzata come validità tariffaria e la
durata è ancorata a `as_of`, non all'attivazione simulata. Le otto offerte che
superano il filtro attuale non dimostrano copertura economica annuale. Questo
audit non modifica il calcolo CdispD. La release Core non aggiorna da sola il
runtime Platform: l'adozione e un nuovo refresh del catalogo restano separati.
I vecchi snapshot privi del campo non vengono riscritti in lettura.


## Rettifica del filtro annuale — 18 ottobre 2026

L'utente ha contestato il risultato di sole otto candidate. L'audit dello
stesso snapshot evidenzia che il filtro Core riutilizza `DATA_INIZIO/FINE`
sia per `subscription_period` sia per `tariff_validity`, poi limita la durata
relativa tramite quella stessa scadenza. Nel percorso prospettico la durata
parte inoltre da `as_of=2026-10-18`, mentre la simulazione inizia il 1° novembre.
Il numero 8 è quindi l'esito di quel filtro e non una verifica che sul mercato
esistano soltanto otto offerte adatte a un confronto annuale.

Ripartizione delle 369 offerte normalizzate:

- 289 hanno durata letta almeno pari a 12 mesi, ma vengono limitate dalla
  data di fine sottoscrizione;
- 24 hanno durata letta di 12 mesi, ma partono dal 18 ottobre e terminano
  prima del 1° novembre 2027;
- 47 non hanno una durata utilizzabile nel campo selezionato dal parser;
- una ha durata letta di un mese;
- otto superano il filtro attuale.

Esempio osservato: `Energia Lunga Luce Easy`, durata letta 36 mesi,
sottoscrizione fino al 10 novembre 2026, viene normalizzata con tariffa valida
soltanto fino all'11 novembre 2026 escluso. Occorre inoltre verificare la
semantica della durata generale del contratto separatamente da quella delle
componenti economiche: in altri record esistono più campi `DURATA` a profondità
diverse. Il conteggio delle durate generali non dimostra da solo la copertura
dei prezzi. La correzione CdispD è verificata; il gate annuale e questa
distinzione restano un difetto aperto, da correggere prima di dichiarare
completa l'accettazione economica. Questo audit non modifica il calcolo.
