import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Literal

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
from italian_energy.domain.costs import (
    BillingResult,
    ComponentMeaning,
    ComponentPricingTreatment,
    CostComponent,
    CostZeroReason,
    PricingResult,
)
from italian_energy.domain.formula import AddPrice, IndexReference, PriceConstant
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import (
    EnergyQuantity,
    Money,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import (
    BillingCategory,
    RegulatoryRuleSet,
    VerificationStatus,
)
from italian_energy.domain.tariff import (
    BandFormula,
    BandPrice,
    ChargeBasis,
    ChargeRule,
    FixedTariff,
    IndexedTariff,
)
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
from italian_energy.portal_offers.models import (
    PortalComponentPriceValidity,
    PortalEconomicComponent,
    PortalOfferType,
    PortalPriceValidityKind,
)
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
                "economic_conditions_duration_provenance": record.source_provenance,
                "components": (
                    PortalEconomicComponent(
                        code="test_energy",
                        description="synthetic test energy price",
                        amount=Decimal("0.12"),
                        unit="EUR/kWh",
                        band="ALL",
                        macroarea="04",
                        price_validity=PortalComponentPriceValidity(
                            kind=PortalPriceValidityKind.DEFAULT
                        ),
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


def _trioraria_request() -> ProjectedDomesticComparisonRequest:
    source_profile = _profile()
    band_shares = (("F1", Decimal("0.40")), ("F2", Decimal("0.35")), ("F3", Decimal("0.25")))
    profile = ConsumptionProfile(
        profile_id="same-profile-three-bands",
        buckets=tuple(
            bucket.model_copy(
                update={
                    "band": band,
                    "energy": EnergyQuantity(kwh=bucket.energy.kwh * share),
                }
            )
            for bucket in source_profile.buckets
            for band, share in band_shares
        ),
    )
    original = _request(profile)
    horizon = future_period(AS_OF)
    current_tariff = FixedTariff(
        tariff_id="current-trioraria",
        validity=horizon,
        prices=(
            BandPrice(
                band="F1",
                rate=UnitRate(amount=Decimal("0.08"), unit=RateUnit.EUR_PER_KWH),
            ),
            BandPrice(
                band="F2",
                rate=UnitRate(amount=Decimal("0.12"), unit=RateUnit.EUR_PER_KWH),
            ),
            BandPrice(
                band="F3",
                rate=UnitRate(amount=Decimal("0.18"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
    )
    return original.model_copy(
        update={
            "current_contract": original.current_contract.model_copy(
                update={"tariff": current_tariff}
            )
        }
    )


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
    assert result.assumptions.market_reference_method == "latest_complete_month_held_constant"
    assert result.assumptions.market_reference_period == DatePeriod(
        start=date(2026, 8, 1), end=date(2026, 9, 1)
    )
    assert result.assumptions.market_reference_value_eur_per_kwh == Decimal("0.10")
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


def test_projected_comparison_uses_latest_pun_and_applies_declared_spread() -> None:
    source = _history(AS_OF)
    reports = []
    for index, report in enumerate(source.reports):
        value = Decimal("0.10") if index < 11 else Decimal("0.20")
        reports.append(
            report.model_copy(
                update={
                    "parsed": report.parsed.model_copy(
                        update={
                            "published_value_eur_per_mwh": value.scaleb(3),
                            "value_eur_per_kwh": value,
                        }
                    )
                }
            )
        )
    history = history_from_reports(AS_OF, tuple(reports))
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor()

    result = service.compare(
        _indexed_request(), _catalog(AS_OF), history, anchor, _coverage(anchor, AS_OF)
    )

    low, base, high = (item.comparison.comparison_result for item in result.scenarios)
    assert low.current_pricing.breakdown.total.amount == Decimal("684.00")
    assert base.current_pricing.breakdown.total.amount == Decimal("828.00")
    assert high.current_pricing.breakdown.total.amount == Decimal("972.00")
    assert result.assumptions.market_reference_value_eur_per_kwh == Decimal("0.20")


def test_projected_comparison_prices_bioraria_offer_against_trioraria_current() -> None:
    request = _trioraria_request()
    original_catalog = _catalog(AS_OF)
    source_offer = original_catalog.records[0]
    bioraria_offer = source_offer.model_copy(
        update={
            "offer_type": PortalOfferType.FIXED,
            "index_code": None,
            "index_codes": (),
            "index_granularity": None,
            "components": (
                PortalEconomicComponent(
                    code="energy_bf1",
                    description="Prezzo energia fascia BF1",
                    amount=Decimal("0.10"),
                    unit="EUR/kWh",
                    band="07",
                    macroarea="04",
                    price_validity=PortalComponentPriceValidity(
                        kind=PortalPriceValidityKind.DEFAULT
                    ),
                ),
                PortalEconomicComponent(
                    code="energy_bf23",
                    description="Prezzo energia fasce BF23",
                    amount=Decimal("0.11"),
                    unit="EUR/kWh",
                    band="08",
                    macroarea="04",
                    price_validity=PortalComponentPriceValidity(
                        kind=PortalPriceValidityKind.DEFAULT
                    ),
                ),
            ),
            "raw_fields": (("TIPOLOGIA_FASCE:1", "07"),),
        }
    )
    catalog = original_catalog.model_copy(update={"records": (bioraria_offer,)})
    anchor = load_domestic_projection_anchor()

    result = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).compare(request, catalog, _history(AS_OF), anchor, _coverage(anchor, AS_OF))

    base = result.scenarios[1].comparison.comparison_result
    assert len(base.alternatives) == 1
    assert base.current_pricing.breakdown.total.amount == Decimal("142.80")
    assert base.alternatives[0].pricing.breakdown.total.amount == Decimal("127.20")
    assert base.alternatives[0].savings is not None
    assert base.alternatives[0].savings.amount > 0


def test_trioraria_current_tariff_compares_with_bioraria_pun_plus_spread() -> None:
    request = _trioraria_request()
    original_catalog = _catalog(AS_OF)
    source_offer = original_catalog.records[0]
    pun_offer = source_offer.model_copy(
        update={
            "offer_type": PortalOfferType.INDEXED,
            "index_code": "01",
            "index_codes": (),
            "index_granularity": "month",
            "components": (
                PortalEconomicComponent(
                    code="spread",
                    description="PUN più delta commerciale",
                    amount=Decimal("0.03"),
                    unit="EUR/kWh",
                    band="01",
                    macroarea="04",
                    index_code="01",
                    price_validity=PortalComponentPriceValidity(
                        kind=PortalPriceValidityKind.DEFAULT
                    ),
                ),
            ),
            "raw_fields": (("TIPOLOGIA_FASCE:1", "07"),),
        }
    )
    catalog = original_catalog.model_copy(update={"records": (pun_offer,)})
    source_history = _history(AS_OF)
    reports = tuple(
        report.model_copy(
            update={
                "parsed": report.parsed.model_copy(
                    update={
                        "published_value_eur_per_mwh": Decimal("200")
                        if index == len(source_history.reports) - 1
                        else Decimal("100"),
                        "value_eur_per_kwh": Decimal("0.20")
                        if index == len(source_history.reports) - 1
                        else Decimal("0.10"),
                    }
                )
            }
        )
        for index, report in enumerate(source_history.reports)
    )
    history = history_from_reports(AS_OF, reports)
    anchor = load_domestic_projection_anchor()

    result = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).compare(request, catalog, history, anchor, _coverage(anchor, AS_OF))

    base = result.scenarios[1].comparison.comparison_result
    import_result = result.scenarios[1].comparison.import_result
    assert len(import_result.eligible_offers) == 1, import_result.exclusions[0].detail
    assert result.assumptions.market_reference_value_eur_per_kwh == Decimal("0.20")
    assert base.current_pricing.breakdown.total.amount == Decimal("142.80")
    assert len(base.alternatives) == 1, base.excluded_offers
    assert base.alternatives[0].pricing.breakdown.total.amount == Decimal("276.00")
    assert base.alternatives[0].savings is not None
    assert base.alternatives[0].savings.amount < 0


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


def test_projected_source_preflight_validates_current_rollover_evidence() -> None:
    from test_regulatory_rollover_service import AS_OF as ROLLOVER_AS_OF
    from test_regulatory_rollover_service import _service

    from italian_energy.arera.rollover_models import RegulatoryRolloverReason

    rollover_service, repository, _ = _service()
    report = rollover_service.refresh_regulatory_state(ROLLOVER_AS_OF)
    anchor = repository.read_current_anchor()
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 30, 13, tzinfo=UTC))

    ready = service.source_preflight(
        ROLLOVER_AS_OF,
        _catalog(ROLLOVER_AS_OF),
        _history(ROLLOVER_AS_OF),
        anchor,
        report.current_coverage,
    )
    assert ready.ready

    first_check = report.current_coverage.source_checks[0]
    altered_evidence = (
        report.current_coverage.model_copy(update={"ready": False, "reason_codes": ()}),
        report.current_coverage.model_copy(
            update={
                "reason_codes": (RegulatoryRolloverReason.PARSER_FAILURE,),
                "ready": False,
            }
        ),
        report.current_coverage.model_copy(update={"source_checks": ()}),
        report.current_coverage.model_copy(
            update={
                "source_checks": (
                    first_check.model_copy(update={"expected_sha256": "f" * 64}),
                    *report.current_coverage.source_checks[1:],
                )
            }
        ),
        report.current_coverage.model_copy(
            update={
                "source_checks": (
                    first_check.model_copy(update={"observed_sha256": None}),
                    *report.current_coverage.source_checks[1:],
                )
            }
        ),
        report.current_coverage.model_copy(
            update={
                "source_checks": (
                    first_check.model_copy(update={"observed_sha256": "f" * 64}),
                    *report.current_coverage.source_checks[1:],
                )
            }
        ),
        report.current_coverage.model_copy(
            update={
                "source_checks": (
                    first_check.model_copy(
                        update={"checked_at": datetime(2026, 10, 1, 12, tzinfo=UTC)}
                    ),
                    *report.current_coverage.source_checks[1:],
                )
            }
        ),
    )

    reasons = tuple(
        service._coverage_evidence_reasons(anchor, ROLLOVER_AS_OF, evidence)
        for evidence in altered_evidence
    )
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in reasons[0]
    assert RegulatoryRolloverReason.PARSER_FAILURE.value in reasons[1]
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in reasons[2]
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in reasons[3]
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in reasons[4]
    assert CoreErrorCode.REGULATORY_SOURCE_CHANGED.value in reasons[5]
    assert CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value in reasons[6]


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


def test_projected_legacy_economic_snapshots_require_a_catalog_refresh() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request()
    catalog = _catalog(AS_OF)
    catalog = catalog.model_copy(
        update={
            "records": tuple(
                item.model_copy(update={"economic_validity_version": None})
                for item in catalog.records
            )
        }
    )
    anchor = load_domestic_projection_anchor()
    result = service.compare(request, catalog, _history(AS_OF), anchor, _coverage(anchor, AS_OF))

    for scenario in result.scenarios:
        comparison = scenario.comparison.comparison_result
        assert comparison.alternatives == ()
        assert len(scenario.comparison.import_result.exclusions) == 2
        assert all(
            item.code.value == "economic_terms_unverified"
            for item in scenario.comparison.import_result.exclusions
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
        current_component_coverage=request.current_component_coverage,
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


def _fixed_annual_continuation_request(
    *,
    continuation: bool,
    continuation_policy: Literal["follow_tariff"] | None = "follow_tariff",
    charge_validity: DatePeriod | None = None,
    full_horizon: bool = False,
) -> ProjectedDomesticComparisonRequest:
    request = _request()
    horizon = future_period(AS_OF)
    original_tariff_validity = (
        horizon if full_horizon else DatePeriod(start=date(2026, 12, 5), end=date(2027, 4, 1))
    )
    original_contract_validity = DatePeriod(
        start=date(2026, 9, 1), end=horizon.end if full_horizon else original_tariff_validity.end
    )
    ordinary_rule = ChargeRule(
        code="fixed_annual",
        description="Commercial fixed fee",
        basis=ChargeBasis.PER_YEAR,
        value=UnitRate(amount=Decimal("84"), unit=RateUnit.EUR_PER_YEAR),
        validity=charge_validity or original_tariff_validity,
        continuation_policy=continuation_policy,
    )
    promotional_rule = ChargeRule(
        code="promo_annual",
        description="Temporary annual discount",
        basis=ChargeBasis.PER_YEAR,
        value=UnitRate(amount=Decimal("-84"), unit=RateUnit.EUR_PER_YEAR),
        validity=DatePeriod(start=date(2026, 12, 5), end=date(2027, 4, 1)),
        discount=True,
        continuation_policy="follow_tariff",
    )
    tariff = FixedTariff(
        tariff_id="current-fixed-annual",
        validity=original_tariff_validity,
        prices=(
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
        fixed_charges=(ordinary_rule,),
        discounts=(promotional_rule,),
    )
    contract = request.current_contract.model_copy(
        update={"validity": original_contract_validity, "tariff": tariff}
    )
    return request.model_copy(
        update={
            "current_contract": contract,
            "continuation_assumption": continuation,
        }
    )


def test_projected_continuation_extends_only_explicit_ordinary_annual_fixed_charge() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)
    horizon = future_period(AS_OF)
    short_validity = DatePeriod(start=date(2026, 12, 5), end=date(2027, 4, 1))

    continued = service.compare(
        _fixed_annual_continuation_request(continuation=True),
        catalog,
        history,
        anchor,
        coverage,
    ).base.comparison_result
    full_term = service.compare(
        _fixed_annual_continuation_request(continuation=False, full_horizon=True),
        catalog,
        history,
        anchor,
        coverage,
    ).base.comparison_result

    fixed_fee = next(
        item
        for item in continued.current_pricing.breakdown.components
        if item.code == "fixed:fixed_annual"
    )
    promo = next(
        item
        for item in continued.current_pricing.breakdown.components
        if item.code == "discount:promo_annual"
    )
    assert fixed_fee.amount.amount == Decimal("84.00")
    assert fixed_fee.quantity is not None
    assert fixed_fee.quantity.quantize(Decimal("0.000001")) == Decimal("1.000000")
    assert fixed_fee.period == horizon
    assert fixed_fee.applied_periods == (horizon,)
    assert promo.amount.amount == Decimal("-27.21")
    assert promo.applied_periods == (short_validity,)

    assert continued.current_billing is not None
    assert full_term.current_billing is not None
    current_bill = continued.current_billing.bill
    full_bill = full_term.current_billing.bill
    vat = next(
        item for item in current_bill.breakdown.components if item.category == BillingCategory.VAT
    )
    assert vat.amount.amount > 0
    assert current_bill.breakdown.total == sum(
        (item.amount for item in current_bill.breakdown.components),
        Money(amount=Decimal(0)),
    )
    assert current_bill.breakdown.total == full_bill.breakdown.total
    assert continued.alternatives == full_term.alternatives

    with pytest.raises(CoreContractError, match="continuation was not declared"):
        service.compare(
            _fixed_annual_continuation_request(continuation=False),
            catalog,
            history,
            anchor,
            coverage,
        )


def test_projected_continuation_does_not_infer_policy_or_extend_ambiguous_validity() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)

    untagged = service.compare(
        _fixed_annual_continuation_request(continuation=True, continuation_policy=None),
        catalog,
        history,
        anchor,
        coverage,
    ).base.comparison_result
    untagged_fee = next(
        item
        for item in untagged.current_pricing.breakdown.components
        if item.code == "fixed:fixed_annual"
    )
    assert untagged_fee.amount.amount == Decimal("27.21")
    assert untagged_fee.applied_periods == (
        DatePeriod(start=date(2026, 12, 5), end=date(2027, 4, 1)),
    )

    ambiguous_validity = service.compare(
        _fixed_annual_continuation_request(
            continuation=True,
            charge_validity=DatePeriod(start=date(2026, 12, 6), end=date(2027, 4, 1)),
        ),
        catalog,
        history,
        anchor,
        coverage,
    ).base.comparison_result
    ambiguous_fee = next(
        item
        for item in ambiguous_validity.current_pricing.breakdown.components
        if item.code == "fixed:fixed_annual"
    )
    assert ambiguous_fee.amount.amount == Decimal("26.98")
    assert ambiguous_fee.applied_periods == (
        DatePeriod(start=date(2026, 12, 6), end=date(2027, 4, 1)),
    )


def test_cost_component_effective_periods_default_and_merge_only_contiguous_windows() -> None:
    from italian_energy.integration.projected_service import _aggregate_components

    horizon = future_period(AS_OF)
    october = DatePeriod(start=date(2026, 10, 1), end=date(2026, 11, 1))
    december = DatePeriod(start=date(2026, 12, 1), end=date(2027, 1, 1))
    component = CostComponent(
        code="test:period",
        description="Period test",
        amount=Money(amount=Decimal("1")),
        period=october,
        formula="test",
    )
    assert component.applied_periods == (october,)
    assert CostComponent.model_validate(component.model_dump()) == component
    legacy_component = CostComponent.model_validate(
        {key: value for key, value in component.model_dump().items() if key != "applied_periods"}
    )
    assert legacy_component.applied_periods == (october,)

    with pytest.raises(ValueError, match="zero_reason is valid only for a zero-valued component"):
        CostComponent.model_validate(
            component.model_dump()
            | {
                "amount": Money(amount=Decimal("1")),
                "zero_reason": CostZeroReason.MONTHLY_RESIDENT_EXEMPTION,
            }
        )

    aggregated = _aggregate_components(
        (
            component,
            CostComponent(
                code=component.code,
                description=component.description,
                amount=Money(amount=Decimal("2")),
                period=december,
                formula=component.formula,
            ),
        ),
        horizon,
    )[0]
    assert aggregated.period == horizon
    assert aggregated.applied_periods == (october, december)

    extended = _aggregate_components(
        (
            component,
            CostComponent(
                code=component.code,
                description=component.description,
                amount=Money(amount=Decimal("2")),
                period=DatePeriod(start=date(2026, 10, 15), end=date(2026, 12, 15)),
                formula=component.formula,
            ),
            CostComponent(
                code=component.code,
                description=component.description,
                amount=Money(amount=Decimal("3")),
                period=december,
                formula=component.formula,
            ),
        ),
        horizon,
    )[0]
    assert extended.applied_periods == (DatePeriod(start=october.start, end=december.end),)


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


def _request_with_component_coverage(
    request: ProjectedDomesticComparisonRequest, coverage: dict[str, object] | None
) -> ProjectedDomesticComparisonRequest:
    payload = request.model_dump(mode="python")
    payload["current_component_coverage"] = coverage
    return ProjectedDomesticComparisonRequest.model_validate(payload)


def test_current_component_coverage_missing_or_unknown_blocks_preflight_and_comparison() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _request_with_component_coverage(_indexed_request(), None)
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)

    preflight = service.preflight(request, catalog, history, anchor, coverage)
    expected = {
        CoreErrorCode.CURRENT_NETWORK_LOSSES_COVERAGE_UNKNOWN.value,
        CoreErrorCode.CURRENT_DISPATCHING_CAPACITY_COVERAGE_UNKNOWN.value,
    }
    assert preflight.checks["current_component_coverage_complete"] is False
    assert preflight.checks["baseline_calculable"] is False
    assert expected.issubset(set(preflight.reason_codes))

    with pytest.raises(CoreContractError) as error:
        service.compare(request, catalog, history, anchor, coverage)
    assert error.value.code == CoreErrorCode.CURRENT_NETWORK_LOSSES_COVERAGE_UNKNOWN
    with pytest.raises(CoreContractError) as error:
        service._contract_with_current_component_coverage(request, request.current_contract)
    assert error.value.code == CoreErrorCode.CURRENT_NETWORK_LOSSES_COVERAGE_UNKNOWN


@pytest.mark.parametrize(
    ("missing_component", "expected_code"),
    [
        ("network_losses", CoreErrorCode.CURRENT_NETWORK_LOSSES_RATE_MISSING),
        ("dispatching_capacity", CoreErrorCode.CURRENT_DISPATCHING_CAPACITY_RATE_MISSING),
    ],
)
def test_separate_current_component_without_rate_blocks_with_component_code(
    missing_component: str, expected_code: CoreErrorCode
) -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    declarations: dict[str, object] = {
        "network_losses": {"treatment": "included"},
        "dispatching_capacity": {"treatment": "included"},
    }
    declarations[missing_component] = {"treatment": "separate"}
    request = _request_with_component_coverage(_indexed_request(), declarations)
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)

    preflight = service.preflight(request, catalog, history, anchor, coverage)
    assert preflight.checks["current_component_coverage_complete"] is False
    assert expected_code.value in preflight.reason_codes
    with pytest.raises(CoreContractError) as error:
        service.compare(request, catalog, history, anchor, coverage)
    assert error.value.code == expected_code


def test_projected_preflight_classifies_core_and_input_validation_errors() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    base = _request_with_component_coverage(
        _indexed_request(),
        {
            "network_losses": {"treatment": "included"},
            "dispatching_capacity": {"treatment": "included"},
        },
    )
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)

    future = service.preflight(
        base.model_copy(update={"as_of": date(2026, 10, 1)}), catalog, history, anchor, coverage
    )
    empty_consumption = base.model_copy(
        update={"consumption": base.consumption.model_copy(update={"buckets": ()})}
    )
    invalid_profile = service.preflight(empty_consumption, catalog, history, anchor, coverage)

    assert future.checks["request_supported"] is False
    assert CoreErrorCode.UNSUPPORTED_HORIZON.value in future.reason_codes
    assert invalid_profile.checks["request_supported"] is False
    assert "unsupported_scenario" in invalid_profile.reason_codes


