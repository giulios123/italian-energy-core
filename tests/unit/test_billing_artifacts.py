from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from italian_energy.billing import (
    BillingArtifactError,
    CoverageLevel,
    load_coverage_matrix,
    load_ruleset,
)
from italian_energy.billing.engine import BillingRequest
from italian_energy.billing.regulatory import RegulatoryBillingEngine
from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.costs import CostBreakdown, CostComponent, CostZeroReason, PricingResult
from italian_energy.domain.money import (
    EnergyQuantity,
    Money,
    Power,
    RateUnit,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import (
    SupplyClassification,
    ThresholdRegulatoryRule,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval

PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
SOURCE = Provenance(
    source="artifact-test",
    source_identifier="spec-006",
    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    effective_period=PERIOD,
)


def request(*, resident: bool) -> BillingRequest:
    contract_type = "domestic_bt_resident" if resident else "domestic_bt_non_resident"
    contract = Contract(
        contract_id=f"artifact-{contract_type}",
        supply=SupplyPoint(
            supply_id=f"pod-{contract_type}",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("1.5") if resident else Decimal("3")),
            residential=resident,
        ),
        tariff=FixedTariff(
            tariff_id="artifact-tariff",
            validity=PERIOD,
            prices=(
                BandPrice(
                    band="ALL",
                    rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
                ),
            ),
        ),
        validity=PERIOD,
        provenance=(SOURCE,),
    )
    pricing_component = CostComponent(
        code="energy",
        description="synthetic energy",
        amount=Money(amount=Decimal("10")),
        quantity=Decimal("100"),
        unit_rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
        period=PERIOD,
        formula="quantity_kwh * rate_eur_per_kwh",
        provenance=(SOURCE,),
    )
    pricing = PricingResult(
        pricing_id=f"pricing-{contract_type}",
        contract_id=contract.contract_id,
        period=PERIOD,
        breakdown=CostBreakdown(
            components=(pricing_component,),
            total=pricing_component.amount,
        ),
        provenance=(SOURCE,),
    )
    return BillingRequest(
        contract=contract,
        consumption=ConsumptionProfile(
            profile_id="artifact-consumption",
            buckets=(
                ConsumptionBucket(
                    interval=TimeInterval(
                        start=datetime(2026, 1, 1, tzinfo=UTC),
                        end=datetime(2026, 1, 2, tzinfo=UTC),
                    ),
                    energy=EnergyQuantity(kwh=Decimal("100")),
                    granularity=Granularity.DAY,
                ),
            ),
        ),
        period=PERIOD,
        pricing_result=pricing,
        classification=SupplyClassification(
            contract_type_code=contract_type,
            voltage_level=VoltageLevel.BT,
            usage_code="domestic",
            residential=resident,
        ),
        rule_set=load_ruleset(segment="resident" if resident else "non-resident"),
        rounding_policy=RoundingPolicy(scale=2),
    )


def test_packaged_artifacts_load_without_arera_extra() -> None:
    resident = load_ruleset(segment="resident")
    non_resident = load_ruleset(segment="non-resident")
    matrix = load_coverage_matrix()

    assert resident.status == VerificationStatus.VERIFIED
    assert non_resident.status == VerificationStatus.VERIFIED
    assert resident.validity == non_resident.validity
    assert len(matrix.entries) == 5
    assert {entry.level.value for entry in matrix.entries} == {
        "ruleset_verified",
        "golden_reconciled",
    }
    evidence_components = {
        item.locator.document
        for item in non_resident.provenance
        if item.locator is not None and item.locator.document is not None
    }
    assert "CDISPD" in evidence_components
    assert "network_total" in evidence_components
    resident_classification = SupplyClassification(
        contract_type_code="domestic_bt_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=True,
    )
    decision = matrix.resolve(
        resident_classification,
        resident.ruleset_id,
        resident.validity,
    )
    assert decision.level == CoverageLevel.RULESET_VERIFIED
    non_resident_classification = SupplyClassification(
        contract_type_code="domestic_bt_non_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=False,
    )
    golden_decision = matrix.resolve(
        non_resident_classification,
        non_resident.ruleset_id,
        DatePeriod(start=date(2026, 3, 1), end=date(2026, 5, 1)),
    )
    assert golden_decision.level == CoverageLevel.GOLDEN_RECONCILED


def test_packaged_rulesets_bill_both_domestic_profiles() -> None:
    engine = RegulatoryBillingEngine()

    resident = engine.evaluate(request(resident=True))
    non_resident = engine.evaluate(request(resident=False))

    assert resident.bill.breakdown.total.amount > Decimal("0")
    assert non_resident.bill.breakdown.total.amount > resident.bill.breakdown.total.amount
    assert any(
        component.code.startswith("regulatory:excise:")
        for component in non_resident.bill.breakdown.components
    )


def test_resident_excise_boundaries_are_monthly_and_profile_specific() -> None:
    engine = RegulatoryBillingEngine()
    expected = {
        "1.5": (
            Decimal("0"),
            Decimal("0"),
            Decimal("2"),
            Decimal("138"),
            Decimal("140"),
            Decimal("142"),
        ),
        "3": (
            Decimal("0"),
            Decimal("0"),
            Decimal("1"),
            Decimal("69"),
            Decimal("70"),
            Decimal("72"),
        ),
        "3.1": (
            Decimal("149"),
            Decimal("150"),
            Decimal("151"),
            Decimal("219"),
            Decimal("220"),
            Decimal("221"),
        ),
    }
    consumptions = (149, 150, 151, 219, 220, 221)
    for power, quantities in expected.items():
        for consumption, expected_quantity in zip(consumptions, quantities, strict=True):
            base = request(resident=True)
            bucket = base.consumption.buckets[0].model_copy(
                update={"energy": EnergyQuantity(kwh=Decimal(consumption))}
            )
            contract = base.contract.model_copy(
                update={
                    "supply": base.contract.supply.model_copy(
                        update={"contracted_power": Power(kw=Decimal(power))}
                    )
                }
            )
            scenario = base.model_copy(
                update={
                    "contract": contract,
                    "consumption": base.consumption.model_copy(update={"buckets": (bucket,)}),
                }
            )
            assert scenario.rule_set is not None
            assert scenario.classification is not None
            profile = engine._select_profile(scenario.rule_set, scenario.classification, scenario)
            excise = next(rule for rule in profile.rules if rule.code == "excise:2026-01")
            assert isinstance(excise, ThresholdRegulatoryRule)
            assert engine._evaluate_quantity(scenario, excise.quantity, PERIOD) == expected_quantity


def test_zero_excise_reason_requires_positive_consumption_and_verified_rule() -> None:
    engine = RegulatoryBillingEngine()
    base = request(resident=True)
    assert base.rule_set is not None
    assert base.classification is not None
    profile = engine._select_profile(base.rule_set, base.classification, base)
    source_rule = next(rule for rule in profile.rules if rule.code == "excise:2026-01")
    assert isinstance(source_rule, ThresholdRegulatoryRule)
    excise = source_rule.model_copy(update={"zero_reason_when_zero": "monthly_resident_exemption"})

    def evaluate(
        kwh: Decimal, *, status: VerificationStatus = VerificationStatus.VERIFIED
    ) -> CostComponent:
        bucket = base.consumption.buckets[0].model_copy(update={"energy": EnergyQuantity(kwh=kwh)})
        scenario = base.model_copy(
            update={
                "consumption": base.consumption.model_copy(update={"buckets": (bucket,)}),
            }
        )
        assert scenario.rounding_policy is not None
        return engine._threshold_component(
            scenario,
            excise.model_copy(update={"status": status}),
            PERIOD,
            scenario.rounding_policy,
            scenario.rule_set.parameters if scenario.rule_set is not None else (),
        )

    no_consumption = evaluate(Decimal("0"))
    exempt_consumption = evaluate(Decimal("100"))
    unverified_rule = evaluate(Decimal("100"), status=VerificationStatus.UNVERIFIED)
    assert no_consumption.amount.amount == 0
    assert no_consumption.zero_reason is None
    assert exempt_consumption.amount.amount == 0
    assert exempt_consumption.zero_reason == CostZeroReason.MONTHLY_RESIDENT_EXEMPTION
    assert unverified_rule.amount.amount == 0
    assert unverified_rule.zero_reason is None


def test_artifact_loader_rejects_ambiguous_or_invalid_inputs(tmp_path: Path) -> None:
    with pytest.raises(BillingArtifactError, match="segment is required"):
        load_ruleset()
    with pytest.raises(BillingArtifactError, match="segment must be"):
        load_ruleset(segment="gas")
    with pytest.raises(BillingArtifactError, match="cannot read"):
        load_ruleset(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(BillingArtifactError, match="cannot read"):
        load_ruleset(bad)
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(BillingArtifactError, match="invalid billing ruleset"):
        load_ruleset(bad)
    with pytest.raises(BillingArtifactError, match="cannot read"):
        load_coverage_matrix(tmp_path / "missing-matrix.json")
