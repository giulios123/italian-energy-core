# Spec 019 — Riuso della provenance nel confronto

Data: 2026-10-25. Stato: scritta, implementata e verificata localmente.

## Obiettivo

Ridurre la latenza del confronto domestico da 950 offerte verso 50–60 secondi
senza modificare formule, precisione, risultati, identificativi o controlli.
La gestione delle fonti ripete serializzazioni identiche e ricerche lineari
fra modelli immutabili durante il pricing e billing dei dodici mesi/scenari.

## Requisiti normativi

1. La deduplicazione del pricing/billing mantiene l'uguaglianza dei modelli
   Provenance, l'ordine di prima apparizione e il primo oggetto equivalente.
   Non sostituire questa uguaglianza con quella del JSON: datetime equivalenti
   con offset diversi sono uguali come modelli ma serializzati diversamente.
2. L'aggregazione proiettata mantiene invece esattamente la chiave JSON
   canonica preesistente, inclusi escape Unicode, ordinamento e primo oggetto.
3. Il JSON canonico di ogni istanza immutabile può essere riutilizzato soltanto
   durante una singola compare(). Il cache conserva il riferimento per evitare
   collisioni dovute al riciclo degli ID. Nessuna cache globale di risultati.
4. Confronti concorrenti e annidati hanno scope separati. La chiusura normale
   e le eccezioni ripristinano il contesto precedente; fuori dallo scope non
   si conserva alcuna serializzazione. Preflight, normalizzazione e tutti i
   controlli rimangono attivi.
5. Nessun cambio di schema, capability, metadati economici o provenance.
   Tutti gli scenari rimangono calcolati; non si limita il numero di offerte.
6. Accettazione: suite Core con coverage branch >=95%, Ruff, format e mypy;
   replay dello stesso confronto congelato con piena uguaglianza del risultato
   pubblico, digest risultato/output e coerenza componenti/totale delle bollette.
   Registrare tempi complessivi e fasi; distinguere esperimento, adozione locale,
   pubblicazione del pacchetto e deployment. Nessuna riscrittura dello storico.

## Frammenti degli input per gli identificativi

Il JSON canonico usato per gli ID pricing/billing può riusare, per identità
immutabile e campo/tipo della richiesta, i frammenti di contratto, consumi,
mercato, classificazione, ruleset e rounding. Le chiavi JSON restano ordinate,
con separatori ed encoding identici a json.dumps(sort_keys=True,
separators=(',', ':'), ensure_ascii=False). La prima serializzazione usa il
serializer del campo della richiesta, senza ricostruire i modelli a mano.

Il solo pricing_result usa un posto riutilizzabile che conserva l'ultimo
oggetto per tipo/campo, verificandone l'identità; consente il riuso fra bill_id
e billing_id senza trattenere tutte le serializzazioni mensili. Campi esclusi
(es. observed_bill) rimangono esclusi anche quando lo scope è già popolato.
Gli altri campi sono serializzati ogni volta. Non si riusano importi calcolati
fra scenari, non si inventano equivalenze per ID o hash commerciale.

Le uguaglianze delle provenance immutabili possono essere rappresentate da
identità numeriche locali allo scope, assegnate usando l'uguaglianza originale
del modello. Oggetti equivalenti condividono solo la chiave: ogni merge
restituisce il primo oggetto del proprio input, anche dopo il riscaldamento
del cache. I riferimenti conservati impediscono il riciclo degli ID.

## Accettazione locale — 25 ottobre 2026

939 test passati, coverage con rami 95,12%; Ruff check/format, mypy e
diff check passano sul checkout adottato. Il replay Platform da 950 offerte
conserva intera vista pubblica e digest risultato/output dello storico;
951 bollette base senza scarti componenti/totale. Le sole valutazioni
lineari osservate scendono da 197.064 a 144. Le cache sono limitate al
confronto e non riusano IVA, accise a soglia, prezzi o totali indicizzati.

L'adozione locale usa mount in sola lettura delle sorgenti Core/Platform;
la metadata installata resta 0.13.6. Nessuna nuova wheel, release, commit,
push o distribuzione esterna. Misure, script, manifest SHA-256 e limiti
del timer nel repository Platform, docs/comparison-performance-2026-10-25/.
