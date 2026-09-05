"""Shared pytest fixtures."""

# pytest's decorator typing differs between supported mypy versions.
# mypy: disable-error-code=untyped-decorator

from datetime import date, datetime
from decimal import Decimal

import pytest

from italian_energy.domain.market import MarketIndex
from italian_energy.domain.money import RateUnit
from italian_energy.domain.time import DatePeriod, Granularity


@pytest.fixture
def period() -> DatePeriod:
    return DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))


@pytest.fixture
def market_index() -> MarketIndex:
    return MarketIndex(
        code="PUN_TEST",
        name="Synthetic PUN",
        unit=RateUnit.EUR_PER_MWH,
        granularity=Granularity.HOUR,
    )


def aware(hour: int) -> datetime:
    return datetime(2026, 1, 1, hour, tzinfo=__import__("zoneinfo").ZoneInfo("Europe/Rome"))


def decimal(value: str) -> Decimal:
    return Decimal(value)
