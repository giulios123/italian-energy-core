# Integrazione Platform — Core 0.13.10

Core espone `RegulatorySourceRevisionRequest`,
`RegulatorySourceRevisionDecision`, `SourceRevisionOutcome` e
`create_source_revision_decision` tramite `italian_energy.integration`.
Il servizio di rollover riceve `source_revision_decisions` tipizzate e produce
coverage v2/report v3 quando osserva versioni cambiate delle fonti dell’anchor.

L’host conserva i nuovi envelope con `dump_envelope`/`load_envelope`, autentica
l’admin, assegna actor e clock server-side e passa il request esatto alla factory.
Il digest della decisione identifica il suo payload canonico. Gli esiti sono
`approve_equivalent`, `reject`, `revoke`. L’approvazione richiede un booleano
esplicito e una motivazione, non può confermare dati diversi rilevati dal parser,
non estende la validità né vale retroattivamente. La revoca referenzia la decisione
precedente. Lo storage deve scegliere una sola decisione corrente per richiesta
e impedire sovrascritture concorrenti.

Ogni refresh acquisisce nuovamente la fonte e valuta la decisione contro
l’anchor e l’osservazione corrente. Una vecchia approvazione non è sufficiente
quando il parser corrente rileva dati/applicabilità diversi o manca una richiesta
corrente corrispondente. Anche il preflight proiettato offline applica il vincolo.
Un esito positivo su una fonte non aggira gli altri controlli.

Gli envelope legacy mantengono i byte serializzati: coverage v1/report v2
continuano ad essere prodotti quando non esiste una versione da rivedere.
L’host aggiorna i pin del package, verifica digest e attestazioni e forza una
scansione completa dopo l’upgrade, prima di rigenerare il catalogo.
Una decisione admin deve invalidare immediatamente i cataloghi precedenti:
usare una generazione atomica, letta prima del refresh e conservata nel catalogo.

Il flusso gestisce versioni cambiate di fonti già note nell’anchor. Nuovi atti,
valori o regole economiche continuano attraverso discovery, parser e mapping;
non possono essere trasformati in equivalenza con un consenso generico.
