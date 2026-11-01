# Spec 016 — Riferimento PUN per il confronto fisso/indicizzato

**Stato:** scritta, implementata e verificata localmente il 2026-10-20
**Data:** 2026-10-20

### Addendum 0.13.8 — pubblicazione GME a cavallo del mese

Per la data del confronto `as_of`, il mese civile immediatamente precedente è
il mese atteso. L'acquisizione tenta prima il PDF GME e usa l'archivio annuale
soltanto dopo HTTP 404, secondo le regole di Spec 013 e ADR 0016. Se il mese
atteso non è ancora pubblicato integralmente, Core può selezionare la finestra
alternativa dei dodici mesi consecutivi che termina un mese prima, purché tutte
le dodici osservazioni siano complete, `VERIFIED` e abbiano provenance GME
ufficiale valida. Il ritardo massimo è un solo mese civile concluso.

Un archivio ufficiale che documenta soltanto una coda incompleta del mese
atteso costituisce prova di pubblicazione in corso solo se i dati partono dal
primo giorno, hanno quarti d'ora consecutivi senza lacune e terminano alla fine
di un giorno civile completo (`Europe/Rome`). La coda è prova di disponibilità,
non un'osservazione: non viene mediata, serializzata come prezzo del mese o
marcata `VERIFIED`. Un PDF presente ma non validabile blocca l'acquisizione;
non si usa l'archivio per nasconderne l'errore. Rete, HTTP diversi da 404,
corruzione, layout, copertura con lacune, digest e provenance invalidi restano
errori bloccanti.

Al successivo aggiornamento si ripetono i tentativi delle pubblicazioni
ufficiali; il mese atteso sostituisce automaticamente il riferimento precedente
appena è verificato. Un ritardo superiore a un mese, o l'indisponibilità della
finestra alternativa interamente verificata, fallisce chiuso con motivo
esplicito. Nessun valore giornaliero, prezzo sintetico o cache non
riverificata colma una lacuna. La data del confronto e i dodici mesi di
consumo restano ancorati ad `as_of`; la finestra GME può terminare un mese
prima.

La selezione tipizzata lega data del confronto, ultimo mese atteso, mese di
riferimento effettivo, periodo storico dei dodici mesi, valore `Decimal`,
provenance del riferimento, ritardo di pubblicazione e prova ufficiale della
pubblicazione incompleta. Risultato e digest includono selezione e prove. Il
preflight valida gli input congelati e `compare()` non acquisisce fonti.
Envelope nuovi usano gli schema ID versionati previsti dall'addendum 0.13.8;
quelli già persistiti restano leggibili senza migrazione o ricalcolo.

## Problema

La comparativa prospettica applica oggi ai mesi futuri la sequenza storica PUN
per mese di calendario. L'utente vuole confrontare offerte a prezzo fisso e
indicizzato sullo stesso profilo di consumo, rendendo esplicita l'ipotesi
necessaria per stimare il prezzo indicizzato. Il catalogo attualmente normalizza
le offerte PUN con granularità mensile; non è corretto usare un'osservazione
giornaliera come se fosse un indice mensile.

## Risultato

Per ogni confronto prospettico che usa PUN mensile, il Core applica a ciascun
mese del periodo stimato l'ultimo valore PUN mensile completo e verificato
precedente all'avvio del confronto. L'indice resta associato alla fascia e alla
formula tariffaria normalizzate. Il motore indicizzato Core applica l'eventuale
spread o altro termine fisso dichiarato nell'offerta. I tre scenari usano il
valore di riferimento moltiplicato per 0,80, 1,00 e 1,20; il costo dell'offerta
fissa resta invariato rispetto agli scenari PUN.

Il risultato espone codice indice, mese di riferimento, valore originale
EUR/kWh e metodo di proiezione. La Platform può mostrare queste informazioni e
un avviso esplicito: è una stima basata sull'ultimo PUN osservato, non una
previsione o garanzia; il PUN futuro può salire o scendere. La provenienza del
valore resta verificabile tramite il rapporto GME mensile incluso negli input
congelati. Non si acquisiscono fonti durante il confronto.

