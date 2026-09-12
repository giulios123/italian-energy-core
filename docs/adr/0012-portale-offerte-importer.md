# ADR 0012 — Portale Offerte open data come catalogo commerciale verificabile

## Stato

Accettata per la Spec 008 v0.8.0.

## Decisione

Il catalogo commerciale viene acquisito esclusivamente dagli open data
ufficiali del Portale Offerte e resta separato dall'importer ARERA e dal
`RegulatoryRuleSet`. Un'esecuzione usa la data esatta `as_of == period.start`,
scarica i cataloghi elettrici Mercato Libero e PLACET e conserva snapshot,
digest, provenance e diagnostiche prima della normalizzazione.

Il parser produce record source-faithful e un ledger completo di esclusioni.
Solo tariffe fixed o indexed esprimibili con i modelli canonici entrano nel
`DeterministicComparisonEngine`; la stima annua del Portale, i forward, le
condizioni testuali non modellate, gli scaglioni e i canoni non sono sostituti
di Pricing o Billing.

I corrispettivi commerciali annui usano il pro-rata mensile a dodicesimi con
frazioni giorni/365. Le offerte indexed richiedono market data verificati e
copertura esatta, senza interpolazione o carry-forward.

## Conseguenze

- Il dominio rimane indipendente da web framework, browser, database, cloud e
  AI; il trasporto HTTP è iniettabile.
- Il catalogo può cambiare quotidianamente senza compromettere il
  determinismo: gli identificativi dipendono da URL, digest, parser e payload
  canonici, non dall'ordine o dall'orario di acquisizione.
- Un cambiamento strutturale della fonte blocca il confronto automatico con
  `REVIEW_REQUIRED`; un singolo record non rappresentabile viene escluso con
  codice stabile e provenance.
- Il supporto a gas, dual fuel, OCR/PDF, persistenza e scheduler richiede ADR e
  specifiche autonome.
