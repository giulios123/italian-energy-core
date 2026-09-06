import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.billing import BillingError, BillingRequest, RegulatoryBillingEngine
from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.costs import (
    Bill,
    BillingResult,
    BillReconciliation,
    CostBreakdown,
    CostComponent,
    ExternalBillItem,
    ObservedBill,
    ObservedBillComponent,
    PricingResult,
    ReconciliationStatus,
)
from italian_energy.domain.money import (
    EnergyQuantity,
    Money,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import (
    AddQuantity,
    BillingBasis,
    BillingCategory,
    BillingMeasure,
    BillingMeasureUnit,
    BillingQuota,
    ClampQuantity,
    LinearRegulatoryRule,
    MaxQuantity,
    MeasureReference,
    MinQuantity,
    MultiplyQuantity,
    PercentageRegulatoryRule,
    ProrationPolicy,
    QuantityConstant,
    QuantityExpression,
    RegulatoryParameter,
    RegulatoryProfile,
    RegulatoryRuleSet,
    SubtractQuantity,
    SupplyClassification,
    ThresholdRegulatoryRule,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval

ROME = ZoneInfo("Europe/Rome")
PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
POLICY = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)
SOURCE = Provenance(
    source="synthetic-test",
    source_identifier="billing-004",
    retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    effective_period=PERIOD,
)


def contract() -> Contract:
    tariff = FixedTariff(
        tariff_id="fixed",
        validity=PERIOD,
        prices=(
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
    )
    return Contract(
        contract_id="contract-004",
        supply=SupplyPoint(
            supply_id="pod-004",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=True,
        ),
        tariff=tariff,
        validity=PERIOD,
        provenance=(SOURCE,),
    )


def pricing_result(*, amount: str = "10.00", code: str = "energy") -> PricingResult:
    component = CostComponent(
        code=code,
        description="commercial energy",
        amount=Money(amount=Decimal(amount)),
        quantity=Decimal("100"),
        unit_rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
        period=PERIOD,
        formula="quantity_kwh * rate_eur_per_kwh",
        provenance=(SOURCE,),
    )
    return PricingResult(
        pricing_id="fixed:pricing-004",
        contract_id="contract-004",
        period=PERIOD,
        breakdown=CostBreakdown(components=(component,), total=Money(amount=Decimal(amount))),
        provenance=(SOURCE,),
    )


def linear(
    code: str,
    basis: BillingBasis,
    value: Money | UnitRate,
    *,
    quota: BillingQuota = BillingQuota.FIXED,
    measure_code: str | None = None,
    proration: ProrationPolicy | None = None,
    credit: bool = False,
) -> LinearRegulatoryRule:
    return LinearRegulatoryRule(
        code=code,
        description=code,
        category=BillingCategory.NETWORK,
        quota=quota,
        validity=PERIOD,
        basis=basis,
        value=value,
        measure_code=measure_code,
        proration=proration,
        credit=credit,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )


def ruleset(
    *rules: LinearRegulatoryRule | ThresholdRegulatoryRule | PercentageRegulatoryRule,
    parameters: tuple[RegulatoryParameter, ...] = (),
    profiles: tuple[RegulatoryProfile, ...] | None = None,
) -> RegulatoryRuleSet:
    if profiles is None:
        if not rules:
            rules = (
                linear(
                    "base",
                    BillingBasis.PER_KWH,
                    UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH),
                ),
            )
        profiles = (
            RegulatoryProfile(
                profile_code="domestic_bt_resident",
                contract_type_code="domestic_bt_resident",
                voltage_level=VoltageLevel.BT,
                usage_code="domestic",
                residential=True,
                rules=tuple(rules),
            ),
        )
    return RegulatoryRuleSet(
        ruleset_id="synthetic-rules",
        schema_version="004-test",
        validity=PERIOD,
        parameters=parameters,
        profiles=tuple(profiles),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )


def request(
    *,
    rules: tuple[
        LinearRegulatoryRule | ThresholdRegulatoryRule | PercentageRegulatoryRule, ...
    ] = (),
    measures: tuple[BillingMeasure, ...] = (),
    external_items: tuple[ExternalBillItem, ...] = (),
    observed: Bill | ObservedBill | None = None,
    pricing: PricingResult | None = None,
    classification: SupplyClassification | None = None,
    rule_set: RegulatoryRuleSet | None = None,
    rounding_policy: RoundingPolicy = POLICY,
) -> BillingRequest:
    return BillingRequest(
        contract=contract(),
        consumption=ConsumptionProfile(
            profile_id="consumption-004",
            buckets=(
                ConsumptionBucket(
                    interval=TimeInterval(
                        start=datetime(2026, 1, 1, tzinfo=ROME),
                        end=datetime(2026, 1, 1, 1, tzinfo=ROME),
                    ),
                    energy=EnergyQuantity(kwh=Decimal("100")),
                    granularity=Granularity.HOUR,
                ),
            ),
        ),
        period=PERIOD,
        observed_bill=observed,
        pricing_result=pricing or pricing_result(),
        classification=classification
        or SupplyClassification(
            contract_type_code="domestic_bt_resident",
            voltage_level=VoltageLevel.BT,
            usage_code="domestic",
            residential=True,
        ),
        rule_set=rule_set or ruleset(*rules),
        measurements=tuple(measures),
        external_items=tuple(external_items),
        rounding_policy=rounding_policy,
    )


def test_billing_calculates_linear_threshold_percentage_and_external_items() -> None:
    network = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("0.02"), unit=RateUnit.EUR_PER_KWH),
        quota=BillingQuota.CONSUMPTION,
    )
    threshold = ThresholdRegulatoryRule(
        code="threshold",
        description="threshold",
        category=BillingCategory.EXCISE,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        quantity=ClampQuantity(
            operand=MultiplyQuantity(
                quantity=MeasureReference(code="reactive", unit=BillingMeasureUnit.KVARH),
                scalar=Decimal("2"),
            ),
            floor=Decimal("1"),
            cap=Decimal("20"),
        ),
        rate=UnitRate(amount=Decimal("0.01"), unit=RateUnit.EUR_PER_KVARH),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    vat = PercentageRegulatoryRule(
        code="vat",
        description="vat",
        category=BillingCategory.VAT,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        base_codes=("energy", "network", "threshold"),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    external = ExternalBillItem(
        code="bonus",
        description="bonus",
        category=BillingCategory.BONUS,
        quota=BillingQuota.PASS_THROUGH,
        amount=Money(amount=Decimal("-1")),
        period=PERIOD,
        credit=True,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
        reconciliation_key="bonus",
    )
    measure = BillingMeasure(
        code="reactive",
        value=Decimal("5"),
        unit=BillingMeasureUnit.KVARH,
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )

    result = RegulatoryBillingEngine().evaluate(
        request(rules=(network, threshold, vat), measures=(measure,), external_items=(external,))
    )

    assert result.bill.breakdown.total.amount == Decimal("12.31")
    assert [component.code for component in result.bill.breakdown.components] == [
        "energy",
        "regulatory:network",
        "regulatory:threshold",
        "regulatory:vat",
        "external:bonus",
    ]
    assert result.bill.breakdown.components[1].amount.amount == Decimal("2.00")
    assert result.bill.breakdown.components[2].amount.amount == Decimal("0.10")
    assert result.bill.breakdown.components[3].amount.amount == Decimal("1.21")


def test_billing_time_and_power_bases_use_explicit_proration() -> None:
    rules = (
        linear(
            "day",
            BillingBasis.PER_DAY,
            UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
            proration=ProrationPolicy.ACTUAL_DAYS,
        ),
        linear(
            "month",
            BillingBasis.PER_MONTH,
            UnitRate(amount=Decimal("30"), unit=RateUnit.EUR_PER_MONTH),
            proration=ProrationPolicy.CALENDAR_MONTH_FRACTION,
        ),
        linear(
            "year",
            BillingBasis.PER_YEAR,
            UnitRate(amount=Decimal("365"), unit=RateUnit.EUR_PER_YEAR),
            proration=ProrationPolicy.CALENDAR_YEAR_FRACTION,
        ),
        linear(
            "kw-day",
            BillingBasis.PER_KW_DAY,
            UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_DAY),
            proration=ProrationPolicy.ACTUAL_DAYS,
        ),
        linear(
            "kw-month",
            BillingBasis.PER_KW_MONTH,
            UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_MONTH),
            proration=ProrationPolicy.FULL_PERIOD,
        ),
        linear(
            "kw-year",
            BillingBasis.PER_KW_YEAR,
            UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_YEAR),
            proration=ProrationPolicy.FULL_PERIOD,
        ),
    )
    result = RegulatoryBillingEngine().evaluate(request(rules=rules))
    amounts = {
        component.reconciliation_key: component.amount.amount
        for component in result.bill.breakdown.components
    }
    assert amounts["day"] == Decimal("31")
    assert amounts["month"] == Decimal("30")
    assert amounts["year"] == Decimal("31")
    assert amounts["kw-day"] == Decimal("93")
    assert amounts["kw-month"] == Decimal("3")
    assert amounts["kw-year"] == Decimal("3")


