# ADR 0015 — Confronto prospettico e recommendation robusta

## Stato

Accettato come decisione normativa per la Spec 011 v0.11.0. L'implementazione
resta una milestone successiva.

## Decisione

Il Core introduce un percorso prospettico separato dal replay storico v0.10.
L'orizzonte canonico è il primo anno civile a partire da `activation_date`,
con catalogo Portale riferito a `quote_date`.

Consumo futuro, schedule della baseline e curve forward sono input tipizzati
del caller, con provenance e assunzioni esplicite. È obbligatorio uno scenario
`base` e almeno uno `stress`; il Core non genera previsioni, non acquisisce
provider forward e non usa l'annual estimate del Portale come calcolo.

Le componenti regolatorie e fiscali sono congelate dai valori verificati attivi
alla `quote_date`. L'anchor deve essere verificato per il profilo richiesto,
ma la sua applicazione oltre il periodo osservato resta una proiezione assunta
e non diventa `VERIFIED`. In assenza di anchor il confronto fallisce chiuso.

La recommendation prospettica può emettere `switch` soltanto per una candidata
calcolabile in tutti gli scenari e con risparmio almeno pari alla soglia
inclusiva in tutti gli scenari. La shortlist segue il costo della base. Una
durata economica assente è assunta a dodici mesi per fixed e indexed, con
warning e provenance; una durata esplicita inferiore a dodici mesi esclude la
candidata.

La superficie `italian_energy.integration` e il contratto JSON v1 vengono
estesi additivamente con nuovi aggregati, schema ID e capability prospettiche.
Le API storiche, la Recommendation 009 e la repository Platform non vengono
modificate semanticamente.

## Conseguenze

- Il risultato prospettico è un insieme di stime scenario-specifiche, non una
  certificazione della bolletta futura.
- Le assunzioni rimangono auditabili e non vengono confuse con dati verificati.
- Il confronto può funzionare anche con una baseline assunta, ma la decisione
  deve superare la soglia in ogni scenario dichiarato.
- L'aggiornamento periodico dell'anchor ARERA resta un prerequisito operativo;
  non è sostituito da fallback automatici.
- Gas, nuovi provider forward, persistenza, UI, Platform e pubblicazione
  richiederanno decisioni separate.
