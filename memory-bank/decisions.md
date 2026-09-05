# Decisions

- Pydantic v2 frozen è il formato canonico dei modelli.
- Decimal è obbligatorio per valori economici.
- I periodi sono semiaperti; gli intervalli di mercato sono timezone-aware.
- L’indicizzazione usa un AST tipizzato senza `eval`.
- `SupplyPoint` è il nome canonico al posto di `Supply`.
- Pricing, Billing, Comparison e Recommendation sono confini distinti.
- La v0.1 modella ma non calcola prezzi o bollette.