def test_billing_quantity_ast_supports_all_nodes() -> None:
    engine = RegulatoryBillingEngine()
    measure = BillingMeasure(
        code="m",
        value=Decimal("4"),
        unit=BillingMeasureUnit.KWH,
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    req = request(measures=(measure,))
    window = PERIOD
    reference = MeasureReference(code="m", unit=BillingMeasureUnit.KWH)
    assert engine._evaluate_quantity(
        req, AddQuantity(left=reference, right=QuantityConstant(value=Decimal("1"))), window
    ) == Decimal("5")
    assert engine._evaluate_quantity(
        req, SubtractQuantity(left=reference, right=QuantityConstant(value=Decimal("1"))), window
    ) == Decimal("3")
    assert engine._evaluate_quantity(
        req, MinQuantity(left=reference, right=QuantityConstant(value=Decimal("1"))), window
    ) == Decimal("1")
    assert engine._evaluate_quantity(
        req, MaxQuantity(left=reference, right=QuantityConstant(value=Decimal("5"))), window
    ) == Decimal("5")
    assert engine._evaluate_quantity(
        req, ClampQuantity(operand=reference, cap=Decimal("3")), window
    ) == Decimal("3")
    with pytest.raises(BillingError, match="unsupported quantity expression"):
        engine._evaluate_quantity(req, cast(QuantityExpression, object()), window)


def test_billing_rejects_missing_or_unverified_inputs_without_partial_bill() -> None:
    engine = RegulatoryBillingEngine()
    base = request()
    for field, message in (
        ("pricing_result", "pricing result"),
        ("rule_set", "regulatory rule set"),
        ("classification", "supply classification"),
        ("rounding_policy", "rounding policy"),
    ):
        with pytest.raises(BillingError, match=message):
            engine.bill(base.model_copy(update={field: None}))

    unverified = linear(
        "bad",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
    ).model_copy(update={"status": VerificationStatus.UNVERIFIED})
    with pytest.raises(BillingError, match="not verified"):
        engine.bill(request(rules=(unverified,)))

    no_rule_provenance = linear(
        "bad-provenance",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
    ).model_copy(update={"provenance": ()})
    with pytest.raises(BillingError, match="provenance"):
        engine.bill(request(rules=(no_rule_provenance,)))

    base_ruleset = request().rule_set
    assert base_ruleset is not None
    no_ruleset_provenance = base_ruleset.model_copy(update={"provenance": ()})
    with pytest.raises(BillingError, match="rule set provenance"):
        engine.bill(request(rule_set=no_ruleset_provenance))


def test_billing_profile_selection_and_identity_are_validated() -> None:
    engine = RegulatoryBillingEngine()
    rule = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
    )
    profiles = (
        RegulatoryProfile(profile_code="one", voltage_level=VoltageLevel.BT, rules=(rule,)),
        RegulatoryProfile(profile_code="two", voltage_level=VoltageLevel.BT, rules=(rule,)),
    )
    with pytest.raises(BillingError, match="ambiguous"):
        engine.bill(request(rule_set=ruleset(profiles=profiles)))
    with pytest.raises(BillingError, match="missing"):
        engine.bill(
            request(
                classification=SupplyClassification(
                    contract_type_code="other",
                    voltage_level=VoltageLevel.MT,
                    usage_code="other",
                )
            )
        )

    mismatch = pricing_result().__class__.model_validate(
        pricing_result().model_dump() | {"contract_id": "other"}
    )
    with pytest.raises(BillingError, match="contract"):
        engine.bill(request(pricing=mismatch))
    mismatch_period = pricing_result().__class__.model_validate(
        pricing_result().model_dump() | {"period": {"start": "2026-02-01", "end": "2026-03-01"}}
    )
    with pytest.raises(BillingError, match="period"):
        engine.bill(request(pricing=mismatch_period))


