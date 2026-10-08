import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from test_portal_offers import _transport
from test_projected_contract import AS_OF, _profile, _request

import italian_energy.integration.projected_service as projected_service
from italian_energy.arera.projection import (
    DomesticProjectionAnchor,
    load_domestic_projection_anchor,
)
from italian_energy.billing.regulatory import BillingError
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import BillingResult, PricingResult
from italian_energy.domain.formula import AddPrice, IndexReference, PriceConstant
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import (
    EnergyQuantity,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import RegulatoryRuleSet, VerificationStatus
from italian_energy.domain.tariff import BandFormula, IndexedTariff
from italian_energy.domain.time import DatePeriod, Granularity
from italian_energy.integration import (
    ProjectedDomesticComparisonRequest,
    ProjectedDomesticEnergyService,
    ProjectedDomesticRecommendationRequest,
)
from italian_energy.integration.current import CurrentCatalogSnapshot, future_period
from italian_energy.integration.errors import CoreContractError, CoreErrorCode
from italian_energy.integration.projected import (
    RegulatoryActFinding,
    RegulatoryCoverageEvidence,
    RegulatoryRegistry,
    RegulatoryRegistryReview,
    RegulatorySourceDigestCheck,
    projection_anchor_digest,
)
from italian_energy.integration.service import CurrentDomesticEnergyService
from italian_energy.market.gme import (
    GmeMarketHistory,
    GmeMonthlyIndexSnapshot,
    ParsedGmeBaseload,
    history_from_reports,
    make_report_provenance,
    recent_months,
    report_url,
)
from italian_energy.portal_offers.importer import PortalOffersImporter
from italian_energy.portal_offers.models import PortalEconomicComponent
from italian_energy.recommendation import Recommendation, RecommendationRequest


def _history(as_of: date) -> GmeMarketHistory:
    reports = []
    for month in recent_months(as_of):
        period = DatePeriod(
            start=month,
            end=date(month.year + (month.month == 12), month.month % 12 + 1, 1),
        )
        raw = f"verified fixture {month.isoformat()}".encode()
        provenance = make_report_provenance(
            raw,
            report_period=period,
            retrieved_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            url=report_url(month),
        )
        reports.append(
            GmeMonthlyIndexSnapshot(
                parsed=ParsedGmeBaseload(
                    period=period,
                    published_value_eur_per_mwh=Decimal("100"),
                    value_eur_per_kwh=Decimal("0.10"),
                ),
                status=VerificationStatus.VERIFIED,
                provenance=provenance,
            )
        )
    return history_from_reports(as_of, tuple(reports))


def _catalog(as_of: date) -> CurrentCatalogSnapshot:
    importer = PortalOffersImporter(
        transport=_transport(),
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC),
    )
    catalog = CurrentDomesticEnergyService(
        importer=importer, clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).acquire_catalog(as_of)
    future = DatePeriod(start=date(2026, 9, 1), end=date(2027, 10, 1))
    records = tuple(
        record.model_copy(
            update={
                "subscription_period": DatePeriod(start=date(2026, 9, 1), end=date(2027, 10, 1)),
                "tariff_validity": future,
                "duration_months": 13,
                "components": (
                    PortalEconomicComponent(
                        code="test_energy",
                        description="synthetic test energy price",
                        amount=Decimal("0.12"),
                        unit="EUR/kWh",
                        band="ALL",
                        macroarea="04",
                    ),
                ),
            }
        )
        for record in catalog.records
    )
    return catalog.model_copy(update={"records": records})


def _indexed_request(
    monthly_kwh: str = "300", *, residential: bool = True
) -> ProjectedDomesticComparisonRequest:
    profile = _profile()
    profile = profile.model_copy(
        update={
            "buckets": tuple(
                bucket.model_copy(update={"energy": EnergyQuantity(kwh=Decimal(monthly_kwh))})
                for bucket in profile.buckets
            )
        }
    )
    original = _request(profile)
    if not residential:
        supply = original.current_contract.supply.model_copy(update={"residential": False})
        contract = original.current_contract.model_copy(update={"supply": supply})
        classification = original.classification.model_copy(
            update={
                "contract_type_code": "domestic_bt_non_resident",
                "residential": False,
            }
        )
        original = original.model_copy(
            update={"current_contract": contract, "classification": classification}
        )
    horizon = future_period(AS_OF)
    indexed = IndexedTariff(
        tariff_id="current-pun-plus-spread",
        validity=horizon,
        granularity=Granularity.MONTH,
        formulas=(
            BandFormula(
                band="ALL",
                expression=AddPrice(
                    left=IndexReference(
                        index_code="PUN",
                        unit=RateUnit.EUR_PER_KWH,
                        granularity=Granularity.MONTH,
                    ),
                    right=PriceConstant(
                        rate=UnitRate(amount=Decimal("0.03"), unit=RateUnit.EUR_PER_KWH)
                    ),
                ),
            ),
        ),
    )
    contract = original.current_contract.model_copy(update={"tariff": indexed})
    return original.model_copy(update={"current_contract": contract})


