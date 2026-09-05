"""Property-based invariants for domain values."""

# Hypothesis' decorator typing differs between supported mypy versions.
# mypy: disable-error-code=untyped-decorator

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from hypothesis import given
from hypothesis import strategies as st

from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.money import EnergyQuantity
from italian_energy.domain.time import Granularity, TimeInterval


@given(
    st.lists(
        st.decimals(
            min_value="0",
            max_value="1000",
            places=3,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=1,
        max_size=12,
    )
)
def test_consumption_total_is_exact_decimal_sum(values: list[Decimal]) -> None:
    origin = datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC"))
    buckets = tuple(
        ConsumptionBucket(
            interval=TimeInterval(
                start=origin + timedelta(hours=index),
                end=origin + timedelta(hours=index + 1),
            ),
            energy=EnergyQuantity(kwh=value),
            granularity=Granularity.HOUR,
        )
        for index, value in enumerate(values)
    )
    profile = ConsumptionProfile(profile_id="property", buckets=buckets)
    assert profile.total_energy().kwh == sum(values, Decimal(0))
