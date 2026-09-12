# Spec 009 — Recommendation Engine v0.9

## Stato

Specifica normativa v0.9.0. L'implementazione locale è autorizzata dal
milestone corrente; commit, tag, push, release e pubblicazione restano operazioni
separate.

## Contesto e obiettivo

Le Spec 007 e 008 producono un confronto deterministico di offerte elettriche
domestiche BT. Manca il quarto confine del core: interpretare quel risultato in
base a preferenze strutturate senza ricalcolare, correggere o mutare gli
importi economici.

La v0.9 produce una decisione `switch` o `stay_current`, una shortlist
deterministica e un ledger di esclusioni. La raccomandazione è consultiva: non
è una garanzia di convenienza futura e non sostituisce Pricing, Billing o
Comparison.

## Perimetro

Incluso:

- preferenza sul tipo di tariffa (`any`, `fixed`, `indexed`);
- tolleranza al rischio di indicizzazione (`low`, `medium`, `high`);
- durata contrattuale minima;
- politica sugli sconti strutturati (`any`, `require`, `avoid`);
- soglia minima di risparmio in EUR sullo stesso scenario e periodo del
  confronto;
- evidenza candidata verificata e con provenance;
- adapter da `PortalComparisonResult` alle evidenze del Recommendation Engine.

Escluso:

- scoring pesato, ranking qualitativo o preferenze interpretate da testo libero;
- forecast di prezzo, stime di volatilità future o ottimizzazione multi-periodo;
- AI/LLM, marketing, qualità del venditore, persistenza, API web e UI;
- nuove formule economiche, modifiche al `ComparisonResult` o ricalcolo di
  Pricing/Billing.

## Modelli e compatibilità

I modelli restano Pydantic v2 frozen, serializzabili e basati su `Decimal`.
`RecommendationPreferences` aggiunge `tariff_preference`,
`temporary_discount_policy` e `minimum_savings`; `volatility_tolerance` diventa
un enum opzionale e `minimum_contract_months` resta invariato.

I campi pubblicati `fixed_preference` e `require_temporary_discounts` restano
accettati per compatibilità. Il primo valore `True` equivale a `fixed`, il
secondo `True` equivale a `require`; i valori `False`/`None` non aggiungono
vincoli. Contraddizioni fra forma legacy e nuova sono errori globali.

`RecommendationCandidateEvidence` contiene `offer_id`, tipo tariffa, rischio
(`fixed`, `indexed_capped`, `indexed_uncapped`), durata in mesi, profilo sconto
(`none`, `permanent`, `temporary`, `unknown`), stato di verifica e provenance.

`RecommendationRequest` conserva il payload legacy senza evidenze. Le evidenze
duplicate o riferite a ID non presenti nelle alternative sono errori globali.
L'evidenza necessaria per una preferenza mancante o non verificata esclude solo
la candidata interessata.

`Recommendation` conserva i campi legacy e aggiunge decisione, shortlist,
esclusioni e codici di motivazione. Il motore concreto è
`DeterministicRecommendationEngine`; l'interfaccia `RecommendationEngine`
resta un protocollo.

## Semantica deterministica

Il motore richiede `current_comparable_total`, `current_billing` e per ogni
alternativa `comparable_total`, `billing` e `savings`. Le valute devono
coincidere e `savings` deve essere coerente con il confronto; nessun importo
viene ricalcolato come output.

I filtri vengono applicati in ordine stabile:

1. evidenza verificata quando richiesta dalla policy;
2. tipo tariffa;
3. tolleranza al rischio: `low` solo fixed, `medium` fixed o indexed con cap
   sull'intera formula di ogni fascia, `high` ogni rischio supportato;
4. durata minima;
5. politica sugli sconti;
6. `savings >= minimum_savings`.

La soglia è inclusiva. Se `minimum_savings` è assente, la compatibilità legacy
consente la valutazione ma non autorizza automaticamente lo switch. La
shortlist mantiene l'ordine economico della Spec 007; la prima candidata
ammissibile viene selezionata. In assenza di candidate ammissibili la decisione
è `stay_current`.

Le esclusioni usano codici stabili per evidenza mancante/non verificata, tipo o
rischio incompatibile, durata sconosciuta/insufficiente, sconto sconosciuto/
incompatibile e soglia non raggiunta. I testi sono deterministici e non
contengono dati personali.

`recommendation_id` è uno SHA-256 del confronto, della policy normalizzata e
delle evidenze ordinate per `offer_id`; non dipende dall'ordine di input.

## Adapter Portale

`PortalRecommendationAdapter` riceve un `PortalComparisonResult` verificato e
costruisce le evidenze delle sole alternative presenti nel confronto. Deriva
durata dal record strutturato, tipo dal tariff canonical e rischio capped solo
quando ogni formula di fascia ha un cap esterno effettivo. Classifica gli
sconti dalle `ChargeRule` applicate; non interpreta `conditions` testuali e non
inventa dati mancanti.

L'adapter non invoca nuovamente Pricing, Billing o Comparison e non crea una
dipendenza inversa del modulo `recommendation` dal Portale.

## Acceptance criteria e test

- Modelli immutabili, round-trip JSON, enum, Decimal e rifiuto dei float.
- Compatibilità legacy, conflitti fra forme vecchie e nuove e ID canonici.
- Test di fixed/indexed, tre tolleranze, durata, sconti, soglia esatta/sotto
  soglia, risparmio nullo/negativo, ranking vuoto e mantenimento del corrente.
- Esclusioni isolate per evidenza mancante/non verificata e errori globali per
  confronto incompleto, duplicati o policy impossibili.
- Invarianza rispetto all'ordine di alternative/evidenze e immutabilità del
  `ComparisonResult`.
- Test dell'adapter per provenance, durata, cap conservativo e assenza di
  interpretazione del testo libero.
- Ruff, format check, mypy strict, pytest con branch coverage almeno 95%,
  pre-commit, build, verificatori esistenti e `git diff --check` passano.

## Fuori perimetro operativo

Nessun commit, tag, push, release GitHub o pubblicazione PyPI è autorizzato da
questa specifica.
