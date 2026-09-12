# Project brief

`italian-energy-core` è una libreria Python open source, domain-first e deterministica per modellare, simulare e confrontare offerte di energia elettrica in Italia.

La release GitHub `v0.4.0` implementa domain core, pricing fixed/indexed e un
Billing Engine data-driven. La `v0.10.0` locale aggiunge importer ARERA,
composer, ruleset domestici BT JSON verificati, Comparison Engine, Portale
Offerte importer, Recommendation Engine e il contratto d'integrazione
Core–Platform, ma non è ancora committata o pubblicata.

I golden privati BT domestici residente e non residente sono riconciliati,
ciascuno soltanto per il proprio ruleset e periodo. La Spec 006 aggiunge il profilo
domestico non residente e una matrice esplicita dei livelli di copertura; la
Spec 007 confronta offerte normalizzate con totale all-in e matrice di copertura
obbligatoria; Spec 008 importa i cataloghi elettrici domestici BT ufficiali con
esclusioni auditabili, senza equivalere a copertura generale delle bollette o a
calcolabilità automatica di ogni formula commerciale.
