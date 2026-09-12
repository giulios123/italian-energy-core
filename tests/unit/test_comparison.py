from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.billing import BillingError, load_coverage_matrix, load_ruleset
from italian_energy.comparison import (
    AlternativePricing,
    ComparisonContext,
    ComparisonError,
    ComparisonRequest,
    DeterministicComparisonEngine,
    OfferExclusionCode,
)
from italian_energy.domain import (
    ConsumptionBucket,
    ConsumptionProfile,
    Contract,
    DatePeriod,
    EnergyQuantity,
    FixedTariff,
    Granularity,
    IndexedTariff,
    MarketData,
    MarketDataPoint,
    MarketIndex,
    Money,
    Offer,
    Power,
    Provenance,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    SupplyClassification,
    SupplyPoint,
    TimeInterval,
    UnitRate,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.domain.costs import (
    Bill,
    BillingResult,
    CostBreakdown,
    ExternalBillItem,
    PricingResult,
)
from italian_energy.domain.formula import IndexReference
from italian_energy.domain.regulatory import BillingCategory
from italian_energy.domain.tariff import BandFormula, BandPrice

ROME = ZoneInfo("Europe/Rome")
PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
AS_OF = date(2026, 1, 15)
ROUNDING = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)
PERCENTAGE_ROUNDING = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)


def _supply() -> SupplyPoint:
    return SupplyPoint(
        supply_id="pod-1",
        market_zone="NORD",
        contracted_power=Power(kw=Decimal("2")),
        residential=True,
    )


def _contract(tariff: FixedTariff | IndexedTariff, contract_id: str = "current") -> Contract:
    return Contract(
        contract_id=contract_id,
        supply=_supply(),
        tariff=tariff,
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
    )


