"""High-level historical domestic service for the Core-Platform boundary."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol

from italian_energy.billing import (
    BillingCoverageError,
    CoverageLevel,
    load_coverage_matrix,
    load_ruleset,
)
from italian_energy.comparison import ComparisonContext, ComparisonError
from italian_energy.domain.money import RoundingMode, RoundingPolicy
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.portal_offers import (
    PortalCatalog,
    PortalComparisonRequest,
    PortalComparisonResult,
    PortalComparisonService,
)
from italian_energy.portal_offers.importer import PortalFetchError, PortalImportError
from italian_energy.portal_offers.recommendation import PortalRecommendationAdapter
from italian_energy.recommendation import (
    DeterministicRecommendationEngine,
    Recommendation,
    RecommendationEngine,
)

from .errors import CoreContractError, CoreErrorCode
from .models import HistoricalPortalComparisonRequest, HistoricalRecommendationRequest

DEFAULT_ROUNDING_POLICY = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)
DEFAULT_PERCENTAGE_ROUNDING_POLICY = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)


class PortalComparisonGateway(Protocol):
    """Injectable comparison boundary used by the façade and its tests."""

    def compare(self, request: PortalComparisonRequest) -> PortalComparisonResult:
        """Compare one fully prepared Portal request."""


class HistoricalDomesticEnergyService:
    """Compose verified packaged billing with the historical Portale flow."""

    def __init__(
        self,
        *,
        portal_service: PortalComparisonGateway | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._portal_service = portal_service or PortalComparisonService()
        self._recommendation_engine = recommendation_engine or DeterministicRecommendationEngine()
        self._clock = clock or (lambda: datetime.now(UTC))

    def compare(self, request: HistoricalPortalComparisonRequest) -> PortalComparisonResult:
        """Compare both official electricity catalogues for a concluded period."""

        self._validate_scenario(request)
        if request.period.end > self._clock().date():
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "historical comparison requires a concluded period",
            )
        segment = "resident" if request.classification.residential else "non-resident"
        try:
            ruleset = load_ruleset(segment=segment)
            if ruleset.status != VerificationStatus.VERIFIED or not ruleset.provenance:
                raise BillingCoverageError("packaged ruleset is not verified")
            matrix = load_coverage_matrix()
            matrix.resolve(
                request.classification,
                ruleset.ruleset_id,
                request.period,
                minimum_level=CoverageLevel.RULESET_VERIFIED,
            )
        except BillingCoverageError as exc:
            raise CoreContractError(
                CoreErrorCode.COVERAGE_UNAVAILABLE,
                "verified billing coverage is unavailable for the scenario",
            ) from exc
        except (OSError, ValueError) as exc:
            raise CoreContractError(
                CoreErrorCode.COVERAGE_UNAVAILABLE,
                "verified billing artifacts are unavailable",
            ) from exc

        context = ComparisonContext(
            current_contract=request.current_contract,
            consumption=request.consumption,
            period=request.period,
            as_of=request.period.start,
            classification=request.classification,
            rule_set=ruleset,
            coverage_matrix=matrix,
            rounding_policy=DEFAULT_ROUNDING_POLICY,
            percentage_rounding_policy=DEFAULT_PERCENTAGE_ROUNDING_POLICY,
            market_data=None,
            measurements=request.measurements,
            external_items=request.external_items,
        )
        portal_request = PortalComparisonRequest(
            comparison=context,
            catalogs=frozenset({PortalCatalog.MARKET_FREE, PortalCatalog.PLACET}),
            eligibility=request.eligibility,
            supplemental_market_data=request.supplemental_market_data,
        )
        try:
            return self._portal_service.compare(portal_request)
        except PortalFetchError as exc:
            raise CoreContractError(
                CoreErrorCode.SOURCE_ACQUISITION_FAILED,
                "official Portale Offerte source acquisition failed",
            ) from exc
        except PortalImportError as exc:
            raise CoreContractError(
                CoreErrorCode.SOURCE_VALIDATION_FAILED,
                "official Portale Offerte source validation failed",
            ) from exc
        except ComparisonError as exc:
            raise CoreContractError(
                CoreErrorCode.COMPARISON_FAILED,
                "historical comparison failed",
            ) from exc

    @staticmethod
    def _validate_scenario(request: HistoricalPortalComparisonRequest) -> None:
        """Re-check boundary invariants for callers using model_construct()."""
        classification = request.classification
        supply = request.current_contract.supply
        if (
            classification.voltage_level != request.eligibility.voltage_level
            or classification.voltage_level != "BT"
            or request.eligibility.voltage_level != "BT"
            or not request.eligibility.domestic
            or classification.usage_code != "domestic"
            or classification.residential is None
            or supply.residential is None
            or classification.residential != supply.residential
            or supply.commodity != "electricity"
        ):
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "integration scenario is not supported",
            )

    def recommend(self, request: HistoricalRecommendationRequest) -> Recommendation:
        """Interpret an existing comparison without repeating economic work."""

        try:
            recommendation_request = PortalRecommendationAdapter().build_request(
                request.comparison,
                request.preferences,
            )
            return self._recommendation_engine.recommend(recommendation_request)
        except (TypeError, ValueError) as exc:
            raise CoreContractError(
                CoreErrorCode.RECOMMENDATION_FAILED,
                "recommendation failed for the supplied comparison",
            ) from exc
