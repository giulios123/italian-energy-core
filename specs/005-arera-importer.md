# Spec 005 — ARERA Importer v0.5

## Contesto

Il core v0.4 usa ruleset regolatori normalizzati e versionati, ma non conserva
il documento sorgente né importa automaticamente i valori ARERA. Il workbook
ufficiale per i corrispettivi elettrici domestici è aggiornato nello stesso URL
e contiene fogli mensili con segmenti per abitazioni di residenza anagrafica e
abitazioni diverse da residenza.

La specifica introduce un confine di acquisizione e normalizzazione. Non
trasforma automaticamente i dati in una bolletta completa: accisa, IVA,
proratazione, inclusione del CDISPD nel prezzo commerciale e composizione di un
`RegulatoryRuleSet` restano decisioni successive.

## Obiettivo

Acquisire e conservare un raw snapshot immutabile del workbook ARERA 2026,
validarne struttura e contenuti senza usare `float` per valori economici e
produrre un bundle normalizzato, auditabile e riproducibile per entrambi i
segmenti domestici.

## Requisiti MUST

- L'URL ufficiale supportato è soltanto
  `https://www.arera.it/fileadmin/area_operatori/prezzi_e_tariffe/Corrispettivi_libero_elettrico_domestico_2026.xlsx`.
- Il fetch deve verificare HTTPS, host finale allowlisted, status HTTP, MIME,
  dimensione massima, archivio ZIP valido, assenza di macro, formule, external
  links e path duplicati o insicuri.
- Il parser deve essere disponibile come `parse_bytes` offline e non può
  attribuire `VERIFIED` a bytes forniti dal chiamante.
- `fetch_and_import(year=2026)` può attribuire `VERIFIED` soltanto dopo
  acquisizione ufficiale e validazione completa del layout noto.
- Un `RawAreraSnapshot` conserva bytes, SHA-256, URL, timestamp timezone-aware,
  MIME e header disponibili; non scrive automaticamente file.
- Il workbook deve contenere fogli mensili contigui, intestazioni note, entrambi
  i segmenti e le quote energia/fissa/potenza. Mesi duplicati, gap, componenti
  sconosciute, formule o totali incoerenti producono `REVIEW_REQUIRED` senza
  bundle verificato parziale.
- Ogni valore economico viene estratto dal token numerico OOXML come `Decimal` e
  quantizzato secondo il formato numerico dichiarato dalla cella. Celle `-` e
  celle numeriche a zero restano distinguibili.
- Il bundle conserva componenti atomiche (`CDISPD`, `sigma1`, `sigma2`, `sigma3`,
  `UC3`, `UC6`, `ASOS`, `ARIM`) e totali dichiarati, con ruolo distinto e
  localizzazione foglio/cella. Nessun componente viene selezionato per il
  Billing Engine.
- `bundle_id` e `snapshot_id` sono derivati dal digest del raw; l'ordine dei
  fogli e il timestamp di acquisizione non alterano l'identità dei dati.
- Il package base resta importabile senza l'extra ARERA. Il parser XLSX è
  disponibile tramite `italian-energy[arera]` con `openpyxl`; `defusedxml` è una
  dipendenza base del package.

## Modelli e API

L'API pubblica risiede in `italian_energy.arera`:

- `AreraDomesticElectricityImporter.fetch_and_import(year=2026,
  timeout_seconds=30)`;
- `AreraDomesticElectricityImporter.parse_bytes(content, retrieved_at,
  source_url=None)`;
- `RawAreraSnapshot`, `AreraImportResult`, `AreraRegulatoryBundle`,
  `AreraChargeValue`, `AreraSourceLocator` e diagnostiche strutturate;
- `AreraImportError`, `AreraFetchError` e `UnsupportedAreraDatasetError`.

`AreraRegulatoryBundle` non è un `RegulatoryRuleSet`, non contiene proratazioni
o imposte e non è accettato dal `BillingEngine`.

## Stati e failure mode

- `VERIFIED`: snapshot ottenuto dal fetch ufficiale e layout/valori verificati.
- `UNVERIFIED`: parsing offline valido, ma provenienza non autenticata dal
  fetcher.
- `REVIEW_REQUIRED`: raw conservato con diagnostiche, ma schema o controlli
  semantici non sufficienti per produrre un bundle.
- Errori di trasporto o input non leggibile producono eccezioni tipizzate prima
  del risultato normalizzato.

## Acceptance criteria

- Un fixture XLSX sintetico equivalente produce i due segmenti, mesi, quote,
  componenti atomiche e totali attesi con `Decimal` e provenance per cella.
- Il fetch simulato restituisce `VERIFIED`; `parse_bytes` restituisce
  `UNVERIFIED`; schema drift e dati incoerenti restituiscono
  `REVIEW_REQUIRED` senza bundle verificato.
- Sono coperti digest, immutabilità, JSON dei modelli, MIME, redirect/host,
  timeout, ZIP ostile, formule, macro, external links, gap/duplicati e Unicode.
- Pricing, Billing, golden privato e import del package base restano invariati.
- Ruff, format check, mypy strict, pytest con branch coverage almeno 95%,
  pre-commit, build/smoke install ed `git diff --check` passano.

## Fuori perimetro

- Anni diversi dal workbook 2026, altri settori o classi non domestiche.
- Download periodico, cache persistente, database, API web, PDF/OCR.
- Accisa, IVA, proratazione, selezione CDISPD e assemblaggio in un ruleset
  completo o direttamente fatturabile.
