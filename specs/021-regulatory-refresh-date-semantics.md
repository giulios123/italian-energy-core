# Spec 021 — discovery tariffaria e classificazione del refresh novembre 2026

Data: 2026-11-04. Correzione della Spec 014, senza modifiche ai valori economici,
agli anchor storici o agli schema pubblici.

## Periodo della discovery

La data di ricerca di un record del canale `arera_tariffs` è `effective_from`.
La pubblicazione resta `published_at` e la data del registro resta
`registry_date`: non si riscrivono questi campi per far superare il gate.
Un atto tariffario appena pubblicato nel periodo resta osservabile anche
quando la decorrenza è futura: questo conserva lo staging anticipato. Quando
la decorrenza cade nel periodo, la ricerca la usa anche se pubblicazione e
registro precedono l'inizio della finestra.
Per gli altri canali la data di ricerca rimane `registry_date` oppure, in sua
assenza, `published_at`.

Validazione, filtro, ordinamento e confronto delle finestre sovrapposte usano
la stessa data di ricerca. La decorrenza mancante su una tariffa rende la
scansione incompleta, senza avanzamento del cursore. Restano bloccanti i record
fuori periodo, le identità discordanti e le pagine incomplete.

La regressione obbligatoria usa la delibera `343/2026/R/com`: pubblicata il
2026-09-29, efficace dal 2026-10-01, accettata in una ricerca che inizia il
2026-10-01. La rimozione in una finestra sovrapposta deve ancora essere rilevata.

## Atti puntuali sul gasolio

La Gazzetta pubblica il decreto `26A05715` il 2026-10-27. Il testo ufficiale
dell'articolo 1 riguarda il gasolio usato come carburante nel periodo
2026-10-28–2026-11-07; l'articolo 2 disciplina la copertura finanziaria.
La misura non modifica i campi dell'anchor dell'elettricità domestica.

Fonti verificate:

- https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A05715&art.dataPubblicazioneGazzetta=2026-10-27&art.flagTipoArticolo=0&art.idArticolo=1&art.idGruppo=0&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1
- https://www.gazzettaufficiale.it/atto/serie_generale/caricaArticolo?art.codiceRedazionale=26A05715&art.dataPubblicazioneGazzetta=2026-10-27&art.flagTipoArticolo=0&art.idArticolo=2&art.idGruppo=0&art.idSottoArticolo=1&art.idSottoArticolo1=10&art.progressivo=0&art.versione=1

Sono previste due regole esatte versionate di irrilevanza per questo anchor:
il decreto Gazzetta con identità/data/URL verificati e il record Normattiva TUA
`095G0523`, pubblicato il 1995-11-29, aggiornato il 2026-10-27, con unico ultimo
atto modificante `26A05715`. Un diverso collegamento, data, documento o URL
rimane da verificare. Titoli e parole chiave non determinano la classificazione.

## Accettazione

Test prima dell'implementazione; suite completa, Ruff, mypy, golden privati,
build e smoke wheel. Il percorso di refresh deve essere verificato su stato
nuovo e persistente. Nessun esito di processo, build o pubblicazione equivale
alla verifica live delle fonti: il gate richiede preflight pronto e nessuna
ragione bloccante. Fonti indisponibili o mutate mantengono il blocco.
