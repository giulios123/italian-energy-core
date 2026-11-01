# Core 0.13.8 — pubblicazione verificata

Data: 2026-11-01. Release GitHub e package PyPI pubblicati dal commit
`c11fe6cfe313c78e411c8284e33888e502bf739c`, tag annotato `v0.13.8`.

## Pubblicazione e verifiche remote

- [GitHub Release v0.13.8](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.8)
- [Package PyPI 0.13.8](https://pypi.org/project/italian-energy/0.13.8/)
- [Workflow Publish to PyPI #41314193152](https://github.com/giulios123/italian-energy-core/actions/runs/41314193152): build, controllo versione/tag, smoke wheel, upload asset e Trusted Publishing tutti riusciti.
- CI [main #41314046534](https://github.com/giulios123/italian-energy-core/actions/runs/41314046534) e [tag #41314046210](https://github.com/giulios123/italian-energy-core/actions/runs/41314046210): Python 3.12, 3.13 e 3.14 tutti riusciti.
- PyPI mostra attestazioni verificate da PyPI, firmate da GitHub Actions, per entrambi i file. L'identità riporta il repository Core, il commit indicato sopra e `.github/workflows/release.yml`.

## Artefatti

Gli SHA-256 osservati su GitHub Release e PyPI coincidono:

| Artefatto | Dimensione GitHub | SHA-256 |
| --- | ---: | --- |
| `italian_energy-0.13.8-py3-none-any.whl` | 286.403 byte | `80712e6ae4674e1a68d60b64486cb30f360ab469de7d24ff286e470f65187411` |
| `italian_energy-0.13.8.tar.gz` | 695.768 byte | `1f396e53f6df6a3174379fe5d20d55d2727e9c88f0c0a50189141c268fe95228` |

La release GitHub contiene anche `SHA256SUMS` (SHA-256 del file:
`5c85ce9874aaf8b4039ec734749e1b0ca1fcc8989962f160b3577891f00faac2`).
PyPI riporta entrambi i file come provenienti da Trusted Publishing e con
provenance verificata.

## Verifica Core e limiti

La verifica locale della preparazione ha completato 961 test con branch
coverage 95,03%; Ruff check/format, mypy, lock check, pre-commit, golden privati,
build wheel/sdist e smoke isolato della wheel sono passati. La CI remota e la
pubblicazione hanno poi completato con successo.

La suite usa fixture offline per la pubblicazione GME e fixture sintetiche per
consumi e catalogo nel caso del 1° novembre 2026; non è stata eseguita una nuova
acquisizione live GME. La Platform non è stata modificata né sottoposta a
integrazione con la nuova wheel. Per adottarla, `application/comparison.py`
deve aggiornare `_public_market_reference`: validare la selezione Core e il
ritardo ammesso al posto di rifiutare `market_reference_period` diverso dal
mese immediatamente precedente. Pin, SHA-256, immagine e gate Platform restano
una decisione e una verifica separate. Non è stato distribuito alcun deployment
Platform.
