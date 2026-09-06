from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from italian_energy.billing import BillingRequest, RegulatoryBillingEngine
from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.money import (
    EnergyQuantity,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import RegulatoryRuleSet, SupplyClassification, VoltageLevel
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval
from italian_energy.pricing.engine import PricingRequest
from italian_energy.pricing.fixed import FixedPricingEngine

ROOT = Path(__file__).resolve().parents[2]
ROME = ZoneInfo("Europe/Rome")
PERIOD = DatePeriod(start=date(2026, 5, 1), end=date(2026, 7, 1))
SOURCE = Provenance(
    source="synthetic-fixture-test",
    source_identifier="regulatory-domestic-bt-resident-v1",
    retrieved_at=datetime(2026, 9, 6, tzinfo=UTC),
    effective_period=PERIOD,
)
POLICY = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)


def test_public_domestic_ruleset_calculates_an_independent_synthetic_bill() -> None:
    ruleset = RegulatoryRuleSet.model_validate_json(
        (ROOT / "tests/fixtures/regulatory-domestic-bt-resident-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert ruleset.status.value == "verified"
    assert all(
        rule.status.value == "verified" for profile in ruleset.profiles for rule in profile.rules
    )
    assert all(rule.provenance for profile in ruleset.profiles for rule in profile.rules)

    tariff = FixedTariff(
        tariff_id="synthetic-fixed",
        validity=PERIOD,
        prices=(
            BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH)),
        ),
        provenance=(SOURCE,),
    )
    contract = Contract(
        contract_id="synthetic-contract",
        supply=SupplyPoint(
            supply_id="synthetic-supply",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=True,
        ),
        tariff=tariff,
        validity=PERIOD,
        provenance=(SOURCE,),
    )
    consumption = ConsumptionProfile(
        profile_id="synthetic-consumption",
        buckets=(
            ConsumptionBucket(
                interval=TimeInterval(
                    start=datetime(2026, 5, 1, tzinfo=ROME),
                    end=datetime(2026, 6, 1, tzinfo=ROME),
                ),
                energy=EnergyQuantity(kwh=Decimal("50")),
                granularity=Granularity.MONTH,
            ),
            ConsumptionBucket(
                interval=TimeInterval(
                    start=datetime(2026, 6, 1, tzinfo=ROME),
                    end=datetime(2026, 7, 1, tzinfo=ROME),
                ),
                energy=EnergyQuantity(kwh=Decimal("50")),
                granularity=Granularity.MONTH,
            ),
        ),
    )
    pricing = FixedPricingEngine().price(
        PricingRequest(
            contract=contract,
            consumption=consumption,
            period=PERIOD,
            rounding_policy=POLICY,
        )
    )
    result = RegulatoryBillingEngine().evaluate(
        BillingRequest(
            contract=contract,
            consumption=consumption,
            period=PERIOD,
            pricing_result=pricing,
            classification=SupplyClassification(
                contract_type_code="domestic_bt_resident",
                voltage_level=VoltageLevel.BT,
                usage_code="domestic",
                residential=True,
            ),
            rule_set=ruleset,
            rounding_policy=POLICY,
        )
    )

    assert result.bill.breakdown.total.amount == Decimal("35.72")
    assert result.reconciliation is None
    assert [component.reconciliation_key for component in result.bill.breakdown.components] == [
        "energy:ALL",
        "network_energy_may",
        "network_energy_june",
        "system_asos_may",
        "system_asos_june",
        "system_arim_may",
        "system_arim_june",
        "network_fixed",
        "network_power",
        "excise",
        "vat",
    ]