def test_billing_parameters_measures_and_external_items_are_fail_closed() -> None:
    rule = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
    ).model_copy(update={"parameter_codes": ("missing",)})
    with pytest.raises(BillingError, match="parameter missing is missing"):
        RegulatoryBillingEngine().bill(request(rules=(rule,)))

    parameter = RegulatoryParameter(
        code="rate",
        value=Decimal("1"),
        unit="EUR/kWh",
        validity=PERIOD,
        status=VerificationStatus.UNVERIFIED,
        provenance=(SOURCE,),
    )
    rule_with_parameter = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
    ).model_copy(update={"parameter_codes": ("rate",)})
    with pytest.raises(BillingError, match="parameter rate is not verified"):
        RegulatoryBillingEngine().bill(
            request(
                rules=(rule_with_parameter,),
                rule_set=ruleset(rule_with_parameter, parameters=(parameter,)),
            )
        )

    measure_rule = linear(
        "reactive",
        BillingBasis.PER_KVARH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KVARH),
        measure_code="m",
    )
    with pytest.raises(BillingError, match="measure m is missing"):
        RegulatoryBillingEngine().bill(request(rules=(measure_rule,)))
    bad_measure = BillingMeasure(
        code="m",
        value=Decimal("1"),
        unit=BillingMeasureUnit.KWH,
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    with pytest.raises(BillingError, match="unit"):
        RegulatoryBillingEngine().bill(request(rules=(measure_rule,), measures=(bad_measure,)))

    item = ExternalBillItem(
        code="other",
        description="other",
        category=BillingCategory.OTHER,
        amount=Money(amount=Decimal("1")),
        period=PERIOD,
        status=VerificationStatus.UNVERIFIED,
        provenance=(SOURCE,),
        reconciliation_key="other",
    )
    with pytest.raises(BillingError, match="external bill item"):
        RegulatoryBillingEngine().bill(request(external_items=(item,)))


def test_billing_sign_units_proration_and_percentage_dependencies_fail_closed() -> None:
    bad_sign = linear(
        "bad",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("-1"), unit=RateUnit.EUR_PER_KWH),
    )
    with pytest.raises(BillingError, match="negative amount"):
        RegulatoryBillingEngine().bill(request(rules=(bad_sign,)))
    no_proration = linear(
        "daily",
        BillingBasis.PER_DAY,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
    )
    with pytest.raises(BillingError, match="proration"):
        RegulatoryBillingEngine().bill(request(rules=(no_proration,)))
    wrong_rate = linear(
        "wrong",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
    )
    with pytest.raises(BillingError, match="requires"):
        RegulatoryBillingEngine().bill(request(rules=(wrong_rate,)))
    percentage = PercentageRegulatoryRule(
        code="vat",
        description="vat",
        category=BillingCategory.VAT,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        base_codes=("missing",),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    with pytest.raises(BillingError, match="base missing"):
        RegulatoryBillingEngine().bill(request(rules=(percentage,)))


def test_billing_reconciliation_is_explicit_and_does_not_change_bill() -> None:
    rule = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("0.02"), unit=RateUnit.EUR_PER_KWH),
        quota=BillingQuota.CONSUMPTION,
    )
    engine = RegulatoryBillingEngine()
    base = request(rules=(rule,))
    calculated = engine.evaluate(base)
    observed_components = tuple(
        ObservedBillComponent(
            reconciliation_key=component.reconciliation_key or component.code,
            code=component.code,
            description=component.description,
            category=component.category or BillingCategory.OTHER,
            quota=component.quota or BillingQuota.FIXED,
            amount=component.amount,
            period=component.period,
        )
        for component in calculated.bill.breakdown.components
    )
    observed = ObservedBill(
        bill_id="observed",
        contract_id="contract-004",
        period=PERIOD,
        components=observed_components,
        declared_total=calculated.bill.breakdown.total,
        provenance=(SOURCE,),
    )
    result = engine.evaluate(base.model_copy(update={"observed_bill": observed}))
    assert result.bill.bill_id == calculated.bill.bill_id
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.PASSED
    assert result.reconciliation.total_difference == Money(amount=Decimal("0"))

    one_cent = observed.model_copy(
        update={
            "components": (
                observed.components[0].model_copy(
                    update={
                        "amount": Money(
                            amount=observed.components[0].amount.amount + Decimal("0.01")
                        )
                    }
                ),
                *observed.components[1:],
            ),
            "declared_total": Money(
                amount=(observed.declared_total or Money(amount=Decimal("0"))).amount
                + Decimal("0.01")
            ),
        }
    )
    one_cent_result = engine.evaluate(base.model_copy(update={"observed_bill": one_cent}))
    assert one_cent_result.reconciliation is not None
    assert one_cent_result.reconciliation.status == ReconciliationStatus.PASSED
    two_cents = one_cent.model_copy(
        update={
            "components": (
                one_cent.components[0].model_copy(
                    update={
                        "amount": Money(
                            amount=one_cent.components[0].amount.amount + Decimal("0.01")
                        )
                    }
                ),
                *one_cent.components[1:],
            )
        }
    )
    failed = engine.evaluate(base.model_copy(update={"observed_bill": two_cents}))
    assert failed.reconciliation is not None
    assert failed.reconciliation.status == ReconciliationStatus.FAILED
    assert failed.reconciliation.components[0].within_tolerance is False

    unmatched = observed.model_copy(
        update={
            "components": (
                *observed.components[:-1],
                observed.components[-1].model_copy(update={"reconciliation_key": "unknown"}),
            )
        }
    )
    unmatched_result = engine.evaluate(base.model_copy(update={"observed_bill": unmatched}))
    assert unmatched_result.reconciliation is not None
    assert unmatched_result.reconciliation.status == ReconciliationStatus.FAILED
    assert unmatched_result.reconciliation.unmatched_computed


