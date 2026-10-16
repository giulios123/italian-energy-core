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

### Decisione temporanea — 2026-10-16

Su richiesta dell'utente, il valore esatto `TIPO_OFFERTA=04` del catalogo
Mercato Libero viene escluso economicamente senza interrompere il resto
dell'importazione. Il parser v2 conserva il record come `unsupported`,
con raw fields e provenance, senza interpretarne i prezzi. Il normalizzatore
produce `unsupported_offer_type`, codice `04` e locator nel dettaglio e
contabilizza il record tra ricevuti ed esclusi.

Questa decisione non assegna un significato economico generale al codice
`04`, non lo converte in fixed/indexed e non accetta altri tipi sconosciuti.
Identificativi e date obbligatori, namespace e controlli d'integrità restano
vincolanti. Il supporto economico del tipo `04` richiederà una decisione
successiva basata sul mapping ufficiale.

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