def _coverage(
    anchor: DomesticProjectionAnchor,
    as_of: date,
    *,
    changed_source: bool = False,
    applicable_act: bool = False,
    authorities: tuple[RegulatoryRegistry, ...] = (
        "ARERA",
        "ADM",
        "Gazzetta Ufficiale",
        "Normattiva",
    ),
) -> RegulatoryCoverageEvidence:
    checked_at = datetime(as_of.year, as_of.month, as_of.day, 12, tzinfo=UTC)
    source_checks = tuple(
        RegulatorySourceDigestCheck(
            source_id=source.source_id,
            expected_sha256=source.sha256,
            observed_sha256=("0" * 64 if changed_source and index == 0 else source.sha256),
            checked_at=checked_at,
        )
        for index, source in enumerate(anchor.sources)
    )
    urls = {
        "ARERA": "https://www.arera.it/atti-e-provvedimenti/",
        "ADM": "https://www.adm.gov.it/portale/aliquote-accisa-nazionali",
        "Gazzetta Ufficiale": "https://www.gazzettaufficiale.it/eli/id/",
        "Normattiva": "https://www.normattiva.it/staticPage/ricercaNeiDocumenti",
    }
    reviews = tuple(
        RegulatoryRegistryReview(
            registry=authority,
            registry_url=urls[authority],
            reviewer="test-reviewer",
            as_of=as_of,
            reviewed_at=checked_at,
            searches=(f"atti applicabili alla data {as_of.isoformat()}",),
            decision_summary="ricerca completata sui registri ufficiali indicati",
            findings=(
                RegulatoryActFinding(
                    act_id="test-act-2026-09-28",
                    url="https://www.arera.it/atti-e-provvedimenti/",
                    applicability="applicable",
                    rationale="synthetic applicable-act fixture",
                ),
            )
            if applicable_act and authority == "ARERA"
            else (),
        )
        for authority in authorities
    )
    return RegulatoryCoverageEvidence(
        anchor_id=anchor.anchor_id,
        anchor_sha256=projection_anchor_digest(anchor),
        comparison_as_of=as_of,
        checked_at=checked_at,
        source_checks=source_checks,
        registry_reviews=reviews,
    )


def test_projected_comparison_bills_three_estimates_and_recommends_on_base_only() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()

    coverage = _coverage(anchor, AS_OF)
    result = service.compare(request, catalog, history, anchor, coverage)

    assert result.period == DatePeriod(start=date(2026, 10, 1), end=date(2027, 10, 1))
    assert result.assumptions.future_values_verified is False
    assert result.assumptions.costs_are_estimates is True
    assert result.assumptions.calendar_month_matching == "same_calendar_month_number"
    assert result.verified_inputs.market_status == VerificationStatus.VERIFIED
    assert result.verified_inputs.regulatory_anchor_date == date(2026, 9, 27)
    assert result.assumptions.regulatory_anchor_date == date(2026, 9, 27)
    assert result.verified_inputs.regulatory_coverage_as_of == AS_OF
    assert result.verified_inputs.regulatory_coverage_id == coverage.evidence_id
    assert len(result.verified_inputs.market_report_provenance) == 12
    assert [item.index_multiplier for item in result.scenarios] == [
        Decimal("0.80"),
        Decimal("1.00"),
        Decimal("1.20"),
    ]
    low, base, high = (item.comparison.comparison_result for item in result.scenarios)
    assert low.current_pricing.breakdown.total.amount == Decimal("396.00")
    assert base.current_pricing.breakdown.total.amount == Decimal("468.00")
    assert high.current_pricing.breakdown.total.amount == Decimal("540.00")
    assert base.ranking
    assert high.alternatives[0].savings is not None
    assert high.alternatives[0].savings.amount > Decimal("50")
    assert all(item.billing is not None for item in base.alternatives)
    assert all(
        any("regulatory_projection_as_of=2026-09-27" in value for value in item.billing.assumptions)
        for item in base.alternatives
        if item.billing is not None
    )


