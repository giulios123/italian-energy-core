# Known gaps

- Gli evaluator fixed e indexed e il Billing Engine sono implementati localmente
  in `v0.4.0`, senza pubblicazione.
- I profili più aggregati della granularità dell'indice sono deliberatamente
  rifiutati; non esiste una ripartizione o stima automatica del consumo.
- Le basi mensili, per-periodo e percentuali restano non supportate dal pricing fixed.
- Il ruleset billing pubblico è limitato al profilo BT domestico residente e al
  periodo 2026-05-01/2026-07-01, con provenance ufficiale; non è un aggiornamento
  automatico ARERA.
- Lo scenario tecnico `private/golden-bill-domestic-bt-resident.json` passa usando
  il documento privato collegato con gli elementi di dettaglio. La copertura è
  limitata a quel profilo, ruleset, periodo e oracle; non è una certificazione
  generale delle bollette domestiche future.
- Nessun importer ARERA, persistenza, API web, cloud, confronto o recommendation
  concreta è incluso.
- La disponibilità del package su PyPI non è stata richiesta né verificata tramite pubblicazione.
