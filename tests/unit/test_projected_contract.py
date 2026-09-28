from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.money import EnergyQuantity, Power, RateUnit, UnitRate
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import SupplyClassification, VoltageLevel
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import BandPrice, FixedTariff
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval
from italian_energy.integration import (
    ProjectedComparisonAssumptions,
    ProjectedDomesticComparisonRequest,
    ProjectedDomesticComparisonResult,
    ProjectedDomesticPreflightResult,
    ProjectedDomesticRecommendationRequest,
    dump_envelope,
    load_envelope,
)
from italian_energy.integration.projected import validate_consumption_periods
from italian_energy.portal_offers.models import PortalEligibilityProfile, PortalTerritory

AS_OF = date(2026, 9, 27)


def _period_months() -> tuple[date, ...]:
    return tuple(date(2025 + (month < 9), month, 1) for month in (*range(9, 13), *range(1, 9)))


def _profile(*, stale: bool = False) -> ConsumptionProfile:
    starts = list(_period_months())
    if stale:
        starts[0] = date(2025, 8, 1)
    return ConsumptionProfile(
        profile_id="historical-monthly",
        buckets=tuple(
            ConsumptionBucket(
                interval=TimeInterval(
                    start=datetime(start.year, start.month, 1, tzinfo=UTC),
                    end=datetime(
                        start.year + (start.month == 12), start.month % 12 + 1, 1, tzinfo=UTC
                    ),
                ),
                energy=EnergyQuantity(kwh=Decimal("100")),
                granularity=Granularity.MONTH,
            )
            for start in starts
        ),
    )


def _request(profile: ConsumptionProfile | None = None) -> ProjectedDomesticComparisonRequest:
    future = DatePeriod(start=date(2026, 10, 1), end=date(2027, 10, 1))
    current_validity = DatePeriod(start=date(2026, 9, 1), end=date(2027, 10, 1))
    tariff = FixedTariff(
        tariff_id="fixed-current",
        validity=future,
        prices=(
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
    )
    return ProjectedDomesticComparisonRequest(
        current_contract=Contract(
            contract_id="current",
            supply=SupplyPoint(
                supply_id="pod",
                market_zone="NORD",
                contracted_power=Power(kw=Decimal("3")),
                residential=True,
            ),
            tariff=tariff,
            validity=current_validity,
        ),
        consumption=profile or _profile(),
        as_of=AS_OF,
        classification=SupplyClassification(
            contract_type_code="domestic_bt_resident",
            voltage_level=VoltageLevel.BT,
            usage_code="domestic",
            residential=True,
        ),
        eligibility=PortalEligibilityProfile(
            territory=PortalTerritory(
                region_code="06", province_code="015", municipality_code="015213"
            ),
            activation_method="02",
            payment_method="01",
        ),
    )


def _projected_result() -> ProjectedDomesticComparisonResult:
    from test_projected_service import _catalog, _history, _indexed_request

    from italian_energy.arera.projection import load_domestic_projection_anchor
    from italian_energy.integration import ProjectedDomesticEnergyService

    return ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).compare(
        _indexed_request(),
        _catalog(AS_OF),
        _history(AS_OF),
        load_domestic_projection_anchor(),
    )


def test_projected_request_and_canonical_envelope_round_trip() -> None:
    request = _request()

    envelope = dump_envelope(request)
    restored = load_envelope(envelope)

    assert isinstance(restored, ProjectedDomesticComparisonRequest)
    assert restored.as_of == AS_OF
    assert restored.consumption.total_energy().kwh == Decimal("1200")


def test_projected_request_rejects_stale_or_incomplete_months() -> None:
    with pytest.raises(ValidationError, match="latest twelve months"):
        _request(_profile(stale=True))


def test_projected_request_rejects_duplicate_month_and_partial_month_boundaries() -> None:
    valid = _profile()
    buckets = list(valid.buckets)
    buckets[-1] = buckets[-2]
    duplicate = ConsumptionProfile.model_construct(
        profile_id=valid.profile_id, buckets=tuple(buckets)
    )
    with pytest.raises(ValidationError, match="consumption"):
        _request(duplicate)

    buckets = list(valid.buckets)
    last = buckets[-1]
    buckets[-1] = last.model_copy(
        update={
            "interval": TimeInterval(
                start=last.interval.start.replace(day=1, hour=1),
                end=last.interval.end,
            )
        }
    )
    partial = ConsumptionProfile.model_construct(
        profile_id=valid.profile_id, buckets=tuple(buckets)
    )
    with pytest.raises(ValidationError, match="complete monthly buckets"):
        _request(partial)


