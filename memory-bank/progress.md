# Progress

## Completato

- Struttura repository, packaging e CI definiti.
- Spec 001 e ADR iniziali scritti.
- Domain core, test unitari e property-based implementati localmente.
- Spec 002, `FixedPricingEngine` e test fixed implementati localmente.
- Spec 003, `IndexedPricingEngine` e test di validazione implementati localmente.
- Spec 004, `RegulatoryBillingEngine`, modelli ruleset, riconciliazione e fixture
  sintetiche implementati localmente.
- Ruleset pubblico domestico BT residente per il periodo 2026-05-01/2026-07-01,
  con provenance ufficiale, fixture di test sintetica e scenario tecnico privato
  sanitizzato preparati.
- `scripts/verify_private_golden.py` esegue il percorso completo
  `PricingRequest → FixedPricingEngine → RegulatoryBillingEngine` e verifica
  stabilità di `bill_id`, chiavi, provenance e riconciliazione.

## Verificato

- 91 test passano con branch coverage package attesa sopra il 95% (fail-under 95%).
- Ruff check/format, mypy strict e pre-commit passano localmente.
- Wheel, sdist e smoke install della `v0.4.0` passano localmente.
- `git diff --check` è pulito.
- La verifica privata è eseguibile ma fallisce correttamente sulle chiavi non
  riconciliate: il documento disponibile è un riepilogo e non fornisce gli
  elementi di dettaglio necessari. Nessuna copertura normativa domestica viene
  dichiarata.

## Da completare

- Ottenere dal fornitore gli elementi di dettaglio della stessa bolletta/offerta,
  sanitizzarli e rieseguire il golden senza inventare partite mancanti.
- Nessun commit, tag, push o GitHub Release di `v0.4.0` è incluso senza
  autorizzazione separata.
