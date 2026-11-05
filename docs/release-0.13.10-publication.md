# Core 0.13.10 — pubblicazione verificata

2026-11-05. Commit `0d68f6662234909fc57320096570b70e4a990619`, tag
`v0.13.10`.

- [GitHub release](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.10).
- [PyPI](https://pypi.org/project/italian-energy/0.13.10/).
- CI main `42027207998` e tag `42027571393`: Python 3.12, 3.13 e 3.14 passati.
- Trusted Publishing `42027581962`: build e pubblicazione riuscite.
- Platform ha scaricato la wheel da PyPI e verificato digest e attestazione
  contro il repository Core; import/runtime disponibili e capability nuova.

| Artefatto pubblicato | SHA-256 |
| --- | --- |
| `italian_energy-0.13.10-py3-none-any.whl` | `437f6c126c01bff47d3c6539429813c0b45f2460dc189c08f0021259466c5603` |
| `italian_energy-0.13.10.tar.gz` | `045b8ac33c8fe97c1ea0d284a5febfff9eebcfc361c165ad7c9f0e17654dc114` |

La suite Platform con la wheel pubblicata, senza override sorgenti Core, passa
382 test / coverage con rami 90,07%. Questo non certifica una fonte ufficiale:
il documento IVA resta da approvare dall’admin. Il deploy Azure della Platform
è una verifica separata, documentata nel repository Platform.