def test_projected_request_rejects_non_domestic_or_non_resident_mismatch() -> None:
    request = _request()
    invalid = request.model_copy(
        update={
            "classification": request.classification.model_copy(
                update={"voltage_level": VoltageLevel.MT}
            )
        }
    )

    with pytest.raises(ValidationError, match="domestic electricity BT"):
        ProjectedDomesticComparisonRequest.model_validate(invalid.model_dump(mode="python"))


def test_projection_assumptions_fix_multipliers_and_horizon_semantics() -> None:
    assumptions = ProjectedComparisonAssumptions(
        historical_consumption_period=DatePeriod(start=date(2025, 9, 1), end=date(2026, 9, 1)),
        historical_market_period=DatePeriod(start=date(2025, 9, 1), end=date(2026, 9, 1)),
        future_period=DatePeriod(start=date(2026, 10, 1), end=date(2027, 10, 1)),
        regulatory_anchor_date=AS_OF,
        current_contract_continued=False,
    )
    assert assumptions.index_multipliers == (
        Decimal("0.80"),
        Decimal("1.00"),
        Decimal("1.20"),
    )
    assert assumptions.future_values_verified is False
    assert assumptions.costs_are_estimates is True
    with pytest.raises(ValidationError, match=r"must be 0\.80"):
        ProjectedComparisonAssumptions.model_validate(
            assumptions.model_dump(mode="python")
            | {"index_multipliers": (Decimal("0.8"), Decimal("1"), Decimal("1.1"))}
        )


def test_preflight_readiness_cannot_collapse_source_and_calculation_gates() -> None:
    period = DatePeriod(start=date(2026, 10, 1), end=date(2027, 10, 1))
    with pytest.raises(ValidationError, match="distinguish source and calculation"):
        ProjectedDomesticPreflightResult(
            ready=True,
            official_data_ready=False,
            projection_calculable=True,
            as_of=AS_OF,
            period=period,
        )


def test_recommendation_thresholds_reject_negative_money_or_percentage() -> None:
    # A valid comparison is required by the typed request, so validation is
    # exercised from a minimally valid, previously serialized projected result.
    from test_projected_service import _catalog, _history, _indexed_request

    from italian_energy.arera.projection import load_domestic_projection_anchor
    from italian_energy.integration import ProjectedDomesticEnergyService

    comparison = ProjectedDomesticEnergyService(
        clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC)
    ).compare(
        _indexed_request(),
        _catalog(AS_OF),
        _history(AS_OF),
        load_domestic_projection_anchor(),
    )
    with pytest.raises(ValidationError, match="non-negative"):
        ProjectedDomesticRecommendationRequest(comparison=comparison, minimum_savings=Decimal("-1"))
    with pytest.raises(ValidationError, match="non-negative"):
        ProjectedDomesticRecommendationRequest(
            comparison=comparison, minimum_percentage_savings=Decimal("-1")
        )


def test_projected_consumption_allows_individual_bands_but_not_total_plus_bands() -> None:
    profile = _profile()
    band_only = profile.model_copy(
        update={
            "buckets": tuple(bucket.model_copy(update={"band": "F1"}) for bucket in profile.buckets)
        }
    )
    assert _request(band_only).consumption.buckets[0].band == "F1"

    with_f1 = profile.model_copy(
        update={
            "buckets": (
                *profile.buckets,
                *tuple(bucket.model_copy(update={"band": "F1"}) for bucket in profile.buckets),
            )
        }
    )
    with pytest.raises(ValidationError, match="cannot mix ALL and named bands"):
        _request(with_f1)


