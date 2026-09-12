from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, ClassVar, cast

import pytest

from italian_energy.billing import BillingCoverageMatrix, load_ruleset
from italian_energy.comparison import ComparisonResult
from italian_energy.domain import (
    ConsumptionBucket,
    ConsumptionProfile,
    EnergyQuantity,
    Granularity,
    MarketData,
    MarketDataPoint,
    MarketIndex,
    Money,
    RateUnit,
    SupplyClassification,
    TimeInterval,
    VoltageLevel,
)
from italian_energy.domain.costs import CostBreakdown, PricingResult
from italian_energy.domain.money import Power, UnitRate
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import (
    CurrentCatalogSnapshot,
    CurrentDomesticEnergyService,
    CurrentPortalComparisonRequest,
    CurrentPortalComparisonResult,
    CurrentRecommendationRequest,
    CurrentScenario,
    CurrentScenarioComparison,
    future_period,
    project_consumption,
    project_market_data,
)
from italian_energy.portal_offers import (
    PortalComparisonResult,
    PortalEligibilityProfile,
    PortalOffersImportResult,
    PortalTerritory,
)
from italian_energy.portal_offers.importer import PortalFetchError, PortalImportError
from italian_energy.recommendation import (
    Recommendation,
    RecommendationDecision,
)

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


def _contract(*, validity_end: date = date(2027, 1, 1)) -> Contract:
    return Contract(
        contract_id="current",
        supply=SupplyPoint(
            supply_id="supply",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=True,
        ),
        tariff=FixedTariff(
            tariff_id="tariff",
            validity=DatePeriod(start=date(2026, 1, 1), end=validity_end),
            prices=(
                BandPrice(
                    band="ALL",
                    rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
                ),
            ),
        ),
        validity=DatePeriod(start=date(2026, 1, 1), end=validity_end),
    )


def _eligibility() -> PortalEligibilityProfile:
    return PortalEligibilityProfile(
        territory=PortalTerritory(region_code="01", province_code="001", municipality_code="000001")
    )


def _classification() -> SupplyClassification:
    return SupplyClassification(
        contract_type_code="domestic_bt_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=True,
    )


def _current_request(
    *,
    validity_end: date = date(2027, 1, 1),
    continuation_assumption: bool = False,
    stress_delta: Decimal = Decimal("0.20"),
) -> CurrentPortalComparisonRequest:
    return CurrentPortalComparisonRequest(
        current_contract=_contract(validity_end=validity_end),
        consumption=_profile(),
        as_of=AS_OF,
        classification=_classification(),
        eligibility=_eligibility(),
        continuation_assumption=continuation_assumption,
        stress_delta=stress_delta,
    )


def _catalog(
    *, with_market_data: bool = True, dataset_date: date = AS_OF
) -> CurrentCatalogSnapshot:
    offers = SimpleNamespace(dataset_date=dataset_date, status=VerificationStatus.VERIFIED)
    indexes = SimpleNamespace(snapshot_id="index-snapshot") if with_market_data else None
    return CurrentCatalogSnapshot.model_construct(
        dataset_date=dataset_date,
        snapshot=cast(Any, SimpleNamespace(offers=offers, indexes=indexes)),
        records=(),
        market_data=_market_data() if with_market_data else None,
    )


def _comparison(*, comparison_id: str = "comparison") -> ComparisonResult:
    pricing = PricingResult(
        pricing_id="pricing",
        contract_id="current",
        period=DatePeriod(start=date(2026, 10, 1), end=date(2027, 10, 1)),
        breakdown=CostBreakdown(total=Money(amount=Decimal("0"))),
    )
    return ComparisonResult.model_construct(
        comparison_id=comparison_id,
        current_contract_id="current",
        current_pricing=pricing,
    )


def _current_result() -> CurrentPortalComparisonResult:
    import_result = PortalOffersImportResult.model_construct(
        snapshot=cast(Any, SimpleNamespace()),
        status=VerificationStatus.VERIFIED,
        import_id="portal-import:" + "4" * 64,
        eligible_offers=(),
        received_count=0,
        eligible_count=0,
        excluded_count=0,
    )
    portal = PortalComparisonResult.model_construct(
        portal_result_id="portal-comparison:" + "5" * 64,
        import_result=import_result,
        comparison_result=_comparison(),
    )
    return CurrentPortalComparisonResult.model_construct(
        current_result_id="current-portal-comparison:" + "6" * 64,
        as_of=AS_OF,
        period=future_period(AS_OF),
        catalog_dataset_date=AS_OF,
        scenarios=tuple(
            CurrentScenarioComparison.model_construct(scenario=scenario, comparison=portal)
            for scenario in CurrentScenario
        ),
    )