def test_legacy_bill_observation_and_model_round_trip() -> None:
    engine = RegulatoryBillingEngine()
    base = request()
    calculated = engine.evaluate(base)
    observed_bill = calculated.bill
    result = engine.evaluate(base.model_copy(update={"observed_bill": observed_bill}))
    assert result.reconciliation is not None
    assert result.reconciliation.status == ReconciliationStatus.PASSED
    assert BillingResult.model_validate_json(result.model_dump_json()) == result
    assert (
        BillReconciliation.model_validate_json(result.reconciliation.model_dump_json())
        == result.reconciliation
    )
    with pytest.raises(ValidationError):
        result.bill.breakdown.total = Money(amount=Decimal("1"))  # type: ignore[misc]


def test_billing_ids_are_stable_and_observed_does_not_affect_bill_id() -> None:
    engine = RegulatoryBillingEngine()
    first = engine.evaluate(request())
    observed = first.bill
    second = engine.evaluate(request(observed=observed))
    assert first.bill.bill_id == second.bill.bill_id
    assert first.billing_id != second.billing_id
    payload = request().model_dump(mode="json", exclude={"observed_bill"})
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert first.bill.bill_id == f"bill:{__import__('hashlib').sha256(encoded).hexdigest()}"


def test_billing_profile_filters_cover_all_selectors_and_power_bounds() -> None:
    rule = linear(
        "network", BillingBasis.PER_KWH, UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)
    )
    classification = SupplyClassification(
        contract_type_code="domestic_bt_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=True,
        tax_profile_code="standard",
        eligibility_codes=("resident",),
    )
    matching = RegulatoryProfile(
        profile_code="matching",
        contract_type_code="domestic_bt_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=True,
        tax_profile_code="standard",
        required_eligibility_codes=("resident",),
        min_contracted_power_kw=Decimal("3"),
        max_contracted_power_kw=Decimal("3"),
        rules=(rule,),
    )
    result = RegulatoryBillingEngine().evaluate(
        request(classification=classification, rule_set=ruleset(profiles=(matching,)))
    )
    assert result.bill.breakdown.components[-1].reconciliation_key == "network"

    for update in (
        {"contract_type_code": "other"},
        {"voltage_level": VoltageLevel.MT},
        {"usage_code": "other"},
        {"residential": False},
        {"tax_profile_code": "other"},
        {"required_eligibility_codes": ("other",)},
    ):
        profile = matching.model_copy(update=update)
        with pytest.raises(BillingError, match="missing"):
            RegulatoryBillingEngine().bill(
                request(classification=classification, rule_set=ruleset(profiles=(profile,)))
            )
    too_low = matching.model_copy(
        update={"min_contracted_power_kw": Decimal("4"), "max_contracted_power_kw": Decimal("5")}
    )
    with pytest.raises(BillingError, match="missing"):
        RegulatoryBillingEngine().bill(
            request(classification=classification, rule_set=ruleset(profiles=(too_low,)))
        )
    too_high = matching.model_copy(
        update={"min_contracted_power_kw": Decimal("1"), "max_contracted_power_kw": Decimal("2")}
    )
    with pytest.raises(BillingError, match="missing"):
        RegulatoryBillingEngine().bill(
            request(classification=classification, rule_set=ruleset(profiles=(too_high,)))
        )