def test_projected_comparison_stays_offline_after_sources_are_supplied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden_network_access(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("compare must not acquire regulatory sources")

    monkeypatch.setattr(projected_service, "fetch_official_source", forbidden_network_access)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor()

    result = service.compare(
        _indexed_request(),
        _catalog(AS_OF),
        _history(AS_OF),
        anchor,
        _coverage(anchor, AS_OF),
    )

    assert result.assumptions.future_values_verified is False


def test_projected_comparison_reuses_september_anchor_on_29_september() -> None:
    comparison_date = date(2026, 9, 29)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 29, 12, tzinfo=UTC))
    request = _indexed_request().model_copy(update={"as_of": comparison_date})
    anchor = load_domestic_projection_anchor()
    result = service.compare(
        request,
        _catalog(AS_OF),
        _history(comparison_date),
        anchor,
        _coverage(anchor, comparison_date),
    )
    readiness = service.preflight(
        request,
        _catalog(AS_OF),
        _history(comparison_date),
        anchor,
        _coverage(anchor, comparison_date),
    )

    assert readiness.ready is True
    assert result.as_of == comparison_date
    assert result.verified_inputs.regulatory_anchor_date == date(2026, 9, 27)
    assert result.verified_inputs.regulatory_coverage_as_of == comparison_date
    assert result.assumptions.regulatory_anchor_date == date(2026, 9, 27)
    assert result.verified_inputs.regulatory_provenance == anchor.to_bundle().provenance
    assert result.assumptions.future_values_verified is False

    recommendation = service.recommend(ProjectedDomesticRecommendationRequest(comparison=result))
    assert recommendation.comparison_id == result.result_id
    assert recommendation.scenario == "base"
    assert recommendation.based_on_estimates is True
    assert recommendation.recommendation.selected_offer_id is None


def test_projected_preflight_distinguishes_sources_from_calculability() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()

    missing_sources = service.preflight(request)
    assert missing_sources.official_data_ready is False
    assert missing_sources.projection_calculable is False
    assert set(missing_sources.reason_codes) == {
        "catalog_snapshot_missing",
        "gme_market_history_missing",
        "regulatory_anchor_missing",
    }
    ready = service.preflight(request, catalog, history, anchor, _coverage(anchor, AS_OF))
    assert ready.ready is True
    assert ready.official_data_ready is True
    assert ready.projection_calculable is True
    assert ready.horizon_eligible_offer_count == 2


def test_projected_comparison_rejects_relabelled_or_stale_market_history() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    history = _history(AS_OF)
    changed = history.model_copy(
        update={
            "market_data": history.market_data.model_copy(
                update={
                    "points": (
                        history.market_data.points[0].model_copy(update={"value": Decimal("9.99")}),
                        *history.market_data.points[1:],
                    )
                }
            )
        }
    )
    assert not service.preflight(
        request,
        _catalog(AS_OF),
        changed,
        load_domestic_projection_anchor(),
        _coverage(load_domestic_projection_anchor(), AS_OF),
    ).checks["market_window_verified"]


def test_projected_comparison_fails_closed_for_each_unverified_input() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()

    with pytest.raises(CoreContractError) as error:
        service.compare(request, catalog, history, anchor)
    assert error.value.code == CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED

    unverified_catalog = catalog.model_copy(
        update={
            "snapshot": catalog.snapshot.model_copy(
                update={
                    "offers": catalog.snapshot.offers.model_copy(
                        update={"status": VerificationStatus.UNVERIFIED}
                    )
                }
            )
        }
    )
    with pytest.raises(CoreContractError) as error:
        service.compare(request, unverified_catalog, history, anchor, _coverage(anchor, AS_OF))
    assert error.value.code == CoreErrorCode.SOURCE_VALIDATION_FAILED

    unverified_history = history.model_copy(update={"status": VerificationStatus.UNVERIFIED})
    with pytest.raises(CoreContractError) as error:
        service.compare(request, catalog, unverified_history, anchor, _coverage(anchor, AS_OF))
    assert error.value.code == CoreErrorCode.SOURCE_VALIDATION_FAILED

    changed_anchor = anchor.model_copy(
        update={
            "sources": (
                anchor.sources[0].model_copy(update={"sha256": "0" * 64}),
                *anchor.sources[1:],
            )
        }
    )
    with pytest.raises(CoreContractError) as error:
        service.compare(request, catalog, history, changed_anchor, _coverage(anchor, AS_OF))
    assert error.value.code == CoreErrorCode.REGULATORY_SOURCE_CHANGED

    with pytest.raises(CoreContractError) as error:
        service.compare(
            request, catalog, history, anchor, _coverage(anchor, AS_OF, changed_source=True)
        )
    assert error.value.code == CoreErrorCode.REGULATORY_SOURCE_CHANGED


