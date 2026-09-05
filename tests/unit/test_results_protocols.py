from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from italian_energy.billing import BillingEngine, BillingRequest
from italian_energy.comparison import ComparisonResult
from italian_energy.domain.costs import Bill, CostBreakdown, CostComponent, PricingResult
from italian_energy.domain.money import Money
from italian_energy.domain.regulatory import RegulatoryParameter
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.time import DatePeriod
from italian_energy.pricing import PricingEngine, PricingRequest
from italian_energy.recommendation import (
    Recommendation,
    RecommendationPreferences,
    RecommendationRequest,
)

PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))


def test_cost_breakdown_total_must_equal_components() -> None:
    component = CostComponent(
        code="energy",
        description="Energy",
        amount=Money(amount=Decimal("10.00")),
        quantity=Decimal("50"),
        period=PERIOD,
        formula="quantity x rate",
    )
    breakdown = CostBreakdown(components=(component,), total=Money(amount=Decimal("10.00")))
    assert breakdown.total.amount == Decimal("10.00")
    with pytest.raises(ValidationError, match="total"):
        CostBreakdown(components=(component,), total=Money(amount=Decimal("11.00")))
    with pytest.raises(ValidationError, match="declared"):
        Bill(
            bill_id="bill-1",
            contract_id="contract-1",
            period=PERIOD,
            breakdown=breakdown,
            declared_total=Money(amount=Decimal("11.00")),
        )


def test_recommendation_references_comparison_without_mutating_it() -> None:
    pricing = PricingResult(
        pricing_id="price-1",
        contract_id="contract-1",
        period=PERIOD,
        breakdown=CostBreakdown(total=Money(amount=Decimal("0"))),
    )
    result = ComparisonResult(
        comparison_id="cmp-1",
        current_contract_id="contract-1",
        current_pricing=pricing,
    )
    request = RecommendationRequest(
        comparison=result,
        preferences=RecommendationPreferences(fixed_preference=True),
    )
    recommendation = Recommendation(
        recommendation_id="rec-1",
        comparison_id=request.comparison.comparison_id,
        selected_offer_id=None,
        rationale=("preferenza fisso",),
    )
    assert recommendation.comparison_id == "cmp-1"
    with pytest.raises(ValidationError):
        result.ranking = ("x",)  # type: ignore[misc]


def test_request_models_are_importable_and_immutable() -> None:
    assert SupplyPoint(supply_id="pod-1", market_zone="NORD").commodity.value == "electricity"
    with pytest.raises(ValidationError):
        BillingRequest.model_validate({"contract": {}, "consumption": {}, "period": {}})
    assert BillingEngine is not None
    assert PricingEngine is not None
    assert PricingRequest is not None
    parameter = RegulatoryParameter(
        code="VAT", value=Decimal("22"), unit="percent", validity=PERIOD
    )
    assert parameter.value == Decimal("22")
