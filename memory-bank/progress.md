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
- Spec 005, ADR 0009 e importer ARERA domestico 2026 implementati localmente:
  raw snapshot immutabili, fetch allowlisted, parser XLSX sicuro, Decimal da
  token OOXML, bundle source-faithful e diagnostiche fail-closed.
- Spec 006 Billing Coverage Expansion v0.6.0 implementata localmente: composer
  deterministico per i due segmenti BT domestici, fiscalità ufficiale versionata,
  proratazione TIT mensile, locator di provenance, ruleset/matrice JSON e loader
  senza dipendenza XLSX.
- Spec 007 Comparison Engine v0.7.0 implementata localmente: confronto all-in,
  `as_of` esplicito, matrice obbligatoria, ranking stabile, esclusioni candidate
  motivate e partite esterne visibili ma escluse.
- Spec 008 Portale Offerte Importer e integrazione frontend specificata come
  milestone locale v0.8.0 implementata: download open-data ufficiale allowlisted,
  snapshot/provenance, parser XML/CSV, indici storici, normalizzazione elettrica
  domestica BT, validità relativa/corrispettivi annuali e orchestrazione verso la
  007 con ledger completo delle esclusioni.
- Documentazione riallineata allo stato reale delle release: `v0.4.0` è una
  release GitHub pubblicata, il golden residente storico è riconciliato e
  `v0.6.0` resta locale e non pubblicata.
- Spec 009 Recommendation Engine v0.9.0 implementata localmente: policy hard,
  evidenze verificate, shortlist/decisione `switch` o `stay_current`, ID
  content-addressed e adapter dal risultato Portale 008.
- Spec 010 Contratto d'integrazione Core–Platform v0.10.0 implementata
  localmente: manifest/capability, façade storica domestica BT, envelope JSON
  versionati e `CoreContractError` con codici stabili; nessuna modifica alla
  repository Platform.
- Corretto il setup CI/dev della suite ARERA: `openpyxl` è dichiarato nel
  gruppo `dev` oltre che nell'extra opzionale `arera`, senza aggiungerlo alle
  dipendenze della wheel base.
- Preparata la Spec 011 v0.11.0 e ADR 0015 per il confronto prospettico:
  orizzonte da attivazione, input futuri tracciati, scenari base/stress,
  congelamento regolatorio esplicito e recommendation robusta; milestone
  documentale senza codice o bump di versione.

## Verificato

- Il baseline della v0.4.0 aveva 91 test; la milestone 006 aggiunge test per
  composer, proratazione, matrice, artefatti e due profili sintetici.
- La suite corrente conta 138 test con branch coverage package 95,36% e
  `fail-under=95`.
- Ruff check/format, mypy strict e pre-commit passano localmente.
- Wheel, sdist, smoke install base/extra e smoke live del workbook ufficiale 2026
  passano localmente.
- `git diff --check` è pulito.
- La verifica privata passa per entrambi i golden reali: il percorso completo
  produce Bill stabili e riconcilia tutte le chiavi entro 0,01 EUR per voce e
  totale; la matrice espone il bimestre non residente come `golden_reconciled`.
- Il parser ARERA ha
  fixture sintetiche per residenti/non residenti, fiducia, layout, sicurezza
  ZIP, precisione e failure mode.
- La suite corrente conta 152 test con branch coverage package 95,56%; i test
  Comparison coprono fixed/indexed, baseline globale, esclusioni, percentuali,
  stabilità degli ID, matrice e partite esterne.
- La suite corrente conta 179 test con branch coverage package 95,11%; i test
  Portal coprono acquisizione allowlisted, schema drift, digest, BOM/encoding,
  validità relativa, applicabilità, duplicati, multi-indice e confronto end-to-end.
- Smoke live Portale eseguito separatamente con data esplicita `2026-09-08`:
  snapshot VERIFIED, 4.472 record e 156 punti indice; digest snapshot
  `67577e044c0b257e3b11cbf1ce3f346218c6e932279e9845098b35ea2bb0d23d`.
- La suite corrente conta 188 test; i 9 test Recommendation coprono soglie,
  rischio, durata, sconti, compatibilità legacy, invarianti d'ordine e adapter
  Portale.
- La suite corrente conta 218 test e branch coverage package 95,36%; i test
  d'integrazione coprono manifest, nove aggregati JSON, errori fail-closed,
  selezione degli artefatti residente/non residente, orizzonte storico e
  recommendation senza ricalcolo.
- Wheel e sdist `0.10.0` costruite; metadata, `__version__`, manifest e
  `CORE_SCHEMA_IDS` coincidono. Smoke in ambienti puliti: base con Portale e
  import ARERA lazy senza `openpyxl`, extra `arera` con importer XLSX.
- Dopo la correzione CI, `uv sync --locked --dev` installa `openpyxl==3.1.5`;
  la suite completa passa su Python 3.12.13 e 3.13.12 con 218 test e branch
  coverage 95,36%. Ruff check/format, mypy strict e `git diff --check` passano;
  Python 3.14 resta affidato alla matrice GitHub perché non è installato
  localmente.
- Smoke live separati verificati: ARERA snapshot
  `b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b`;
  Portale dataset `2026-09-08`, 4.472 record, 156 punti indice, snapshot
  `67577e044c0b257e3b11cbf1ce3f346218c6e932279e9845098b35ea2bb0d23d`.

## Da completare

- Nessuna azione tecnica residua nella Spec 005; commit, tag, push e release
  restano esclusi e richiedono autorizzazione separata.
- Commit, tag, push e release della v0.6.0 restano esclusi e richiedono
  autorizzazione separata.
- Commit, tag, push e release della v0.7.0 restano esclusi e richiedono
  autorizzazione separata.
- Commit, tag, push e release della v0.8.0 restano esclusi e richiedono
  autorizzazione separata; lo smoke live del Portale non blocca la suite offline.
- Commit, tag, push e release della v0.9.0 restano esclusi e richiedono
  autorizzazione separata.
- Commit, tag, push e release della v0.10.0 restano esclusi e richiedono
  autorizzazione separata; l'allineamento della Platform è fuori milestone.
- L'implementazione della Spec 011, il rinnovo dell'anchor ARERA alla
  `quote_date`, i nuovi envelope/capability e l'allineamento della Platform
  restano milestone successive con autorizzazione separata.
