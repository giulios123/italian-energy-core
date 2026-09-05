from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.money import EnergyQuantity
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval

ROME = ZoneInfo("Europe/Rome")


def bucket(start_hour: int, end_hour: int, band: str = "ALL") -> ConsumptionBucket:
    return ConsumptionBucket(
        interval=TimeInterval(
            start=datetime(2026, 1, 1, start_hour, tzinfo=ROME),
            end=datetime(2026, 1, 1, end_hour, tzinfo=ROME),
        ),
        energy=EnergyQuantity(kwh=Decimal("1.25")),
        band=band,
        granularity=Granularity.HOUR,
    )


def test_period_is_half_open_and_requires_positive_length() -> None:
    assert DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2)).end.isoformat() == "2026-01-02"
    with pytest.raises(ValidationError):
        DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 1))


def test_naive_market_interval_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TimeInterval(start=datetime(2026, 1, 1), end=datetime(2026, 1, 1, 1))
    with pytest.raises(ValidationError):
        TimeInterval(start=datetime(2026, 1, 1, tzinfo=ROME), end=datetime(2026, 1, 1))
    with pytest.raises(ValidationError, match="end > start"):
        TimeInterval(
            start=datetime(2026, 1, 1, 1, tzinfo=ROME),
            end=datetime(2026, 1, 1, tzinfo=ROME),
        )


def test_profile_rejects_overlapping_buckets_and_mixed_all_band() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        ConsumptionProfile(profile_id="p1", buckets=(bucket(0, 2), bucket(1, 3)))
    with pytest.raises(ValidationError, match="mix"):
        ConsumptionProfile(profile_id="p2", buckets=(bucket(0, 1), bucket(1, 2, "F1")))


def test_profile_totals_are_decimal_and_adjacent_buckets_are_valid() -> None:
    profile = ConsumptionProfile(profile_id="p3", buckets=(bucket(0, 1), bucket(1, 2)))
    assert profile.total_energy().kwh == Decimal("2.50")
