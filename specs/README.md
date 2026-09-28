# Specifiche

Le specifiche sono il contratto normativo del progetto. Una funzionalità rilevante segue sempre:

`spec → test → implementazione → verifica → Memory Bank`.

## Stato roadmap

| Spec | Titolo | Stato |
| --- | --- | --- |
| 001 | Domain Core v0.1 | Implementata in `v0.1.0` |
| 002 | Fixed Pricing | Implementata; inclusa nella release GitHub `v0.4.0` |
| 003 | Indexed Pricing | Implementata; inclusa nella release GitHub `v0.4.0` |
| 004 | Billing / Golden Bill | Implementata, golden privata verificata e release GitHub `v0.4.0` pubblicata |
| 005 | ARERA Importer | Implementata localmente in `v0.5.0` (non pubblicata) |
| 006 | Billing Coverage Expansion | Implementata localmente in `v0.6.0`; artefatti ARERA 2026 congelati, golden residente e non residente verificati |
| 007 | Comparison Engine | Implementata localmente in `v0.7.0`; confronto all-in di offerte normalizzate, senza importer Portale Offerte |
| 008 | Portale Offerte Importer e integrazione frontend | Implementata localmente in `v0.8.0`; snapshot open-data, normalizzazione elettrica domestica BT e orchestrazione verso Comparison Engine 007 verificate |
| 009 | Recommendation Engine | Implementata localmente in `v0.9.0`; preferenze strutturate, shortlist deterministica e adapter dal Portale Offerte |
| 010 | Contratto d'integrazione Core–Platform | Implementata localmente in `v0.10.0`; manifest, façade storica, envelope JSON e errori stabili |
| 011 | Current Domestic Advisor | Rilasciata in `v0.11.1`; scenari deterministici, snapshot verificati, preflight tipizzato ed envelope correnti |
| 012 | Confronto prospettico con forward e recommendation robusta | Differita; solo documentale, non implementata |
| 013 | Confronto beta con scenari storici | Rilasciata in `v0.12.0`; fonti live e gate Core verificati |

Le spec pianificate non autorizzano ancora codice produttivo. I dettagli diventano vincolanti soltanto quando la spec viene scritta e accettata.

L'ordine numerico identifica le specifiche. La 006 amplia la copertura di
billing necessaria ai confronti; la 007 conserva i vincoli di confronto all-in,
offerte correnti, esclusioni motivate e matrice obbligatoria. La 008 aggiunge
l'acquisizione esatta dei cataloghi Mercato Libero/PLACET, gli indici storici e
il ledger completo delle esclusioni prima del ranking.
La 009 interpreta il confronto già calcolato con vincoli hard ed evidenza
verificata; non ricalcola costi e non introduce scoring o AI.
La 010 congela il primo contratto pubblico consumabile dalla Platform senza
modificare la logica economica: il percorso Portale resta un replay storico
con periodo concluso e la recommendation opera sul risultato già ottenuto.
La 011 aggiunge il percorso corrente a scenari, mantenendo separata la
proiezione deterministica dalle previsioni e fallendo chiuso in assenza di
copertura regolatoria futura verificata.

La 012 conserva come progetto differito il percorso basato su schedule e
scenari forward forniti dal caller. La 013 definisce invece la beta basata sui
dodici mesi storici, con assunzioni stagionali e regolatorie esplicite; non
modifica gli envelope storici né il replay concluso.

La Spec 013 aggiunge una capability e schemi prospettici tipizzati senza
modificare gli envelope storici rilasciati. Acquisizione live GME, anchor
ARERA/fiscale e test locali sono verificati; il confronto con dati di un cliente
richiede un envelope request esplicito e non è certificato dal solo riepilogo
delle fonti. La capability è inclusa nel package `v0.12.0`.