def test_billing_ruleset_validity_parameters_and_rule_windows_fail_closed() -> None:
    engine = RegulatoryBillingEngine()
    base = request()
    assert base.rule_set is not None
    unverified_set = base.rule_set.model_copy(update={"status": VerificationStatus.REVIEW_REQUIRED})
    with pytest.raises(BillingError, match="rule set is not verified"):
        engine.bill(base.model_copy(update={"rule_set": unverified_set}))
    outside = base.rule_set.model_copy(
        update={"validity": DatePeriod(start=date(2026, 2, 1), end=date(2026, 3, 1))}
    )
    with pytest.raises(BillingError, match="outside"):
        engine.bill(base.model_copy(update={"rule_set": outside}))
    parameter = RegulatoryParameter(
        code="p",
        value=Decimal("1"),
        unit="EUR/kWh",
        validity=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    rule = linear(
        "p-rule", BillingBasis.PER_KWH, UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)
    ).model_copy(update={"parameter_codes": ("p",)})
    valid = engine.evaluate(request(rules=(rule,), rule_set=ruleset(rule, parameters=(parameter,))))
    assert SOURCE in valid.bill.provenance
    missing_provenance = parameter.model_copy(update={"provenance": ()})
    with pytest.raises(BillingError, match="provenance"):
        engine.bill(
            request(rules=(rule,), rule_set=ruleset(rule, parameters=(missing_provenance,)))
        )
    outside_parameter = parameter.model_copy(
        update={"validity": DatePeriod(start=date(2026, 1, 2), end=date(2026, 2, 1))}
    )
    with pytest.raises(BillingError, match="does not cover"):
        engine.bill(request(rules=(rule,), rule_set=ruleset(rule, parameters=(outside_parameter,))))
    windowless = linear(
        "future", BillingBasis.PER_KWH, UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)
    ).model_copy(update={"validity": DatePeriod(start=date(2027, 1, 1), end=date(2027, 2, 1))})
    no_window = engine.evaluate(request(rules=(windowless,)))
    assert all(
        component.reconciliation_key != "future"
        for component in no_window.bill.breakdown.components
    )


def test_billing_component_key_validation_and_commercial_defaults() -> None:
    engine = RegulatoryBillingEngine()
    first = pricing_result()
    duplicate_component = first.breakdown.components[0].model_copy()
    duplicate_pricing = first.model_copy(
        update={
            "breakdown": CostBreakdown(
                components=(first.breakdown.components[0], duplicate_component),
                total=Money(amount=Decimal("20")),
            )
        }
    )
    with pytest.raises(BillingError, match="duplicate billing component keys"):
        engine.bill(request(pricing=duplicate_pricing))
    duplicate_rule = linear(
        "energy", BillingBasis.PER_KWH, UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)
    )
    with pytest.raises(BillingError, match="duplicate billing component key"):
        engine.bill(request(rules=(duplicate_rule,)))
    item = ExternalBillItem(
        code="energy",
        description="duplicate",
        category=BillingCategory.OTHER,
        amount=Money(amount=Decimal("0")),
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
        reconciliation_key="energy",
    )
    with pytest.raises(BillingError, match="duplicate billing component key"):
        engine.bill(request(external_items=(item,)))
    fixed = CostComponent(
        code="fixed",
        description="fixed",
        amount=Money(amount=Decimal("1")),
        period=PERIOD,
        formula="fixed",
        provenance=(SOURCE,),
    )
    variable = fixed.model_copy(update={"code": "variable", "quantity": Decimal("2")})
    assert engine._commercial_component(fixed).quota == BillingQuota.FIXED
    assert engine._commercial_component(variable).quota == BillingQuota.CONSUMPTION
    assert (
        engine._commercial_component(fixed.model_copy(update={"quota": BillingQuota.POWER})).quota
        == BillingQuota.POWER
    )


