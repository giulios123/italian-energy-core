from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from italian_energy.domain import (
    ConsumptionBucket,
    ConsumptionProfile,
    EnergyQuantity,
    Granularity,
    MarketData,
    MarketDataPoint,
    MarketIndex,
    RateUnit,
    SupplyClassification,
    TimeInterval,
    VoltageLevel,
)
from italian_energy.domain.money import Power, UnitRate
from italian_energy.domain.offer import Contract
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import (
    CurrentPortalComparisonRequest,
    CurrentScenario,
    future_period,
    project_consumption,
    project_market_data,
)
from italian_energy.portal_offers import PortalEligibilityProfile, PortalTerritory

AS_OF = date(2026, 9, 12)


def _profile() -> ConsumptionProfile:
    buckets = []
    for offset in range(12, 0, -1):
        absolute = AS_OF.year * 12 + AS_OF.month - 1 - offset
        year, month0 = divmod(absolute, 12)
        month = month0 + 1
        start = datetime(year, month, 1, tzinfo=UTC)
        next_absolute = absolute + 1
        end_year, end_month0 = divmod(next_absolute, 12)
        end = datetime(end_year, end_month0 + 1, 1, tzinfo=UTC)
        buckets.append(
            ConsumptionBucket(
                interval=TimeInterval(start=start, end=end),
                energy=EnergyQuantity(kwh=Decimal("100")),
                granularity=Granularity.MONTH,
            )
        )
    return ConsumptionProfile(profile_id="profile", buckets=tuple(buckets))


def _market_data() -> MarketData:
    index = MarketIndex(
        code="PUN",
        name="Prezzo unico nazionale",
        unit=RateUnit.EUR_PER_KWH,
        granularity=Granularity.MONTH,
        timezone="UTC",
    )
    points = []
    for offset in range(12, 0, -1):
        absolute = AS_OF.year * 12 + AS_OF.month - 1 - offset
        year, month0 = divmod(absolute, 12)
        month = month0 + 1
        start = datetime(year, month, 1, tzinfo=UTC)
        next_absolute = absolute + 1
        end_year, end_month0 = divmod(next_absolute, 12)
        end = datetime(end_year, end_month0 + 1, 1, tzinfo=UTC)
        points.append(
            MarketDataPoint(
                index_code="PUN",
                interval=TimeInterval(start=start, end=end),
                value=Decimal("0.10"),
            )
        )
    return MarketData(indexes=(index,), points=tuple(points))


def test_future_horizon_is_next_twelve_complete_months() -> None:
    assert future_period(AS_OF) == DatePeriod(start=date(2026, 10, 1), end=date(2027, 10, 1))


def test_consumption_and_market_scenarios_shift_and_scale() -> None:
    projected = project_consumption(_profile(), AS_OF)
    assert projected.buckets[0].interval.start.date() == date(2026, 10, 1)
    assert projected.buckets[-1].interval.start.date() == date(2027, 9, 1)
    low = project_market_data(_market_data(), AS_OF, CurrentScenario.LOW_INDEX, Decimal("0.20"))
    base = project_market_data(_market_data(), AS_OF, CurrentScenario.BASE, Decimal("0.20"))
    high = project_market_data(_market_data(), AS_OF, CurrentScenario.HIGH_INDEX, Decimal("0.20"))
    assert low.points[0].value == Decimal("0.080")
    assert base.points[0].value == Decimal("0.10")
    assert high.points[0].value == Decimal("0.120")
    assert low.points[0].interval.start.date() == date(2026, 10, 1)


def test_current_request_rejects_incomplete_history() -> None:
    contract = Contract(
        contract_id="contract",
        supply=SupplyPoint(
            supply_id="supply",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=True,
        ),
        tariff=FixedTariff(
            tariff_id="tariff",
            validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
            prices=(
                BandPrice(
                    band="ALL", rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH)
                ),
            ),
        ),
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
    )
    eligibility = PortalEligibilityProfile(
        territory=PortalTerritory(region_code="01", province_code="001", municipality_code="000001")
    )
    with pytest.raises(Exception, match="twelve complete"):
        CurrentPortalComparisonRequest(
            current_contract=contract,
            consumption=ConsumptionProfile(profile_id="empty"),
            as_of=AS_OF,
            classification=SupplyClassification(
                contract_type_code="domestic_bt_resident",
                voltage_level=VoltageLevel.BT,
                usage_code="domestic",
                residential=True,
            ),
            eligibility=eligibility,
        )
