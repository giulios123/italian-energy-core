# Core 0.13.12 — revisione amministrativa degli atti

Spec 023 e ADR 0017 D33. La capability generica evita una release per ogni
atto che l’admin attesta non incidere sui dati economici in uso. Nuove formule,
nuovi mapping, fonti mancanti e variazioni economiche restano nei controlli Core.

Richieste e decisioni canoniche, coverage v3 e report v4 conservano versione,
provenance, periodo e consenso esplicito. I permalink Normattiva ELI fissano
la data consolidata. Gli artefatti storici restano immutabili.

La verifica della milestone ha superato 1.048 test con coverage 95,08%, Ruff,
format e mypy. La preparazione alla pubblicazione ripete i gate sul lockfile
allineato agli aggiornamenti remoti delle dipendenze. I risultati di CI e
Trusted Publishing saranno registrati dopo la rispettiva conclusione.

Non è stata approvata alcuna fonte live. Adozione e deployment della Platform
restano distinti dalla pubblicazione della libreria.

## Gate sul lockfile aggiornato

21 novembre: `uv sync --locked --dev` e controllo lock offline passati;
1.048 test / 95,08%, Ruff/format e mypy passati, due golden privati superati.
Wheel e sdist costruite; import isolato della wheel conferma 0.13.12 e
`regulatory_act_review`. Il codice resta in attesa della CI e della pubblicazione
remota, che non sono dedotte dal solo build locale.
