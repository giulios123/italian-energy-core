# Active context

Milestone corrente: chiusura tecnica della Spec 004 Billing / Golden Bill v0.4.

Il ruleset pubblico `arera-domestic-bt-resident-2026-05-06`, il test sintetico
indipendente, il verificatore end-to-end e lo scenario JSON tecnico sanitizzato
sono presenti. La verifica privata non passa ancora: la bolletta sorgente locale
contiene riepiloghi, ma non gli elementi di dettaglio necessari per riconciliare
ogni chiave normativa entro 0,01 EUR. Nessun importo o aliquota è stato adattato
per forzare il risultato; v0.4.0 resta non pubblicata.

La repository è pubblica su GitHub, il domain core v0.1.0 è verificato e la CI storica è verde su Python 3.12, 3.13 e 3.14. La Release `v0.1.0` è pubblicata; `v0.4.0` è locale e non pubblicata. La working tree contiene anche le milestone 002 e 003 da preservare.