def test_billing_linear_measure_and_boundary_errors() -> None:
    engine = RegulatoryBillingEngine()
    kvarh_rule = linear(
        "reactive",
        BillingBasis.PER_KVARH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KVARH),
        measure_code="r",
    )
    kvarh_no_code = kvarh_rule.model_copy(update={"measure_code": None})
    with pytest.raises(BillingError, match="measure code"):
        engine.bill(request(rules=(kvarh_no_code,)))
    measure = BillingMeasure(
        code="r",
        value=Decimal("2"),
        unit=BillingMeasureUnit.KVARH,
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    duplicate = measure.model_copy()
    with pytest.raises(BillingError, match="ambiguous"):
        engine.bill(request(rules=(kvarh_rule,), measures=(measure, duplicate)))
    with pytest.raises(BillingError, match="not verified"):
        engine.bill(
            request(
                rules=(kvarh_rule,),
                measures=(measure.model_copy(update={"status": VerificationStatus.UNVERIFIED}),),
            )
        )
    with pytest.raises(BillingError, match="provenance"):
        engine.bill(
            request(rules=(kvarh_rule,), measures=(measure.model_copy(update={"provenance": ()}),))
        )
    short_measure = measure.model_copy(
        update={"period": DatePeriod(start=date(2026, 1, 2), end=date(2026, 2, 1))}
    )
    with pytest.raises(BillingError, match="cover"):
        engine.bill(request(rules=(kvarh_rule,), measures=(short_measure,)))
    bucket = request().consumption.buckets[0]
    crossing = bucket.model_copy(
        update={
            "interval": TimeInterval(
                start=datetime(2025, 12, 31, 23, tzinfo=ROME),
                end=datetime(2026, 1, 1, 1, tzinfo=ROME),
            )
        }
    )
    with pytest.raises(BillingError, match="crosses requested"):
        engine.bill(
            request().model_copy(
                update={
                    "consumption": request().consumption.model_copy(update={"buckets": (crossing,)})
                }
            )
        )
    with pytest.raises(BillingError, match="crosses regulatory"):
        narrow_rule = linear(
            "narrow",
            BillingBasis.PER_KWH,
            UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
        ).model_copy(update={"validity": DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2))})
        regulatory_crossing = bucket.model_copy(
            update={
                "interval": TimeInterval(
                    start=datetime(2026, 1, 1, tzinfo=ROME),
                    end=datetime(2026, 1, 3, tzinfo=ROME),
                )
            }
        )
        engine.bill(
            request(
                rules=(narrow_rule,),
            ).model_copy(
                update={
                    "consumption": request().consumption.model_copy(
                        update={"buckets": (regulatory_crossing,)}
                    )
                }
            )
        )


def test_billing_power_defaults_and_rule_type_errors() -> None:
    engine = RegulatoryBillingEngine()
    power_rule = linear(
        "power",
        BillingBasis.PER_KW_DAY,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_DAY),
        proration=ProrationPolicy.FULL_PERIOD,
    )
    no_power_contract = contract().model_copy(
        update={"supply": contract().supply.model_copy(update={"contracted_power": None})}
    )
    with pytest.raises(BillingError, match="contracted power"):
        engine.bill(request(rules=(power_rule,)).model_copy(update={"contract": no_power_contract}))
    consumption_measure_rule = linear(
        "consumption",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
        measure_code="consumption_kwh",
    )
    result = engine.evaluate(request(rules=(consumption_measure_rule,)))
    assert result.bill.breakdown.components[-1].quantity == Decimal("100")
    contracted_measure_rule = ThresholdRegulatoryRule(
        code="contracted",
        description="contracted",
        category=BillingCategory.NETWORK,
        quota=BillingQuota.POWER,
        validity=PERIOD,
        quantity=MeasureReference(code="contracted_power_kw", unit=BillingMeasureUnit.KW),
        rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_DAY),
        provenance=(SOURCE,),
        status=VerificationStatus.VERIFIED,
    )
    result = engine.evaluate(request(rules=(contracted_measure_rule,)))
    assert result.bill.breakdown.components[-1].quantity == Decimal("3")
    flat = linear("flat", BillingBasis.FLAT, Money(amount=Decimal("1")))
    assert engine.evaluate(request(rules=(flat,))).bill.breakdown.components[
        -1
    ].amount.amount == Decimal("1.00")
    bad_flat = flat.model_copy(
        update={"value": UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY)}
    )
    with pytest.raises(BillingError, match="flat basis"):
        engine.bill(request(rules=(bad_flat,)))
    bad_linear = linear("bad", BillingBasis.PER_KWH, Money(amount=Decimal("1")))
    with pytest.raises(BillingError, match="requires a unit rate"):
        engine.bill(request(rules=(bad_linear,)))
    percentage_basis = linear(
        "bad-percent", BillingBasis.PERCENTAGE, UnitRate(amount=Decimal("1"), unit=RateUnit.PERCENT)
    )
    with pytest.raises(BillingError, match="percentage basis"):
        engine.bill(request(rules=(percentage_basis,)))


