# Core 0.13.9 — preparazione e verifica locale

Data: 2026-11-04. Spec 021 e ADR 0017 D30.

La discovery considera la decorrenza tariffaria quando cade nella finestra,
preservando l'osservazione anticipata degli atti appena pubblicati e il rilevamento
delle rimozioni nelle finestre sovrapposte. Pubblicazione e decorrenza rimangono
distinte. I record tariffari senza decorrenza restano bloccanti.

Due policy esatte classificano il decreto sul gasolio `26A05715` e il relativo
aggiornamento TUA Normattiva del 2026-10-27, senza escludere atti simili con
identità, date, URL o collegamenti diversi. Lo scope delle fonti e tutti i gate
di integrità rimangono obbligatori; nessun valore tariffario è modificato.

## Verifica

- Regressioni eseguite prima della correzione: 5 fallimenti attesi.
- Suite completa: **989 passati**, branch coverage **95,04%**.
- Ruff check/format, mypy, lock offline e golden privati: superati.
- Wheel/sdist costruite; import della wheel verificato in un ambiente isolato.
- Contratto e schema pubblici invariati; fixture esistenti aggiornate per
  dichiarare esplicitamente la decorrenza dei record tariffari sintetici.

## Fonte live e limiti

La prova con un repository nuovo in memoria completa tutti e cinque i canali,
non genera review residue e rimuove il falso cambio fonte ARERA. Un controllo
IVA resta però bloccante: la pagina Normattiva Tabella A fissata al 2026-10-08
ha un hash osservato diverso da quello dell'anchor incluso nella wheel.
Questo esito è distinto dal difetto corretto: non viene aggirato né convertito
in certezza. La nuova versione non certifica automaticamente quel documento.

Il percorso Platform persistente, che conserva un anchor Q4 acquisito e
verificato successivamente, deve essere provato con la wheel pubblicata e
documentato separatamente. Pubblicazione, adozione e deploy sono milestone distinte.
