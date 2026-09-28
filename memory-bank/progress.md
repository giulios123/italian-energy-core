# Progress

## Completato

- Release Core `v0.12.0` del 2026-09-28: Spec 013 beta storica, importer GME,
  anchor regolatoria/fiscale, servizio e envelope prospettici inclusi. GitHub
  Release con wheel/sdist/`SHA256SUMS`; PyPI pubblicato tramite Trusted
  Publishing OIDC. La Platform non è stata modificata.
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
- Release Core `v0.11.1` completata: preflight tipizzato specificato, testato e
  pubblicato; 235 test passano con 95,16% branch coverage e tutti i gate locali
  sono verdi. Tag e release GitHub pubblicati, wheel/sdist/`SHA256SUMS` allegati,
  Trusted Publishing OIDC riuscito, hash PyPI riconciliati e installazione
  isolata verificata. L'accettazione staging Platform resta separata.
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
- Verifica locale 2026-09-13: aggiunti test per acquisizione catalogo, scenari
  low/base/high, validazioni fail-closed, copertura billing e recommendation;
  232 test Core passano con 95,29% di branch coverage. Ruff check/format, mypy
  strict e `git diff --check` passano; nessun valore regolatorio è stato
  inventato.
- Preparato il workflow dedicato `.github/workflows/release.yml` per Trusted
  Publishing su PyPI: build wheel/sdist, smoke import, artifact condiviso e
  publish OIDC nell'environment GitHub `pypi`, con dispatch manuale per `v0.11.0`.
- Workflow `Publish to PyPI` eseguito con successo per `v0.11.0`: wheel e sdist
  sono presenti su PyPI; API metadata 200 e smoke import isolato da PyPI
  restituisce `italian_energy.__version__ == 0.11.0`.

## Catalogo reale — 2026-09-27

- Comando di acquisizione esatta con riepilogo JSON e errori Core espliciti,
  specificato nell'addendum operativo della Spec 008.
- Live Portale: 4.478 record, 156 punti indice, cinque file ufficiali; PUN e PE
  coprono gennaio 2020–giugno 2026. Persistenza nella Platform verificata tramite
  rilettura dei cinque file e validazione dei digest.
- Live ARERA: VERIFIED, stesso digest congelato, periodo 2026-01-01/2026-09-01.
- Scelta utente: beta con scenari storici base/-20%/+20%; acquisizione del
  catalogo e copertura economica restano verifiche separate.
- Verifica finale: 240 test passano, branch coverage 95,21%; Ruff check,
  format-check, mypy src/tests e git diff --check passano. Il nuovo comando è
  stato eseguito anche sul catalogo live 2026-09-27. Nessun commit, cambio di
  versione o pubblicazione.

## Specifica beta storica — 2026-09-27

- Risolto il doppio uso di 011: il Current Domestic Advisor rilasciato resta
  Spec 011; proposta forward e robusta rinumerata Spec 012 e differita.
- Aggiunte Spec 013 e ADR 0016 con confronto dei 12 mesi recenti e consecutivi,
  ripetizione sullo stesso mese, indici x0,80/x1,00/x1,20, anchor ARERA/fiscale
  puntuale e recommendation solo base.
- Il lavoro comprende importer GME e fonti regolatorie/fiscali correnti,
  output stimato additivo, CLI live, test dedicati e gate Core; è incluso nella
  release Core `v0.12.0`.
- Verifica live ufficiale: `projection_cli --date 2026-09-27 --verify-sources`
  ha restituito `verified`. Catalogo Portale: 4.478 offerte e 156 punti indice;
  snapshot `portal-snapshot:d425ff802cf6233ff1e86711718e91848b6d4664f1ddd129446376324e351d86`.
- GME: PUN Index GME mensile MGP Baseload, unità EUR/MWh convertita con
  `Decimal` in EUR/kWh, esattamente settembre 2025–agosto 2026; dodici mesi
  consecutivi senza buchi o duplicati. Prezzi medi GME per fascia di luglio e
  agosto 2026 acquisiti e verificati come serie distinta, senza auto-mapping
  alle offerte.
- Anchor: fonti 575/2025, 588/2025 e 227/2026 ARERA, ADM 18 settembre 2026,
  TUA D.Lgs. 43/2025 e decreto 26A01335, DPR 633/1972 Tabella A e art. 16
  Normattiva fissati al 27 settembre 2026. Otto digest live corrispondono;
  validità dell'anchor 2026-09-01/2026-10-01, usata in futuro solo come
  assunzione. L'aliquota IVA domestica del 10% è supportata separatamente da
  Tabella A n. 103 e art. 16.
- Verifica sintetica e gate: 311 test passano, branch coverage 95,22%, Ruff
  check/format, mypy e `git diff --check` verdi. Entrambi i golden privati e
  smoke dipendenze opzionali (`openpyxl` 3.1.5, `pypdf` 6.19.0) passano.
- La CLI live ha verificato le fonti, non una bolletta personale: nessun
  `ProjectedDomesticComparisonRequest` con dati utente è stato fornito. La
  Platform non è stata modificata.