def test_projected_source_preflight_requires_date_coverage_and_blocks_expired_anchor() -> None:
    anchor = load_domestic_projection_anchor()
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 29, 12, tzinfo=UTC))
    comparison_date = date(2026, 9, 29)
    gate = service.source_preflight(
        comparison_date, _catalog(AS_OF), _history(comparison_date), anchor, None
    )
    assert gate.ready is False
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in gate.reason_codes

    confirmed = service.source_preflight(
        comparison_date,
        _catalog(AS_OF),
        _history(comparison_date),
        anchor,
        _coverage(anchor, comparison_date),
    )
    assert confirmed.ready is True

    expired_date = date(2026, 10, 1)
    expired_service = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 10, 1, 12, tzinfo=UTC)
    )
    expired = expired_service.source_preflight(
        expired_date,
        _catalog(AS_OF),
        _history(expired_date),
        anchor,
        _coverage(anchor, expired_date),
    )
    assert expired.ready is False
    assert CoreErrorCode.COVERAGE_EXPIRED.value in expired.reason_codes


def test_projected_source_preflight_does_not_ignore_a_later_applicable_act() -> None:
    anchor = load_domestic_projection_anchor()
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 29, 12, tzinfo=UTC))
    evidence = _coverage(anchor, date(2026, 9, 29), applicable_act=True)

    result = service.source_preflight(
        date(2026, 9, 29),
        _catalog(AS_OF),
        _history(date(2026, 9, 29)),
        anchor,
        evidence,
    )

    assert result.ready is False
    assert CoreErrorCode.APPLICABLE_REGULATORY_ACT.value in result.reason_codes


def test_source_preflight_rejects_misbound_incomplete_and_future_coverage_evidence() -> None:
    anchor = load_domestic_projection_anchor()
    as_of = date(2026, 9, 29)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 29, 12, tzinfo=UTC))
    catalog = _catalog(AS_OF)
    history = _history(as_of)
    valid = _coverage(anchor, as_of)

    wrong_date = valid.model_copy(update={"comparison_as_of": date(2026, 9, 28)})
    wrong_anchor_id = valid.model_copy(update={"anchor_id": "different-anchor"})
    wrong_anchor_digest = valid.model_copy(update={"anchor_sha256": "0" * 64})
    future_evidence = valid.model_copy(update={"checked_at": datetime(2026, 9, 30, 12, tzinfo=UTC)})
    missing_source = valid.model_copy(update={"source_checks": valid.source_checks[1:]})
    future_source = valid.model_copy(
        update={
            "source_checks": (
                valid.source_checks[0].model_copy(
                    update={"checked_at": datetime(2026, 9, 30, 12, tzinfo=UTC)}
                ),
                *valid.source_checks[1:],
            )
        }
    )
    missing_registry = valid.model_copy(update={"registry_reviews": valid.registry_reviews[:-1]})
    future_review = valid.model_copy(
        update={
            "registry_reviews": (
                valid.registry_reviews[0].model_copy(
                    update={"reviewed_at": datetime(2026, 9, 30, 12, tzinfo=UTC)}
                ),
                *valid.registry_reviews[1:],
            )
        }
    )
    uncertain_act = valid.model_copy(
        update={
            "registry_reviews": (
                valid.registry_reviews[0].model_copy(
                    update={
                        "findings": (
                            RegulatoryActFinding(
                                act_id="uncertain-act",
                                url="https://www.arera.it/atti-e-provvedimenti/",
                                applicability="uncertain",
                                rationale="applicability needs review",
                            ),
                        )
                    }
                ),
                *valid.registry_reviews[1:],
            )
        }
    )

    for evidence in (
        wrong_date,
        wrong_anchor_id,
        future_evidence,
        missing_source,
        future_source,
        missing_registry,
        future_review,
        uncertain_act,
    ):
        result = service.source_preflight(as_of, catalog, history, anchor, evidence)
        assert result.ready is False
        assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in result.reason_codes

    changed_anchor_digest = service.source_preflight(
        as_of,
        catalog,
        history,
        anchor,
        wrong_anchor_digest,
    )
    assert CoreErrorCode.REGULATORY_SOURCE_CHANGED.value in changed_anchor_digest.reason_codes

    unverified_anchor = anchor.model_copy(update={"status": VerificationStatus.UNVERIFIED})
    unverified = service.source_preflight(as_of, catalog, history, unverified_anchor, valid)
    assert "regulatory_anchor_unverified" in unverified.reason_codes

    before_validity = service.source_preflight(
        date(2026, 8, 31), catalog, history, anchor, _coverage(anchor, date(2026, 8, 31))
    )
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in before_validity.reason_codes


