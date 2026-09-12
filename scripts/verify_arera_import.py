"""Live smoke check for the official ARERA 2026 workbook.

This script intentionally prints metadata and counts only. It never writes the
downloaded workbook or source values to the repository.
"""

from __future__ import annotations

from italian_energy.arera import AreraDomesticElectricityImporter
from italian_energy.domain.regulatory import VerificationStatus


def main() -> None:
    result = AreraDomesticElectricityImporter().fetch_and_import()
    if result.status != VerificationStatus.VERIFIED or result.bundle is None:
        codes = ", ".join(item.code for item in result.diagnostics)
        raise SystemExit(f"ARERA import is not verified: {codes or result.status.value}")
    segments = sorted({charge.segment.value for charge in result.bundle.charges})
    print(f"status={result.status.value}")
    print(f"snapshot_id={result.snapshot.snapshot_id}")
    print(f"bundle_id={result.bundle.bundle_id}")
    print(f"charges={len(result.bundle.charges)}")
    print(f"segments={','.join(segments)}")


if __name__ == "__main__":
    main()