def test_billing_threshold_percentage_signs_proration_and_external_validation() -> None:
    engine = RegulatoryBillingEngine()
    negative_threshold = ThresholdRegulatoryRule(
        code="negative",
        description="negative",
        category=BillingCategory.EXCISE,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        quantity=QuantityConstant(value=Decimal("-1")),
        rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
        provenance=(SOURCE,),
        status=VerificationStatus.VERIFIED,
    )
    with pytest.raises(BillingError, match="negative quantity"):
        engine.bill(request(rules=(negative_threshold,)))
    unsupported_threshold = negative_threshold.model_copy(
        update={
            "quantity": QuantityConstant(value=Decimal("1")),
            "rate": UnitRate(amount=Decimal("1"), unit=RateUnit.PERCENT),
        }
    )
    with pytest.raises(BillingError, match="unsupported rate"):
        engine.bill(request(rules=(unsupported_threshold,)))
    mismatched_threshold = unsupported_threshold.model_copy(
        update={
            "rate": UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KVARH),
            "quantity": MeasureReference(code="m", unit=BillingMeasureUnit.KWH),
        }
    )
    measure = BillingMeasure(
        code="m",
        value=Decimal("1"),
        unit=BillingMeasureUnit.KWH,
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    with pytest.raises(BillingError, match="quantity unit"):
        engine.bill(request(rules=(mismatched_threshold,), measures=(measure,)))
    percentage_wrong = PercentageRegulatoryRule(
        code="vat",
        description="vat",
        category=BillingCategory.VAT,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
        base_codes=("energy",),
        provenance=(SOURCE,),
        status=VerificationStatus.VERIFIED,
    )
    with pytest.raises(BillingError, match="requires percent"):
        engine.bill(request(rules=(percentage_wrong,)))
    credit = linear("credit", BillingBasis.FLAT, Money(amount=Decimal("1")), credit=True)
    with pytest.raises(BillingError, match="positive amount"):
        engine.bill(request(rules=(credit,)))
    invalid_proration = linear(
        "time",
        BillingBasis.PER_DAY,
        UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
        proration=ProrationPolicy.ACTUAL_DAYS,
    )
    invalid_proration = invalid_proration.model_copy(update={"proration": object()})
    with pytest.raises(BillingError, match="unsupported proration"):
        engine.bill(request(rules=(invalid_proration,)))
    december = DatePeriod(start=date(2026, 12, 1), end=date(2027, 1, 1))
    assert RegulatoryBillingEngine._next_month(date(2026, 12, 1)) == date(2027, 1, 1)
    assert RegulatoryBillingEngine._time_quantity(
        december, ProrationPolicy.CALENDAR_MONTH_FRACTION
    ) == Decimal(1)
    external = ExternalBillItem(
        code="x",
        description="x",
        category=BillingCategory.OTHER,
        amount=Money(amount=Decimal("1")),
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(),
        reconciliation_key="x",
    )
    with pytest.raises(BillingError, match="provenance"):
        engine.bill(request(external_items=(external,)))
    outside = external.model_copy(
        update={
            "provenance": (SOURCE,),
            "period": DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 2)),
        }
    )
    with pytest.raises(BillingError, match="outside"):
        engine.bill(request(external_items=(outside,)))


def test_billing_reconciliation_mismatch_and_observed_shape_errors() -> None:
    engine = RegulatoryBillingEngine()
    base = request()
    calculated = engine.evaluate(base)
    observed = calculated.bill
    mismatch = observed.model_copy(update={"contract_id": "other"})
    with pytest.raises(BillingError, match="observed bill contract"):
        engine.bill(base.model_copy(update={"observed_bill": mismatch}))
    component = calculated.bill.breakdown.components[0]
    duplicated_bill = calculated.bill.model_copy(
        update={
            "breakdown": CostBreakdown(
                components=(component, component),
                total=Money(amount=component.amount.amount * 2),
            ),
            "declared_total": Money(amount=component.amount.amount * 2),
        }
    )
    with pytest.raises(BillingError, match="duplicate reconciliation"):
        engine.bill(base.model_copy(update={"observed_bill": duplicated_bill}))
    observed_component = ObservedBillComponent(
        reconciliation_key="unknown",
        code="unknown",
        description="unknown",
        category=BillingCategory.OTHER,
        quota=BillingQuota.FIXED,
        amount=Money(amount=Decimal("1")),
        period=PERIOD,
    )
    extra = ObservedBill(
        bill_id="observed",
        contract_id="contract-004",
        period=PERIOD,
        components=(observed_component,),
        declared_total=Money(amount=Decimal("1")),
        provenance=(SOURCE,),
    )
    result = engine.evaluate(base.model_copy(update={"observed_bill": extra}))
    assert result.reconciliation is not None
    assert result.reconciliation.unmatched_observed == ("unknown",)
    assert result.reconciliation.total_difference is not None
    outside_component = observed_component.model_copy(
        update={"period": DatePeriod(start=date(2025, 1, 1), end=date(2025, 2, 1))}
    )
    outside_observed = extra.model_copy(update={"components": (outside_component,)})
    with pytest.raises(BillingError, match="outside computed period"):
        engine.bill(base.model_copy(update={"observed_bill": outside_observed}))