def test_projected_preflight_reports_stale_sources_and_no_candidate() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF).model_copy(update={"dataset_date": date(2026, 9, 28)})
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    result = service.preflight(request, catalog, history, anchor, _coverage(anchor, AS_OF))

    assert result.ready is False
    assert result.official_data_ready is False
    assert CoreErrorCode.SOURCE_VALIDATION_FAILED.value in result.reason_codes
    assert result.checks["catalog_verified"] is False

    no_offers = catalog.model_copy(
        update={
            "dataset_date": AS_OF,
            "records": (),
        }
    )
    no_candidates = service.preflight(request, no_offers, history, anchor, _coverage(anchor, AS_OF))
    assert no_candidates.projection_calculable is False
    assert no_candidates.checks["supported_candidate_available"] is False
    assert no_candidates.horizon_eligible_offer_count == 0


def test_projected_comparison_rejects_future_date_and_inactive_baseline() -> None:
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    request = _indexed_request()
    future_service = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 26, 12, tzinfo=UTC)
    )
    with pytest.raises(CoreContractError) as error:
        future_service.compare(request, catalog, history, anchor, _coverage(anchor, AS_OF))
    assert error.value.code == CoreErrorCode.UNSUPPORTED_HORIZON

    inactive = request.model_copy(
        update={
            "current_contract": request.current_contract.model_copy(
                update={"validity": DatePeriod(start=date(2025, 1, 1), end=date(2026, 9, 1))}
            )
        }
    )
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    with pytest.raises(CoreContractError) as error:
        service.compare(inactive, catalog, history, anchor, _coverage(anchor, AS_OF))
    assert error.value.code == CoreErrorCode.UNSUPPORTED_HORIZON


def test_projected_comparison_excludes_declared_current_offer_and_pricing_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    source_offer = "portal:market_free:" + catalog.records[0].source_offer_id
    request = request.model_copy(
        update={
            "current_contract": request.current_contract.model_copy(
                update={"source_offer_id": source_offer}
            )
        }
    )
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor()
    result = service.compare(request, catalog, _history(AS_OF), anchor, _coverage(anchor, AS_OF))
    from italian_energy.comparison import OfferExclusionCode

    same_current = result.base.comparison_result.excluded_offers
    assert any(item.code == OfferExclusionCode.SAME_AS_CURRENT for item in same_current)

    from italian_energy.pricing.fixed import FixedPricingError

    evaluate = service._evaluate_contract

    def fail_candidate(
        request: ProjectedDomesticComparisonRequest,
        contract: Contract,
        consumption: ConsumptionProfile,
        market_data: MarketData,
        ruleset: RegulatoryRuleSet,
    ) -> tuple[PricingResult, BillingResult]:
        if contract.contract_id.startswith("projected-contract:"):
            raise FixedPricingError("candidate fixed price is invalid")
        return evaluate(request, contract, consumption, market_data, ruleset)

    monkeypatch.setattr(service, "_evaluate_contract", fail_candidate)
    failed = service.compare(
        _indexed_request(),
        catalog,
        _history(AS_OF),
        load_domestic_projection_anchor(),
        _coverage(load_domestic_projection_anchor(), AS_OF),
    )
    assert failed.base.comparison_result.alternatives == ()
    assert all(
        item.code == OfferExclusionCode.PRICING_FAILED
        for item in failed.base.comparison_result.excluded_offers
    )


