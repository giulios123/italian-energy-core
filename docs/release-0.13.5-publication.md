# Core 0.13.5 publication evidence — 2026-10-19

## Release identity

- Release: [GitHub v0.13.5](https://github.com/giulios123/italian-energy-core/releases/tag/v0.13.5)
- PyPI: [italian-energy 0.13.5](https://pypi.org/project/italian-energy/0.13.5/)
- Tag `v0.13.5` points to release commit
  `6220db76f88085ae1e759774b985ce7b8f544c87` (`release: Italian Energy Core 0.13.5`).
- The feature source is commit `05623b75aff7e9a72f35808a8791cf87272159f2`;
  the release commit adds publication metadata and points to the same versioned
  source tree.
- GitHub release workflow [39289896115](https://github.com/giulios123/italian-energy-core/actions/runs/39289896115)
  completed successfully, including build and Trusted Publishing jobs.

## Published artifact verification

The PyPI artifacts match their GitHub Release asset digests:

| Artifact | SHA-256 |
| --- | --- |
| `italian_energy-0.13.5-py3-none-any.whl` | `33b20140e3e84c3f79be61eef6c192641da1f9c219c3acaf57845b4250d21ed5` |
| `italian_energy-0.13.5.tar.gz` | `a610f40aac3903055d0ff70eeb2db9129179a8717b84fdae40db945035c7620a` |

The Platform fetcher independently verified the wheel digest, package manifest,
PEP 740 provenance and Core repository identity before local installation.

## Source validation

Before publication, the Core suite passed **895 tests** with **95.00% branch
coverage**. Ruff check/format, mypy, `uv lock --check --offline`, wheel/sdist
builds and an isolated wheel smoke test passed. The smoke test imported
`italian_energy` 0.13.5 and verified the Portal economic-validity capability.
The economic behavior and official catalog replay are described in
[`offer-economic-validity-0.13.5.md`](offer-economic-validity-0.13.5.md).

Publication does not update a Platform runtime, refresh its catalog or deploy
images. Those are separate adoption and operational checks.