def test_current_component_coverage_adds_separate_rates_once_to_baseline_only() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    request = _indexed_request("100")
    included_request = _request_with_component_coverage(
        request,
        {
            "network_losses": {"treatment": "included"},
            "dispatching_capacity": {"treatment": "included"},
        },
    )
    separate_request = _request_with_component_coverage(
        request,
        {
            "network_losses": {
                "treatment": "separate",
                "unit_rate": UnitRate(amount=Decimal("0.015"), unit=RateUnit.EUR_PER_KWH),
            },
            "dispatching_capacity": {
                "treatment": "separate",
                "unit_rate": UnitRate(amount=Decimal("0.002"), unit=RateUnit.EUR_PER_KWH),
            },
        },
    )
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)
    included_projected = service.compare(included_request, catalog, history, anchor, coverage)
    separate_projected = service.compare(separate_request, catalog, history, anchor, coverage)
    included = included_projected.base.comparison_result
    separate = separate_projected.base.comparison_result

    assert included.current_billing is not None
    assert separate.current_billing is not None
    included_codes = {item.code for item in included.current_pricing.breakdown.components}
    assert "additional:current_component_network_losses" not in included_codes
    assert "additional:current_component_dispatching_capacity" not in included_codes
    separate_pricing = separate.current_pricing.breakdown
    separate_lines = {
        item.code: item
        for item in separate_pricing.components
        if item.code.startswith("additional:")
    }
    network = separate_lines["additional:current_component_network_losses"]
    dispatch = separate_lines["additional:current_component_dispatching_capacity"]
    assert network.amount.amount == Decimal("18.00")
    assert dispatch.amount.amount == Decimal("2.40")
    assert network.applied_periods == (future_period(AS_OF),)
    assert dispatch.applied_periods == (future_period(AS_OF),)
    assert network.meaning == ComponentMeaning.NETWORK_LOSSES
    assert network.pricing_treatment == ComponentPricingTreatment.SEPARATE
    assert network.losses_included is False
    assert dispatch.meaning == ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
    assert dispatch.included_semantics == (
        ComponentMeaning.DISPATCHING,
        ComponentMeaning.CAPACITY_MARKET,
    )
    assert (
        separate_projected.current_component_coverage == separate_request.current_component_coverage
    )
    coverage_json = separate_projected.model_dump(mode="json")["current_component_coverage"]
    assert coverage_json["network_losses"]["treatment"] == "separate"
    assert coverage_json["dispatching_capacity"]["unit_rate"]["unit"] == "EUR/kWh"
    assert sum(item.code == network.code for item in separate_pricing.components) == 1
    assert sum(item.code == dispatch.code for item in separate_pricing.components) == 1

    separate_bill = separate.current_billing.bill.breakdown
    bill_lines = {item.code: item for item in separate_bill.components}
    assert bill_lines[network.code].amount.amount == Decimal("18.00")
    assert bill_lines[dispatch.code].amount.amount == Decimal("2.40")
    assert bill_lines[network.code].meaning == ComponentMeaning.NETWORK_LOSSES
    assert bill_lines[network.code].pricing_treatment == ComponentPricingTreatment.SEPARATE
    assert bill_lines[network.code].losses_included is False
    assert bill_lines[dispatch.code].meaning == ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
    assert bill_lines[dispatch.code].included_semantics == (
        ComponentMeaning.DISPATCHING,
        ComponentMeaning.CAPACITY_MARKET,
    )
    assert sum(item.code == network.code for item in separate_bill.components) == 1
    assert sum(item.code == dispatch.code for item in separate_bill.components) == 1

    included_vat = next(
        item
        for item in included.current_billing.bill.breakdown.components
        if item.category == BillingCategory.VAT
    )
    separate_vat = next(
        item for item in separate_bill.components if item.category == BillingCategory.VAT
    )
    assert separate_vat.amount.amount - included_vat.amount.amount == Decimal("2.04")
    assert (
        separate_bill.total.amount - included.current_billing.bill.breakdown.total.amount
        == Decimal("22.44")
    )
    assert separate_bill.total == sum(
        (item.amount for item in separate_bill.components), Money(amount=Decimal(0))
    )
    assert tuple(item.offer_id for item in separate.alternatives) == tuple(
        item.offer_id for item in included.alternatives
    )
    assert all(
        current.pricing == baseline.pricing and current.billing == baseline.billing
        for current, baseline in zip(separate.alternatives, included.alternatives, strict=True)
    )
    assert separate.ranking == included.ranking


