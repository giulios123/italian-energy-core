"""High-level historical domestic service for the Core-Platform boundary."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Protocol

from italian_energy.billing import (
    BillingCoverageError,
    CoverageLevel,
    load_coverage_matrix,
    load_ruleset,
)
from italian_energy.billing.coverage import BillingCoverageMatrix
from italian_energy.comparison import (
    ComparisonContext,
    ComparisonError,
    DeterministicComparisonEngine,
)
from italian_energy.domain.money import RoundingMode, RoundingPolicy
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import RegulatoryRuleSet, VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers import (
    PortalCatalog,
    PortalComparisonRequest,
    PortalComparisonResult,
    PortalComparisonService,
)
from italian_energy.portal_offers.importer import (
    PortalFetchError,
    PortalImportError,
    PortalOffersImporter,
)
from italian_energy.portal_offers.normalizer import normalize_offers
from italian_energy.portal_offers.recommendation import PortalRecommendationAdapter
from italian_energy.recommendation import (
    DeterministicRecommendationEngine,
    Recommendation,
    RecommendationEngine,
)

from .current import (
    CurrentCatalogSnapshot,
    CurrentPortalComparisonRequest,
    CurrentPortalComparisonResult,
    CurrentRecommendationRequest,
    CurrentScenario,
    CurrentScenarioComparison,
    future_period,
    project_consumption,
    project_market_data,
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


class CurrentDomesticEnergyService:
    """Build and compare a current twelve-month scenario from verified snapshots."""

    def __init__(
        self,
        *,
        importer: PortalOffersImporter | None = None,
        engine: DeterministicComparisonEngine | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        ruleset_loader: Callable[..., RegulatoryRuleSet] = load_ruleset,
        coverage_loader: Callable[[], BillingCoverageMatrix] = load_coverage_matrix,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._importer = importer or PortalOffersImporter()
        self._engine = engine or DeterministicComparisonEngine()
        self._recommendation_engine = recommendation_engine or DeterministicRecommendationEngine()
        self._ruleset_loader = ruleset_loader
        self._coverage_loader = coverage_loader
        self._clock = clock or (lambda: datetime.now(UTC))

    def acquire_catalog(self, dataset_date: date | None = None) -> CurrentCatalogSnapshot:
        """Acquire and parse one verified official catalogue snapshot."""

        target = dataset_date or self._clock().date()
        try:
            snapshot = self._importer.fetch(target, include_indexes=True)
            records = self._importer.parse_offers(snapshot.offers)
            market_data = (
                None
                if snapshot.indexes is None
                else self._importer.parse_market_data(snapshot.indexes)
            )
            return CurrentCatalogSnapshot(
                dataset_date=target,
                snapshot=snapshot,
                records=records,
                market_data=market_data,
            )
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

    def compare(
        self,
        request: CurrentPortalComparisonRequest,
        catalog: CurrentCatalogSnapshot | None = None,
    ) -> CurrentPortalComparisonResult:
        """Evaluate low, base and high index scenarios using one frozen catalogue."""

        self._validate_request(request)
        period = future_period(request.as_of)
        snapshot = catalog or self.acquire_catalog(request.as_of)
        if snapshot.dataset_date > request.as_of:
            raise CoreContractError(
                CoreErrorCode.SOURCE_VALIDATION_FAILED,
                "catalogue snapshot date is after the comparison date",
            )
        if snapshot.market_data is None:
            raise CoreContractError(
                CoreErrorCode.SOURCE_VALIDATION_FAILED,
                "verified historical index snapshot is required for current scenarios",
            )
        ruleset, matrix = self._billing_artifacts(request, period)
        contract = self._contract_for_period(request, period)
        projected_consumption = project_consumption(request.consumption, request.as_of)
        scenarios: list[CurrentScenarioComparison] = []
        for scenario in (
            CurrentScenario.LOW_INDEX,
            CurrentScenario.BASE,
            CurrentScenario.HIGH_INDEX,
        ):
            market_data = (
                None
                if snapshot.market_data is None
                else project_market_data(
                    snapshot.market_data, request.as_of, scenario, request.stress_delta
                )
            )
            try:
                import_result = normalize_offers(
                    snapshot.snapshot.offers,
                    snapshot.records,
                    request.eligibility,
                    period.start,
                    period.end,
                    market_data=market_data,
                ).model_copy(update={"index_snapshot": snapshot.snapshot.indexes})
                context = ComparisonContext(
                    current_contract=contract,
                    consumption=projected_consumption,
                    period=period,
                    as_of=period.start,
                    classification=request.classification,
                    rule_set=ruleset,
                    coverage_matrix=matrix,
                    rounding_policy=DEFAULT_ROUNDING_POLICY,
                    percentage_rounding_policy=DEFAULT_PERCENTAGE_ROUNDING_POLICY,
                    market_data=market_data,
                    measurements=request.measurements,
                    external_items=request.external_items,
                )
                comparison = self._engine.compare(context.to_request(import_result.eligible_offers))
            except (ComparisonError, BillingCoverageError, ValueError) as exc:
                raise CoreContractError(
                    CoreErrorCode.COMPARISON_FAILED,
                    "current comparison failed",
                ) from exc
            result_id = hashlib.sha256(
                json.dumps(
                    {
                        "import_id": import_result.import_id,
                        "comparison_id": comparison.comparison_id,
                        "scenario": scenario.value,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            portal_result = PortalComparisonResult(
                portal_result_id=f"portal-comparison:{result_id}",
                import_result=import_result,
                comparison_result=comparison,
            )
            scenarios.append(CurrentScenarioComparison(scenario=scenario, comparison=portal_result))
        result_digest = hashlib.sha256(
            json.dumps(
                {
                    "as_of": request.as_of.isoformat(),
                    "period": period.model_dump(mode="json"),
                    "scenarios": [item.comparison.portal_result_id for item in scenarios],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return CurrentPortalComparisonResult(
            current_result_id=f"current-portal-comparison:{result_digest}",
            as_of=request.as_of,
            period=period,
            catalog_dataset_date=snapshot.dataset_date,
            scenarios=tuple(scenarios),
        )

    def recommend(self, request: CurrentRecommendationRequest) -> Recommendation:
        """Apply the recommendation policy to the base scenario only."""

        preferences = request.preferences.model_copy(
            update={
                "minimum_savings": request.preferences.minimum_savings or request.minimum_savings,
                "minimum_percentage_savings": (
                    request.preferences.minimum_percentage_savings
                    if request.preferences.minimum_percentage_savings is not None
                    else request.minimum_percentage_savings
                ),
            }
        )
        try:
            recommendation_request = PortalRecommendationAdapter().build_request(
                request.comparison.base,
                preferences,
            )
            return self._recommendation_engine.recommend(recommendation_request)
        except (TypeError, ValueError) as exc:
            raise CoreContractError(
                CoreErrorCode.RECOMMENDATION_FAILED,
                "recommendation failed for the supplied current comparison",
            ) from exc

    def _billing_artifacts(
        self, request: CurrentPortalComparisonRequest, period: DatePeriod
    ) -> tuple[RegulatoryRuleSet, BillingCoverageMatrix]:
        segment = "resident" if request.classification.residential else "non-resident"
        try:
            ruleset = self._ruleset_loader(segment=segment)
            if ruleset.status != VerificationStatus.VERIFIED or not ruleset.provenance:
                raise BillingCoverageError("packaged ruleset is not verified")
            matrix = self._coverage_loader()
            matrix.resolve(
                request.classification,
                ruleset.ruleset_id,
                period,
                minimum_level=CoverageLevel.RULESET_VERIFIED,
            )
            return ruleset, matrix
        except (BillingCoverageError, OSError, ValueError) as exc:
            raise CoreContractError(
                CoreErrorCode.COVERAGE_UNAVAILABLE,
                "verified billing coverage is unavailable for the future period",
            ) from exc

    @staticmethod
    def _contract_for_period(
        request: CurrentPortalComparisonRequest, period: DatePeriod
    ) -> Contract:
        contract = request.current_contract
        if not (contract.validity.start <= request.as_of < contract.validity.end):
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "current contract is not active at the comparison date",
            )
        if period.end <= contract.validity.end:
            return contract
        if not request.continuation_assumption:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "current contract does not cover the future period",
            )
        extended_tariff = contract.tariff.model_copy(update={"validity": period})
        return contract.model_copy(
            update={
                "contract_id": f"{contract.contract_id}:continued",
                "validity": period,
                "tariff": extended_tariff,
                "conditions": (*contract.conditions, "continuation_assumption=true"),
            }
        )

    def _validate_request(self, request: CurrentPortalComparisonRequest) -> None:
        if request.as_of > self._clock().date():
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "current comparison date cannot be in the future",
            )