def _fixed_tariff(rate: str, tariff_id: str) -> FixedTariff:
    return FixedTariff(
        tariff_id=tariff_id,
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        prices=(
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal(rate), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
    )


def _indexed_tariff(tariff_id: str) -> IndexedTariff:
    return IndexedTariff(
        tariff_id=tariff_id,
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        granularity=Granularity.HOUR,
        formulas=(
            BandFormula(
                band="ALL",
                expression=IndexReference(
                    index_code="PUN_TEST",
                    unit=RateUnit.EUR_PER_MWH,
                    granularity=Granularity.HOUR,
                ),
            ),
        ),
    )


def _consumption() -> ConsumptionProfile:
    return ConsumptionProfile(
        profile_id="consumption-1",
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
    )


def _classification() -> SupplyClassification:
    return SupplyClassification(
        contract_type_code="domestic_bt_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=True,
    )


def _request(
    offers: tuple[Offer, ...],
    *,
    current_contract: Contract | None = None,
    period: DatePeriod = PERIOD,
    as_of: date = AS_OF,
    market_data: MarketData | None = None,
    external_items: tuple[ExternalBillItem, ...] = (),
) -> ComparisonRequest:
    ruleset = load_ruleset(segment="resident")
    return ComparisonRequest(
        current_contract=current_contract or _contract(_fixed_tariff("0.20", "current")),
        consumption=_consumption(),
        available_offers=offers,
        period=period,
        as_of=as_of,
        classification=_classification(),
        rule_set=ruleset,
        coverage_matrix=load_coverage_matrix(),
        rounding_policy=ROUNDING,
        percentage_rounding_policy=PERCENTAGE_ROUNDING,
        market_data=market_data,
        external_items=external_items,
    )


def _offer(offer_id: str, rate: str, *, period: DatePeriod | None = None) -> Offer:
    return Offer(
        offer_id=offer_id,
        supplier_id=f"supplier-{offer_id}",
        name=f"Offer {offer_id}",
        subscription_period=period or DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        tariff=_fixed_tariff(rate, f"tariff-{offer_id}"),
    )


def test_comparison_ranks_all_in_totals_and_is_order_independent() -> None:
    offers = (_offer("expensive", "0.30"), _offer("cheap", "0.10"))
    first = DeterministicComparisonEngine().compare(_request(offers))
    second = DeterministicComparisonEngine().compare(_request(tuple(reversed(offers))))

    assert first.ranking == ("cheap", "expensive")
    assert first.ranking == second.ranking
    assert first.comparison_id == second.comparison_id
    assert [item.offer_id for item in first.alternatives] == ["cheap", "expensive"]
    assert all(
        item.billing is not None and item.billing.bill.breakdown.total.amount > 0
        for item in first.alternatives
    )
    savings = first.alternatives[0].savings
    assert savings is not None
    assert savings.amount > 0
    percentage = first.alternatives[0].percentage_difference
    assert percentage is not None
    assert percentage > 0


def test_comparison_supports_indexed_candidate_with_shared_market_data() -> None:
    indexed = Offer(
        offer_id="indexed",
        supplier_id="supplier-indexed",
        name="Indexed",
        subscription_period=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        tariff=_indexed_tariff("indexed"),
    )
    market = MarketData(
        indexes=(
            MarketIndex(
                code="PUN_TEST",
                name="Synthetic PUN",
                unit=RateUnit.EUR_PER_MWH,
                granularity=Granularity.HOUR,
            ),
        ),
        points=(
            MarketDataPoint(
                index_code="PUN_TEST",
                interval=TimeInterval(
                    start=datetime(2026, 1, 1, tzinfo=ROME),
                    end=datetime(2026, 1, 1, 1, tzinfo=ROME),
                ),
                value=Decimal("100"),
            ),
        ),
    )
    result = DeterministicComparisonEngine().compare(_request((indexed,), market_data=market))
    assert result.ranking == ("indexed",)
    assert result.alternatives[0].pricing.pricing_id.startswith("indexed:")


def test_external_items_are_visible_but_do_not_change_ranking() -> None:
    provenance = Provenance(
        source="fixture",
        source_identifier="external-1",
        retrieved_at=datetime(2026, 1, 1, tzinfo=ROME),
    )
    item = ExternalBillItem(
        code="tv-fee",
        description="Canone TV",
        category=BillingCategory.TV_FEE,
        amount=Money(amount=Decimal("99.00")),
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(provenance,),
        reconciliation_key="tv-fee",
    )
    without = DeterministicComparisonEngine().compare(_request((_offer("cheap", "0.10"),)))
    with_extra = DeterministicComparisonEngine().compare(
        _request((_offer("cheap", "0.10"),), external_items=(item,))
    )
    assert without.ranking == with_extra.ranking
    assert without.alternatives[0].comparable_total == with_extra.alternatives[0].comparable_total
    assert with_extra.excluded_external_total.amount == Decimal("99.00")
    assert len(with_extra.excluded_external_items) == 1


def test_not_current_and_same_current_offers_are_excluded() -> None:
    current = _contract(_fixed_tariff("0.20", "current"))
    offers = (
        _offer("future", "0.10", period=DatePeriod(start=date(2026, 2, 1), end=date(2027, 1, 1))),
        Offer(
            offer_id="current-offer",
            supplier_id="supplier-current",
            name="Current",
            subscription_period=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
            tariff=_fixed_tariff("0.20", "current-offer"),
        ),
    )
    current = current.model_copy(update={"source_offer_id": "current-offer"})
    result = DeterministicComparisonEngine().compare(_request(offers, current_contract=current))
    assert result.ranking == ()
    assert {item.offer_id: item.code for item in result.excluded_offers} == {
        "future": OfferExclusionCode.NOT_CURRENT,
        "current-offer": OfferExclusionCode.SAME_AS_CURRENT,
    }


def test_candidate_pricing_failure_is_isolated() -> None:
    valid = _offer("valid", "0.10")
    invalid_market = Offer(
        offer_id="needs-market",
        supplier_id="supplier-market",
        name="Needs market",
        subscription_period=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        tariff=_indexed_tariff("needs-market"),
    )
    result = DeterministicComparisonEngine().compare(_request((invalid_market, valid)))
    assert result.ranking == ("valid",)
    assert result.excluded_offers[0].offer_id == "needs-market"
    assert result.excluded_offers[0].code == OfferExclusionCode.PRICING_FAILED


def test_candidate_billing_failure_is_isolated() -> None:
    engine = DeterministicComparisonEngine()
    original = engine._bill

    def fail_candidate(
        request: ComparisonRequest, contract: Contract, pricing: PricingResult
    ) -> BillingResult:
        if contract.source_offer_id == "broken-billing":
            from italian_energy.billing import BillingError

            raise BillingError("synthetic billing failure")
        return original(request, contract, pricing)

    with patch.object(engine, "_bill", side_effect=fail_candidate):
        result = engine.compare(
            _request((_offer("broken-billing", "0.10"), _offer("valid", "0.12")))
        )
    assert result.ranking == ("valid",)
    assert result.excluded_offers[0].code == OfferExclusionCode.BILLING_FAILED


def test_global_coverage_failure_is_fail_closed() -> None:
    matrix = load_coverage_matrix()
    ruleset = load_ruleset(segment="resident")
    request = _request((_offer("cheap", "0.10"),)).model_copy(
        update={
            "period": DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 1)),
            "coverage_matrix": matrix,
            "rule_set": ruleset,
        }
    )
    with pytest.raises(ComparisonError, match="coverage"):
        DeterministicComparisonEngine().compare(request)


