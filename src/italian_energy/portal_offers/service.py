"""End-to-end Portale Offerte orchestration over the existing comparison engine."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import datetime

from italian_energy.comparison import (
    DeterministicComparisonEngine,
)
from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.portal_offers.importer import PortalImportError, PortalOffersImporter
from italian_energy.portal_offers.models import (
    PortalComparisonRequest,
    PortalComparisonResult,
    VerifiedMarketData,
)
from italian_energy.portal_offers.normalizer import normalize_offers


def merge_market_data(
    official: MarketData | None,
    supplemental: VerifiedMarketData | None,
) -> MarketData | None:
    """Merge verified series, rejecting conflicting index definitions or points."""
    if official is None and supplemental is None:
        return None
    indexes: dict[str, MarketIndex] = {}
    points: dict[tuple[str, object, object], MarketDataPoint] = {}
    for source in (official, None if supplemental is None else supplemental.data):
        if source is None:
            continue
        for index in source.indexes:
            previous = indexes.get(index.code)
            if previous is not None and previous != index:
                raise PortalImportError(f"conflicting market index definition: {index.code}")
            indexes[index.code] = index
        for point in source.points:
            key = (point.index_code, point.interval.start, point.interval.end)
            previous_point = points.get(key)
            if previous_point is not None and previous_point != point:
                raise PortalImportError(f"conflicting market data point: {point.index_code}")
            points[key] = point
    return MarketData(
        indexes=tuple(indexes[code] for code in sorted(indexes)),
        points=tuple(
            points[key] for key in sorted(points, key=lambda item: (item[0], item[1], item[2]))
        ),
    )


class PortalComparisonService:
    """Acquire, normalize and compare electricity offers deterministically."""

    def __init__(
        self,
        importer: PortalOffersImporter | None = None,
        engine: DeterministicComparisonEngine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._importer = importer or PortalOffersImporter()
        self._engine = engine or DeterministicComparisonEngine()
        self._clock = clock or (lambda: datetime.now().astimezone())

    def compare(self, request: PortalComparisonRequest) -> PortalComparisonResult:
        if request.comparison.period.end > self._clock().date():
            raise PortalImportError("historical replay period must be concluded")
        self._engine.preflight(request.comparison)
        snapshot = self._importer.fetch(request.comparison.as_of, include_indexes=True)
        if snapshot.offers.status != VerificationStatus.VERIFIED:
            raise PortalImportError("unverified offers snapshot cannot be compared")
        records = self._importer.parse_offers(snapshot.offers)
        official_market = (
            None if snapshot.indexes is None else self._importer.parse_market_data(snapshot.indexes)
        )
        market_data = merge_market_data(official_market, request.supplemental_market_data)
        import_result = normalize_offers(
            snapshot.offers,
            records,
            request.eligibility,
            request.comparison.period.start,
            request.comparison.period.end,
            market_data=market_data,
        ).model_copy(update={"index_snapshot": snapshot.indexes})
        context = request.comparison.model_copy(update={"market_data": market_data})
        comparison_request = context.to_request(import_result.eligible_offers)
        comparison = self._engine.compare(comparison_request)
        result_id = hashlib.sha256(
            json.dumps(
                {
                    "import_id": import_result.import_id,
                    "comparison_id": comparison.comparison_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return PortalComparisonResult(
            portal_result_id=f"portal-comparison:{result_id}",
            import_result=import_result,
            comparison_result=comparison,
        )


def compare_portal_offers(request: PortalComparisonRequest) -> PortalComparisonResult:
    return PortalComparisonService().compare(request)