def test_current_component_coverage_rejects_conflicts_and_reuses_exact_charge() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    base_request = _indexed_request("100")
    network_rate = UnitRate(amount=Decimal("0.015"), unit=RateUnit.EUR_PER_KWH)
    existing_charge = ChargeRule(
        code="current_component_network_losses",
        description="Declared network losses",
        basis=ChargeBasis.PER_KWH,
        value=network_rate,
    )
    tariff = base_request.current_contract.tariff
    contract_with_charge = base_request.current_contract.model_copy(
        update={
            "tariff": tariff.model_copy(
                update={"additional_charges": (*tariff.additional_charges, existing_charge)}
            )
        }
    )
    covered_contract = base_request.model_copy(update={"current_contract": contract_with_charge})

    included = _request_with_component_coverage(
        covered_contract,
        {
            "network_losses": {"treatment": "included"},
            "dispatching_capacity": {"treatment": "included"},
        },
    )
    conflict_preflight = service.preflight(
        included,
        _catalog(AS_OF),
        _history(AS_OF),
        load_domestic_projection_anchor(),
        _coverage(load_domestic_projection_anchor(), AS_OF),
    )
    assert conflict_preflight.checks["current_component_coverage_complete"] is False
    assert CoreErrorCode.CURRENT_COMPONENT_CHARGE_CONFLICT.value in conflict_preflight.reason_codes
    with pytest.raises(CoreContractError) as error:
        service._contract_with_current_component_coverage(included, included.current_contract)
    assert error.value.code == CoreErrorCode.CURRENT_COMPONENT_CHARGE_CONFLICT

    separate = _request_with_component_coverage(
        covered_contract,
        {
            "network_losses": {"treatment": "separate", "unit_rate": network_rate},
            "dispatching_capacity": {"treatment": "included"},
        },
    )
    reused = service._contract_with_current_component_coverage(separate, separate.current_contract)
    assert reused is separate.current_contract
    assert (
        sum(
            item.code == "current_component_network_losses"
            for item in reused.tariff.additional_charges
        )
        == 1
    )

    mismatched = _request_with_component_coverage(
        separate,
        {
            "network_losses": {
                "treatment": "separate",
                "unit_rate": UnitRate(amount=Decimal("0.02"), unit=RateUnit.EUR_PER_KWH),
            },
            "dispatching_capacity": {"treatment": "included"},
        },
    )
    mismatch_preflight = service.preflight(
        mismatched,
        _catalog(AS_OF),
        _history(AS_OF),
        load_domestic_projection_anchor(),
        _coverage(load_domestic_projection_anchor(), AS_OF),
    )
    assert CoreErrorCode.CURRENT_COMPONENT_CHARGE_CONFLICT.value in mismatch_preflight.reason_codes
    with pytest.raises(CoreContractError) as error:
        service._contract_with_current_component_coverage(mismatched, mismatched.current_contract)
    assert error.value.code == CoreErrorCode.CURRENT_COMPONENT_CHARGE_CONFLICT


