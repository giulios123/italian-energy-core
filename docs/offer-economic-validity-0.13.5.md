# Core 0.13.5 — adesione e durata economica

Data della preparazione: 2026-10-18. Base sorgente: `b4de15a` (0.13.4).
Integrato anche il successore documentale `e8ac2bf`, senza modifiche al codice
di base e senza perdere le evidenze della pubblicazione 0.13.4.
Questa milestone prepara una versione futura: non pubblica package, tag,
commit o deployment e non adotta automaticamente il nuovo Core in Platform.

## Scritto

Spec 008 addendum v0.8.4, Spec 013 e ADR 0012/0016 separano:

- **Adesione:** `DATA_INIZIO <= as_of <= DATA_FINE`, inclusa la scadenza.
- **Attivazione simulata:** primo giorno dell'orizzonte annuale, attualmente
  il primo giorno del mese successivo al mese di `as_of`.
- **Durata economica:** mesi dal campo diretto `DettaglioOfferta/DURATA`;
  `-1` significa indeterminata. I periodi dei singoli prezzi sono distinti.

Le fonti primarie sono le [Specifiche SII Mercato Retail v5.0](https://siiportale.acquirenteunico.it/processi/trasversali/mercato-retail),
p. 53 per DURATA e pp. 59/64 per periodi e sottoscrizione, e le
[Regole Portale v4.2](https://www.ilportaleofferte.it/portaleOfferte/resources/cms/documents/6bc502553cb0ea45958840b2de20078d.pdf),
pp. 25–26 per prezzi predefiniti e periodi strutturati.

## Implementato

Il parser v6 conserva i percorsi strutturali e la loro provenienza. Il
percorso prospettico passa attivazione e periodo economico al normalizzatore;
non tronca le quote a DATA_FINE né fa partire i dodici mesi dal giorno della
ricerca. Snapshot precedenti restano leggibili ma richiedono refresh per la
nuova semantica. I risultati storici non vengono ricalcolati.

`NormalizedPortalOffer.economic_terms` espone data, periodo, durata nota,
ambito, base e provenance. La capability è `portal_offer_economic_validity`.
Un prezzo predefinito annualizzabile con durata indeterminata permette una
stima senza promettere una durata finita. Una durata dichiarata inferiore
all'anno, prezzi mancanti o un cambio non rappresentabile restano esclusi.

Gli sconti già modellati mantengono l'effettiva finestra applicabile; i nodi
XML `Sconto` non ancora supportati sono conservati e bloccati esplicitamente,
anziché essere omessi dal totale. Il supporto completo dei loro codici resta
fuori da questa versione.

La Platform copia quattro campi pubblici senza acquisire fonti o calcolare
economia. Il badge oltre dodici mesi distingue condizioni del venditore e
solo prezzo/formula energia. Per indexed rimane “Prezzo variabile”.

## Verificato

La suite completa passa con **895 test** e copertura con branch **95,00%**.
Ruff check/format, mypy `src tests` e `uv lock --check --offline` passano.
Wheel e sdist locali sono costruiti; uno smoke isolato verifica versione
`0.13.5`, parser v6, mapping v2 e nuova capability, senza adottare il package
nel runtime Platform.
Le prove sintetiche controllano importi attesi indipendenti:
3.600 kWh × 0,20 EUR/kWh + quota annua 84 = 804 EUR commerciali; passando a
quota 120, l'aumento all-in è 39,60 EUR (36 + IVA 10%) e il ranking segue
l'importo corretto. Il caso con quota 120 vale 840 EUR commerciali anche
quando l'adesione scade il giorno prima dell'attivazione simulata.

Il replay del catalogo ufficiale prova parsing e selezione dopo hydration.
Non è una nuova attestazione della regolazione futura, un confronto completo
live con GME/anchor o un collaudo HTTP del worker Platform con il wheel 0.13.5.

Il [riepilogo pubblico del replay](evidence/offer-economic-validity-2026-10-18.json)
conserva profilo sintetico, snapshot, URL e digest dei file del 18 ottobre.
Su **4.550 record**, per Roma/non residente e modalità attivazione/pagamento
01/01, il criterio corretto seleziona **257 candidate annuali**, contro le
otto del filtro precedente. **57** espongono condizioni oltre dodici mesi.
Le esclusioni restano motivate: 2.117 per classificazione, 1.735 per
attivazione, 205 per pagamento, 116 per componenti commerciali non supportate
(inclusi `Sconto`), 53 per tariffa non rappresentabile, 51 per territorio,
10 duplicati e sei casi residui. Una sola offerta ha durata dichiarata
insufficiente; non è stata annualizzata artificialmente.

Platform: **270 test Python non integration**, copertura **90,68%**,
**26 test web** e build passano. Lint e typecheck del delta, architettura e
OpenAPI passano. I controlli statici dell'intero checkout Platform trovano
ancora errori nel lavoro locale estraneo a questo delta: non sono un gate
passato. Nessun nuovo test PostgreSQL/HTTP/browser è stato eseguito.

## Passaggi per il rilascio successivo

Pubblicare solo dopo l'autorizzazione del rilascio. L'adozione Platform deve
verificare l'artefatto pubblicato, aggiornare il pin con digest, ricostruire i
runtime e acquisire un nuovo catalogo v6. Serve poi il collaudo HTTP del
worker e della persistenza. La sola lettura di vecchi risultati non cambia
prezzi, profilo o graduatoria e non può beneficiare del nuovo calcolo.
