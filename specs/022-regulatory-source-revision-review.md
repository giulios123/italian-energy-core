# 022 — Revisione delle nuove versioni dei documenti ufficiali

## Obiettivo e perimetro

Un cambiamento dei bytes di una fonte nota genera una richiesta di revisione
persistibile e notificabile dall'applicazione all'amministratore. Non richiede
una release della libreria per accettare una versione esaminata. Core conserva
l'interpretazione economica; l'applicazione autentica il revisore, conserva gli
artefatti e presenta la coda. Nessuna email o notifica esterna è implicita.

La prima versione gestisce la sostituzione di un documento già referenziato
dall'anchor corrente. Nuovi atti e valori economici diversi continuano attraverso
discovery, parser, mapping e candidate; approvare l'equivalenza di un documento
non approva aliquote o tariffe diverse.

## Richiesta e decisione

`RegulatorySourceRevisionRequest` identifica anchor ID e digest, fonte e URL
ufficiale, digest precedente e osservato, validità dell'anchor, data di rilevazione,
valori correnti e valutazione del contenuto (`equivalent`, `changed`,
`manual_review`). L'ID deterministico lega anchor, fonte, URL, entrambi i digest e
validità; il repository conserva la prima osservazione immutabile per tale ID.
I raw bytes restano esterni agli envelope e sono archiviati per digest.

Quando esiste un parser supportato, Core espone dati estratti, versione del parser
e confronto con i valori dell'anchor. Per Normattiva IVA si distinguono la
disposizione domestica della Tabella A e il rinvio all'articolo 16; spaziatura o
HTML estraneo alla disposizione non costituiscono una variazione economica.
La data `vig` richiesta e il timestamp effettivo di acquisizione sono distinti:
riacquisire oggi un URL storico non autorizza a falsificare `fetched_at`.

Una decisione immutabile lega l'intera richiesta, revisore, timestamp consapevole
del fuso, motivazione e risultato: `approve_equivalent`, `reject` o `revoke`.
L'approvazione richiede una conferma esplicita di equivalenza; una valutazione
Core `changed` non può essere approvata come equivalente. `manual_review`
richiede un'attestazione umana esplicita, non una presunzione del parser.
Una nuova decisione può sostituire soltanto la decisione corrente attesa (CAS),
senza modificare o cancellare le precedenti.

La decisione positiva vale esclusivamente per quel digest osservato, URL, fonte,
anchor ID/digest e periodo. Non è retroattiva rispetto al giorno civile della
revisione, non estende la validità dell'anchor e non approva versioni successive.
I confronti salvati e gli anchor originali rimangono immutabili.

## Coverage e serializzazione

Il mismatch resta bloccante in assenza di approvazione valida. La coverage v2
conserva controllo originale e decisione esatta; Core convalida in modo offline
tutti i collegamenti, i digest, le date e l'esito prima di accettare l'osservazione.
Una decisione non supera fonte assente, discovery incompleta, nuovo atto
applicabile, scadenza, conflitto, parser che prova valori diversi o altra ragione
indipendente. Le approvazioni di fonte non possono rendere pronto un candidate
con valori economici non validati.

Gli envelope coverage/report v1 e v2 già pubblicati conservano i bytes e digest
originali. I nuovi artefatti hanno schema espliciti; la manifest espone la
capability `regulatory_source_revision_review`. La Platform deve verificarla
prima di abilitare la funzione admin.

## Integrazione operativa Platform

Il worker crea una richiesta per ciascun mismatch e riusa la stessa richiesta
finché anchor e versione non cambiano. L'admin vede fonte ufficiale, versione
scaricata, dati interessati, valutazione e motivazione richiesta; può approvare
l'equivalenza, rifiutare o revocare. Gli utenti ordinari non possono leggere la
coda o decidere. Identità e timestamp provengono dalla sessione e dal server.

La decisione richiede un nuovo controllo delle fonti e un nuovo catalogo. Fino a
quel controllo nessuna vecchia snapshot precedente alla decisione può essere
usata per un confronto nuovo. La Platform richiede l'avvio dopo la decisione e
permette un ricontrollo manuale; il job periodico ogni sei ore funge anche da
recupero. La pianificazione è una responsabilità dell'host.
L'approvazione non implica `ready=true`.

## Accettazione

1. Mismatch senza decisione: richiesta deduplicata, gate chiuso.
2. Approvazione valida: stessa versione accettata nei controlli successivi,
   anchor e artefatti storici identici.
3. Digest/URL/fonte/anchor/periodo diversi, data futura o esito negativo:
   approvazione non applicabile e gate chiuso.
4. Fonte assente, scadenza e discovery incompleta restano bloccanti.
5. Valore estratto diverso: approvazione di equivalenza rifiutata.
6. Round trip dei nuovi schema; digest dei vecchi envelope invariati.
7. API: admin, CSRF, payload limitato, ID sconosciuto, CAS concorrente,
   idempotenza e file esatto per digest; nessun dato cliente nel report.
8. Decisione/revoca invalida immediatamente le snapshot precedenti per i nuovi
   confronti; il worker riprende il lavoro e archivia nuova coverage/catalogo.
9. Browser: richiesta pendente, anteprima, approvazione motivata, rifiuto, errore
   e stato di controllo in corso; nessuna approvazione del documento live da
   parte dell'agente al posto dell'admin.

## Regressione di integrazione — 2026-11-05

La verifica di completezza dei digest nel preflight proiettato deve usare la
stessa valutazione digest/versione/decisione della verifica normativa. Una
versione approvata, ancora osservata e valida, non può lasciare un check falso
senza reason code. La copertura completa delle fonti resta obbligatoria; envelope
legacy senza approvazioni mantengono il confronto esatto del digest originale.