## Vincoli

- La granularità del PUN segue la dichiarazione dell'offerta. Per le offerte
  attualmente normalizzate a `MONTH` si usa l'ultimo mese completo; un valore
  giornaliero non viene convertito o presentato come PUN mensile.
- Si conserva la verifica dell'intera finestra storica di dodici mesi e la sua
  provenance, anche se il valore applicato alla stima è l'ultimo mese completo.
- Non si ricostruiscono formule, delta, componenti, imposte o totali fuori dai
  motori di pricing e billing Core.
- I valori PUN basso e alto sono sensitività dichiarate ±20%, non prezzi futuri
  verificati. Il prezzo fisso non cambia tra questi scenari.
- Una sola pubblicazione mensile ancora incompleta ammette la finestra
  alternativa sopra definita; oltre un mese, o senza dodici mesi alternativi
  verificati, il confronto fallisce chiuso.
- Nessuna migrazione database, acquisizione live durante `compare`, pubblicazione
  o deployment è inclusa.

## Criteri di accettazione

| ID | Criterio | Verifica |
| --- | --- | --- |
| AC-016-01 | La proiezione mensile usa lo stesso ultimo PUN completo verificato in tutti i dodici mesi futuri. | Test unitari su valori storici distinti e intervalli futuri |
| AC-016-02 | Scenari basso/base/alto applicano esattamente 0,80/1,00/1,20 al riferimento; prezzi fissi non variano. | Test dei tre scenari |
| AC-016-03 | Il Core applica lo spread dichiarato dalla tariffa indicizzata sul PUN di riferimento attraverso la formula tariffaria esistente. | Test pricing integrato con PUN + spread |
| AC-016-04 | Le assunzioni espongono indice, periodo, valore e metodo e restano incluse nel digest del risultato. | Test contratto, validazione e digest |
| AC-016-05 | I dodici mesi selezionati sono completi, distinti, consecutivi, mensili e ufficialmente verificati; un solo mese atteso incompleto può ammettere la finestra alternativa con prova. | Regressioni su coverage, selezione e validazione |
| AC-016-06 | La documentazione qualifica i risultati come stime sensibili a variazioni PUN al rialzo o al ribasso. | Test stringhe/warning del contratto e verifica Platform |
| AC-016-07 | Il risultato identifica data, mese atteso e usato, finestra GME, valore, provenance e ritardo; selezione e prova appartengono al digest. | Round-trip, digest e validatori |
| AC-016-08 | Errori di rete/HTTP non-404, PDF invalido, archivio corrotto o con lacune, digest/provenance invalidi non attivano il mese alternativo. | Regressioni fail-closed |
| AC-016-09 | Al successivo refresh il mese nuovo completo diventa riferimento; al secondo mese di ritardo l'acquisizione fallisce esplicitamente. | Test novembre/dicembre e passaggio d'anno |

## Stato di avanzamento

- **Scritto:** il 2026-10-20 in risposta alla richiesta di confronto diretto tra
  prezzo fisso e variabile, con PUN dell'ultimo periodo concluso e spread
  dichiarato applicato dal Core.
- **Implementato:** `project_market_data` usa l'ultimo PUN mensile completo
  verificato per tutti i dodici mesi stimati. Il Core applica gli scenari di
  sensitività e la formula tariffaria originale, compreso lo spread dichiarato;
  il risultato espone metodo, periodo e valore di riferimento. I periodi sono
  costruiti nel fuso civile Europe/Rome anche dopo il round-trip JSON.
- **Verificato:** 903 test passati, branch coverage 95,02%; Ruff check e format,
  mypy su `src tests` e `git diff --check` passano. L'E2E economico Platform
  resta subordinato al gate live catalogo/regolazione; nessuna release Core è
  stata pubblicata.

- **Addendum 0.13.8:** la specifica estende il fallback alla sola incompletezza
  della pubblicazione del mese atteso, con un massimo di un mese di ritardo e
  dodici mesi alternativi integri e verificati. È un addendum normativo; test,
  implementazione e gate locali sono registrati nella milestone di rilascio.
