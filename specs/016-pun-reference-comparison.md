# Spec 016 — Riferimento PUN per il confronto fisso/indicizzato

**Stato:** scritta, implementata e verificata localmente il 2026-10-20
**Data:** 2026-10-20

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
- La mancanza dell'ultimo mese completo, la granularità non supportata o la
  provenance invalida mantengono il comportamento fail-closed esistente.
- Nessuna migrazione database, acquisizione live durante `compare`, pubblicazione
  o deployment è inclusa.

## Criteri di accettazione

| ID | Criterio | Verifica |
| --- | --- | --- |
| AC-016-01 | La proiezione mensile usa lo stesso ultimo PUN completo verificato in tutti i dodici mesi futuri. | Test unitari su valori storici distinti e intervalli futuri |
| AC-016-02 | Scenari basso/base/alto applicano esattamente 0,80/1,00/1,20 al riferimento; prezzi fissi non variano. | Test dei tre scenari |
| AC-016-03 | Il Core applica lo spread dichiarato dalla tariffa indicizzata sul PUN di riferimento attraverso la formula tariffaria esistente. | Test pricing integrato con PUN + spread |
| AC-016-04 | Le assunzioni espongono indice, periodo, valore e metodo e restano incluse nel digest del risultato. | Test contratto, validazione e digest |
| AC-016-05 | Dati storici incompleti, duplicati, non consecutivi o con granularità non mensile falliscono chiuso. | Regressioni su coverage e validazione |
| AC-016-06 | La documentazione qualifica i risultati come stime sensibili a variazioni PUN al rialzo o al ribasso. | Test stringhe/warning del contratto e verifica Platform |

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