def test_current_pricing_and_billing_failures_are_global() -> None:
    request = _request((_offer("candidate", "0.10"),))
    engine = DeterministicComparisonEngine()
    with (
        patch.object(engine, "_price", side_effect=ComparisonError("synthetic pricing failure")),
        pytest.raises(ComparisonError, match="current pricing"),
    ):
        engine.compare(request)
    with (
        patch.object(engine, "_bill", side_effect=BillingError("synthetic billing failure")),
        pytest.raises(ComparisonError, match="current billing"),
    ):
        engine.compare(request)


def test_global_validation_rejects_as_of_ruleset_and_matrix_mismatch() -> None:
    base = _request((_offer("candidate", "0.10"),))
    with pytest.raises(ComparisonError, match="as_of"):
        DeterministicComparisonEngine().compare(base.model_copy(update={"as_of": date(2027, 1, 1)}))
    with pytest.raises(ComparisonError, match="ruleset is not verified"):
        DeterministicComparisonEngine().compare(
            base.model_copy(
                update={"rule_set": base.rule_set.model_copy(update={"status": "unverified"})}
            )
        )
    with pytest.raises(ComparisonError, match="provenance"):
        DeterministicComparisonEngine().compare(
            base.model_copy(
                update={"rule_set": base.rule_set.model_copy(update={"provenance": ()})}
            )
        )
    bad_entry = base.coverage_matrix.entries[0].model_copy(update={"profile_code": "other"})
    with pytest.raises(ComparisonError, match="profile does not match"):
        DeterministicComparisonEngine().compare(
            base.model_copy(
                update={
                    "coverage_matrix": base.coverage_matrix.model_copy(
                        update={"entries": (bad_entry,)}
                    )
                }
            )
        )