def test_projected_excise_zero_reason_is_resident_and_monthly() -> None:
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    resident_request = _indexed_request("100", residential=True)
    non_resident_request = _indexed_request("100", residential=False)
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)

    resident = service.compare(
        resident_request, catalog, history, anchor, coverage
    ).base.comparison_result
    non_resident = service.compare(
        non_resident_request, catalog, history, anchor, coverage
    ).base.comparison_result
    assert resident.current_billing is not None
    assert non_resident.current_billing is not None
    resident_excise = tuple(
        item
        for item in resident.current_billing.bill.breakdown.components
        if item.code.startswith("regulatory:excise:")
    )
    non_resident_excise = tuple(
        item
        for item in non_resident.current_billing.bill.breakdown.components
        if item.code.startswith("regulatory:excise:")
    )
    assert resident_excise and non_resident_excise
    assert all(item.amount.amount == 0 for item in resident_excise)
    assert all(
        item.zero_reason == CostZeroReason.MONTHLY_RESIDENT_EXEMPTION for item in resident_excise
    )
    assert all(item.amount.amount > 0 for item in non_resident_excise)
    assert all(item.zero_reason is None for item in non_resident_excise)

    concentrated_buckets = tuple(
        bucket.model_copy(
            update={
                "energy": EnergyQuantity(
                    kwh=(
                        Decimal("180")
                        if index == 0
                        else Decimal("20")
                        if index == 1
                        else Decimal("100")
                    )
                )
            }
        )
        for index, bucket in enumerate(resident_request.consumption.buckets)
    )
    concentrated_request = resident_request.model_copy(
        update={
            "consumption": resident_request.consumption.model_copy(
                update={"buckets": concentrated_buckets}
            )
        }
    )
    assert (
        concentrated_request.consumption.total_energy().kwh
        == resident_request.consumption.total_energy().kwh
    )
    assert all(bucket.energy.kwh > 0 for bucket in concentrated_request.consumption.buckets)
    concentrated = service.compare(
        concentrated_request, catalog, history, anchor, coverage
    ).base.comparison_result
    assert concentrated.current_billing is not None
    concentrated_excise = tuple(
        item
        for item in concentrated.current_billing.bill.breakdown.components
        if item.code.startswith("regulatory:excise:")
    )
    assert sum((item.amount.amount for item in concentrated_excise), Decimal(0)) > sum(
        (item.amount.amount for item in resident_excise), Decimal(0)
    )
    assert any(item.zero_reason is None and item.amount.amount > 0 for item in concentrated_excise)


