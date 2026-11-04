# Adozione Platform — Core 0.13.9

Core 0.13.9 corregge la selezione temporale della discovery tariffaria e aggiunge
due classificazioni normative esatte per il decreto sul gasolio del 27 ottobre.
Contratto e schema pubblici rimangono quelli di 0.13.8; non servono ricalcoli o
migrazioni dei confronti storici.

La Platform deve adottare la wheel pubblicata verificandone SHA-256 e attestazione,
ricostruire l'immagine e aggiornare runtime API/worker e job. Eseguire prima il
refresh normativo, poi il catalogo. L'esito richiesto per l'utilizzo è un catalogo
odierno verificato con `comparisons_enabled=true` e `reason_codes=[]`.

La prova Core su stato nuovo elimina il falso errore ARERA e tutte le review
di classificazione, ma conserva il blocco quando la pagina IVA Normattiva differisce
dall'hash incluso nell'anchor. Un processo concluso o un'immagine avviata non
dimostrano la disponibilità delle fonti. Non aggiornare hash o anchor persistiti
senza una nuova verifica normativa e una procedura esplicita.