def test_period_exclusion_and_non_positive_warning() -> None:
    invalid_period = _offer(
        "outside",
        "0.10",
        period=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
    ).model_copy(
        update={
            "tariff": _fixed_tariff("0.10", "outside").model_copy(
                update={"validity": DatePeriod(start=date(2026, 2, 1), end=date(2027, 1, 1))}
            )
        }
    )
    result = DeterministicComparisonEngine().compare(_request((invalid_period,)))
    assert result.excluded_offers[0].code == OfferExclusionCode.PERIOD_NOT_COVERED

    zero_breakdown = CostBreakdown(total=Money(amount=Decimal("0")))
    zero_bill = BillingResult(
        billing_id="zero",
        bill=Bill(bill_id="zero", contract_id="current", period=PERIOD, breakdown=zero_breakdown),
    )
    engine = DeterministicComparisonEngine()
    with patch.object(engine, "_bill", return_value=zero_bill):
        result = engine.compare(_request((_offer("candidate", "0.10"),)))
    assert any("non-positive" in warning for warning in result.warnings)


def test_external_item_validation_and_result_invariants() -> None:
    provenance = Provenance(
        source="fixture",
        source_identifier="external-1",
        retrieved_at=datetime(2026, 1, 1, tzinfo=ROME),
    )
    base_item = ExternalBillItem(
        code="extra",
        description="Extra",
        category=BillingCategory.OTHER,
        amount=Money(amount=Decimal("1")),
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(provenance,),
        reconciliation_key="same",
    )
    with pytest.raises(ValidationError, match="external item keys"):
        _request((_offer("one", "0.10"),), external_items=(base_item, base_item))
    with pytest.raises(ValidationError, match="contained"):
        _request(
            (_offer("one", "0.10"),),
            external_items=(
                base_item.model_copy(
                    update={"period": DatePeriod(start=date(2025, 1, 1), end=date(2025, 2, 1))}
                ),
            ),
        )

    pricing = PricingResult(
        pricing_id="p",
        contract_id="c",
        period=PERIOD,
        breakdown=CostBreakdown(total=Money(amount=Decimal("0"))),
    )
    alternative = AlternativePricing(
        offer_id="same",
        pricing=pricing,
        absolute_difference=Money(amount=Decimal("0")),
    )
    with pytest.raises(ValidationError, match="alternative offer ids"):
        from italian_energy.comparison import ComparisonResult

        ComparisonResult(
            comparison_id="c",
            current_contract_id="c",
            current_pricing=pricing,
            alternatives=(alternative, alternative),
        )
    with pytest.raises(ValidationError, match="ranking"):
        ComparisonResult(
            comparison_id="c",
            current_contract_id="c",
            current_pricing=pricing,
            alternatives=(alternative,),
            ranking=("other",),
        )


def test_zero_current_total_has_no_percentage() -> None:
    savings = Money(amount=Decimal("10"))
    zero = Money(amount=Decimal("0"))
    assert (
        DeterministicComparisonEngine._percentage_difference(savings, zero, PERCENTAGE_ROUNDING)
        is None
    )


def test_request_rejects_duplicate_offer_ids_and_bad_external_items() -> None:
    with pytest.raises(ValidationError, match="offer ids"):
        _request((_offer("same", "0.10"), _offer("same", "0.20")))

    with pytest.raises(ValidationError, match="external item"):
        _request(
            (_offer("one", "0.10"),),
            external_items=(
                ExternalBillItem(
                    code="unverified",
                    description="Unverified",
                    category=BillingCategory.OTHER,
                    amount=Money(amount=Decimal("1.00")),
                    period=PERIOD,
                    reconciliation_key="unverified",
                ),
            ),
        )


def test_result_and_request_are_immutable_and_round_trip() -> None:
    request = _request((_offer("one", "0.10"),))
    result = DeterministicComparisonEngine().compare(request)
    assert ComparisonRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        result.ranking = ("mutated",)  # type: ignore[misc]


def test_comparison_context_supports_preflight_and_offer_binding() -> None:
    offer = _offer("one", "0.10")
    full = _request((offer,))
    context = ComparisonContext.model_validate(full.model_dump(exclude={"available_offers"}))
    engine = DeterministicComparisonEngine()
    decision = engine.preflight(context)
    assert decision.profile_code == full.classification.contract_type_code
    assert context.to_request((offer,)) == full