def test_projected_recommendation_requires_verified_data_and_wraps_engine_failures() -> None:
    result = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).compare(
        _indexed_request(),
        _catalog(AS_OF),
        _history(AS_OF),
        load_domestic_projection_anchor(),
        _coverage(load_domestic_projection_anchor(), AS_OF),
    )
    unverified = result.model_copy(
        update={
            "verified_inputs": result.verified_inputs.model_copy(
                update={"market_status": VerificationStatus.UNVERIFIED}
            )
        }
    )
    with pytest.raises(CoreContractError) as error:
        ProjectedDomesticEnergyService().recommend(
            ProjectedDomesticRecommendationRequest(comparison=unverified)
        )
    assert error.value.code == CoreErrorCode.RECOMMENDATION_FAILED

    class FailingRecommendationEngine:
        def recommend(self, _request: RecommendationRequest) -> Recommendation:
            raise ValueError("not a comparable recommendation")

    service = ProjectedDomesticEnergyService(
        recommendation_engine=FailingRecommendationEngine(),
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC),
    )
    with pytest.raises(CoreContractError) as error:
        service.recommend(ProjectedDomesticRecommendationRequest(comparison=result))
    assert error.value.code == CoreErrorCode.RECOMMENDATION_FAILED


def test_projected_acquisition_and_ruleset_failures_have_stable_core_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        projected_service,
        "fetch_recent_market_history",
        lambda _as_of: (_ for _ in ()).throw(ValueError("missing monthly report")),
    )
    with pytest.raises(CoreContractError) as error:
        ProjectedDomesticEnergyService.acquire_market_history(AS_OF)
    assert error.value.code == CoreErrorCode.SOURCE_ACQUISITION_FAILED

    monkeypatch.setattr(
        projected_service,
        "load_domestic_projection_anchor",
        lambda _as_of=None: (_ for _ in ()).throw(ValueError("bad source digest")),
    )
    with pytest.raises(CoreContractError) as error:
        ProjectedDomesticEnergyService.acquire_regulatory_anchor()
    assert error.value.code == CoreErrorCode.COVERAGE_UNAVAILABLE

    with pytest.raises(CoreContractError) as error:
        ProjectedDomesticEnergyService._ruleset(load_domestic_projection_anchor(), None)
    assert error.value.code == CoreErrorCode.UNSUPPORTED_SCENARIO

    anchor = load_domestic_projection_anchor().model_copy(update={"charges": ()})
    with pytest.raises(CoreContractError) as error:
        ProjectedDomesticEnergyService._ruleset(anchor, True)
    assert error.value.code == CoreErrorCode.COVERAGE_UNAVAILABLE


def test_anchor_refresh_downloads_pinned_sources_and_preserves_snapshot_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = load_domestic_projection_anchor()
    source_bytes = {
        source.url: f"verified source {source.source_id}".encode() for source in original.sources
    }
    anchor = original.model_copy(
        update={
            "sources": tuple(
                source.model_copy(
                    update={"sha256": hashlib.sha256(source_bytes[source.url]).hexdigest()}
                )
                for source in original.sources
            )
        }
    )
    monkeypatch.setattr(
        projected_service, "load_domestic_projection_anchor", lambda _as_of=None: anchor
    )
    calls: list[str] = []
    check_number = 0

    def clock() -> datetime:
        nonlocal check_number
        result = datetime(2026, 9, 29, 12, tzinfo=UTC) + timedelta(seconds=check_number)
        check_number += 1
        return result

    def fetch(url: str) -> bytes:
        calls.append(url)
        return source_bytes[url]

    reviews = _coverage(anchor, date(2026, 9, 29)).registry_reviews
    result = ProjectedDomesticEnergyService(clock=clock).refresh_regulatory_anchor(
        date(2026, 9, 29), reviews, fetch
    )

    assert result.ready is True
    assert len(calls) == len(anchor.sources) == 8
    assert result.anchor.as_of == date(2026, 9, 27)
    assert result.coverage_evidence.comparison_as_of == date(2026, 9, 29)
    assert result.checks["source_digests_match"] is True
    assert result.coverage_evidence.checked_at >= max(
        check.checked_at for check in result.coverage_evidence.source_checks
    )