def test_current_component_coverage_rejects_non_eur_per_kwh_rate() -> None:
    request = _indexed_request()
    with pytest.raises(ValueError, match="EUR/kWh"):
        _request_with_component_coverage(
            request,
            {
                "network_losses": {
                    "treatment": "separate",
                    "unit_rate": UnitRate(amount=Decimal("15"), unit=RateUnit.EUR_PER_MWH),
                },
                "dispatching_capacity": {"treatment": "included"},
            },
        )


def test_projected_cdispd_does_not_carry_august_rate_into_annual_horizon() -> None:
    from test_cdispd_reference import _verified_import

    from italian_energy.arera.cdispd_reference import cdispd_reference_snapshot_from_import
    from italian_energy.portal_offers.models import (
        PORTAL_DISPATCHING_MAPPING_VERSION,
        PortalComponentSemantic,
        PortalLossTreatment,
        PortalPricingTreatment,
    )

    as_of = date(2026, 10, 18)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    base_request = _indexed_request()
    history_months = (
        *(date(2025, month, 1) for month in range(10, 13)),
        *(date(2026, month, 1) for month in range(1, 10)),
    )
    shifted_profile = base_request.consumption.model_copy(
        update={
            "buckets": tuple(
                bucket.model_copy(
                    update={
                        "interval": bucket.interval.model_copy(
                            update={
                                "start": datetime(month.year, month.month, 1, tzinfo=UTC),
                                "end": datetime(
                                    month.year + (month.month == 12),
                                    month.month % 12 + 1,
                                    1,
                                    tzinfo=UTC,
                                ),
                            }
                        )
                    }
                )
                for bucket, month in zip(
                    base_request.consumption.buckets, history_months, strict=True
                )
            )
        }
    )
    request = base_request.model_copy(
        update={
            "as_of": as_of,
            "consumption": shifted_profile,
            "continuation_assumption": True,
        }
    )
    catalog_source = _catalog(AS_OF)
    offer_period = DatePeriod(start=date(2026, 10, 1), end=date(2027, 11, 1))
    source_record = catalog_source.records[0]
    portal_provenance = tuple(
        item.model_copy(update={"effective_period": offer_period})
        for item in source_record.source_provenance
    )
    cdispd = PortalEconomicComponent(
        code="dispatching:14",
        description="Aggregated dispatching and capacity charge",
        amount=None,
        unit="EUR/kWh",
        source_code="14",
        semantic=PortalComponentSemantic.DISPATCHING_CAPACITY_AGGREGATE,
        pricing_treatment=PortalPricingTreatment.REGULATORY_REFERENCE,
        loss_treatment=PortalLossTreatment.INCLUDED,
        included_semantics=(
            PortalComponentSemantic.DISPATCHING,
            PortalComponentSemantic.CAPACITY_MARKET,
        ),
        period=offer_period,
        mapping_version=PORTAL_DISPATCHING_MAPPING_VERSION,
        source_provenance=portal_provenance,
        source_fields=(("TIPO_DISPACCIAMENTO", "14"),),
    )
    annual_record = source_record.model_copy(
        update={
            "subscription_period": offer_period,
            "tariff_validity": offer_period,
            "duration_months": 14,
            "components": (*source_record.components, cdispd),
            "source_provenance": tuple(
                item.model_copy(update={"effective_period": offer_period})
                for item in source_record.source_provenance
            ),
        }
    )
    catalog = catalog_source.model_copy(update={"records": (annual_record,)})
    anchor = load_domestic_projection_anchor(as_of)
    coverage = _coverage(anchor, as_of)
    reference = cdispd_reference_snapshot_from_import(_verified_import(month_count=8))

    horizon = future_period(as_of)
    readiness = service.preflight(
        request,
        catalog,
        _history(as_of),
        anchor,
        coverage,
        cdispd_reference=reference,
    )

    assert horizon == DatePeriod(start=date(2026, 11, 1), end=date(2027, 11, 1))
    assert reference.validity == DatePeriod(start=date(2026, 1, 1), end=date(2026, 9, 1))
    assert readiness.official_data_ready is True
    assert readiness.checks["cdispd_reference_period_covered"] is False
    assert readiness.horizon_eligible_offer_count == 0
    assert readiness.ready is False
    assert "cdispd_reference_unavailable" in readiness.reason_codes

    with pytest.raises(CoreContractError, match="no complete candidate"):
        service.compare(
            request,
            catalog,
            _history(as_of),
            anchor,
            coverage,
            cdispd_reference=reference,
        )

    complete_record = catalog_source.records[1].model_copy(
        update={
            "subscription_period": offer_period,
            "tariff_validity": offer_period,
            "duration_months": 14,
            "source_provenance": tuple(
                item.model_copy(update={"effective_period": offer_period})
                for item in catalog_source.records[1].source_provenance
            ),
        }
    )
    catalog_with_fallback = catalog.model_copy(update={"records": (annual_record, complete_record)})
    fallback_preflight = service.preflight(
        request,
        catalog_with_fallback,
        _history(as_of),
        anchor,
        coverage,
        cdispd_reference=reference,
    )
    assert fallback_preflight.official_data_ready is True
    assert fallback_preflight.checks["cdispd_reference_period_covered"] is False
    assert fallback_preflight.horizon_eligible_offer_count == 1
    assert fallback_preflight.ready is True

    fallback_comparison = service.compare(
        request,
        catalog_with_fallback,
        _history(as_of),
        anchor,
        coverage,
        cdispd_reference=reference,
    )
    assert len(fallback_comparison.base.comparison_result.alternatives) == 1
    assert fallback_comparison.verified_inputs.cdispd_reference_snapshot_id == reference.snapshot_id
    assert fallback_comparison.verified_inputs.cdispd_reference_snapshot_digest == reference.digest
    assert fallback_comparison.verified_inputs.cdispd_reference_period == horizon


