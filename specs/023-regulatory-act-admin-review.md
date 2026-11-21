# 023 — Revisione amministrativa degli atti rilevati

Le segnalazioni discovery `review_required` producono richieste canoniche per
l'anchor corrente. Una richiesta lega record ufficiale completo (inclusi data
aggiornamento e atti modificanti), digest dei bytes ufficiali acquisiti, anchor
ID/digest e validità. Timestamp e variazioni estranee dell'indice non cambiano
l'identità; ogni variazione del record o documento la cambia. I bytes restano
archiviati dall'host attraverso l'observer esistente.

Per Normattiva la fonte da esaminare è la pagina ufficiale dell'atto identificata
dal permalink ufficiale ELI, con codice redazionale, pubblicazione e data della
versione consolidata rilevata, non l'endpoint POST
di ricerca. Non si interpreta il titolo o si presume l'irrilevanza di un atto.
La richiesta mostra anche gli identificativi degli atti modificanti.

Gli esiti sono `approve_equivalent` (attestazione umana che l'atto non cambia i
dati economici rappresentati), `requires_update`, `reject`, `revoke`. Identità e
clock sono assegnati dall'host autenticato. Una decisione positiva richiede
conferma esplicita, fonte acquisita, motivazione, periodo residuo non retroattivo.
Richiesta senza bytes verificabili: visibile ma non approvabile. Revoca richiede
il riferimento alla decisione precedente. Le decisioni sono append-only.

Il Core applica la decisione solo alla medesima richiesta ancora osservata nel
refresh. Decisioni obsolete, ambigue, future, negative o fuori periodo non
sbloccano. Gli atti con interpretazione già supportata non possono essere
sovrascritti da questo flusso. Discovery incompleta, variazioni economiche,
fonti anchor mancanti o modificate, scadenze e gap restano bloccanti.

Coverage v3 e report v4 conservano richieste e decisioni; i preflight normativo
e proiettato ricontrollano offline tutti i collegamenti anche se `ready` è
stato falsificato. Gli schema storici conservano struttura e digest. Le decisioni
valgono solo per l'anchor corrente: non promuovono un successore con nuovi dati.

La capability additiva `regulatory_act_review` espone richieste, decisioni e
factory generica. Le successive decisioni sui singoli atti non richiedono una
release. Nuove formule o nuovi mapping economici restano lavoro del Core.

Accettazione test-first: stessa osservazione deduplicata; nuova modifica/bytes
riapre; approvazione valida rende pronta la coverage corrente; negative/revoca,
assenza fonte, date errate, anchor diverso e discovery incompleta bloccano;
coverage offline contraffatta respinta; roundtrip vecchi e nuovi schema;
refresh completo produce richieste e riutilizza solo le decisioni applicabili.
