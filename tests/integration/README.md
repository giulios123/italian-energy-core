# Integration tests

La Spec 010 mantiene le fixture Core→Platform sintetiche nei test contrattuali
`tests/unit/test_integration.py`: manifest, richieste storiche, risultati,
recommendation ed envelope JSON sono validati senza dipendenze dalla repository
Platform. Le fixture usano soltanto dati tecnici sintetici; documenti, bollette,
offerte e identificativi reali restano in `private/`.
