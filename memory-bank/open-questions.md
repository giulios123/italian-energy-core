# Open questions

- Il BillingRequest v0.6 resta compatibile con ruleset custom verificati; il
  ComparisonRequest v0.7 richiede invece la matrice nel proprio resolver.
- Quale estensione futura, separata dalla v0.8, coprirà gas, nuovi formati o
  ulteriori anni del catalogo Portale Offerte?
- Conservare nel materiale privato il digest del documento collegato e rinnovare
  la verifica se il fornitore emette un conguaglio sullo stesso periodo.
- Quale formato di persistenza esterna, se autorizzata in una spec successiva,
  mantenere per gli snapshot ARERA già content-addressed?
- Quale policy successiva, separata dalla v0.9 hard-filter, potrà introdurre
  preferenze pesate o un orizzonte multi-periodo senza confonderle con la
  convenienza all-in deterministica?
- La Spec 013 è rilasciata in Core `v0.12.0`; manca un envelope d'input cliente
  per eseguire il percorso comparativo con dati utente. La verifica live delle
  fonti ufficiali non sostituisce quella prova.
- Quando riattivare la proposta differita Spec 012 e quale fonte forward
  verificata userà il caller per scenari base/stress?
- Quando potrà essere pianificato l'allineamento della Platform al manifest e
  agli envelope `italian-energy/contract/v1`?
