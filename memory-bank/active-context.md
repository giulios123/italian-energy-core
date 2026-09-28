# Active context

Release Core `v0.12.0` del 2026-09-28: Spec 013, importer GME, anchor
ARERA/fiscale, envelope e CLI di verifica sono inclusi nel package. La release
GitHub allega wheel, sdist e checksum; PyPI viene pubblicato dal workflow OIDC.
La Platform non è stata modificata e il suo vincolo `<0.12.0` richiede
allineamento prima di consumare questa versione. Nessun envelope cliente è
stato fornito per il confronto personalizzato.

Milestone completata localmente (2026-09-27): Spec 013 `Confronto beta
domestico con scenari storici`, ADR 0016 e capability additiva in Core. Il
metodo congelato è: 12 mesi civili recenti e consecutivi, proiezione sul
medesimo mese dell'anno, indici 0,80/1,00/1,20 e recommendation solo sul base;
i valori futuri sono stime. La precedente proposta forward/robust è ora Spec
012 differita; Spec 011 resta il Current Domestic Advisor rilasciato. La
working tree contiene anche le modifiche catalog CLI preesistenti: preservate.

Aggiornamento 2026-09-27: autorizzato e implementato un comando operativo
`italian_energy.integration.catalog_cli` per l'acquisizione esatta del catalogo
reale con diagnostica delle fonti/indici. Il catalogo live 2026-09-27 è VERIFIED:
4.478 record, 156 punti indice, snapshot
`d425ff802cf6233ff1e86711718e91848b6d4664f1ddd129446376324e351d86`.
I due indici arrivano a giugno 2026; il workbook ARERA live conserva il digest
congelato e la copertura termina il 2026-09-01. La Platform ha persistito i
cinque file (20.992.193 bytes), verificato i digest in lettura e riporta il
catalogo disponibile. Questo non chiude la copertura economica prospettica.
L'utente ha scelto per la beta scenari sullo storico: base, -20%, +20%; Entra
External ID è rimandata alla versione finale. Il contratto prospettico forward
è stato rinumerato Spec 012 e resta differito; Spec 013 governa la beta storica.
Nessun cambio di versione o pubblicazione.

Baseline pubblicata: Spec 011 Current Domestic Advisor v0.11.1. Il preflight
tipizzato `CurrentDomesticEnergyService.preflight` resta compatibile; la Spec
013 è stata poi rilasciata in v0.12.0. L'accettazione staging della Platform
resta separata.
Il digest ARERA 2026 VERIFIED congelato per il replay storico è
`b43ac3fa4b96335634785e26ac68d27191e2a6a770ea8ebf51bdf88fce1d5f7b` e copre
2026-01-01/2026-09-01; il nuovo anchor prospettico di settembre è separato.

Verifica finale Spec 013: 311 test passano con 95,22% di branch coverage; Ruff
check/format, mypy, `git diff --check`, entrambi i golden privati e smoke extra
`gme`/`arera` sono verdi. La verifica live `projection_cli --date 2026-09-27
--verify-sources` è `verified`: catalogo 4.478 offerte, storico PUN completo
settembre 2025–agosto 2026, report GME F1/F2/F3 verificati separatamente per
luglio/agosto 2026 e anchor ARERA/fiscale completo, valido 2026-09-01/2026-10-01.
L'anchor include le versioni Normattiva di Tabella A e art. 16 fissate al
2026-09-27; tutte le otto fonti hanno digest corrispondenti. I valori dei mesi
futuri restano stime sotto l'ipotesi di congelamento dell'anchor. Non è stato
fornito un envelope con consumi e contratto di un cliente, quindi la verifica
live non ha eseguito una comparazione personalizzata. La Platform non è stata
modificata.

Sono presenti composer deterministico, ruleset JSON residente/non residente,
matrice di copertura e loader indipendente dall'extra XLSX. Il checkpoint
non residente usa il PDF privato `private/nonresident.pdf`, che contiene già
riepilogo, letture mensili, dettaglio fiscale e Box dell'offerta; non è richiesto
un nome file specifico. Il JSON sanitizzato e il mapping privato sono presenti.

Il ruleset pubblico `arera-domestic-bt-resident-2026-05-06`, i test sintetici
indipendenti, il verificatore end-to-end e i due scenari JSON tecnici
sanitizzati sono presenti. Il golden residente e quello non residente passano
con bill stabile, chiavi abbinate e differenze entro 0,01 EUR. Nessun importo o
aliquota è stato adattato per forzare il risultato. La Spec 005 aggiunge un importer per il workbook elettrico
domestico ARERA 2026: il raw snapshot è content-addressed e conservato in
memoria, il parsing offline resta `UNVERIFIED`, mentre il fetch ufficiale può
produrre valori `VERIFIED` soltanto con layout e controlli completi. Il risultato
è un bundle source-faithful, non un `RegulatoryRuleSet` fatturabile.

