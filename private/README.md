# Materiale privato

Questa directory è riservata a documenti locali non committati, come bollette reali o snapshot con dati personali. Usare soltanto fixture sintetiche o legalmente anonimizzate in `tests/fixtures/`.

Prima della verifica golden, creare una rappresentazione JSON sanitizzata in
`private/golden-bill-domestic-bt-resident.json`. Il JSON deve contenere soltanto
input tecnici, condizioni dell'offerta, misure e voci osservate necessarie al
calcolo; non deve contenere nome, indirizzo, POD, codice fiscale, numeri cliente,
coordinate bancarie, QR code o URL personali.

Un PDF sorgente non sanitizzato può restare qui per la sola consultazione locale,
ma non è mai una fixture pubblica né un input da aggiungere allo staging Git.
Se il PDF rimanda a una pagina privata di elementi di dettaglio, conservarne
soltanto il digest nel JSON sanitizzato e lasciare il documento fuori dal
repository.
