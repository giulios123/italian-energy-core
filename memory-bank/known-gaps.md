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
- La proposta differita `specs/012-prospective-comparison.md` non è implementata:
  schedule della baseline, curve forward e recommendation robusta restano una
  milestone futura da numerare separatamente.
- La Spec 013 è inclusa nella release Core `v0.12.0`; la verifica live del
  2026-09-27 ha completato i 12 mesi PUN e l'anchor ARERA/fiscale di settembre.
  Il confronto live con consumi e contratto di un cliente resta da eseguire con un envelope
  `ProjectedDomesticComparisonRequest`; non è stato fornito input utente.
- La copertura di mapping live è PUN mensile; i report GME F1/F2/F3 sono distinti
  e non vengono associati automaticamente a codici d'offerta. Indici non
  supportati escludono la singola offerta con motivo; dati mancanti della
  baseline bloccano il confronto. Il CSV indici del Portale arriva a giugno 2026
  e non sostituisce la serie GME richiesta per settembre 2025–agosto 2026.
- La validità dell'ancora regolatoria/fiscale resta quella verificata al mese di
  `as_of`; applicarla da ottobre 2026 in poi è un'assunzione esplicita, non una
  verifica normativa futura. Aggiornare data e fonti prima di confronti con un
  diverso `as_of`.
- La proposta forward della Spec 012 richiede curve base/stress e consumo
  futuro forniti dal caller; la beta Spec 013 non produce forecast.
- Il contratto JSON v1 è fail-closed e non migra payload automaticamente; una
  modifica incompatibile richiederà un nuovo schema ID o una nuova versione.
- L'adapter della repository Platform verso la capability prospettica non è
  ancora implementato. Il vincolo attuale `italian-energy>=0.11.1,<0.12.0`
  esclude `v0.12.0` e dovrà essere aggiornato nella milestone Platform.
