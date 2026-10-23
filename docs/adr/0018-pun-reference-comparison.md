# ADR 0018 — Ultimo PUN mensile completo per la stima comparativa

## Stato

Accettata per la Spec 016; implementata e verificata localmente il 2026-10-20.

## Contesto

Il confronto prospettico Core richiede una serie mensile futura. Il catalogo
normalizza gli indici PUN supportati con granularità `MONTH`, e l'evaluator
indicizzato applica a ogni consumo mensile l'osservazione dello stesso mese.
La proiezione stagionale dell'ultimo anno storico non soddisfa la richiesta di
usare un riferimento PUN osservato recente per confrontare offerte fisse e
indicizzate. Un PUN giornaliero, se non dichiarato dalla granularità tariffaria,
non è intercambiabile con un PUN mensile.

## Decisione

Per il confronto mensile, il Core seleziona l'ultimo mese completo della finestra
GME verificata e lo mantiene costante nei dodici mesi stimati. Le sensitività
basso e alto restano ±20% del riferimento. L'evaluator tariffario Core continua
a interpretare formula e spread dell'offerta; la Platform riceve valore, periodo
e metodo per spiegare che il risultato è una stima e che il PUN può variare in
entrambe le direzioni.

## Conseguenze

- Le offerte PUN sono confrontabili in costo annuo con quelle fisse sullo stesso
  profilo di consumo, senza approssimare la formula commerciale nella Platform.
- La data e il valore di riferimento rendono l'ipotesi leggibile e auditabile.
- Il risultato annuale non costituisce una previsione del prezzo mensile futuro.
- L'intera finestra di dodici mesi continua a essere verificata per freschezza,
  continuità e provenienza, anche se la base usa solo l'ultima osservazione.
- Indici non PUN o granularità non supportate non diventano confrontabili per
  effetto di questa decisione.
- Un futuro supporto a offerte dichiarate giornaliere richiede un contratto,
  fonte e proiezione espliciti; non è implicato da questa ADR.
- Verifica locale: 903 test Core, branch coverage 95,02%, Ruff check/format,
  mypy e `git diff --check` passano. Nessuna pubblicazione o deployment.
