"""Acquire an exact official electricity catalogue and report source coverage."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date

from italian_energy.integration.current import CurrentCatalogSnapshot
from italian_energy.integration.errors import CoreContractError
from italian_energy.integration.service import CurrentDomesticEnergyService


def summarize_catalog(catalog: CurrentCatalogSnapshot) -> dict[str, object]:
    """Report acquisition metadata without prices, raw content or readiness claims."""

    files = catalog.snapshot.offers.files
    if catalog.snapshot.indexes is not None:
        files += (catalog.snapshot.indexes.file,)
    indexes: list[dict[str, object]] = []
    if catalog.market_data is not None:
        for index in sorted(catalog.market_data.indexes, key=lambda item: item.code):
            points = [
                point for point in catalog.market_data.points if point.index_code == index.code
            ]
            if points:
                indexes.append(
                    {
                        "code": index.code,
                        "points": len(points),
                        "first_month": min(point.interval.start for point in points).strftime(
                            "%Y-%m"
                        ),
                        "last_month": max(point.interval.start for point in points).strftime(
                            "%Y-%m"
                        ),
                    }
                )
    return {
        "dataset_date": catalog.dataset_date.isoformat(),
        "snapshot_id": catalog.snapshot.offers.snapshot_id,
        "status": catalog.snapshot.offers.status.value,
        "records": len(catalog.records),
        "records_by_type": dict(
            sorted(Counter(record.offer_type.value for record in catalog.records).items())
        ),
        "files": [
            {
                "role": item.role.value,
                "url": item.final_url,
                "size": item.size,
                "sha256": item.sha256,
                "retrieved_at": item.retrieved_at.isoformat(),
            }
            for item in sorted(files, key=lambda item: item.role.value)
        ],
        "historical_indexes": indexes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    args = parser.parse_args(argv)
    try:
        catalog = CurrentDomesticEnergyService().acquire_catalog(args.date)
    except CoreContractError as exc:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "dataset_date": args.date.isoformat(),
                    "error": exc.code.value,
                    "detail": exc.detail,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(summarize_catalog(catalog), sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - executable module entrypoint
    raise SystemExit(main())