def test_projected_consumption_requires_buckets_and_aware_month_boundaries() -> None:
    empty = ConsumptionProfile.model_construct(profile_id="empty", buckets=())
    with pytest.raises(ValidationError, match="twelve complete monthly"):
        _request(empty)

    profile = _profile()
    buckets = list(profile.buckets)
    last = buckets[-1]
    buckets[-1] = last.model_copy(
        update={
            "interval": TimeInterval.model_construct(
                start=last.interval.start.replace(tzinfo=None),
                end=last.interval.end,
            )
        }
    )
    naive = ConsumptionProfile.model_construct(
        profile_id=profile.profile_id, buckets=tuple(buckets)
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        validate_consumption_periods(naive, AS_OF)


def test_projected_comparison_result_checks_scenario_order_and_exact_windows() -> None:
    result = _projected_result()
    restored = load_envelope(dump_envelope(result))
    assert isinstance(restored, ProjectedDomesticComparisonResult)
    assert restored.result_id == result.result_id

    payload = result.model_dump(mode="python")
    payload["scenarios"] = tuple(reversed(payload["scenarios"]))
    with pytest.raises(ValidationError, match="low, base and high"):
        ProjectedDomesticComparisonResult.model_validate(payload)

    evidence = result.verified_inputs.model_dump(mode="python")
    evidence["market_report_provenance"] = tuple(reversed(evidence["market_report_provenance"]))
    with pytest.raises(ValidationError, match="exact recent twelve-month window"):
        ProjectedDomesticComparisonResult.model_validate(
            result.model_dump(mode="python") | {"verified_inputs": evidence}
        )


def test_verified_inputs_fail_closed_for_status_digest_window_and_source_url() -> None:
    evidence = _projected_result().verified_inputs
    base = evidence.model_dump(mode="python")
    bad_payloads = []

    bad = deepcopy(base)
    bad["catalog_status"] = "unverified"
    bad_payloads.append((bad, "verified Portale Offerte catalog"))

    bad = deepcopy(base)
    bad["catalog_dataset_date"] = date(2026, 9, 28)
    bad_payloads.append((bad, "cannot be newer"))

    bad = deepcopy(base)
    bad["market_status"] = "unverified"
    bad_payloads.append((bad, "verified GME history"))

    bad = deepcopy(base)
    bad["market_report_provenance"] = bad["market_report_provenance"][:-1]
    bad_payloads.append((bad, "twelve source-backed market reports"))

    bad = deepcopy(base)
    bad["market_report_provenance"][0]["source"] = "Other"
    bad_payloads.append((bad, "GME source, digest and month"))

    bad = deepcopy(base)
    bad["market_report_provenance"][0]["url"] = (
        "https://example.com/202509_Dati_di_sintesi_mensile.pdf"
    )
    bad_payloads.append((bad, "matching official GME report"))

    bad = deepcopy(base)
    bad["regulatory_status"] = "unverified"
    bad_payloads.append((bad, "verified regulatory anchor"))

    bad = deepcopy(base)
    bad["regulatory_provenance"] = ()
    bad_payloads.append((bad, "regulatory provenance is required"))

    for payload, message in bad_payloads:
        with pytest.raises(ValidationError, match=message):
            type(evidence).model_validate(payload)


def test_projected_result_rejects_wrong_anchor_period_multiplier_and_missing_billing() -> None:
    result = _projected_result()

    payload = deepcopy(result.model_dump(mode="python"))
    payload["assumptions"]["regulatory_anchor_date"] = date(2026, 9, 26)
    with pytest.raises(ValidationError, match="projection anchor must match as_of"):
        ProjectedDomesticComparisonResult.model_validate(payload)

    payload = deepcopy(result.model_dump(mode="python"))
    payload["scenarios"][0]["index_multiplier"] = Decimal("0.81")
    with pytest.raises(ValidationError, match="multipliers must match"):
        ProjectedDomesticComparisonResult.model_validate(payload)

    payload = deepcopy(result.model_dump(mode="python"))
    payload["scenarios"][0]["comparison"]["comparison_result"]["current_billing"] = None
    with pytest.raises(ValidationError, match="projected billing"):
        ProjectedDomesticComparisonResult.model_validate(payload)

    payload = deepcopy(result.model_dump(mode="python"))
    payload["scenarios"][0]["comparison"]["comparison_result"]["current_pricing"]["period"] = (
        DatePeriod(start=date(2026, 10, 1), end=date(2027, 9, 1))
    )
    with pytest.raises(ValidationError, match="projected pricing"):
        ProjectedDomesticComparisonResult.model_validate(payload)
