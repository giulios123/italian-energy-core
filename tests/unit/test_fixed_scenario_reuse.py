"""Fixed evaluations may be shared only inside one projected comparison."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from test_projected_contract import AS_OF, _request
from test_projected_service import _catalog, _coverage, _history, _indexed_request

from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import BillingResult, PricingResult
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import EnergyQuantity
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import RegulatoryRuleSet
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import (
    ProjectedDomesticComparisonRequest,
    ProjectedDomesticEnergyService,
    ProjectedDomesticRecommendationRequest,
)
from italian_energy.integration.current import project_consumption
from italian_energy.integration.errors import CoreContractError
from italian_energy.portal_offers.models import (
    PortalComponentPriceValidity,
    PortalEconomicComponent,
    PortalOfferType,
    PortalPriceValidityKind,
)


class CountingService(ProjectedDomesticEnergyService):
    def __init__(self) -> None:
        super().__init__(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
        self.evaluations: list[Contract] = []

    def _evaluate_contract(
        self,
        request: ProjectedDomesticComparisonRequest,
        contract: Contract,
        consumption: ConsumptionProfile,
        market_data: MarketData,
        ruleset: RegulatoryRuleSet,
    ) -> tuple[PricingResult, BillingResult]:
        result = super()._evaluate_contract(request, contract, consumption, market_data, ruleset)
        self.evaluations.append(contract)
        return result


class UncachedService(CountingService):
    def _evaluate_scenario_contract(
        self,
        request: ProjectedDomesticComparisonRequest,
        contract: Contract,
        consumption: ConsumptionProfile,
        market_data: MarketData,
        ruleset: RegulatoryRuleSet,
        fixed_evaluations: dict[Contract, tuple[PricingResult, BillingResult]],
    ) -> tuple[PricingResult, BillingResult]:
        return self._evaluate_contract(request, contract, consumption, market_data, ruleset)


@pytest.mark.parametrize("fixed_current", [True, False])
def test_fixed_results_are_evaluated_once_and_entire_output_is_unchanged(
    fixed_current: bool,
) -> None:
    request = _request() if fixed_current else _indexed_request()
    catalog, history = _catalog(AS_OF), _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)
    cached, uncached = CountingService(), UncachedService()

    expected = uncached.compare(request, catalog, history, anchor, coverage)
    actual = cached.compare(request, catalog, history, anchor, coverage)

    assert actual.model_dump_json() == expected.model_dump_json()
    expected_advice = uncached.recommend(
        ProjectedDomesticRecommendationRequest(comparison=expected)
    )
    actual_advice = cached.recommend(ProjectedDomesticRecommendationRequest(comparison=actual))
    assert actual_advice.model_dump_json() == expected_advice.model_dump_json()
    fixed_calls = Counter(c for c in cached.evaluations if c.tariff.kind == "fixed")
    assert fixed_calls and set(fixed_calls.values()) == {1}
    original_fixed_calls = Counter(c for c in uncached.evaluations if c.tariff.kind == "fixed")
    assert set(original_fixed_calls.values()) == {3}
    indexed_calls = Counter(c for c in cached.evaluations if c.tariff.kind == "indexed")
    assert all(count == 3 for count in indexed_calls.values())
    if not fixed_current:
        assert indexed_calls
    low, base, high = (scenario.comparison.comparison_result for scenario in actual.scenarios)
    if fixed_current:
        assert low.current_pricing is base.current_pricing is high.current_pricing
        assert low.current_billing is base.current_billing is high.current_billing
    fixed_id = next(
        offer.offer_id
        for offer in actual.base.import_result.eligible_offers
        if offer.tariff.kind == "fixed"
        and any(alternative.offer_id == offer.offer_id for alternative in base.alternatives)
    )
    alternatives = [
        next(item for item in result.alternatives if item.offer_id == fixed_id)
        for result in (low, base, high)
    ]
    assert alternatives[0].pricing is alternatives[1].pricing is alternatives[2].pricing
    assert alternatives[0].billing is alternatives[1].billing is alternatives[2].billing
    if not fixed_current:
        assert len({item.savings.amount for item in alternatives if item.savings}) == 3


def test_fixed_cache_is_not_reused_by_later_comparisons_or_changed_consumption() -> None:
    service = CountingService()
    request = _request()
    catalog, history = _catalog(AS_OF), _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)
    first = service.compare(request, catalog, history, anchor, coverage)
    first_calls = len(service.evaluations)
    assert first_calls
    second = service.compare(request, catalog, history, anchor, coverage)
    assert len(service.evaluations) == 2 * first_calls
    assert first.model_dump_json() == second.model_dump_json()
    changed_profile = request.consumption.model_copy(
        update={
            "buckets": tuple(
                bucket.model_copy(update={"energy": EnergyQuantity(kwh=bucket.energy.kwh * 2)})
                for bucket in request.consumption.buckets
            )
        }
    )
    changed_request = request.model_copy(update={"consumption": changed_profile})
    third = service.compare(changed_request, catalog, history, anchor, coverage)
    assert len(service.evaluations) == 3 * first_calls
    assert (
        third.base.comparison_result.current_comparable_total
        != first.base.comparison_result.current_comparable_total
    )
    expected = UncachedService().compare(changed_request, catalog, history, anchor, coverage)
    assert third.model_dump_json() == expected.model_dump_json()
    blocked = coverage.model_copy(update={"anchor_sha256": "0" * 64})
    before = len(service.evaluations)
    with pytest.raises(CoreContractError):
        service.compare(request, catalog, history, anchor, blocked)
    assert len(service.evaluations) == before


def test_indexed_alternatives_keep_their_own_market_in_every_scenario() -> None:
    catalog = _catalog(AS_OF)
    fixed = catalog.records[0]
    indexed = fixed.model_copy(
        update={
            "source_offer_id": fixed.source_offer_id + "-indexed",
            "offer_type": PortalOfferType.INDEXED,
            "index_code": "01",
            "index_codes": (),
            "index_granularity": "month",
            "components": (
                PortalEconomicComponent(
                    code="spread",
                    description="PUN più spread",
                    amount=Decimal("0.03"),
                    unit="EUR/kWh",
                    band="ALL",
                    macroarea="04",
                    index_code="01",
                    price_validity=PortalComponentPriceValidity(
                        kind=PortalPriceValidityKind.DEFAULT
                    ),
                ),
            ),
        }
    )
    catalog = catalog.model_copy(update={"records": (fixed, indexed)})
    anchor = load_domestic_projection_anchor()
    service = CountingService()
    result = service.compare(_request(), catalog, _history(AS_OF), anchor, _coverage(anchor, AS_OF))
    calls = Counter(c for c in service.evaluations if c.tariff.kind == "indexed")
    assert len(calls) == 1 and set(calls.values()) == {3}
    indexed_id = next(
        offer.offer_id
        for offer in result.base.import_result.eligible_offers
        if offer.tariff.kind == "indexed"
    )
    indexed_totals = {
        next(
            alternative
            for alternative in scenario.comparison.comparison_result.alternatives
            if alternative.offer_id == indexed_id
        ).pricing.breakdown.total.amount
        for scenario in result.scenarios
    }
    assert len(indexed_totals) == 3


def test_fixed_cache_distinguishes_full_contract_content_and_does_not_store_errors() -> None:
    service = CountingService()
    request = _request()
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    consumption = project_consumption(request.consumption, request.as_of)
    ruleset = service._ruleset(anchor, True)
    contract = request.current_contract
    changed_tariff = contract.tariff.model_copy(update={"conditions": ("different tariff",)})
    changed = contract.model_copy(update={"tariff": changed_tariff})
    cache: dict[Contract, tuple[PricingResult, BillingResult]] = {}
    first = service._evaluate_scenario_contract(
        request, contract, consumption, history.market_data, ruleset, cache
    )
    second = service._evaluate_scenario_contract(
        request, changed, consumption, history.market_data, ruleset, cache
    )
    assert contract.contract_id == changed.contract_id
    assert len(service.evaluations) == len(cache) == 2
    assert first[0].pricing_id != second[0].pricing_id
    invalid_contract = contract.model_copy(
        update={"validity": DatePeriod(start=AS_OF, end=AS_OF + timedelta(days=1))}
    )
    for _ in range(2):
        with pytest.raises(ValueError):
            service._evaluate_scenario_contract(
                request, invalid_contract, consumption, history.market_data, ruleset, cache
            )
    assert invalid_contract not in cache
    assert len(cache) == 2