def _call_validator(value: Any, name: str) -> None:
    getattr(value, name)()


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


@pytest.mark.parametrize("stress_delta", (Decimal("-0.01"), Decimal("1")))
def test_current_request_rejects_invalid_stress_delta(stress_delta: Decimal) -> None:
    with pytest.raises(ValueError, match="stress_delta"):
        _current_request(stress_delta=stress_delta)


def test_current_request_rejects_unsupported_classification_and_history_shapes() -> None:
    invalid_classification = _current_request().model_copy(
        update={"classification": _classification().model_copy(update={"usage_code": "commercial"})}
    )
    with pytest.raises(Exception, match="domestic electricity"):
        _call_validator(invalid_classification, "validate_scenario")

    day_bucket = _profile().buckets[0].model_copy(update={"granularity": Granularity.DAY})
    invalid_granularity = _current_request().model_copy(
        update={
            "consumption": ConsumptionProfile.model_construct(
                profile_id="invalid", buckets=(day_bucket,)
            )
        }
    )
    with pytest.raises(Exception, match="monthly"):
        _call_validator(invalid_granularity, "validate_scenario")

    unknown_band = _profile().buckets[0].model_copy(update={"band": "F4"})
    invalid_band = _current_request().model_copy(
        update={
            "consumption": ConsumptionProfile.model_construct(
                profile_id="invalid", buckets=(unknown_band,)
            )
        }
    )
    with pytest.raises(Exception, match="F1/F2/F3"):
        _call_validator(invalid_band, "validate_scenario")

    late_bucket = (
        _profile()
        .buckets[-1]
        .model_copy(
            update={
                "interval": TimeInterval(
                    start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 9, 2, tzinfo=UTC)
                )
            }
        )
    )
    invalid_end = _current_request().model_copy(
        update={
            "consumption": ConsumptionProfile.model_construct(
                profile_id="invalid", buckets=(*_profile().buckets[:-1], late_bucket)
            )
        }
    )
    with pytest.raises(Exception, match="latest complete"):
        _call_validator(invalid_end, "validate_scenario")


def test_current_request_rejects_band_with_incomplete_month_set() -> None:
    buckets = tuple(
        bucket.model_copy(update={"band": "F1" if index < 11 else "F2"})
        for index, bucket in enumerate(_profile().buckets)
    )
    invalid = _current_request().model_copy(
        update={
            "consumption": ConsumptionProfile.model_construct(profile_id="invalid", buckets=buckets)
        }
    )
    with pytest.raises(Exception, match="same twelve"):
        _call_validator(invalid, "validate_scenario")


def test_current_snapshot_and_projected_scenario_validators_fail_closed() -> None:
    verified_offers = SimpleNamespace(dataset_date=AS_OF, status=VerificationStatus.VERIFIED)
    mismatched = CurrentCatalogSnapshot.model_construct(
        dataset_date=date(2026, 9, 11),
        snapshot=cast(Any, SimpleNamespace(offers=verified_offers, indexes=None)),
        records=(),
        market_data=None,
    )
    with pytest.raises(ValueError, match="date mismatch"):
        _call_validator(mismatched, "validate_snapshot")

    unverified = CurrentCatalogSnapshot.model_construct(
        dataset_date=AS_OF,
        snapshot=cast(
            Any,
            SimpleNamespace(
                offers=SimpleNamespace(dataset_date=AS_OF, status=VerificationStatus.UNVERIFIED),
                indexes=None,
            ),
        ),
        records=(),
        market_data=None,
    )
    with pytest.raises(ValueError, match="must be verified"):
        _call_validator(unverified, "validate_snapshot")

    missing_market = CurrentCatalogSnapshot.model_construct(
        dataset_date=AS_OF,
        snapshot=cast(Any, SimpleNamespace(offers=verified_offers, indexes=SimpleNamespace())),
        records=(),
        market_data=None,
    )
    with pytest.raises(ValueError, match="parsed market data"):
        _call_validator(missing_market, "validate_snapshot")

    old_point = MarketDataPoint(
        index_code="PUN",
        interval=TimeInterval(
            start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 10, 1, tzinfo=UTC)
        ),
        value=Decimal("0.10"),
    )
    old_data = MarketData(indexes=_market_data().indexes, points=(old_point,))
    with pytest.raises(ValueError, match="inside the future period"):
        from italian_energy.integration.current import ProjectedMarketScenarioSet

        ProjectedMarketScenarioSet(
            as_of=AS_OF,
            period=future_period(AS_OF),
            low_index=old_data,
            base=MarketData(),
            high_index=MarketData(),
        )