def _current_parameter_case(
    as_of: date, *, residential: bool = True, rate: str = "0.020000"
) -> tuple[ProjectedDomesticComparisonRequest, CurrentCatalogSnapshot]:
    from italian_energy.portal_offers.dispatching_mapping import make_dispatching_component

    request = _indexed_request(residential=residential)
    months = recent_months(as_of)
    request = request.model_copy(
        update={
            "as_of": as_of,
            "continuation_assumption": True,
            "eligibility": request.eligibility.model_copy(update={"residential": residential}),
            "consumption": request.consumption.model_copy(
                update={
                    "buckets": tuple(
                        bucket.model_copy(
                            update={
                                "interval": bucket.interval.model_copy(
                                    update={
                                        "start": datetime(month.year, month.month, 1, tzinfo=UTC),
                                        "end": datetime(
                                            month.year + (month.month == 12),
                                            month.month % 12 + 1,
                                            1,
                                            tzinfo=UTC,
                                        ),
                                    }
                                )
                            }
                        )
                        for bucket, month in zip(request.consumption.buckets, months, strict=True)
                    )
                }
            ),
        }
    )
    transport = _transport()
    transport.contents = {
        **transport.contents,
        "parametriML": (
            (
                "nome_parametro,valore,descrizione\n"
                f"cdispd,{rate},Corrispettivo capacita e dispacciamento\n"
            ).encode(),
            "text/csv",
        ),
    }
    catalog = CurrentDomesticEnergyService(
        importer=PortalOffersImporter(transport=transport)
    ).acquire_catalog(as_of)
    template = _catalog(AS_OF).records[0]
    offer_period = DatePeriod(start=as_of.replace(day=1), end=future_period(as_of).end)
    cdispd = make_dispatching_component(
        source_code="14",
        name="CdispD",
        description="Dispacciamento e mercato capacita",
        amount=None,
        period=offer_period,
        source_fields=(("TIPO_DISPACCIAMENTO", "14"),),
        source_provenance=template.source_provenance,
    )
    record = template.model_copy(
        update={
            "subscription_period": offer_period,
            "tariff_validity": offer_period,
            "duration_months": 13,
            "components": (*template.components, cdispd),
        }
    )
    return request, catalog.model_copy(update={"records": (record,)})


