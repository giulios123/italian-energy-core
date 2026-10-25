# Core 0.13.7 — pubblicazione verificata

Data: 2026-10-25. Pubblicazione richiesta dall'utente e completata.

## Identità del rilascio

- Commit di release: `53b1e94948b5b7910fde0c188b70cb7800907776`.
- Tag annotato: `v0.13.7`, oggetto `691916c9534bbf49f078a62a107b0c1bc3d18083`.
- [GitHub Release](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.7),
  pubblicata il 25 ottobre 2026 alle 19:09:38 Europe/Rome, non draft/prerelease.
- [PyPI](https://pypi.org/project/italian-energy/0.13.7/).

## Gate remoti

- [CI main](https://github.com/giulios123/italian-energy-core/actions/runs/40219676909):
  Python 3.12, 3.13 e 3.14 tutti superati sul commit di release.
- [CI tag](https://github.com/giulios123/italian-energy-core/actions/runs/40219793488):
  Python 3.12, 3.13 e 3.14 tutti superati sullo stesso commit.
- [Publish to PyPI](https://github.com/giulios123/italian-energy-core/actions/runs/40219910959):
  build, asset GitHub e pubblicazione PyPI tramite Trusted Publishing riusciti.

## Artefatti verificati

| File | Byte | SHA-256 |
|---|---:|---|
| italian_energy-0.13.7-py3-none-any.whl | 280866 | `0a07154623c86d77d6e9d05f28e2f07f6270f745fc555545aa1c97f386093b13` |
| italian_energy-0.13.7.tar.gz | 677223 | `109836c2efb8677d42fa24366074ac15a9264e94d5587c0119035f9dbde08a7a` |

Entrambi gli artefatti sono stati scaricati da GitHub e da PyPI: byte,
dimensione e hash coincidono, inclusa la verifica di `SHA256SUMS`. Coincidono
anche con i file costruiti localmente dal commit di release.

Le attestazioni PyPI di wheel e sdist sono state verificate con
`pypi-attestations verify pypi --repository
https://github.com/giulios123/italian-energy-core`: entrambe OK.

La wheel pubblicata è stata installata da PyPI in un ambiente isolato:
metadata e import confermano 0.13.7 da site-packages, contratto v1,
moduli delle ottimizzazioni presenti e runtime base senza openpyxl/pypdf.
La build locale verifica inoltre che tutti i file Python coincidano con
la sorgente testata e che wheel/sdist non contengano i golden privati.

## Verifica e limiti

939 test passati, coverage con branch 95,12%, Ruff check/format, mypy,
pre-commit e due golden economici privati superati prima del push.
Dettagli della [preparazione](release-0.13.7-preparation.md).

La release include Specs 019/020 senza cambiare contratti, schemi, capability,
formule o dipendenze runtime. Il replay integrato da 950 offerte mantiene
vista pubblica e digest, con 951 bollette coerenti. La mediana 57,148 s
include anche ottimizzazioni proprie della Platform, separate da questa wheel.

La Platform resta nella precedente configurazione locale con mount sorgente;
non sono stati modificati pin, SHA-256, immagine o runtime installato della
Platform. La sua adozione della wheel 0.13.7 e il deployment sono passaggi
separati. Nessun confronto storico o fonte è stato aggiornato dal rilascio.