La repository è pubblica su GitHub e la CI della release `v0.4.0` è verde su
Python 3.12, 3.13 e 3.14. Le release GitHub `v0.1.0` e `v0.4.0` sono pubblicate;
la working tree contiene la milestone 005 locale da preservare.

Il Comparison Engine opera su offerte già normalizzate e prequalificate, usa il
totale Billing all-in, consulta obbligatoriamente la matrice e isola candidate
non calcolabili con esclusioni motivate. Le partite esterne sono restituite come
evidenza ma escluse da Bill e ranking. La Spec 008 fornisce ora l'adapter
allowlisted che porta i cataloghi commerciali elettrici domestici BT alla 007;
non promette che ogni formula commerciale sorgente sia calcolabile.

La Spec 008 Portale Offerte Importer v0.8.0 è implementata localmente senza
commit/tag/push/release: `ComparisonContext`/`PortalComparisonRequest`, snapshot
content-addressed, acquisizione HTTPS allowlisted, parser XML/CSV, indici storici,
normalizzazione fixed/indexed e orchestrazione verso la 007 sono presenti. La
validità relativa usa mesi calendario con clamp e i corrispettivi annuali usano
1/12 per i mesi completi e giorni/365 per le frazioni. Ogni record termina come
offerta idonea o esclusione motivata; duplicati nello stesso catalogo escludono
tutte le occorrenze. Gas, PDF/OCR, persistenza, scheduler e UI restano fuori
perimetro; lo smoke live Portale è separato dalla suite offline.
Lo smoke live esplicito del 2026-09-08 ha acquisito 4.472 record e 156 punti
indice, producendo snapshot VERIFIED
`portal-snapshot:67577e044c0b257e3b11cbf1ce3f346218c6e932279e9845098b35ea2bb0d23d`.

La Spec 009 aggiunge RecommendationPreferences tipizzate, evidenze candidate
verificate, `DeterministicRecommendationEngine` e `PortalRecommendationAdapter`.
La decisione usa filtri hard e il minor totale comparabile; la soglia minima in
EUR è inclusiva e, se assente, il risultato resta `stay_current` per compatibilità
legacy. Nessun costo viene ricalcolato e nessun testo commerciale viene
interpretato.

La Spec 010 espone `italian_energy.integration` come contratto stabile: manifest
con capability/schema ID ordinati (anche tramite `CORE_SCHEMA_IDS`), richieste tipizzate per replay storico e
recommendation separata, envelope JSON canonici fail-closed e
`CoreContractError` con codici stabili. La façade seleziona ruleset e matrice
packaged per residente/non residente, richiede elettricità domestica BT e usa
rounding EUR/percentuali a due decimali HALF_UP. `defusedxml` è nella dipendenza
base; `openpyxl` resta nell'extra ARERA. L'allineamento della Platform e la
pubblicazione v0.10.0 restano milestone successive.

La CI della milestone locale include ora `openpyxl` anche nel gruppo `dev`,
perché la suite ARERA costruisce workbook XLSX sintetici. La dipendenza resta
comunque opzionale nel pacchetto distribuito: la wheel base non richiede
`openpyxl`, mentre l'extra `arera` continua ad abilitarlo per gli utenti.

La Spec 011 v0.11.0 è stata preparata come milestone documentale separata dal
replay storico: definisce dodici mesi da `activation_date`, catalogo alla
`quote_date`, profilo di consumo futuro fornito dal caller, schedule della
baseline e scenari `base`/`stress` con curve forward tracciate. La regolazione
e le imposte vengono congelate dai valori verificati attivi alla quotazione, ma
la loro applicazione futura resta una proiezione non `VERIFIED`; senza anchor
verificato il confronto fallisce chiuso. La recommendation può emettere
`switch` soltanto quando la stessa candidata supera la soglia in tutti gli
scenari. Sono stati aggiunti la spec e ADR 0015; questa milestone non ha
modificato codice, test, versione, Platform o pubblicazione. La working tree
contiene però modifiche concorrenti al percorso `Current Domestic Advisor`,
che devono essere preservate e consolidate separatamente.

Nel lavoro Platform del 2026-09-12 il percorso corrente è stato implementato
localmente: contratti `CurrentDomesticEnergyService`, scenari low/base/high,
capability/schema ID v1 e soglia percentuale sono ora presenti e coperti. La
suite è stata riallineata ai rami del current advisor (232 test, 95,29% branch
coverage); la release v0.11.0 include gli artefatti wheel/sdist installabili.
Il workflow `.github/workflows/release.yml` prepara e pubblica wheel/sdist su
PyPI tramite Trusted Publishing OIDC nell'environment GitHub `pypi`; il dispatch
manuale ha pubblicato il tag già esistente `v0.11.0` su PyPI.