def test_current_result_and_recommendation_validators_reject_bad_payloads() -> None:
    result = _current_result()
    invalid_result = result.model_copy(update={"scenarios": tuple(reversed(result.scenarios))})
    with pytest.raises(ValueError, match="low, base and high"):
        _call_validator(invalid_result, "validate_scenarios")

    with pytest.raises(ValueError, match="non-negative"):
        CurrentRecommendationRequest(
            comparison=result,
            minimum_percentage_savings=Decimal("-1"),
        )


def test_current_service_acquires_catalog_and_maps_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import italian_energy.integration.service as integration_service

    class Importer:
        def __init__(self) -> None:
            self.snapshot = SimpleNamespace(offers="offers", indexes="indexes")
            self.calls: list[tuple[date, bool]] = []

        def fetch(self, target: date, *, include_indexes: bool) -> Any:
            self.calls.append((target, include_indexes))
            return self.snapshot

        def parse_offers(self, offers: Any) -> tuple[str, ...]:
            assert offers == "offers"
            return ("record",)

        def parse_market_data(self, indexes: Any) -> MarketData:
            assert indexes == "indexes"
            return _market_data()

    captured: list[dict[str, Any]] = []

    def fake_catalog(**kwargs: Any) -> dict[str, Any]:
        captured.append(kwargs)
        return kwargs

    monkeypatch.setattr(integration_service, "CurrentCatalogSnapshot", fake_catalog)
    importer = Importer()
    service = CurrentDomesticEnergyService(
        importer=cast(Any, importer), clock=lambda: datetime(2026, 9, 13, tzinfo=UTC)
    )
    result = cast(Any, service.acquire_catalog())
    assert result["dataset_date"] == date(2026, 9, 13)
    assert result["records"] == ("record",)
    assert result["market_data"] == _market_data()
    assert importer.calls == [(date(2026, 9, 13), True)]

    importer.snapshot = SimpleNamespace(offers="offers", indexes=None)
    result_without_indexes = cast(Any, service.acquire_catalog(date(2026, 9, 12)))
    assert result_without_indexes["market_data"] is None
    assert len(captured) == 2

    class FetchFailure(Importer):
        def fetch(self, target: date, *, include_indexes: bool) -> Any:
            raise PortalFetchError("private fetch detail")

    with pytest.raises(Exception, match="acquisition failed"):
        CurrentDomesticEnergyService(importer=cast(Any, FetchFailure())).acquire_catalog(AS_OF)

    class ParseFailure(Importer):
        def parse_offers(self, offers: Any) -> tuple[str, ...]:
            raise PortalImportError("private parse detail")

    with pytest.raises(Exception, match="validation failed"):
        CurrentDomesticEnergyService(importer=cast(Any, ParseFailure())).acquire_catalog(AS_OF)


def test_current_service_compares_three_frozen_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    import italian_energy.integration.service as integration_service

    class Engine:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def compare(self, request: Any) -> ComparisonResult:
            self.requests.append(request)
            return _comparison(comparison_id=f"comparison-{len(self.requests)}")

    import_count = 0

    def fake_normalize(*args: Any, **kwargs: Any) -> PortalOffersImportResult:
        nonlocal import_count
        import_count += 1
        return PortalOffersImportResult.model_construct(
            snapshot=cast(Any, SimpleNamespace()),
            status=VerificationStatus.VERIFIED,
            import_id=f"portal-import:{import_count:064d}",
            eligible_offers=(),
            received_count=0,
            eligible_count=0,
            excluded_count=0,
        )

    engine = Engine()
    service = CurrentDomesticEnergyService(engine=cast(Any, engine))
    monkeypatch.setattr(
        service,
        "_billing_artifacts",
        lambda request, period: (
            load_ruleset(segment="resident"),
            BillingCoverageMatrix.model_construct(matrix_id="test", schema_version="1", entries=()),
        ),
    )
    monkeypatch.setattr(integration_service, "normalize_offers", fake_normalize)
    result = service.compare(
        _current_request(continuation_assumption=True),
        _catalog(),
    )
    assert tuple(item.scenario for item in result.scenarios) == tuple(CurrentScenario)
    assert len(engine.requests) == 3
    assert [request.market_data.points[0].value for request in engine.requests] == [
        Decimal("0.080"),
        Decimal("0.10"),
        Decimal("0.120"),
    ]
    assert all(
        request.current_contract.contract_id == "current:continued" for request in engine.requests
    )
    assert all(request.period == future_period(AS_OF) for request in engine.requests)


