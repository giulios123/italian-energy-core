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
- Quando implementare la Spec 011 e rinnovare l'anchor ARERA verificato in modo
  che copra la `quote_date` operativa?
- Quale fonte forward verificata e quale processo di controllo userà il caller
  per fornire gli scenari base/stress della Spec 011?
- Quando potrà essere pianificato l'allineamento della Platform al manifest e
  agli envelope `italian-energy/contract/v1`?
