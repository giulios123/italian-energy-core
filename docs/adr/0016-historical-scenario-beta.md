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

L’ancora regolatoria e fiscale contiene valori verificati e validi alla data
del confronto. Riutilizzare quei valori in futuro è una proiezione esplicita,
con metadati distinti dalla verifica della fonte. Il billing storico conserva
i propri controlli e non riceve ruleset con periodi alterati per apparire
verificato.

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