def test_billing_json_models_reject_non_decimal_and_extra_fields() -> None:
    with pytest.raises((TypeError, ValidationError)):
        BillingMeasure.model_validate(
            {"code": "x", "value": 1.2, "unit": BillingMeasureUnit.KWH, "period": PERIOD}
        )
    with pytest.raises(ValidationError):
        SupplyClassification.model_validate(
            {
                "contract_type_code": "x",
                "voltage_level": VoltageLevel.BT,
                "usage_code": "x",
                "extra_field": "no",
            }
        )
    with pytest.raises(ValidationError):
        QuantityConstant.model_validate({"value": "NaN"})
    with pytest.raises(ValidationError):
        QuantityConstant.model_validate({"value": "Infinity"})
    with pytest.raises(ValidationError):
        RegulatoryProfile(profile_code="x", rules=())
    with pytest.raises(ValidationError):
        PercentageRegulatoryRule(
            code="x",
            description="x",
            category=BillingCategory.VAT,
            quota=BillingQuota.TAX,
            validity=PERIOD,
            rate=UnitRate(amount=Decimal("1"), unit=RateUnit.PERCENT),
            base_codes=("a", "a"),
        )


def test_billing_percentage_categories_and_dependency_order_are_explicit() -> None:
    network = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("0.02"), unit=RateUnit.EUR_PER_KWH),
        quota=BillingQuota.CONSUMPTION,
    )
    vat = PercentageRegulatoryRule(
        code="vat",
        description="vat",
        category=BillingCategory.VAT,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        base_categories=(BillingCategory.NETWORK,),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    surcharge = PercentageRegulatoryRule(
        code="surcharge",
        description="surcharge",
        category=BillingCategory.OTHER,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        base_codes=("vat",),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    result = RegulatoryBillingEngine().evaluate(request(rules=(network, surcharge, vat)))
    amounts = {
        component.reconciliation_key: component.amount.amount
        for component in result.bill.breakdown.components
    }
    assert amounts["vat"] == Decimal("0.20")
    assert amounts["surcharge"] == Decimal("0.02")
    first = surcharge.model_copy(update={"base_codes": ("surcharge-2",)})
    second = surcharge.model_copy(update={"code": "surcharge-2", "base_codes": ("surcharge",)})
    with pytest.raises(BillingError, match="missing or cyclic"):
        RegulatoryBillingEngine().bill(request(rules=(network, first, second)))


def test_public_synthetic_golden_fixture_matches_calculated_bill() -> None:
    fixture_path = Path(__file__).parents[1] / "golden" / "billing-domestic-bt-resident.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    network = linear(
        "network",
        BillingBasis.PER_KWH,
        UnitRate(amount=Decimal("0.02"), unit=RateUnit.EUR_PER_KWH),
        quota=BillingQuota.CONSUMPTION,
    )
    threshold = ThresholdRegulatoryRule(
        code="threshold",
        description="threshold",
        category=BillingCategory.EXCISE,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        quantity=QuantityConstant(value=Decimal("10")),
        rate=UnitRate(amount=Decimal("0.01"), unit=RateUnit.EUR_PER_KWH),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    vat = PercentageRegulatoryRule(
        code="vat",
        description="vat",
        category=BillingCategory.VAT,
        quota=BillingQuota.TAX,
        validity=PERIOD,
        rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        base_codes=("energy", "network", "threshold"),
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    bonus = ExternalBillItem(
        code="bonus",
        description="bonus",
        category=BillingCategory.BONUS,
        amount=Money(amount=Decimal("-1")),
        period=PERIOD,
        credit=True,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
        reconciliation_key="bonus",
    )
    result = RegulatoryBillingEngine().evaluate(
        request(rules=(network, threshold, vat), external_items=(bonus,))
    )
    assert result.bill.contract_id == fixture["contract_id"]
    assert result.bill.period.model_dump(mode="json") == fixture["period"]
    amounts = {
        component.reconciliation_key: component.amount.amount
        for component in result.bill.breakdown.components
    }
    assert amounts == {
        item["reconciliation_key"]: Decimal(item["amount"]) for item in fixture["components"]
    }
    assert result.bill.breakdown.total.amount == Decimal(fixture["total"])
