"""Tests for the Core-Platform integration contract."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Any

import pytest

from italian_energy.billing import BillingCoverageMatrix, load_coverage_matrix, load_ruleset
from italian_energy.comparison import ComparisonError, ComparisonResult
from italian_energy.domain import (
    BandPrice,
    ConsumptionProfile,
    Contract,
    CostBreakdown,
    DatePeriod,
    FixedTariff,
    MarketData,
    Money,
    Power,
    PricingResult,
    Provenance,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    SupplyClassification,
    SupplyPoint,
    UnitRate,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.integration import (
    CORE_CAPABILITIES,
    CORE_CONTRACT_VERSION,
    CORE_MANIFEST,
    CORE_SCHEMA_IDS,
    CoreContractError,
    CoreErrorCode,
    CoreIntegrationError,
    HistoricalDomesticEnergyService,
    HistoricalPortalComparisonRequest,
    HistoricalRecommendationRequest,
    dump_envelope,
    load_envelope,
)
from italian_energy.integration import (
    ConsumptionProfile as IntegrationConsumptionProfile,
)
from italian_energy.integration import (
    Contract as IntegrationContract,
)
from italian_energy.integration import (
    PortalComparisonResult as IntegrationPortalComparisonResult,
)
from italian_energy.integration import (
    Recommendation as IntegrationRecommendation,
)
from italian_energy.integration import (
    RecommendationPreferences as IntegrationRecommendationPreferences,
)
from italian_energy.integration import (
    SupplyPoint as IntegrationSupplyPoint,
)
from italian_energy.integration import (
    VerifiedMarketData as IntegrationVerifiedMarketData,
)
from italian_energy.integration.manifest import CoreCapability, CoreSchemaId
from italian_energy.portal_offers import (
    PortalCatalog,
    PortalComparisonResult,
    PortalEligibilityProfile,
    PortalFileSnapshot,
    PortalOffersImportResult,
    PortalOffersSnapshot,
    PortalSourceRole,
    PortalTerritory,
    VerifiedMarketData,
)
from italian_energy.portal_offers.importer import PortalFetchError, PortalImportError
from italian_energy.recommendation import (
    Recommendation,
    RecommendationDecision,
    RecommendationPreferences,
)

PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
RETRIEVED_AT = datetime(2026, 2, 2, tzinfo=UTC)
PROVENANCE = Provenance(
    source="test",
    source_identifier="integration-fixture",
    retrieved_at=RETRIEVED_AT,
    dataset_version="1",
)


def _tariff() -> FixedTariff:
    return FixedTariff(
        tariff_id="tariff",
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        prices=(
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
    )


def _contract(*, resident: bool = True) -> Contract:
    return Contract(
        contract_id="current",
        supply=SupplyPoint(
            supply_id="supply",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=resident,
        ),
        tariff=_tariff(),
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
    )


def _classification(*, resident: bool = True) -> SupplyClassification:
    return SupplyClassification(
        contract_type_code="domestic_bt_resident" if resident else "domestic_bt_non_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=resident,
    )


def _eligibility() -> PortalEligibilityProfile:
    return PortalEligibilityProfile(
        territory=PortalTerritory(
            region_code="01",
            province_code="001",
            municipality_code="000001",
        )
    )


def _request(*, resident: bool = True) -> HistoricalPortalComparisonRequest:
    return HistoricalPortalComparisonRequest(
        current_contract=_contract(resident=resident),
        consumption=ConsumptionProfile(profile_id="consumption"),
        period=PERIOD,
        classification=_classification(resident=resident),
        eligibility=_eligibility(),
    )


def _verified_market_data() -> VerifiedMarketData:
    return VerifiedMarketData(
        data=MarketData(),
        status=VerificationStatus.VERIFIED,
        provenance=(PROVENANCE,),
        sha256="0" * 64,
    )


def _portal_result() -> PortalComparisonResult:
    roles = (
        PortalSourceRole.MARKET_FREE_OFFERS,
        PortalSourceRole.MARKET_FREE_PARAMETERS,
        PortalSourceRole.PLACET_OFFERS,
        PortalSourceRole.PLACET_PARAMETERS,
    )
    files = tuple(
        PortalFileSnapshot(
            role=role,
            catalog=(
                PortalCatalog.MARKET_FREE
                if role
                in {
                    PortalSourceRole.MARKET_FREE_OFFERS,
                    PortalSourceRole.MARKET_FREE_PARAMETERS,
                }
                else PortalCatalog.PLACET
            ),
            original_url="https://example.test/catalog.csv",
            final_url="https://example.test/catalog.csv",
            retrieved_at=RETRIEVED_AT,
            content_type="text/csv",
            size=0,
            sha256=sha256(b"").hexdigest(),
            dataset_date=PERIOD.start,
            status=VerificationStatus.VERIFIED,
        )
        for role in roles
    )
    snapshot = PortalOffersSnapshot(
        dataset_date=PERIOD.start,
        files=files,
        snapshot_id="portal-snapshot:" + "1" * 64,
        status=VerificationStatus.VERIFIED,
        parser_version="test",
    )
    import_result = PortalOffersImportResult(
        snapshot=snapshot,
        status=VerificationStatus.VERIFIED,
        import_id="portal-import:" + "2" * 64,
        received_count=0,
        eligible_count=0,
        excluded_count=0,
    )
    pricing = PricingResult(
        pricing_id="pricing",
        contract_id="current",
        period=PERIOD,
        breakdown=CostBreakdown(total=Money(amount=Decimal("0"))),
    )
    comparison = ComparisonResult(
        comparison_id="comparison",
        current_contract_id="current",
        current_pricing=pricing,
    )
    return PortalComparisonResult(
        portal_result_id="portal-comparison:" + "3" * 64,
        import_result=import_result,
        comparison_result=comparison,
    )


class _RecordingPortalService:
    def __init__(self, result: PortalComparisonResult | None = None) -> None:
        self.calls = 0
        self.requests: list[Any] = []
        self.result = result or _portal_result()

    def compare(self, request: Any) -> PortalComparisonResult:
        self.calls += 1
        self.requests.append(request)
        return self.result


def test_manifest_is_canonical_and_matches_package_identity() -> None:
    from importlib.metadata import version

    assert CORE_CONTRACT_VERSION == "1"
    assert CORE_MANIFEST.distribution == "italian-energy"
    assert CORE_MANIFEST.import_package == "italian_energy"
    assert CORE_MANIFEST.package_version == version("italian-energy")
    assert tuple(item.value for item in CORE_MANIFEST.capabilities) == CORE_CAPABILITIES
    assert tuple(sorted(CORE_CAPABILITIES)) == CORE_CAPABILITIES
    assert CoreCapability.HISTORICAL_PORTAL_COMPARISON in CORE_MANIFEST.capabilities
    assert "current_portal_comparison" not in CORE_CAPABILITIES
    assert CORE_MANIFEST.schema_ids == tuple(sorted(CORE_MANIFEST.schema_ids))
    assert tuple(item.value for item in CORE_MANIFEST.schema_ids) == CORE_SCHEMA_IDS


def test_manifest_exposes_only_integration_schema_ids() -> None:
    assert set(CORE_MANIFEST.schema_ids) == {
        CoreSchemaId.SUPPLY_POINT,
        CoreSchemaId.CONTRACT,
        CoreSchemaId.CONSUMPTION_PROFILE,
        CoreSchemaId.VERIFIED_MARKET_DATA,
        CoreSchemaId.HISTORICAL_PORTAL_COMPARISON_REQUEST,
        CoreSchemaId.PORTAL_COMPARISON_RESULT,
        CoreSchemaId.RECOMMENDATION_PREFERENCES,
        CoreSchemaId.HISTORICAL_RECOMMENDATION_REQUEST,
        CoreSchemaId.RECOMMENDATION,
    }


def test_contract_error_alias_is_stable() -> None:
    assert CoreIntegrationError is CoreContractError
    assert IntegrationConsumptionProfile is ConsumptionProfile
    assert IntegrationContract is Contract
    assert IntegrationPortalComparisonResult is PortalComparisonResult
    assert IntegrationRecommendation is Recommendation
    assert IntegrationRecommendationPreferences is RecommendationPreferences
    assert IntegrationSupplyPoint is SupplyPoint
    assert IntegrationVerifiedMarketData is VerifiedMarketData


def test_envelopes_are_canonical_and_round_trip() -> None:
    values = (
        _contract(),
        _contract().supply,
        ConsumptionProfile(profile_id="consumption"),
        _verified_market_data(),
        _request(),
        _portal_result(),
        RecommendationPreferences(),
        HistoricalRecommendationRequest(comparison=_portal_result()),
        Recommendation(
            recommendation_id="recommendation",
            comparison_id="comparison",
            decision=RecommendationDecision.STAY_CURRENT,
        ),
    )
    for value in values:
        encoded = dump_envelope(value)
        assert encoded == dump_envelope(value)
        assert load_envelope(encoded) == value
        assert json.loads(encoded)["contract_version"] == CORE_CONTRACT_VERSION


def test_envelope_rejects_unknown_versions_schemas_extra_keys_and_bad_json() -> None:
    encoded = dump_envelope(_contract())
    base = json.loads(encoded)
    cases = (
        ({**base, "contract_version": "999"}, CoreErrorCode.UNSUPPORTED_CONTRACT_VERSION),
        ({**base, "schema_id": "italian-energy/unknown/v1"}, CoreErrorCode.UNSUPPORTED_SCHEMA),
        ({**base, "extra": True}, CoreErrorCode.INVALID_ENVELOPE),
    )
    for payload, code in cases:
        with pytest.raises(CoreIntegrationError) as error:
            load_envelope(json.dumps(payload))
        assert error.value.code is code
    with pytest.raises(CoreIntegrationError) as error:
        load_envelope(b"not-json")
    assert error.value.code is CoreErrorCode.INVALID_ENVELOPE
    with pytest.raises(CoreIntegrationError) as error:
        load_envelope(
            '{"contract_version":"1","contract_version":"1","schema_id":"x","payload":{}}'
        )
    assert error.value.code is CoreErrorCode.INVALID_ENVELOPE


def test_envelope_rejects_schema_mismatch_and_economic_float() -> None:
    encoded = dump_envelope(_contract())
    payload = json.loads(encoded)
    payload["schema_id"] = CoreSchemaId.CONSUMPTION_PROFILE.value
    with pytest.raises(CoreIntegrationError) as error:
        load_envelope(json.dumps(payload))
    assert error.value.code is CoreErrorCode.INVALID_PAYLOAD

    invalid_json = encoded.replace(b'"0.10"', b"NaN")
    with pytest.raises(CoreContractError) as error:
        load_envelope(invalid_json)
    assert error.value.code is CoreErrorCode.INVALID_ENVELOPE

    invalid = json.loads(encoded)
    invalid["payload"]["tariff"]["prices"][0]["rate"]["amount"] = 0.1
    with pytest.raises(CoreIntegrationError) as error:
        load_envelope(json.dumps(invalid))
    assert error.value.code is CoreErrorCode.INVALID_PAYLOAD


def test_envelope_rejects_raw_portal_content() -> None:
    encoded = dump_envelope(_portal_result())
    payload = json.loads(encoded)
    payload["payload"]["import_result"]["snapshot"]["files"][0]["content"] = "raw"
    with pytest.raises(CoreContractError) as error:
        load_envelope(json.dumps(payload))
    assert error.value.code is CoreErrorCode.INVALID_PAYLOAD


def test_dump_rejects_unregistered_payload_type() -> None:
    with pytest.raises(CoreContractError) as error:
        dump_envelope(object())  # type: ignore[arg-type]
    assert error.value.code is CoreErrorCode.UNSUPPORTED_SCHEMA


def test_historical_service_selects_resident_artifact_and_defaults_rounding() -> None:
    portal = _RecordingPortalService()
    service = HistoricalDomesticEnergyService(
        portal_service=portal,
        clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    result = service.compare(_request())
    assert result is portal.result
    assert portal.calls == 1
    context = portal.requests[0].comparison
    assert context.as_of == PERIOD.start
    assert context.rule_set.ruleset_id == load_ruleset(segment="resident").ruleset_id
    assert context.coverage_matrix.matrix_id == load_coverage_matrix().matrix_id
    assert context.rounding_policy == RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)
    assert context.percentage_rounding_policy == RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)
    assert portal.requests[0].catalogs == frozenset(
        {PortalCatalog.MARKET_FREE, PortalCatalog.PLACET}
    )


def test_historical_service_selects_non_resident_artifact() -> None:
    portal = _RecordingPortalService()
    HistoricalDomesticEnergyService(
        portal_service=portal,
        clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    ).compare(_request(resident=False))
    assert (
        portal.requests[0].comparison.rule_set.ruleset_id
        == load_ruleset(segment="non-resident").ruleset_id
    )


def test_historical_service_rejects_future_before_transport() -> None:
    portal = _RecordingPortalService()
    service = HistoricalDomesticEnergyService(
        portal_service=portal,
        clock=lambda: datetime(2026, 1, 15, tzinfo=UTC),
    )
    with pytest.raises(CoreIntegrationError) as error:
        service.compare(_request())
    assert error.value.code is CoreErrorCode.UNSUPPORTED_HORIZON
    assert portal.calls == 0


def test_historical_service_maps_coverage_and_source_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import italian_energy.integration.service as integration_service

    unverified_ruleset = load_ruleset(segment="resident").model_copy(
        update={"status": "unverified"}
    )
    monkeypatch.setattr(integration_service, "load_ruleset", lambda *, segment: unverified_ruleset)
    with pytest.raises(CoreContractError) as error:
        HistoricalDomesticEnergyService(
            portal_service=_RecordingPortalService(),
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(_request())
    assert error.value.code is CoreErrorCode.COVERAGE_UNAVAILABLE

    monkeypatch.setattr(integration_service, "load_ruleset", load_ruleset)
    empty_matrix = BillingCoverageMatrix(matrix_id="empty", schema_version="1", entries=())
    monkeypatch.setattr(integration_service, "load_coverage_matrix", lambda: empty_matrix)
    with pytest.raises(CoreIntegrationError) as error:
        HistoricalDomesticEnergyService(
            portal_service=_RecordingPortalService(),
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(_request())
    assert error.value.code is CoreErrorCode.COVERAGE_UNAVAILABLE

    class FailingPortal:
        def compare(self, request: Any) -> PortalComparisonResult:
            raise PortalFetchError("secret source detail")

    monkeypatch.setattr(integration_service, "load_coverage_matrix", load_coverage_matrix)
    with pytest.raises(CoreIntegrationError) as error:
        HistoricalDomesticEnergyService(
            portal_service=FailingPortal(),
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(_request())
    assert error.value.code is CoreErrorCode.SOURCE_ACQUISITION_FAILED
    assert "secret" not in str(error.value)

    class FailingComparison:
        def compare(self, request: Any) -> PortalComparisonResult:
            raise ComparisonError("private engine detail")

    with pytest.raises(CoreContractError) as error:
        HistoricalDomesticEnergyService(
            portal_service=FailingComparison(),
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(_request())
    assert error.value.code is CoreErrorCode.COMPARISON_FAILED
    assert "private" not in str(error.value)


def test_historical_service_recommendation_does_not_recompare() -> None:
    portal = _RecordingPortalService()

    class RecordingRecommendationEngine:
        calls = 0

        def recommend(self, request: Any) -> Recommendation:
            self.calls += 1
            return Recommendation(
                recommendation_id="recommendation",
                comparison_id=request.comparison.comparison_id,
                decision=RecommendationDecision.STAY_CURRENT,
            )

    recommendation_engine = RecordingRecommendationEngine()
    service = HistoricalDomesticEnergyService(
        portal_service=portal,
        recommendation_engine=recommendation_engine,
        clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    )
    comparison = service.compare(_request())
    recommendation = service.recommend(HistoricalRecommendationRequest(comparison=comparison))
    assert recommendation.decision is RecommendationDecision.STAY_CURRENT
    assert portal.calls == 1
    assert recommendation_engine.calls == 1


def test_historical_request_requires_explicit_matching_residence() -> None:
    with pytest.raises(CoreContractError) as error:
        HistoricalPortalComparisonRequest(
            current_contract=_contract(resident=False),
            consumption=ConsumptionProfile(profile_id="consumption"),
            period=PERIOD,
            classification=_classification(resident=True),
            eligibility=_eligibility(),
        )
    assert error.value.code is CoreErrorCode.UNSUPPORTED_SCENARIO


@pytest.mark.parametrize(
    ("field", "value"),
    (("voltage_level", VoltageLevel.MT), ("usage_code", "commercial"), ("residential", None)),
)
def test_historical_request_rejects_unsupported_scenario_fields(field: str, value: object) -> None:
    classification = _classification().model_copy(update={field: value})
    with pytest.raises(CoreContractError) as error:
        HistoricalPortalComparisonRequest(
            current_contract=_contract(),
            consumption=ConsumptionProfile(profile_id="consumption"),
            period=PERIOD,
            classification=classification,
            eligibility=_eligibility(),
        )
    assert error.value.code is CoreErrorCode.UNSUPPORTED_SCENARIO


def test_historical_service_rechecks_unsupported_scenario_at_boundary() -> None:
    classification = _classification().model_copy(update={"voltage_level": VoltageLevel.MT})
    invalid = _request().model_copy(update={"classification": classification})
    with pytest.raises(CoreContractError) as error:
        HistoricalDomesticEnergyService(
            portal_service=_RecordingPortalService(),
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(invalid)
    assert error.value.code is CoreErrorCode.UNSUPPORTED_SCENARIO


def test_historical_service_maps_source_validation_and_recommendation_errors() -> None:
    class InvalidPortal:
        def compare(self, request: Any) -> PortalComparisonResult:
            raise PortalImportError("private source detail")

    with pytest.raises(CoreIntegrationError) as error:
        HistoricalDomesticEnergyService(
            portal_service=InvalidPortal(),
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(_request())
    assert error.value.code is CoreErrorCode.SOURCE_VALIDATION_FAILED
    assert "private" not in str(error.value)

    class InvalidRecommendation:
        def build_request(self, result: PortalComparisonResult, preferences: Any) -> Any:
            raise AssertionError("adapter should not be replaced")

    # A comparison without economic totals is rejected by the existing
    # recommendation engine and normalized to the integration error contract.
    malformed = _portal_result()
    with pytest.raises(CoreIntegrationError) as error:
        HistoricalDomesticEnergyService().recommend(
            HistoricalRecommendationRequest(comparison=malformed)
        )
    assert error.value.code is CoreErrorCode.RECOMMENDATION_FAILED
