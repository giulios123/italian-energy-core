# Core 0.13.11 — preflight delle fonti approvate

2026-11-05. Commit `966587ffe70c4fe2d44e589c6538bfeab7d6ea7a`,
tag `v0.13.11`. CI main `42117160944` riuscita su Python 3.12–3.14;
Trusted Publishing `42117515098` riuscito.

- [GitHub release](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.11).
- [PyPI](https://pypi.org/project/italian-energy/0.13.11/).
- Wheel SHA-256 `5bcd44780496fe1aadc08dff1c08e592e5ecce6929cb1f6045cba8170fb4603e`.
- Sdist pubblicata SHA-256 `a7da3b2f78625691936ab65ab536751d8063549aeb3da32a2925443c54ac236a`.

La Platform ha verificato wheel PyPI, digest e attestazione contro il repository
Core. La patch corregge il controllo proiettato di completezza che richiedeva
ancora l'hash originale dopo una revisione valida: source preflight risultava
false senza reason code, nonostante la coverage normativa approvata.

La regressione riprodotta prima del fix verifica ora il preflight proiettato
completo positivo e una nuova versione non approvata negativa. 1.027 test,
coverage con rami 95,03%; Ruff, mypy, due golden privati, build e import isolato
passati. Nessuno schema o valore economico modificato.

L'approvazione IVA live è stata registrata dall'admin; questa patch non crea
nuove decisioni. L'adozione dell'immagine e la nuova verifica del catalogo Azure
sono documentate nel repository Platform.
