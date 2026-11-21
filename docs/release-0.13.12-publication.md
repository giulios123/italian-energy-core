# Core 0.13.12 — revisione amministrativa degli atti

Pubblicata il 21 novembre 2026. Commit `69c03e8a007f255d4564dc260d1384591834681d`,
tag annotato `v0.13.12`.

- [Release GitHub](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.12).
- [PyPI 0.13.12](https://pypi.org/project/italian-energy/0.13.12/).
- [CI main](https://github.com/giulios123/italian-energy-core/actions/runs/44901961589): riuscita su Python 3.12–3.14.
- [CI tag](https://github.com/giulios123/italian-energy-core/actions/runs/44902101103): riuscita su Python 3.12–3.14.
- [Trusted Publishing](https://github.com/giulios123/italian-energy-core/actions/runs/44902102003): riuscito; wheel/sdist e checksum allegati alla release.
- Wheel SHA-256 `7e80736d3c9b5d141bf9bea9e08f77815d854801f03aa98a8c742b8be1b8db6d`.
- Sdist SHA-256 `8286fd1b923b4fdc391c5b35067c2f6640550c574aea05118136773b580e0585`.

La Platform ha verificato digest e attestazione PyPI contro il repository Core
prima di installare la wheel. Il digest coincide anche con il build locale.
Il runtime isolato conferma versione 0.13.12 e capability `regulatory_act_review`.

Gate locali sul lockfile aggiornato: 1.048 test / 95,08%, Ruff/format, mypy,
lock check, due golden privati, build wheel/sdist e smoke isolato passati.

Le decisioni sui singoli atti sono dati amministrabili, vincolati a record,
bytes, anchor e periodo. Non sono state approvate norme live per questa release.
Adozione e deployment Platform sono milestone distinte: il push Platform attiva
CI, mentre build dell'immagine e deploy Azure sono workflow manuali.