def test_anchor_refresh_fails_closed_on_changed_source_new_act_or_expired_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = load_domestic_projection_anchor()
    now = datetime(2026, 9, 29, 12, tzinfo=UTC)
    good_bytes = {
        source.url: f"verified source {source.source_id}".encode() for source in original.sources
    }
    anchor = original.model_copy(
        update={
            "sources": tuple(
                source.model_copy(
                    update={"sha256": hashlib.sha256(good_bytes[source.url]).hexdigest()}
                )
                for source in original.sources
            )
        }
    )
    monkeypatch.setattr(
        projected_service, "load_domestic_projection_anchor", lambda _as_of=None: anchor
    )
    service = ProjectedDomesticEnergyService(clock=lambda: now)
    reviews = _coverage(anchor, date(2026, 9, 29)).registry_reviews

    changed = service.refresh_regulatory_anchor(
        date(2026, 9, 29), reviews, lambda _url: b"altered source"
    )
    assert changed.ready is False
    assert CoreErrorCode.REGULATORY_SOURCE_CHANGED.value in changed.reason_codes

    applicable_reviews = _coverage(anchor, date(2026, 9, 29), applicable_act=True).registry_reviews
    applicable = service.refresh_regulatory_anchor(
        date(2026, 9, 29), applicable_reviews, lambda url: good_bytes[url]
    )
    assert applicable.ready is False
    assert CoreErrorCode.APPLICABLE_REGULATORY_ACT.value in applicable.reason_codes

    calls: list[str] = []

    def fetch_expired(url: str) -> bytes:
        calls.append(url)
        return good_bytes[url]

    expired = service.refresh_regulatory_anchor(date(2026, 10, 1), (), fetch_expired)
    assert expired.ready is False
    assert CoreErrorCode.COVERAGE_EXPIRED.value in expired.reason_codes
    assert calls == []


def test_preflight_and_compare_report_baseline_billing_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    monkeypatch.setattr(
        service,
        "_evaluate_contract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(BillingError("tax data missing")),
    )
    coverage = _coverage(anchor, AS_OF)
    preflight = service.preflight(request, catalog, history, anchor, coverage)
    assert preflight.checks["baseline_calculable"] is False
    assert CoreErrorCode.COMPARISON_FAILED.value in preflight.reason_codes
    with pytest.raises(CoreContractError) as error:
        service.compare(request, catalog, history, anchor, coverage)
    assert error.value.code == CoreErrorCode.COMPARISON_FAILED


def test_market_history_matcher_rejects_status_index_points_and_provenance_mutations() -> None:
    history = _history(AS_OF)
    service = ProjectedDomesticEnergyService()
    report = history.reports[0]

    wrong_report_status = history.model_copy(
        update={
            "reports": (
                report.model_copy(update={"status": VerificationStatus.UNVERIFIED}),
                *history.reports[1:],
            )
        }
    )
    assert not service._market_history_matches(wrong_report_status, AS_OF)

    wrong_provenance = report.model_copy(
        update={"provenance": report.provenance.model_copy(update={"sha256": None})}
    )
    bad_digest = history.model_copy(update={"reports": (wrong_provenance, *history.reports[1:])})
    assert not service._market_history_matches(bad_digest, AS_OF)

    wrong_index = history.market_data.model_copy(
        update={"indexes": (history.market_data.indexes[0].model_copy(update={"code": "PE"}),)}
    )
    assert not service._market_history_matches(
        history.model_copy(update={"market_data": wrong_index}), AS_OF
    )

    missing_points = history.market_data.model_copy(
        update={"points": history.market_data.points[:-1]}
    )
    assert not service._market_history_matches(
        history.model_copy(update={"market_data": missing_points}), AS_OF
    )

    wrong_point = history.market_data.points[0].model_copy(update={"value": Decimal("9.99")})
    wrong_points = history.market_data.model_copy(
        update={"points": (wrong_point, *history.market_data.points[1:])}
    )
    assert not service._market_history_matches(
        history.model_copy(update={"market_data": wrong_points}), AS_OF
    )


