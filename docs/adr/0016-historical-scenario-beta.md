# ADR 0016 — Confronto beta su scenari storici

## Stato

Accettato per la Spec 013. La recommendation della beta è autorizzata sul
solo scenario base.

## Decisione

La beta confronta i prossimi dodici mesi completi con i dodici mesi storici
più recenti e consecutivi, ripetendo ogni mese sul medesimo mese futuro
dell’anno. I tre scenari cambiano il solo indice energetico applicando 0,80,
1,00 e 1,20. Consumo, spread, prezzi fissi, quote, regolazione e policy
fiscale rimangono uguali, salvo il ricalcolo delle imposte sulle basi
imponibili risultanti.

Gli indici derivano da dataset ufficiali con mapping e provenance. Il mapping
esplicita definizione, unità, granularità e fascia; PUN, PE, picco/fuori-picco
e prezzi F1/F2/F3 non sono equivalenti. Una finestra incompleta o arretrata non
è sostituita in silenzio.

L’anchor regolatorio e fiscale conserva `as_of` come data del suo snapshot
verificato e `validity` come intervallo di applicabilità half-open. Un confronto
in un’altra data interna a tale intervallo richiede un’evidenza separata che
lega l’anchor immutato alla data richiesta, verifica tutti i digest versionati
e documenta la revisione degli atti successivi applicabili. Hash corrispondenti
non provano da soli l’assenza di nuovi provvedimenti. Un digest modificato, una
revisione assente/incompleta o un nuovo atto applicabile bloccano l’uso; per
recepire l’atto serve un nuovo anchor verificato.

Acquisizione e verifica delle fonti sono operazioni esplicite separate dal
preflight e dal confronto deterministici, che consumano snapshot ed evidenza
persistibili senza rete. Il package immutabile dell’anchor non richiede un
refresh giornaliero: può essere riutilizzato entro la validità dopo una
conferma di copertura riferita alla data del confronto. I risultati mantengono
la data originale dell’anchor distinta dalla data del confronto. Applicare
l’anchor ai dodici mesi futuri è un’assunzione esplicita, mai `VERIFIED`. Il
billing storico conserva i propri controlli e non riceve ruleset con periodi
alterati per apparire verificato.

L’API Core `refresh_regulatory_anchor` e la CLI `--refresh-anchor` scaricano e
verificano tutti i documenti dell’anchor corrente e producono un envelope con
esito e digest, senza richiedere un nuovo download del package. La revisione
datata degli atti successivi resta un input esplicito: un atto applicabile o
incerto blocca l’uso, e il Core non ne deduce l’irrilevanza da hash o parole
chiave. Generare un anchor per un periodo ulteriore richiede nuovi parser e
mapping versionati. Acquisizione e discovery restano fuori dal percorso offline
di calcolo.

Si aggiungono un servizio e schema ID/capability d’integrazione; i contratti
correnti restano compatibili. La recommendation riusa policy e soglie esistenti
sullo scenario base senza rivalutare i costi. Il percorso forward della
proposta Spec 012 rimane differito.

## Conseguenze

- L’output è una stima condizionata alle assunzioni esposte.
- Un indice essenziale, un’ancora o una regola fiscale non provati rendono il
  preflight non pronto.
- Un mapping commerciale assente esclude l’offerta interessata; non viene
  trasformato in un sinonimo di un altro indice.
- La Platform potrà consumare il nuovo contratto in una milestone distinta;
  persistenza e interfaccia restano fuori dalla Core.
