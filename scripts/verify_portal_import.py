#!/usr/bin/env python3
"""Non-blocking live smoke for one exact Portale Offerte catalogue date."""

from __future__ import annotations

import argparse
import json
from datetime import date

from italian_energy.portal_offers import PortalOffersImporter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--date",
        required=True,
        type=date.fromisoformat,
        help="exact open-data dataset date (YYYY-MM-DD)",
    )
    args = parser.parse_args()
    importer = PortalOffersImporter()
    snapshot = importer.fetch(args.date, include_indexes=True)
    records = importer.parse_offers(snapshot.offers)
    index_count = 0
    if snapshot.indexes is not None:
        index_count = len(importer.parse_market_data(snapshot.indexes).points)
    print(
        json.dumps(
            {
                "dataset_date": args.date.isoformat(),
                "snapshot_id": snapshot.offers.snapshot_id,
                "status": snapshot.offers.status.value,
                "records": len(records),
                "historical_index_points": index_count,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