def test_projected_month_and_aggregation_helpers_reject_invalid_empty_inputs() -> None:
    from italian_energy.domain.money import Money
    from italian_energy.integration.projected_service import (
        _aggregate_billing,
        _aggregate_pricing,
        _alternative_sort_key,
        _months,
        _percentage_difference,
    )

    horizon = future_period(AS_OF)
    assert len(_months(horizon)) == 12
    with pytest.raises(ValueError, match="complete calendar months"):
        _months(DatePeriod(start=date(2026, 10, 15), end=date(2027, 10, 1)))
    with pytest.raises(ValueError, match="empty pricing"):
        _aggregate_pricing((), horizon)
    with pytest.raises(ValueError, match="empty billing"):
        _aggregate_billing((), horizon)
    assert (
        _percentage_difference(
            Money(amount=Decimal("1")),
            Money(amount=Decimal("0")),
            RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP),
        )
        is None
    )

    comparison = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).compare(
        _indexed_request(),
        _catalog(AS_OF),
        _history(AS_OF),
        load_domestic_projection_anchor(),
        _coverage(load_domestic_projection_anchor(), AS_OF),
    )
    alternative = comparison.base.comparison_result.alternatives[0]
    with pytest.raises(ValueError, match="comparable total"):
        _alternative_sort_key(alternative.model_copy(update={"comparable_total": None}))


def test_projected_offers_without_known_price_duration_are_excluded() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    catalog = catalog.model_copy(
        update={
            "records": tuple(
                item.model_copy(update={"duration_months": None}) for item in catalog.records
            )
        }
    )
    anchor = load_domestic_projection_anchor()
    result = service.compare(request, catalog, _history(AS_OF), anchor, _coverage(anchor, AS_OF))

    for scenario in result.scenarios:
        comparison = scenario.comparison.comparison_result
        assert comparison.alternatives == ()
        assert len(comparison.excluded_offers) == 2
        assert all(
            "absent duration is not inferred" in item.detail for item in comparison.excluded_offers
        )


def test_projected_nonresident_uses_its_distinct_regulatory_profile() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor()
    result = service.compare(
        _indexed_request(residential=False),
        _catalog(AS_OF),
        _history(AS_OF),
        anchor,
        _coverage(anchor, AS_OF),
    )
    base = result.base.comparison_result

    assert base.current_pricing.breakdown.total.amount == Decimal("468.00")
    assert base.current_billing is not None
    assert base.current_billing.bill.breakdown.total.amount > Decimal("500.00")
    assert any(
        item.code.startswith("regulatory:anchor:non-resident:system:fixed")
        for item in base.current_billing.bill.breakdown.components
    )


def test_current_baseline_continuation_requires_explicit_assumption() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    contract = request.current_contract
    shorter_horizon = DatePeriod(start=date(2026, 10, 1), end=date(2027, 4, 1))
    short_contract = contract.model_copy(
        update={
            "validity": DatePeriod(start=date(2026, 9, 1), end=date(2027, 4, 1)),
            "tariff": contract.tariff.model_copy(update={"validity": shorter_horizon}),
        }
    )
    no_continuation = ProjectedDomesticComparisonRequest(
        current_contract=short_contract,
        consumption=request.consumption,
        as_of=request.as_of,
        classification=request.classification,
        eligibility=request.eligibility,
    )
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)
    preflight = service.preflight(no_continuation, catalog, history, anchor, coverage)
    assert preflight.checks["baseline_contract_covers_horizon"] is False
    assert preflight.checks["baseline_calculable"] is False
    try:
        service.compare(no_continuation, catalog, history, anchor, coverage)
    except CoreContractError as exc:
        assert "continuation was not declared" in str(exc)
    else:  # pragma: no cover - fail if the baseline is implicitly extended
        raise AssertionError("baseline continuation must be explicitly declared")

    continued = no_continuation.model_copy(update={"continuation_assumption": True})
    continued_result = service.compare(continued, catalog, history, anchor, coverage)
    assert continued_result.assumptions.current_contract_continued is True
    assert any(
        "continuation_assumption=true" in value
        for value in continued_result.base.comparison_result.current_pricing.assumptions
    )


def test_refresh_regulatory_coverage_is_compatible_alias_for_anchor_refresh() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 29, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor()
    reviews = _coverage(anchor, date(2026, 9, 29)).registry_reviews

    legacy = service.refresh_regulatory_anchor(
        date(2026, 9, 29),
        reviews,
        fetch_source=lambda _url: b"synthetic source bytes",
    )
    semantic = service.refresh_regulatory_coverage(
        date(2026, 9, 29),
        reviews,
        fetch_source=lambda _url: b"synthetic source bytes",
    )

    assert semantic == legacy
