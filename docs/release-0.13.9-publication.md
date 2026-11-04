# Core 0.13.9 — pubblicazione verificata

Data: 2026-11-04. Commit della release
`a024eddedbbed7aed6511c80ee4095be663e703d`, tag annotato `v0.13.9`.

- [GitHub Release](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.9).
- [PyPI 0.13.9](https://pypi.org/project/italian-energy/0.13.9/).
- [CI main](https://github.com/giulios123/italian-energy-core/actions/runs/41855403667)
  e [CI tag](https://github.com/giulios123/italian-energy-core/actions/runs/41855886143):
  Python 3.12, 3.13 e 3.14 tutti riusciti.
- [Trusted Publishing](https://github.com/giulios123/italian-energy-core/actions/runs/41855934897):
  build, smoke wheel, asset GitHub e pubblicazione PyPI riusciti.

| Artefatto | SHA-256 |
| --- | --- |
| `italian_energy-0.13.9-py3-none-any.whl` | `fd574a9eb31c8fded6d0843633d7ef78312f81194a0ceda4a6332905e0f00a07` |
| `italian_energy-0.13.9.tar.gz` | `162dfbd8772f413cf13e5b526909e0080a20837d43e5504c2030213ff7268280` |

La Platform ha scaricato la wheel da PyPI e verificato hash, manifest e
attestazione repository-scoped con `pypi-attestations verify pypi`.
Il digest coincide con l'asset GitHub e con la wheel locale costruita dal
commit della release. Preparazione: 989 test / 95,04% branch coverage,
Ruff/mypy, pre-commit, lock e golden privati superati.

Il percorso locale Platform persistente è stato aggiornato con la wheel
pubblicata. Una discovery completa esplicita è necessaria per rivalutare
le decisioni precedenti conservate fuori dalla finestra incrementale:
non elimina report né modifica i confronti storici. Dopo discovery e catalogo,
lo snapshot locale del 2026-11-04 è verificato, con confronto abilitato e
nessun reason code. Il report di adozione Platform documenta i test separatamente.

Il limite dello stato nuovo resta esplicito: la scansione con il seed incluso
può bloccare per l'hash diverso della pagina IVA Normattiva. Tale controllo
non è stato aggirato e il package non certifica automaticamente la variazione.
Non è stato eseguito un deploy Azure durante questo rilascio.
