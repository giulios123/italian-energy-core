"""Deterministic future estimates using an exact historical scenario window."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, localcontext

from italian_energy.arera.composer import AreraDomesticRuleSetComposer
from italian_energy.arera.projection import (
    DomesticProjectionAnchor,
    load_domestic_projection_anchor,
)
from italian_energy.arera.rollover_coverage import RegulatoryAnchorCoverageEvidence
from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.billing.engine import BillingRequest
from italian_energy.billing.regulatory import BillingError, RegulatoryBillingEngine
from italian_energy.comparison import (
    AlternativePricing,
    ComparisonResult,
    OfferExclusion,
    OfferExclusionCode,
)
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import (
    Bill,
    BillingResult,
    CostBreakdown,
    CostComponent,
    PricingResult,
)
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import Money, RoundingPolicy
from italian_energy.domain.offer import Contract, Offer
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import RegulatoryRuleSet, VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.integration.current import (
    CurrentCatalogSnapshot,
    CurrentScenario,
    future_period,
    project_consumption,
    project_market_data,
)
from italian_energy.integration.errors import CoreContractError, CoreErrorCode
from italian_energy.market.gme import (
    GmeMarketHistory,
    fetch_recent_market_history,
    recent_months,
)
from italian_energy.portal_offers.importer import PortalOffersImporter
from italian_energy.portal_offers.models import (
    NormalizedPortalOffer,
    PortalComparisonResult,
    PortalOffersImportResult,
)
from italian_energy.portal_offers.normalizer import normalize_offers
from italian_energy.portal_offers.recommendation import PortalRecommendationAdapter
from italian_energy.pricing.engine import PricingRequest
from italian_energy.pricing.fixed import FixedPricingEngine, FixedPricingError
from italian_energy.pricing.indexed import IndexedPricingEngine, IndexedPricingError
from italian_energy.recommendation import (
    DeterministicRecommendationEngine,
    RecommendationEngine,
)

from .projected import (
    ProjectedComparisonAssumptions,
    ProjectedDomesticComparisonRequest,
    ProjectedDomesticComparisonResult,
    ProjectedDomesticPreflightResult,
    ProjectedDomesticRecommendationRequest,
    ProjectedDomesticRecommendationResult,
    ProjectedScenarioComparison,
    ProjectedSourcePreflightResult,
    ProjectedVerifiedInputs,
    RegulatoryAnchorRefreshResult,
    RegulatoryCoverageEvidence,
    RegulatoryRegistry,
    RegulatoryRegistryReview,
    projection_anchor_digest,
    validate_consumption_periods,
)
from .regulatory_acquisition import fetch_official_source, verify_anchor_source_digests
from .service import (
    DEFAULT_PERCENTAGE_ROUNDING_POLICY,
    DEFAULT_ROUNDING_POLICY,
    CurrentDomesticEnergyService,
)

_INDEX_DELTA = Decimal("0.20")
_REQUIRED_REGISTRIES: tuple[RegulatoryRegistry, ...] = (
    "ARERA",
    "ADM",
    "Gazzetta Ufficiale",
    "Normattiva",
)


class ProjectedDomesticEnergyService:
    """Acquire snapshots explicitly and calculate estimated future comparison scenarios."""

    def __init__(
        self,
        *,
        importer: PortalOffersImporter | None = None,
        recommendation_engine: RecommendationEngine | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog_service = CurrentDomesticEnergyService(importer=importer, clock=clock)
        self._recommendation_engine = recommendation_engine or DeterministicRecommendationEngine()
        self._clock = clock or (lambda: datetime.now(UTC))
        self._fixed = FixedPricingEngine()
        self._indexed = IndexedPricingEngine()
        self._billing = RegulatoryBillingEngine()

    def acquire_catalog(self, dataset_date: date | None = None) -> CurrentCatalogSnapshot:
        """Acquire and parse the five official Portale Offerte files."""
        return self._catalog_service.acquire_catalog(dataset_date)

    @staticmethod
    def acquire_market_history(as_of: date) -> GmeMarketHistory:
        """Acquire exactly the twelve complete historical GME PUN months."""
        try:
            return fetch_recent_market_history(as_of)
        except ValueError as exc:
            raise CoreContractError(
                CoreErrorCode.SOURCE_ACQUISITION_FAILED,
                "official GME PUN history is incomplete or could not be acquired",
            ) from exc

    @staticmethod
    def acquire_regulatory_anchor(as_of: date | None = None) -> DomesticProjectionAnchor:
        """Load the packaged anchor active on the requested civil date."""
        try:
            return load_domestic_projection_anchor(as_of)
        except ValueError as exc:
            raise CoreContractError(
                CoreErrorCode.COVERAGE_UNAVAILABLE,
                "verified regulatory projection anchor is unavailable",
            ) from exc

    def refresh_regulatory_coverage(
        self,
        as_of: date,
        registry_reviews: tuple[RegulatoryRegistryReview, ...] = (),
        fetch_source: Callable[[str], bytes] = fetch_official_source,
    ) -> RegulatoryAnchorRefreshResult:
        """Refresh coverage of the packaged anchor; this does not build a successor."""
        anchor = self.acquire_regulatory_anchor(as_of)
        date_valid = (
            anchor.status == VerificationStatus.VERIFIED
            and anchor.as_of <= as_of
            and anchor.validity.start <= as_of < anchor.validity.end
        )
        source_checks = (
            verify_anchor_source_digests(anchor, fetch_source, self._clock) if date_valid else ()
        )
        now = self._clock()
        evidence = RegulatoryCoverageEvidence(
            anchor_id=anchor.anchor_id,
            anchor_sha256=projection_anchor_digest(anchor),
            comparison_as_of=as_of,
            checked_at=now,
            source_checks=source_checks,
            registry_reviews=registry_reviews,
        )
        expected_sources = {source.source_id: source.sha256 for source in anchor.sources}
        observed_sources = {check.source_id: check for check in source_checks}
        digests_match = set(observed_sources) == set(expected_sources) and all(
            expected is not None
            and observed_sources[source_id].expected_sha256 == expected
            and observed_sources[source_id].observed_sha256 == expected
            for source_id, expected in expected_sources.items()
        )
        reviews = {review.registry: review for review in registry_reviews}
        review_complete = set(reviews) == set(_REQUIRED_REGISTRIES) and all(
            review.as_of == as_of and review.reviewed_at <= now for review in reviews.values()
        )
        applicable = any(
            finding.applicability == "applicable"
            for review in registry_reviews
            for finding in review.findings
        )
        uncertain = any(
            finding.applicability == "uncertain"
            for review in registry_reviews
            for finding in review.findings
        )
        checks = {
            "anchor_verified": anchor.status == VerificationStatus.VERIFIED,
            "anchor_valid_at_as_of": date_valid,
            "source_digests_match": digests_match,
            "registry_reviews_complete": review_complete,
            "no_applicable_later_regulatory_act": not applicable,
            "no_uncertain_later_regulatory_act": not uncertain,
        }
        reasons: list[str] = []
        if not date_valid:
            reasons.append(
                CoreErrorCode.COVERAGE_EXPIRED.value
                if as_of >= anchor.validity.end
                else CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
            )
        if not digests_match:
            changed = any(
                check.observed_sha256 is not None and check.expected_sha256 != check.observed_sha256
                for check in source_checks
            )
            reasons.append(
                CoreErrorCode.REGULATORY_SOURCE_CHANGED.value
                if changed
                else CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
            )
        if not review_complete or uncertain:
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        if applicable:
            reasons.append(CoreErrorCode.APPLICABLE_REGULATORY_ACT.value)
        return RegulatoryAnchorRefreshResult(
            as_of=as_of,
            anchor=anchor,
            coverage_evidence=evidence,
            ready=all(checks.values()),
            checks=checks,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def refresh_regulatory_anchor(
        self,
        as_of: date,
        registry_reviews: tuple[RegulatoryRegistryReview, ...] = (),
        fetch_source: Callable[[str], bytes] = fetch_official_source,
    ) -> RegulatoryAnchorRefreshResult:
        """Compatibility alias for refresh_regulatory_coverage."""

        return self.refresh_regulatory_coverage(as_of, registry_reviews, fetch_source)

    def preflight(
        self,
        request: ProjectedDomesticComparisonRequest,
        catalog: CurrentCatalogSnapshot | None = None,
        market_history: GmeMarketHistory | None = None,
        anchor: DomesticProjectionAnchor | None = None,
        coverage_evidence: RegulatoryCoverageEvidence
        | RegulatoryAnchorCoverageEvidence
        | None = None,
    ) -> ProjectedDomesticPreflightResult:
        """Report official-data availability separately from projection readiness."""
        horizon = future_period(request.as_of)
        source_gate = self.source_preflight(
            request.as_of, catalog, market_history, anchor, coverage_evidence
        )
        checks = {
            "request_supported": True,
            **source_gate.checks,
            "baseline_contract_covers_horizon": False,
            "baseline_calculable": False,
            "supported_candidate_available": False,
        }
        reasons: list[str] = list(source_gate.reason_codes)
        normalized_count = 0
        eligible_count = 0
        excluded_count = 0
        try:
            self._validate_as_of(request.as_of)
            validate_consumption_periods(request.consumption, request.as_of)
        except (CoreContractError, ValueError) as exc:
            checks["request_supported"] = False
            reasons.append(
                exc.code.value if isinstance(exc, CoreContractError) else "unsupported_scenario"
            )

        try:
            self._contract_for_horizon(request, horizon)
            checks["baseline_contract_covers_horizon"] = True
        except CoreContractError as exc:
            reasons.append(exc.code.value)

        if (
            checks["request_supported"]
            and checks["baseline_contract_covers_horizon"]
            and checks["market_window_verified"]
            and checks["regulatory_anchor_verified"]
        ):
            try:
                assert anchor is not None
                assert market_history is not None
                ruleset = self._ruleset(anchor, request.classification.residential)
                consumption = project_consumption(request.consumption, request.as_of)
                self._evaluate_contract(
                    request,
                    self._contract_for_horizon(request, horizon),
                    consumption,
                    project_market_data(
                        market_history.market_data,
                        request.as_of,
                        CurrentScenario.BASE,
                        _INDEX_DELTA,
                    ),
                    ruleset,
                )
                checks["baseline_calculable"] = True
            except (
                CoreContractError,
                BillingError,
                FixedPricingError,
                IndexedPricingError,
                ValueError,
            ):
                reasons.append(CoreErrorCode.COMPARISON_FAILED.value)

        if checks["catalog_verified"] and checks["market_window_verified"]:
            assert catalog is not None
            assert market_history is not None
            import_result = self._normalize(request, catalog, market_history)
            normalized_count = len(import_result.normalized)
            excluded_count = len(import_result.exclusions)
            eligible_count = sum(
                1 for item in import_result.normalized if self._offer_covers_horizon(item, horizon)
            )
            excluded_count += normalized_count - eligible_count
            checks["supported_candidate_available"] = eligible_count > 0
            if not checks["supported_candidate_available"]:
                reasons.append(CoreErrorCode.SOURCE_VALIDATION_FAILED.value)

        official_ready = source_gate.ready
        calculable = all(
            checks[name]
            for name in (
                "request_supported",
                "baseline_contract_covers_horizon",
                "baseline_calculable",
                "supported_candidate_available",
            )
        )
        return ProjectedDomesticPreflightResult(
            ready=official_ready and calculable,
            official_data_ready=official_ready,
            projection_calculable=calculable,
            as_of=request.as_of,
            period=horizon,
            checks=checks,
            reason_codes=tuple(dict.fromkeys(reasons)),
            normalized_offer_count=normalized_count,
            horizon_eligible_offer_count=eligible_count,
            excluded_offer_count=excluded_count,
        )

    def source_preflight(
        self,
        as_of: date,
        catalog: CurrentCatalogSnapshot | None,
        market_history: GmeMarketHistory | None,
        anchor: DomesticProjectionAnchor | None,
        coverage_evidence: RegulatoryCoverageEvidence | RegulatoryAnchorCoverageEvidence | None,
    ) -> ProjectedSourcePreflightResult:
        """Gate reusable official inputs without acquiring data or calculating offers."""
        checks = {
            "comparison_date_supported": False,
            "catalog_verified": False,
            "market_window_verified": False,
            "regulatory_anchor_verified": False,
            "regulatory_anchor_valid_at_as_of": False,
            "regulatory_source_digests_match": False,
            "regulatory_registry_coverage_complete": False,
            "no_applicable_later_regulatory_act": False,
        }
        reasons: list[str] = []
        try:
            self._validate_as_of(as_of)
            checks["comparison_date_supported"] = True
        except CoreContractError as exc:
            reasons.append(exc.code.value)

        if catalog is None:
            reasons.append("catalog_snapshot_missing")
        else:
            checks["catalog_verified"] = (
                catalog.dataset_date <= as_of
                and catalog.snapshot.offers.status == VerificationStatus.VERIFIED
                and all(
                    item.status == VerificationStatus.VERIFIED
                    for item in catalog.snapshot.offers.files
                )
            )
            if not checks["catalog_verified"]:
                reasons.append(CoreErrorCode.SOURCE_VALIDATION_FAILED.value)

        if market_history is None:
            reasons.append("gme_market_history_missing")
        else:
            checks["market_window_verified"] = self._market_history_matches(market_history, as_of)
            if not checks["market_window_verified"]:
                reasons.append(CoreErrorCode.SOURCE_VALIDATION_FAILED.value)

        if anchor is None:
            reasons.append("regulatory_anchor_missing")
        elif anchor.status != VerificationStatus.VERIFIED:
            checks["regulatory_anchor_valid_at_as_of"] = False
            reasons.append("regulatory_anchor_unverified")
        else:
            checks["regulatory_anchor_valid_at_as_of"] = (
                anchor.as_of <= as_of and anchor.validity.start <= as_of < anchor.validity.end
            )
            if not checks["regulatory_anchor_valid_at_as_of"]:
                if as_of >= anchor.validity.end:
                    reasons.append(CoreErrorCode.COVERAGE_EXPIRED.value)
                else:
                    reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)

        if anchor is not None and coverage_evidence is not None:
            coverage_reasons = self._coverage_evidence_reasons(anchor, as_of, coverage_evidence)
            reasons.extend(coverage_reasons)
            checks["regulatory_source_digests_match"] = (
                CoreErrorCode.REGULATORY_SOURCE_CHANGED.value not in coverage_reasons
                and self._source_digests_complete(anchor, coverage_evidence)
            )
            if isinstance(coverage_evidence, RegulatoryAnchorCoverageEvidence):
                checks["regulatory_registry_coverage_complete"] = not any(
                    reason
                    in {
                        RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
                        RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE,
                    }
                    for reason in coverage_evidence.reason_codes
                )
                checks["no_applicable_later_regulatory_act"] = not any(
                    reason
                    in {
                        RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                        RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                        RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
                    }
                    for reason in coverage_evidence.reason_codes
                )
            else:
                reviews = {item.registry: item for item in coverage_evidence.registry_reviews}
                checks["regulatory_registry_coverage_complete"] = (
                    set(reviews) == set(_REQUIRED_REGISTRIES)
                    and all(item.as_of == as_of for item in reviews.values())
                    and all(item.reviewed_at <= self._clock() for item in reviews.values())
                )
                checks["no_applicable_later_regulatory_act"] = not any(
                    finding.applicability == "applicable"
                    for review in coverage_evidence.registry_reviews
                    for finding in review.findings
                )
            checks["regulatory_anchor_verified"] = (
                checks["regulatory_anchor_valid_at_as_of"]
                and checks["regulatory_source_digests_match"]
                and checks["regulatory_registry_coverage_complete"]
                and checks["no_applicable_later_regulatory_act"]
                and not coverage_reasons
            )
        elif anchor is not None:
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)

        unique_reasons = tuple(dict.fromkeys(reasons))
        return ProjectedSourcePreflightResult(
            ready=all(checks[name] for name in checks),
            as_of=as_of,
            checks=checks,
            reason_codes=unique_reasons,
        )

    def _coverage_evidence_reasons(
        self,
        anchor: DomesticProjectionAnchor,
        as_of: date,
        evidence: RegulatoryCoverageEvidence | RegulatoryAnchorCoverageEvidence,
    ) -> tuple[str, ...]:
        reasons: list[str] = []
        if evidence.comparison_as_of != as_of:
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        if evidence.anchor_id != anchor.anchor_id:
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        if evidence.anchor_sha256 != projection_anchor_digest(anchor):
            reasons.append(CoreErrorCode.REGULATORY_SOURCE_CHANGED.value)
        if evidence.checked_at > self._clock():
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        if isinstance(evidence, RegulatoryAnchorCoverageEvidence):
            reason_map = {
                RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY: (
                    CoreErrorCode.REGULATORY_SOURCE_CHANGED.value
                ),
                RegulatoryRolloverReason.CURRENT_ANCHOR_EXPIRED: (
                    CoreErrorCode.COVERAGE_EXPIRED.value
                ),
                RegulatoryRolloverReason.SOURCE_UNAVAILABLE: (
                    CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
                ),
                RegulatoryRolloverReason.INCOMPLETE_COVERAGE: (
                    CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
                ),
                RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE: (
                    CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
                ),
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE: (
                    CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
                ),
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY: (
                    CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value
                ),
            }
            reasons.extend(reason_map.get(reason, reason.value) for reason in evidence.reason_codes)
            if not evidence.ready and not evidence.reason_codes:
                reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
            anchor_checks_by_id = {item.source_id: item for item in evidence.source_checks}
            expected_ids = {item.source_id for item in anchor.sources}
            if set(anchor_checks_by_id) != expected_ids:
                reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
            for source in anchor.sources:
                anchor_check = anchor_checks_by_id.get(source.source_id)
                if anchor_check is None:
                    continue
                if (
                    source.sha256 is None
                    or anchor_check.expected_sha256 != source.sha256
                    or anchor_check.observed_sha256 is None
                ):
                    reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
                elif anchor_check.observed_sha256 != source.sha256:
                    reasons.append(CoreErrorCode.REGULATORY_SOURCE_CHANGED.value)
                if anchor_check.checked_at > self._clock():
                    reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
            return tuple(dict.fromkeys(reasons))
        checks_by_id = {item.source_id: item for item in evidence.source_checks}
        expected_ids = {item.source_id for item in anchor.sources}
        if set(checks_by_id) != expected_ids:
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        if any(item.checked_at > self._clock() for item in evidence.source_checks):
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        for source in anchor.sources:
            check = checks_by_id.get(source.source_id)
            if check is None:
                continue
            if (
                source.sha256 is None
                or check.expected_sha256 != source.sha256
                or check.observed_sha256 is None
            ):
                reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
            elif check.observed_sha256 != source.sha256:
                reasons.append(CoreErrorCode.REGULATORY_SOURCE_CHANGED.value)

        reviews_by_registry = {item.registry: item for item in evidence.registry_reviews}
        if set(reviews_by_registry) != set(_REQUIRED_REGISTRIES):
            reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        for review in evidence.registry_reviews:
            if review.as_of != as_of or review.reviewed_at > self._clock():
                reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
            if any(finding.applicability == "applicable" for finding in review.findings):
                reasons.append(CoreErrorCode.APPLICABLE_REGULATORY_ACT.value)
            if any(finding.applicability == "uncertain" for finding in review.findings):
                reasons.append(CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value)
        return tuple(dict.fromkeys(reasons))

    @staticmethod
    def _source_digests_complete(
        anchor: DomesticProjectionAnchor,
        evidence: RegulatoryCoverageEvidence | RegulatoryAnchorCoverageEvidence,
    ) -> bool:
        checks_by_id = {item.source_id: item for item in evidence.source_checks}
        return set(checks_by_id) == {item.source_id for item in anchor.sources} and all(
            source.sha256 is not None
            and checks_by_id[source.source_id].expected_sha256 == source.sha256
            and checks_by_id[source.source_id].observed_sha256 == source.sha256
            for source in anchor.sources
        )

    def compare(
        self,
        request: ProjectedDomesticComparisonRequest,
        catalog: CurrentCatalogSnapshot,
        market_history: GmeMarketHistory,
        anchor: DomesticProjectionAnchor,
        coverage_evidence: RegulatoryCoverageEvidence
        | RegulatoryAnchorCoverageEvidence
        | None = None,
    ) -> ProjectedDomesticComparisonResult:
        """Return low/base/high monthly-billed future estimates from explicit snapshots."""
        self._validate_as_of(request.as_of)
        validate_consumption_periods(request.consumption, request.as_of)
        source_gate = self.source_preflight(
            request.as_of, catalog, market_history, anchor, coverage_evidence
        )
        if not source_gate.ready:
            errors = set(source_gate.reason_codes)
            priority = (
                CoreErrorCode.UNSUPPORTED_HORIZON.value,
                CoreErrorCode.COVERAGE_EXPIRED.value,
                CoreErrorCode.REGULATORY_SOURCE_CHANGED.value,
                CoreErrorCode.APPLICABLE_REGULATORY_ACT.value,
                CoreErrorCode.REGULATORY_COVERAGE_UNCONFIRMED.value,
                CoreErrorCode.SOURCE_VALIDATION_FAILED.value,
                CoreErrorCode.COVERAGE_UNAVAILABLE.value,
            )
            code = next((item for item in priority if item in errors), None)
            if code is None:
                code = CoreErrorCode.COVERAGE_UNAVAILABLE.value
            raise CoreContractError(
                CoreErrorCode(code),
                "projected comparison source preflight is not ready: "
                + ", ".join(source_gate.reason_codes),
            )
        assert coverage_evidence is not None

        horizon = future_period(request.as_of)
        baseline_contract = self._contract_for_horizon(request, horizon)
        ruleset = self._ruleset(anchor, request.classification.residential)
        projected_consumption = project_consumption(request.consumption, request.as_of)
        import_result = self._normalize(request, catalog, market_history)
        multipliers = (Decimal("0.80"), Decimal("1.00"), Decimal("1.20"))
        scenario_pairs = (
            (CurrentScenario.LOW_INDEX, multipliers[0]),
            (CurrentScenario.BASE, multipliers[1]),
            (CurrentScenario.HIGH_INDEX, multipliers[2]),
        )
        scenarios: list[ProjectedScenarioComparison] = []
        for scenario, multiplier in scenario_pairs:
            projected_market = project_market_data(
                market_history.market_data,
                request.as_of,
                scenario,
                _INDEX_DELTA,
            )
            comparison = self._compare_scenario(
                request,
                baseline_contract,
                import_result,
                projected_consumption,
                projected_market,
                ruleset,
                horizon,
                scenario,
            )
            scenarios.append(
                ProjectedScenarioComparison(
                    scenario=scenario,
                    index_multiplier=multiplier,
                    comparison=comparison,
                )
            )

        history_period = DatePeriod(
            start=recent_months(request.as_of)[0],
            end=_add_months(recent_months(request.as_of)[-1], 1),
        )
        provenance = anchor.to_bundle().provenance
        evidence = ProjectedVerifiedInputs(
            catalog_snapshot_id=catalog.snapshot.offers.snapshot_id,
            catalog_dataset_date=catalog.dataset_date,
            catalog_status=catalog.snapshot.offers.status,
            market_status=market_history.status,
            market_period=history_period,
            market_report_provenance=tuple(report.provenance for report in market_history.reports),
            regulatory_anchor_id=anchor.anchor_id,
            regulatory_status=anchor.status,
            regulatory_anchor_date=anchor.as_of,
            regulatory_provenance=provenance,
            comparison_as_of=request.as_of,
            regulatory_anchor_validity=anchor.validity,
            regulatory_coverage_as_of=coverage_evidence.comparison_as_of,
            regulatory_coverage_id=coverage_evidence.evidence_id,
        )
        assumptions = ProjectedComparisonAssumptions(
            historical_consumption_period=history_period,
            historical_market_period=history_period,
            future_period=horizon,
            regulatory_anchor_date=anchor.as_of,
            current_contract_continued=request.continuation_assumption,
        )
        digest = _digest(
            {
                "as_of": request.as_of.isoformat(),
                "period": horizon.model_dump(mode="json"),
                "catalog": catalog.snapshot.offers.snapshot_id,
                "market_digests": [item.sha256 for item in evidence.market_report_provenance],
                "anchor": anchor.anchor_id,
                "regulatory_coverage": coverage_evidence.evidence_id,
                "scenarios": [item.comparison.portal_result_id for item in scenarios],
                "assumptions": assumptions.model_dump(mode="json"),
            }
        )
        return ProjectedDomesticComparisonResult(
            result_id=f"projected-domestic-comparison:{digest}",
            as_of=request.as_of,
            period=horizon,
            assumptions=assumptions,
            verified_inputs=evidence,
            scenarios=tuple(scenarios),
        )

    def recommend(
        self, request: ProjectedDomesticRecommendationRequest
    ) -> ProjectedDomesticRecommendationResult:
        """Apply accepted recommendation filters to the base estimate only."""
        comparison = request.comparison
        if comparison.verified_inputs.market_status != VerificationStatus.VERIFIED:
            raise CoreContractError(
                CoreErrorCode.RECOMMENDATION_FAILED,
                "recommendation requires a comparison with verified official inputs",
            )
        preferences = request.preferences.model_copy(
            update={
                "minimum_savings": (
                    request.preferences.minimum_savings
                    if request.preferences.minimum_savings is not None
                    else Money(amount=request.minimum_savings)
                ),
                "minimum_percentage_savings": (
                    request.preferences.minimum_percentage_savings
                    if request.preferences.minimum_percentage_savings is not None
                    else request.minimum_percentage_savings
                ),
            }
        )
        try:
            recommendation_request = PortalRecommendationAdapter().build_request(
                comparison.base,
                preferences,
            )
            recommendation = self._recommendation_engine.recommend(recommendation_request)
        except (TypeError, ValueError) as exc:
            raise CoreContractError(
                CoreErrorCode.RECOMMENDATION_FAILED,
                "base-scenario recommendation failed",
            ) from exc
        return ProjectedDomesticRecommendationResult(
            recommendation=recommendation,
            comparison_id=comparison.result_id,
            assumptions=comparison.assumptions,
        )

    def _compare_scenario(
        self,
        request: ProjectedDomesticComparisonRequest,
        current_contract: Contract,
        import_result: PortalOffersImportResult,
        consumption: ConsumptionProfile,
        market_data: MarketData,
        ruleset: RegulatoryRuleSet,
        horizon: DatePeriod,
        scenario: CurrentScenario,
    ) -> PortalComparisonResult:
        try:
            current_pricing, current_billing = self._evaluate_contract(
                request, current_contract, consumption, market_data, ruleset
            )
        except (BillingError, FixedPricingError, IndexedPricingError, ValueError) as exc:
            raise CoreContractError(
                CoreErrorCode.COMPARISON_FAILED,
                "current-contract future estimate cannot be calculated",
            ) from exc
        current_total = current_billing.bill.breakdown.total
        alternatives: list[AlternativePricing] = []
        exclusions: list[OfferExclusion] = []
        for item in import_result.normalized:
            offer = item.offer
            if (
                request.current_contract.source_offer_id is not None
                and offer.offer_id == request.current_contract.source_offer_id
            ):
                exclusions.append(
                    OfferExclusion(
                        offer_id=offer.offer_id,
                        code=OfferExclusionCode.SAME_AS_CURRENT,
                        detail="offer is the declared source offer of the current contract",
                    )
                )
                continue
            if not self._offer_covers_horizon(item, horizon):
                exclusions.append(
                    OfferExclusion(
                        offer_id=offer.offer_id,
                        code=OfferExclusionCode.PERIOD_NOT_COVERED,
                        detail=(
                            "known economic duration does not cover the full future horizon; "
                            "an absent duration is not inferred from the subscription window"
                        ),
                    )
                )
                continue
            contract = Contract(
                contract_id=_candidate_contract_id(request, offer),
                supply=current_contract.supply,
                tariff=offer.tariff,
                validity=offer.tariff.validity,
                source_offer_id=offer.offer_id,
                conditions=offer.conditions,
                provenance=offer.provenance,
            )
            try:
                pricing, billing = self._evaluate_contract(
                    request, contract, consumption, market_data, ruleset
                )
            except (BillingError, FixedPricingError, IndexedPricingError, ValueError) as exc:
                exclusions.append(
                    OfferExclusion(
                        offer_id=offer.offer_id,
                        code=(
                            OfferExclusionCode.PRICING_FAILED
                            if isinstance(exc, (FixedPricingError, IndexedPricingError))
                            else OfferExclusionCode.BILLING_FAILED
                        ),
                        detail=str(exc),
                    )
                )
                continue
            alternative_total = billing.bill.breakdown.total
            savings = current_total - alternative_total
            alternatives.append(
                AlternativePricing(
                    offer_id=offer.offer_id,
                    pricing=pricing,
                    absolute_difference=Money(amount=abs(savings.amount)),
                    percentage_difference=_percentage_difference(
                        savings, current_total, DEFAULT_PERCENTAGE_ROUNDING_POLICY
                    ),
                    candidate_contract_id=contract.contract_id,
                    billing=billing,
                    comparable_total=alternative_total,
                    savings=savings,
                )
            )
        alternatives.sort(key=_alternative_sort_key)
        ranking = tuple(item.offer_id for item in alternatives)
        exclusions.sort(key=lambda item: item.offer_id)
        assumptions = (
            "all future cost and savings values are estimates",
            "historical monthly consumption is repeated in the same calendar month",
            "only verified monthly PUN Index GME values are available as indexed inputs",
            (
                f"regulatory and fiscal values verified at {request.as_of.isoformat()} "
                "are assumed constant"
            ),
            "published offer terms must cover the full future horizon; terms are never extended",
        )
        payload = {
            "current_contract_id": current_contract.contract_id,
            "current_pricing_id": current_pricing.pricing_id,
            "scenario": scenario.value,
            "ranking": ranking,
            "period": horizon.model_dump(mode="json"),
        }
        result = ComparisonResult(
            comparison_id=f"projected-comparison:{_digest(payload)}",
            current_contract_id=current_contract.contract_id,
            current_pricing=current_pricing,
            alternatives=tuple(alternatives),
            ranking=ranking,
            assumptions=assumptions,
            warnings=("future billing and savings are estimates, not verified future values",),
            current_billing=current_billing,
            current_comparable_total=current_total,
            coverage=None,
            excluded_offers=tuple(exclusions),
        )
        result_id = _digest(
            {"import_id": import_result.import_id, "comparison_id": result.comparison_id}
        )
        return PortalComparisonResult(
            portal_result_id=f"portal-comparison:{result_id}",
            import_result=import_result,
            comparison_result=result,
        )

    def _evaluate_contract(
        self,
        request: ProjectedDomesticComparisonRequest,
        contract: Contract,
        consumption: ConsumptionProfile,
        market_data: MarketData,
        ruleset: RegulatoryRuleSet,
    ) -> tuple[PricingResult, BillingResult]:
        pricing_results: list[PricingResult] = []
        billing_results: list[BillingResult] = []
        for month in _months(future_period(request.as_of)):
            pricing_request = PricingRequest(
                contract=contract,
                consumption=consumption,
                period=month,
                rounding_policy=DEFAULT_ROUNDING_POLICY,
                market_data=market_data if contract.tariff.kind == "indexed" else None,
            )
            if contract.tariff.kind == "fixed":
                pricing = self._fixed.price(pricing_request)
            elif contract.tariff.kind == "indexed":
                pricing = self._indexed.price(pricing_request)
            else:  # pragma: no cover - enum prevents unrecognized tariffs
                raise ValueError("unsupported future tariff type")
            billing = self._billing.evaluate(
                BillingRequest(
                    contract=contract,
                    consumption=consumption,
                    period=month,
                    pricing_result=pricing,
                    classification=request.classification,
                    rule_set=ruleset,
                    measurements=(),
                    external_items=(),
                    rounding_policy=DEFAULT_ROUNDING_POLICY,
                    regulatory_projection_as_of=request.as_of,
                )
            )
            pricing_results.append(pricing)
            billing_results.append(billing)
        return (
            _aggregate_pricing(pricing_results, future_period(request.as_of)),
            _aggregate_billing(billing_results, future_period(request.as_of)),
        )

    def _normalize(
        self,
        request: ProjectedDomesticComparisonRequest,
        catalog: CurrentCatalogSnapshot,
        market_history: GmeMarketHistory,
    ) -> PortalOffersImportResult:
        import_result = normalize_offers(
            catalog.snapshot.offers,
            catalog.records,
            request.eligibility,
            request.as_of,
            request.as_of + timedelta(days=1),
            market_data=market_history.market_data,
        )
        return import_result.model_copy(update={"index_snapshot": catalog.snapshot.indexes})

    @staticmethod
    def _offer_covers_horizon(item: NormalizedPortalOffer, horizon: DatePeriod) -> bool:
        # DATA_FINE describes the subscription window; without a known economic
        # duration it cannot support an assumed twelve-month price lock.
        if item.source_record.duration_months is None:
            return False
        return (
            item.offer.tariff.validity.start <= horizon.start
            and item.offer.tariff.validity.end >= horizon.end
        )

    @staticmethod
    def _contract_for_horizon(
        request: ProjectedDomesticComparisonRequest,
        horizon: DatePeriod,
    ) -> Contract:
        contract = request.current_contract
        if not (contract.validity.start <= request.as_of < contract.validity.end):
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "current contract is not active on the comparison date",
            )
        if contract.validity.end >= horizon.end and contract.tariff.validity.end >= horizon.end:
            return contract
        if not request.continuation_assumption:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "current contract does not cover the projection and continuation was not declared",
            )
        tariff = contract.tariff.model_copy(update={"validity": horizon})
        return contract.model_copy(
            update={
                "contract_id": f"{contract.contract_id}:continued",
                "validity": horizon,
                "tariff": tariff,
                "conditions": (*contract.conditions, "continuation_assumption=true"),
            }
        )

    @staticmethod
    def _ruleset(anchor: DomesticProjectionAnchor, residential: bool | None) -> RegulatoryRuleSet:
        if residential is None:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "domestic projection requires explicit resident/non-resident classification",
            )
        from italian_energy.arera.models import AreraCustomerSegment

        segment = (
            AreraCustomerSegment.RESIDENT if residential else AreraCustomerSegment.NON_RESIDENT
        )
        try:
            return AreraDomesticRuleSetComposer().compose(
                anchor.to_bundle(), segment, anchor.fiscal_policy()
            )
        except ValueError as exc:
            raise CoreContractError(
                CoreErrorCode.COVERAGE_UNAVAILABLE,
                "verified regulatory anchor cannot be composed for this profile",
            ) from exc

    @staticmethod
    def _market_history_matches(history: GmeMarketHistory, as_of: date) -> bool:
        if history.status != VerificationStatus.VERIFIED or history.as_of != as_of:
            return False
        expected = recent_months(as_of)
        actual = tuple(report.parsed.period.start for report in history.reports)
        if actual != expected or len(history.reports) != 12:
            return False
        if any(report.status != VerificationStatus.VERIFIED for report in history.reports):
            return False
        if any(
            report.provenance.source != "GME"
            or not report.provenance.sha256
            or report.provenance.url is None
            or report.provenance.effective_period != report.parsed.period
            for report in history.reports
        ):
            return False
        if len(history.market_data.indexes) != 1 or history.market_data.indexes[0].code != "PUN":
            return False
        if len(history.market_data.points) != len(history.reports):
            return False
        return all(
            point.index_code == "PUN"
            and point.interval.start.date() == report.parsed.period.start
            and point.interval.end.date() == report.parsed.period.end
            and point.value == report.parsed.value_eur_per_kwh
            and any(
                item.sha256 == report.provenance.sha256
                and item.effective_period == report.parsed.period
                for item in point.provenance
            )
            for report, point in zip(history.reports, history.market_data.points, strict=True)
        )

    def _validate_as_of(self, as_of: date) -> None:
        if as_of > self._clock().date():
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_HORIZON,
                "comparison date cannot be in the future",
            )


def _months(period: DatePeriod) -> tuple[DatePeriod, ...]:
    """Split a calendar-month horizon into its twelve monthly billing periods."""
    if period.start.day != 1 or period.end.day != 1:
        raise ValueError("projected billing period must contain complete calendar months")
    result: list[DatePeriod] = []
    current = period.start
    while current < period.end:
        following = _add_months(current, 1)
        result.append(DatePeriod(start=current, end=following))
        current = following
    if current != period.end:
        raise ValueError("projected billing period must contain complete calendar months")
    return tuple(result)


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, 1)


def _candidate_contract_id(request: ProjectedDomesticComparisonRequest, offer: Offer) -> str:
    value = {
        "as_of": request.as_of.isoformat(),
        "offer": offer.model_dump(mode="json"),
    }
    return "projected-contract:" + _digest(value)


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _merge_provenance(*groups: Iterable[Provenance]) -> tuple[Provenance, ...]:
    unique: dict[bytes, Provenance] = {}
    for provenance_group in groups:
        for item in provenance_group:
            key = json.dumps(
                item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            unique.setdefault(key, item)
    return tuple(unique[key] for key in sorted(unique))


def _aggregate_components(
    components: Iterable[CostComponent], period: DatePeriod
) -> tuple[CostComponent, ...]:
    groups: dict[tuple[object, ...], list[CostComponent]] = defaultdict(list)
    for item in components:
        key = (
            item.code,
            item.description,
            item.formula,
            item.category,
            item.quota,
            item.reconciliation_key,
            item.unit_rate.unit if item.unit_rate is not None else None,
        )
        groups[key].append(item)

    result: list[CostComponent] = []
    ordered_keys: list[tuple[object, ...]] = sorted(
        groups,
        key=lambda value: tuple("" if part is None else str(part) for part in value),
    )
    for group_key in ordered_keys:
        items = groups[group_key]
        quantity = (
            sum(
                (item.quantity for item in items if item.quantity is not None),
                Decimal(0),
            )
            if all(item.quantity is not None for item in items)
            else None
        )
        rates = tuple(item.unit_rate for item in items)
        rate = rates[0] if rates and all(candidate == rates[0] for candidate in rates) else None
        result.append(
            CostComponent(
                code=items[0].code,
                description=items[0].description,
                amount=sum((item.amount for item in items), Money(amount=Decimal(0))),
                quantity=quantity,
                unit_rate=rate,
                period=period,
                formula=items[0].formula,
                provenance=_merge_provenance(*(item.provenance for item in items)),
                category=items[0].category,
                quota=items[0].quota,
                reconciliation_key=items[0].reconciliation_key,
            )
        )
    return tuple(result)


def _aggregate_pricing(results: Sequence[PricingResult], period: DatePeriod) -> PricingResult:
    if not results:
        raise ValueError("cannot aggregate an empty pricing result sequence")
    components = _aggregate_components(
        (component for result in results for component in result.breakdown.components), period
    )
    total = sum((item.breakdown.total for item in results), Money(amount=Decimal(0)))
    assumptions = tuple(dict.fromkeys(value for item in results for value in item.assumptions))
    warnings = tuple(dict.fromkeys(value for item in results for value in item.warnings))
    return PricingResult(
        pricing_id="projected-pricing:" + _digest([item.pricing_id for item in results]),
        contract_id=results[0].contract_id,
        period=period,
        breakdown=CostBreakdown(
            components=components,
            total=total,
            assumptions=assumptions,
            warnings=warnings,
        ),
        assumptions=assumptions,
        warnings=warnings,
        provenance=_merge_provenance(*(item.provenance for item in results)),
    )


def _aggregate_billing(results: Sequence[BillingResult], period: DatePeriod) -> BillingResult:
    if not results:
        raise ValueError("cannot aggregate an empty billing result sequence")
    components = _aggregate_components(
        (component for result in results for component in result.bill.breakdown.components),
        period,
    )
    total = sum((item.bill.breakdown.total for item in results), Money(amount=Decimal(0)))
    assumptions = tuple(dict.fromkeys(value for item in results for value in item.assumptions))
    warnings = tuple(dict.fromkeys(value for item in results for value in item.warnings))
    bill = Bill(
        bill_id="projected-bill:" + _digest([item.bill.bill_id for item in results]),
        contract_id=results[0].bill.contract_id,
        period=period,
        breakdown=CostBreakdown(
            components=components,
            total=total,
            assumptions=assumptions,
            warnings=warnings,
        ),
        declared_total=total,
        provenance=_merge_provenance(*(item.bill.provenance for item in results)),
    )
    return BillingResult(
        billing_id="projected-billing:" + _digest([item.billing_id for item in results]),
        bill=bill,
        assumptions=assumptions,
        warnings=warnings,
        provenance=_merge_provenance(*(item.provenance for item in results)),
    )


def _percentage_difference(
    savings: Money, current_total: Money, policy: RoundingPolicy
) -> Decimal | None:
    if current_total.amount <= 0:
        return None
    with localcontext() as context:
        context.prec = 28
        raw = savings.amount / current_total.amount * Decimal("100")
    quantum = Decimal(1).scaleb(-policy.scale)
    return raw.quantize(quantum, rounding=policy.mode.decimal_mode)


def _alternative_sort_key(item: AlternativePricing) -> tuple[Decimal, str]:
    if item.comparable_total is None:
        raise ValueError("projected alternatives require a comparable total")
    return item.comparable_total.amount, item.offer_id


__all__ = ["ProjectedDomesticEnergyService"]