@pytest.mark.parametrize("as_of", [AS_OF, date(2026, 10, 18)])
@pytest.mark.parametrize("residential", [True, False])
def test_projected_current_cdispd_parameter_prices_the_year_after_envelope_hydration(
    as_of: date, residential: bool
) -> None:
    from italian_energy.integration.serialization import dump_envelope, load_envelope

    request, catalog = _current_parameter_case(as_of, residential=residential)
    hydrated = load_envelope(dump_envelope(catalog))
    assert isinstance(hydrated, CurrentCatalogSnapshot)
    assert all(file.content is None for file in hydrated.snapshot.offers.files)
    service = ProjectedDomesticEnergyService(
        clock=lambda: datetime(as_of.year, as_of.month, as_of.day, 12, tzinfo=UTC)
    )
    anchor = load_domestic_projection_anchor(as_of)
    coverage = _coverage(anchor, as_of)
    history = _history(as_of)
    readiness = service.preflight(request, hydrated, history, anchor, coverage)
    assert readiness.ready is True
    assert readiness.horizon_eligible_offer_count == 1
    assert readiness.checks["cdispd_parameter_projection_available"] is True
    assert "cdispd_reference_unavailable" not in readiness.reason_codes

    result = service.compare(request, hydrated, history, anchor, coverage)
    projection = result.assumptions.cdispd_projection
    assert projection is not None
    assert projection.parameter.dataset_date == as_of
    assert projection.parameter.rate.amount == Decimal("0.020000")
    assert projection.period == future_period(as_of)
    assert projection.future_values_verified is False
    assert projection.costs_are_estimates is True
    assert projection.policy == "portal_current_parameter_constant"
    assert projection.catalog_snapshot_id == hydrated.snapshot.offers.snapshot_id
    assert projection.parameter.provenance[0].effective_period != result.period

    without_charge = hydrated.model_copy(
        update={
            "records": (
                hydrated.records[0].model_copy(
                    update={"components": hydrated.records[0].components[:-1]}
                ),
            )
        }
    )
    control = service.compare(request, without_charge, history, anchor, coverage)
    for scenario, control_scenario in zip(result.scenarios, control.scenarios, strict=True):
        alternative = scenario.comparison.comparison_result.alternatives[0]
        control_alternative = control_scenario.comparison.comparison_result.alternatives[0]
        charges = tuple(
            component
            for component in alternative.pricing.breakdown.components
            if component.meaning == ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
        )
        assert len(charges) == 1
        charge = charges[0]
        # Independent arithmetic: twelve months * 300 kWh * EUR 0.02 = EUR 72.
        # VAT at 10% adds EUR 7.20; no extra 10% network-loss uplift is allowed.
        assert charge.quantity == Decimal("3600")
        assert charge.amount.amount == Decimal("72.00")
        assert charge.unit_rate == UnitRate(amount=Decimal("0.02"), unit=RateUnit.EUR_PER_KWH)
        assert charge.losses_included is True
        assert charge.applied_periods == (future_period(as_of),)
        assert alternative.comparable_total is not None
        assert control_alternative.comparable_total is not None
        assert (
            alternative.comparable_total.amount - control_alternative.comparable_total.amount
            == Decimal("79.20")
        )
    assert result.result_id != control.result_id
    restored = load_envelope(dump_envelope(result))
    assert restored == result


def test_projected_cdispd_parameter_changes_result_digest_and_rejects_stale_parameter() -> None:
    from italian_energy.portal_offers.models import PortalSourceRole

    as_of = date(2026, 10, 18)
    request, catalog = _current_parameter_case(as_of)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor(as_of)
    history = _history(as_of)
    coverage = _coverage(anchor, as_of)
    first = service.compare(request, catalog, history, anchor, coverage)
    _, changed = _current_parameter_case(as_of, rate="0.030000")
    second = service.compare(request, changed, history, anchor, coverage)
    assert first.result_id != second.result_id
    assert first.assumptions.cdispd_projection != second.assumptions.cdispd_projection
    assert first.base.comparison_result.ranking == second.base.comparison_result.ranking

    _, stale = _current_parameter_case(as_of - timedelta(days=1))
    invalid_offers = catalog.snapshot.offers.model_copy(
        update={"cdispd_parameter": stale.snapshot.offers.cdispd_parameter}
    )
    stale_catalog = catalog.model_copy(
        update={"snapshot": catalog.snapshot.model_copy(update={"offers": invalid_offers})}
    )
    with pytest.raises(ValueError, match="must match the verified daily catalog source"):
        CurrentCatalogSnapshot.model_validate_json(stale_catalog.model_dump_json())
    readiness = service.preflight(request, stale, history, anchor, coverage)
    assert readiness.ready is False
    assert readiness.checks["cdispd_parameter_projection_available"] is False

    parameter_file = next(
        file
        for file in catalog.snapshot.offers.files
        if file.role == PortalSourceRole.MARKET_FREE_PARAMETERS
    )
    assert first.assumptions.cdispd_projection is not None
    assert (
        first.assumptions.cdispd_projection.parameter.provenance[0].sha256 == parameter_file.sha256
    )
    assert stale.snapshot.offers.cdispd_parameter is not None
    for attribute, bad_value in (
        ("catalog_snapshot_id", "portal-snapshot:" + "0" * 64),
        ("period", {"start": "2026-11-01", "end": "2027-12-01"}),
        ("parameter", stale.snapshot.offers.cdispd_parameter.model_dump(mode="json")),
    ):
        tampered = first.model_dump(mode="json")
        tampered["assumptions"]["cdispd_projection"][attribute] = bad_value
        with pytest.raises(ValueError, match="current catalog and future horizon"):
            type(first).model_validate(tampered)


def _catalog_expiring_before_activation(
    as_of: date,
    *,
    expires_on: date = date(2026, 10, 31),
    duration: int | None = 12,
    annual_fee: str = "120",
    component_duration: int | None = None,
) -> CurrentCatalogSnapshot:
    from test_portal_offers import XML

    transport = _transport()
    xml = XML.replace(
        b"31/12/2026_23:59:59",
        f"{expires_on:%d/%m/%Y}_23:59:59".encode(),
    ).replace(
        b"<FASCIA_COMPONENTE>01</FASCIA_COMPONENTE>", b"<FASCIA_COMPONENTE>91</FASCIA_COMPONENTE>"
    )
    if duration is not None:
        xml = xml.replace(
            b"</DettaglioOfferta>", f"<DURATA>{duration}</DURATA></DettaglioOfferta>".encode()
        )
    if component_duration is not None:
        xml = xml.replace(
            b"</IntervalloPrezzi>",
            (
                f"<PeriodoValidita><DURATA>{component_duration}</DURATA></PeriodoValidita>"
                "</IntervalloPrezzi>"
            ).encode(),
        )
    xml = xml.replace(b"<PREZZO>120</PREZZO>", f"<PREZZO>{annual_fee}</PREZZO>".encode())
    transport.contents = {**transport.contents, "offerteML": (xml, "application/xml")}
    catalog = CurrentDomesticEnergyService(
        importer=PortalOffersImporter(transport=transport)
    ).acquire_catalog(as_of)
    return catalog.model_copy(
        update={"records": tuple(r for r in catalog.records if r.catalog.value == "market_free")}
    )