def test_current_service_rejects_future_snapshot_missing_indexes_and_horizon() -> None:
    service = CurrentDomesticEnergyService(clock=lambda: datetime(2026, 9, 12, tzinfo=UTC))
    with pytest.raises(Exception, match="future"):
        service.compare(_current_request(), _catalog())

    with pytest.raises(Exception, match="after"):
        service.compare(
            _current_request(),
            _catalog(dataset_date=date(2026, 9, 13)),
        )

    with pytest.raises(Exception, match="index snapshot"):
        service.compare(_current_request(), _catalog(with_market_data=False))


def test_current_service_maps_billing_and_comparison_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import italian_energy.integration.service as integration_service

    request = _current_request(continuation_assumption=True)
    period = future_period(AS_OF)
    verified = load_ruleset(segment="resident")
    matrix = BillingCoverageMatrix.model_construct(matrix_id="test", schema_version="1", entries=())

    class LoaderFailure:
        def __call__(self, **kwargs: Any) -> Any:
            raise OSError("private artifact detail")

    service = CurrentDomesticEnergyService(
        ruleset_loader=LoaderFailure(), coverage_loader=lambda: matrix
    )
    with pytest.raises(Exception, match="coverage"):
        service._billing_artifacts(request, period)

    service = CurrentDomesticEnergyService(
        ruleset_loader=lambda **kwargs: verified.model_copy(
            update={"status": VerificationStatus.UNVERIFIED}
        ),
        coverage_loader=lambda: matrix,
    )
    with pytest.raises(Exception, match="coverage"):
        service._billing_artifacts(request, period)

    monkeypatch.setattr(BillingCoverageMatrix, "resolve", lambda self, *args, **kwargs: None)
    service = CurrentDomesticEnergyService(
        ruleset_loader=lambda **kwargs: verified,
        coverage_loader=lambda: matrix,
    )
    assert service._billing_artifacts(request, period) == (verified, matrix)

    def failing_normalize(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("private comparison detail")

    monkeypatch.setattr(service, "_billing_artifacts", lambda request, period: (verified, matrix))
    monkeypatch.setattr(integration_service, "normalize_offers", failing_normalize)
    with pytest.raises(Exception, match="comparison failed"):
        service.compare(request, _catalog())


def test_current_service_contract_horizon_and_recommendation_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import italian_energy.integration.service as integration_service

    service = CurrentDomesticEnergyService(clock=lambda: datetime(2026, 9, 12, tzinfo=UTC))
    matrix = BillingCoverageMatrix.model_construct(matrix_id="test", schema_version="1", entries=())
    monkeypatch.setattr(
        service,
        "_billing_artifacts",
        lambda request, period: (load_ruleset(segment="resident"), matrix),
    )
    with pytest.raises(Exception, match="not active"):
        service.compare(
            _current_request(validity_end=date(2026, 9, 1), continuation_assumption=True),
            _catalog(),
        )
    with pytest.raises(Exception, match="does not cover"):
        service.compare(_current_request(), _catalog())

    class Adapter:
        calls: ClassVar[list[tuple[Any, Any]]] = []

        def build_request(self, comparison: Any, preferences: Any) -> str:
            self.calls.append((comparison, preferences))
            return "recommendation-request"

    class RecommendationEngine:
        def __init__(self) -> None:
            self.requests: list[Any] = []

        def recommend(self, request: Any) -> Recommendation:
            self.requests.append(request)
            return Recommendation.model_construct(
                recommendation_id="recommendation",
                comparison_id="comparison",
                decision=RecommendationDecision.STAY_CURRENT,
            )

    monkeypatch.setattr(integration_service, "PortalRecommendationAdapter", Adapter)
    recommendation_engine = RecommendationEngine()
    service = CurrentDomesticEnergyService(recommendation_engine=recommendation_engine)
    recommendation = service.recommend(CurrentRecommendationRequest(comparison=_current_result()))
    assert recommendation.decision is RecommendationDecision.STAY_CURRENT
    assert recommendation_engine.requests == ["recommendation-request"]
    assert Adapter.calls[0][1].minimum_savings == Money(amount=Decimal("50.00"))

    class FailingAdapter:
        def build_request(self, comparison: Any, preferences: Any) -> Any:
            raise ValueError("private recommendation detail")

    monkeypatch.setattr(integration_service, "PortalRecommendationAdapter", FailingAdapter)
    with pytest.raises(Exception, match="recommendation failed"):
        service.recommend(CurrentRecommendationRequest(comparison=_current_result()))
