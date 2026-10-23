# Spec 018 — Riuso delle valutazioni fisse fra scenari

Data: 2026-10-23. Stato: scritta, implementata e verificata localmente.

## Obiettivo e confini

Nel confronto della Spec 013, i tre scenari variano soltanto gli indici.
Il pricing delle tariffe `fixed` non riceve dati di mercato e il billing
usa gli stessi consumi, classificazione, regole, periodi e arrotondamenti.
Ripetere il loro calcolo mensile tre volte produce lo stesso risultato.

Il Core può riutilizzare un risultato fisso già calcolato con successo
durante la stessa chiamata `compare()`, per contratto corrente e alternative.
La cache è locale alla chiamata; non è globale, persistita o condivisa fra
confronti. La chiave è l'intero contratto immutabile, compresi tariffa,
fornitura, validità, condizioni e provenance, non il solo identificativo.

## Requisiti e criteri di accettazione

1. Ogni contratto fisso valutato con successo viene calcolato al massimo una
   volta nei tre scenari dello stesso confronto. Riusare sia pricing sia billing.
2. I contratti indicizzati continuano a ricevere il mercato del proprio
   scenario e a essere calcolati separatamente per low/base/high.
3. Differenze, percentuali, ranking, esclusioni e raccomandazione restano
   calcolati per lo scenario corretto. Non riutilizzare un'intera alternativa:
   con baseline indicizzata il risparmio di una tariffa fissa varia per scenario.
4. Non memorizzare eccezioni o risultati incompleti. Gli errori restano nelle
   stesse fasi, con gli stessi codici, dettagli ed esclusioni.
5. Il cache termina con `compare()`. Una chiamata successiva, anche sulla
   stessa istanza, rivaluta consumi, residenza, potenza, tariffe, data e fonti.
   Tutti i preflight e i controlli di validità continuano a essere eseguiti.
6. Il risultato serializzato, gli identificativi e i digest sono identici al
   percorso senza riuso per gli stessi input. Nessuna formula, precisione
   Decimal, imposta, fonte o policy di arrotondamento cambia.

## Verifiche

- Regressioni su conteggio chiamate e identità dei risultati fissi; tariffe
  indicizzate ancora distinte e risparmi dipendenti dalla baseline corrente.
- Controllo dell'intero JSON/envelope contro un'esecuzione senza riuso.
- Chiamate successive con input diversi, contratti con identico ID ma
  contenuto diverso, errori dei candidati e preflight non pronto.
- Suite Core e gate di copertura 95%, Ruff, format e mypy.
- Replay offline sul confronto Platform di 950 offerte con gli stessi
  snapshot/input, confronto dei digest e misura prima/dopo senza riscrivere
  lo storico. Il guadagno atteso dipende dal numero di tariffe fisse.

## Contratto pubblico, privacy e rilascio

Nessun nuovo campo, capability, formato o migrazione. Non cambiano i confini
Core–Platform, la provenance o la persistenza dei confronti. Nessun nuovo
confronto cliente viene creato dal benchmark. Adozione locale della sorgente,
wheel pubblicata e deployment rimangono evidenze separate.

## Accettazione locale del 23 ottobre 2026

Cinque nuove regressioni, 924 test totali e coverage branch 95,08%; Ruff
check/format, mypy e diff check superati sul checkout completo. Il nuovo
helper è interamente coperto. Nei replay del confronto Platform da 950
offerte le valutazioni fisse riuscite nei tre scenari scendono 174 → 58:
116 valutazioni annuali/1.392 mensili evitate, con 2.724 tentativi indicizzati
invariati. Entrambi i digest e il risultato pubblico completo restano uguali
allo storico; le 951 bollette base non hanno discrepanze delle componenti.

Una singola coppia di misure locali osserva 193,315 → 175,433 s; non è una
garanzia di latenza. API/worker locali adottano la sorgente sul mount già
esistente dopo verifica di assenza di confronti attivi. Nessun nuovo job,
commit/push, wheel pubblicata o deployment esterno. Evidenze nel repository
Platform: `docs/fixed-scenario-reuse-2026-10-23/verification.md`.