@pytest.mark.parametrize("as_of", [date(2026, 10, 18), date(2026, 10, 31)])
def test_projected_subscription_expiry_does_not_shorten_twelve_month_prices(as_of: date) -> None:
    from italian_energy.integration.serialization import dump_envelope, load_envelope

    service = ProjectedDomesticEnergyService(
        clock=lambda: datetime(as_of.year, as_of.month, as_of.day, 12, tzinfo=UTC)
    )
    request, _ = _current_parameter_case(as_of)
    catalog = _catalog_expiring_before_activation(as_of)
    restored = load_envelope(dump_envelope(catalog))
    assert isinstance(restored, CurrentCatalogSnapshot)
    anchor = load_domestic_projection_anchor(as_of)
    history = _history(as_of)
    coverage = _coverage(anchor, as_of)

    readiness = service.preflight(request, restored, history, anchor, coverage)
    assert readiness.ready is True
    assert readiness.horizon_eligible_offer_count == 1
    assert readiness.period == DatePeriod(start=date(2026, 11, 1), end=date(2027, 11, 1))
    result = service.compare(request, restored, history, anchor, coverage)
    for scenario in result.scenarios:
        imported = scenario.comparison.import_result
        item = imported.normalized[0]
        assert item.offer.subscription_period.end == date(2026, 11, 1)
        assert item.offer.tariff.validity.start == date(2026, 11, 1)
        assert item.offer.tariff.validity.end >= date(2027, 11, 1)
        terms = item.economic_terms
        assert terms is not None
        assert terms.activation_date == date(2026, 11, 1)
        assert terms.estimate_period == result.period
        assert terms.known_duration_months == 12
        assert terms.extends_beyond_12_months is False
        assert terms.basis == "declared_economic_conditions"
        alternative = scenario.comparison.comparison_result.alternatives[0]
        # Independent amount: 3,600 kWh * EUR 0.20 + EUR 120 = EUR 840 sales.
        assert alternative.pricing.breakdown.total.amount == Decimal("840.00")
        energy = sum(
            component.amount.amount
            for component in alternative.pricing.breakdown.components
            if component.meaning == ComponentMeaning.ENERGY_PRICE
        )
        assert energy == Decimal("720.00")
        assert all(
            component.applied_periods == (result.period,)
            for component in alternative.pricing.breakdown.components
        )

    control_catalog = _catalog_expiring_before_activation(as_of, annual_fee="0")
    control = service.compare(request, control_catalog, history, anchor, coverage)
    charged = result.base.comparison_result.alternatives[0]
    uncharged = control.base.comparison_result.alternatives[0]
    assert charged.comparable_total is not None
    assert uncharged.comparable_total is not None
    # The annual fee adds EUR 120 + EUR 12 VAT, independently of excise/network costs.
    assert charged.comparable_total.amount - uncharged.comparable_total.amount == Decimal("132.00")
    assert load_envelope(dump_envelope(result)) == result


def test_projected_offer_expired_yesterday_is_excluded() -> None:
    as_of = date(2026, 11, 1)
    request, _ = _current_parameter_case(as_of)
    catalog = _catalog_expiring_before_activation(as_of)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 11, 1, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor(as_of)
    readiness = service.preflight(
        request, catalog, _history(as_of), anchor, _coverage(anchor, as_of)
    )
    assert readiness.ready is False
    assert readiness.horizon_eligible_offer_count == 0


@pytest.mark.parametrize("duration", [24, 36, 60])
def test_projected_economic_terms_beyond_one_year_are_frozen_as_offer_metadata(
    duration: int,
) -> None:
    as_of = date(2026, 10, 18)
    request, _ = _current_parameter_case(as_of)
    catalog = _catalog_expiring_before_activation(as_of, duration=duration)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor(as_of)
    result = service.compare(request, catalog, _history(as_of), anchor, _coverage(anchor, as_of))
    item = result.base.import_result.normalized[0]
    assert item.economic_terms is not None
    assert item.economic_terms.known_duration_months == duration
    assert item.economic_terms.duration_scope == "seller_conditions"
    assert item.economic_terms.extends_beyond_12_months is True
    assert item.economic_terms.basis == "declared_economic_conditions"
    assert result.period == DatePeriod(start=date(2026, 11, 1), end=date(2027, 11, 1))
    changed_catalog = _catalog_expiring_before_activation(as_of, duration=duration + 1)
    changed = service.compare(
        request, changed_catalog, _history(as_of), anchor, _coverage(anchor, as_of)
    )
    assert changed.result_id != result.result_id


def test_projected_indeterminate_terms_are_annual_estimates_without_a_duration_promise() -> None:
    as_of = date(2026, 10, 18)
    request, _ = _current_parameter_case(as_of)
    catalog = _catalog_expiring_before_activation(as_of, duration=-1)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor(as_of)
    readiness = service.preflight(
        request, catalog, _history(as_of), anchor, _coverage(anchor, as_of)
    )
    assert readiness.ready is True
    result = service.compare(request, catalog, _history(as_of), anchor, _coverage(anchor, as_of))
    terms = result.base.import_result.normalized[0].economic_terms
    assert terms is not None
    assert terms.known_duration_months is None
    assert terms.extends_beyond_12_months is None
    assert terms.basis == "published_default_prices"


def test_projected_annual_fees_affect_vat_and_ranking_after_subscription_expiry() -> None:
    as_of = date(2026, 10, 18)
    request, _ = _current_parameter_case(as_of)
    catalog = _catalog_expiring_before_activation(as_of, annual_fee="84")
    dearer = _catalog_expiring_before_activation(as_of, annual_fee="120").records[0]
    dearer = dearer.model_copy(update={"source_offer_id": "HIGHER_ANNUAL_FEE"})
    catalog = catalog.model_copy(update={"records": (*catalog.records, dearer)})
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor(as_of)
    result = service.compare(request, catalog, _history(as_of), anchor, _coverage(anchor, as_of))
    alternatives = result.base.comparison_result.alternatives
    assert len(alternatives) == 2
    cheaper, dearer_result = sorted(
        alternatives, key=lambda item: item.pricing.breakdown.total.amount
    )
    assert cheaper.pricing.breakdown.total.amount == Decimal("804.00")
    assert dearer_result.pricing.breakdown.total.amount == Decimal("840.00")
    assert cheaper.comparable_total is not None
    assert dearer_result.comparable_total is not None
    assert dearer_result.comparable_total.amount - cheaper.comparable_total.amount == Decimal(
        "39.60"
    )
    ranking = result.base.comparison_result.ranking
    assert list(ranking) == [cheaper.offer_id, dearer_result.offer_id]


def test_projected_horizon_gate_rejects_missing_or_different_economic_context() -> None:
    as_of = date(2026, 10, 18)
    request, _ = _current_parameter_case(as_of)
    catalog = _catalog_expiring_before_activation(as_of)
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 10, 18, 12, tzinfo=UTC))
    anchor = load_domestic_projection_anchor(as_of)
    result = service.compare(request, catalog, _history(as_of), anchor, _coverage(anchor, as_of))
    imported = result.base.import_result.normalized[0]
    terms = imported.economic_terms
    assert terms is not None
    assert service._offer_covers_horizon(imported, result.period)
    assert not service._offer_covers_horizon(
        imported.model_copy(update={"economic_terms": None}), result.period
    )
    for changed in (
        {"activation_date": as_of},
        {"estimate_period": DatePeriod(start=date(2026, 11, 1), end=date(2027, 12, 1))},
    ):
        assert not service._offer_covers_horizon(
            imported.model_copy(update={"economic_terms": terms.model_copy(update=changed)}),
            result.period,
        )
