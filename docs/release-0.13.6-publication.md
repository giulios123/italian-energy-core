# Core 0.13.6 — pubblicazione verificata

Release pubblicata il 2026-10-23, verificata anche il 2026-10-24.

- Commit: `8b0d1475e38f701a8a81e1b0d7a428abcf33e36d`.
- Tag annotato: `v0.13.6`, sul commit verificato.
- [GitHub Release](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.6).
- [PyPI](https://pypi.org/project/italian-energy/0.13.6/).
- [CI main](https://github.com/giulios123/italian-energy-core/actions/runs/40028813495) e
  [CI tag](https://github.com/giulios123/italian-energy-core/actions/runs/40029001585):
  Python 3.12, 3.13 e 3.14 tutti riusciti.
- [Trusted Publishing](https://github.com/giulios123/italian-energy-core/actions/runs/40029005191):
  build e publish PyPI riusciti; attestazioni digitali caricate.

## Artefatti effettivamente pubblicati

| Artefatto | Byte | SHA-256 GitHub = PyPI |
| --- | ---: | --- |
| italian_energy-0.13.6-py3-none-any.whl | 277945 | b557d28fe8776ccae3fa43fe38053d26e082daf3de57c745153910083115e37a |
| italian_energy-0.13.6.tar.gz | 663838 | ad74ee6245e71323908f4bb61d6e65da88b67fb8a9870c0f9dd17110d25bd6db |

Scaricati gli asset GitHub e confrontati con SHA256SUMS e metadati PyPI;
entrambi coincidono. La wheel contiene solo package e dist-info. Lo sdist
contiene sotto `private/` solo il README pubblico, nessun golden privato.
Il controllo iniziale che escludeva l'intera cartella privata era troppo
ampio: sostituito con l'asserzione esatta sul solo README distribuito.

## Verifiche e adozione

Prima del tag: 924 test, branch coverage 95,08%, Ruff/format/mypy, pre-commit,
due golden economici privati, build e import isolato della wheel. Dettagli in
[preparazione](release-0.13.6-preparation.md).

Platform ha scaricato la wheel da PyPI con verifica SHA-256 e PEP 740 verso
il repository Core; import e manifest host confermano 0.13.6 da site-packages.
L'immagine locale costruisce/installando esattamente quel pacchetto e supera
lo smoke del manifest e dell'anchor packaged del 2026-10-08. Quest'ultimo non
certifica le fonti nella data odierna. L'adozione completa è documentata nel
repository Platform in `docs/core-0136-platform-adoption-2026-10-23.md`.
Nessun deployment di produzione è implicato dalla pubblicazione del Core.
