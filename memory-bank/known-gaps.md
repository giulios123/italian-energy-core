# Known gaps

- Gli evaluator fixed e indexed e il Billing Engine sono pubblicati nella
  release GitHub `v0.4.0`; la pubblicazione del package su PyPI non è stata
  richiesta né verificata.
- I profili più aggregati della granularità dell'indice sono deliberatamente
  rifiutati; non esiste una ripartizione o stima automatica del consumo.
- Le basi mensili, per-periodo e percentuali restano non supportate dal pricing fixed.
- I ruleset billing v0.6 coprono i due profili BT domestici e i mesi contigui
  2026-01-01/2026-09-01 dello snapshot congelato; non sono un aggiornamento
  automatico ARERA.
- Gli scenari tecnici `private/golden-bill-domestic-bt-resident.json` e
  `private/golden-bill-domestic-bt-non-resident.json` passano usando i documenti
  privati e la copertura è limitata ai rispettivi profili, ruleset, periodi e
  oracle; non è una certificazione generale delle bollette domestiche future.
- L'importer ARERA 005 resta source-faithful; la composizione v0.6 richiede
  policy fiscali ufficiali versionate e non salva il raw XLSX.
- Il profilo BT domestico non residente è `golden_reconciled` soltanto per il
  periodo 2026-03-01/2026-05-01 del documento privato; tutti gli altri mesi
  restano coperti dal ruleset verificato dello snapshot.
- L'importer Portale Offerte v0.8 supporta solo i formati elettrici ufficiali
  congelati, replay storici con snapshot esatto e formule fixed/indexed
  rappresentabili; gas, altri anni/formati e condizioni commerciali non
  strutturate restano esclusi con evidenza.
- Il Comparison Engine v0.7 confronta soltanto offerte già prequalificate dal
  caller: non valuta eligibility commerciale, condizioni testuali, costi di
  switching o forecast di mercato.
- Il totale comparabile esclude intenzionalmente partite esterne request-wide;
  l'output le conserva come evidenza ma non è una certificazione di ogni voce
  della bolletta osservata.
- Non esistono ancora importer per altri anni/formati, persistenza, API web o
  cloud; la Recommendation v0.9 è concreta ma resta consultiva e locale.
- La Recommendation v0.9 è verificata localmente ma resta consultiva: non
  prevede prezzi futuri, non valuta qualità del venditore e richiede evidenza
  strutturata per i vincoli non economici; la soglia assente non abilita lo
  switch automatico.
- La façade d'integrazione v0.10 supporta replay storici conclusi; il current
  advisor v0.11 aggiunge soltanto scenari deterministici basati sugli ultimi
  dodici mesi e non è un forecast di mercato.
- La specifica documentale `011-prospective-comparison.md` non è implementata:
  schedule della baseline, curve forward e recommendation robusta restano una
  milestone futura da numerare separatamente.
- Un confronto prospettico operativo richiederà un anchor ARERA verificato
  efficace alla `quote_date`; lo snapshot locale attuale termina il 2026-09-01
  e non può essere esteso automaticamente.
- Le curve forward base/stress e il profilo di consumo futuro devono essere
  forniti dal caller con provenance o assunzioni; il Core non produce forecast.
- Il contratto JSON v1 è fail-closed e non migra payload automaticamente; una
  modifica incompatibile richiederà un nuovo schema ID o una nuova versione.
- L'adapter della repository Platform verso `italian-energy>=0.11,<0.12` non è
  ancora implementato per scelta di perimetro della Spec 010.
