from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.money import RateUnit
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import Granularity, TimeInterval


def test_provenance_requires_aware_timestamp_and_valid_hash() -> None:
    provenance = Provenance(
        source="test",
        source_identifier="dataset-1",
        retrieved_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        sha256="a" * 64,
    )
    assert provenance.model_dump(mode="json")["sha256"] == "a" * 64
    with pytest.raises(ValidationError):
        Provenance(
            source="test",
            source_identifier="dataset-1",
            retrieved_at=datetime(2026, 1, 1),
        )
    with pytest.raises(ValidationError):
        Provenance(
            source="test",
            source_identifier="dataset-1",
            retrieved_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            sha256="bad",
        )
    with pytest.raises(ValidationError):
        Provenance(
            source="test",
            source_identifier="dataset-1",
            retrieved_at=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
            url=" ",
        )


def test_market_data_references_known_unique_indexes() -> None:
    index = MarketIndex(
        code="IDX",
        name="Index",
        unit=RateUnit.EUR_PER_MWH,
        granularity=Granularity.HOUR,
    )
    interval = TimeInterval(
        start=datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")),
        end=datetime(2026, 1, 1, 1, tzinfo=ZoneInfo("UTC")),
    )
    data = MarketData(
        indexes=(index,),
        points=(MarketDataPoint(index_code="IDX", interval=interval, value=Decimal("100")),),
    )
    assert data.points[0].value == 100
    with pytest.raises(ValidationError, match="unknown index"):
        MarketData(
            points=(MarketDataPoint(index_code="MISSING", interval=interval, value=Decimal("1")),)
        )
    with pytest.raises(ValidationError, match="unique"):
        MarketData(indexes=(index, index))
    with pytest.raises(ValidationError, match="duplicate"):
        MarketData(
            indexes=(index,),
            points=(
                MarketDataPoint(index_code="IDX", interval=interval, value=Decimal("1")),
                MarketDataPoint(index_code="IDX", interval=interval, value=Decimal("2")),
            ),
        )
    with pytest.raises(ValidationError, match="unknown timezone"):
        MarketIndex(
            code="BAD",
            name="Bad",
            unit=RateUnit.EUR_PER_MWH,
            granularity=Granularity.HOUR,
            timezone="Mars/Phobos",
        )
