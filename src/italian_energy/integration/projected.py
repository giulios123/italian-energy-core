"""Typed Core--Platform contract for historical-scenario projections."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import (
    SupplyClassification,
    VerificationStatus,
    VoltageLevel,
)
from italian_energy.domain.time import DatePeriod
from italian_energy.integration.current import (
    CurrentCatalogSnapshot,
    CurrentScenario,
    future_period,
)
from italian_energy.market.gme import GmeMarketHistory
from italian_energy.portal_offers.models import (
    PortalComparisonResult,
    PortalEligibilityProfile,
)
from italian_energy.recommendation import Recommendation, RecommendationPreferences

RegulatoryRegistry = Literal["ARERA", "ADM", "Gazzetta Ufficiale", "Normattiva"]
_REGISTRY_HOSTS = {
    "ARERA": {"arera.it", "www.arera.it"},
    "ADM": {"adm.gov.it", "www.adm.gov.it"},
    "Gazzetta Ufficiale": {"gazzettaufficiale.it", "www.gazzettaufficiale.it"},
    "Normattiva": {"normattiva.it", "www.normattiva.it"},
}


class RegulatorySourceDigestCheck(DomainModel):
    """One live digest observation bound to a source listed by the anchor."""

    source_id: str = Field(min_length=1)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def require_aware_check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("regulatory source check time must be timezone-aware")
        return value


class RegulatoryActFinding(DomainModel):
    """An act discovered while reviewing an official registry for applicability."""

    act_id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    applicability: Literal["applicable", "not_applicable", "uncertain"]
    rationale: str = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def require_official_act_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not any(parsed.hostname in hosts for hosts in _REGISTRY_HOSTS.values())
        ):
            raise ValueError("regulatory act URL must use an official HTTPS registry")
        return value


class RegulatoryRegistryReview(DomainModel):
    """Dated manual review or reproducible automated scan of one official registry."""

    registry: RegulatoryRegistry
    registry_url: str = Field(min_length=1)
    reviewer: str = Field(min_length=1)
    as_of: date
    reviewed_at: datetime
    searches: tuple[str, ...] = Field(min_length=1)
    decision_summary: str = Field(min_length=1)
    findings: tuple[RegulatoryActFinding, ...] = ()
    discovery_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    discovery_version: Literal["registry-scan-v1"] | None = None
    search_start: date | None = None

    @model_validator(mode="after")
    def validate_review(self) -> Self:
        parsed = urlsplit(self.registry_url)
        if parsed.scheme != "https" or parsed.hostname not in _REGISTRY_HOSTS[self.registry]:
            raise ValueError("registry review URL must match its official HTTPS registry")
        if self.reviewed_at.tzinfo is None or self.reviewed_at.utcoffset() is None:
            raise ValueError("registry review time must be timezone-aware")
        if not self.searches or any(not item.strip() for item in self.searches):
            raise ValueError("registry review must record its searches")
        if (self.discovery_sha256 is None) != (self.discovery_version is None):
            raise ValueError("automated registry review requires a digest and version together")
        if self.discovery_version is not None and self.search_start is None:
            raise ValueError("automated registry review requires its search start date")
        return self


class RegulatoryCoverageEvidence(DomainModel):
    """Versioned evidence binding source checks and later-act review to one date."""

    evidence_version: Literal[1] = 1
    anchor_id: str = Field(min_length=1)
    anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparison_as_of: date
    checked_at: datetime
    source_checks: tuple[RegulatorySourceDigestCheck, ...]
    registry_reviews: tuple[RegulatoryRegistryReview, ...]

    @model_validator(mode="after")
    def validate_coverage_evidence(self) -> Self:
        if self.checked_at.tzinfo is None or self.checked_at.utcoffset() is None:
            raise ValueError("regulatory coverage evidence time must be timezone-aware")
        source_ids = tuple(item.source_id for item in self.source_checks)
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("regulatory source checks must be unique")
        registries = tuple(item.registry for item in self.registry_reviews)
        if len(set(registries)) != len(registries):
            raise ValueError("regulatory registry reviews must be unique")
        if any(item.as_of != self.comparison_as_of for item in self.registry_reviews):
            raise ValueError("registry reviews must attest the requested comparison date")
        if any(item.checked_at > self.checked_at for item in self.source_checks) or any(
            item.reviewed_at > self.checked_at for item in self.registry_reviews
        ):
            raise ValueError("coverage evidence time cannot precede a recorded check or review")
        return self

    @property
    def evidence_id(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(
            payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        )
        return f"regulatory-coverage:{hashlib.sha256(encoded.encode('utf-8')).hexdigest()}"


class RegulatoryAnchorRefreshResult(DomainModel):
    """Live source refresh result, reusable by an offline caller after persistence."""

    as_of: date
    anchor: DomesticProjectionAnchor
    coverage_evidence: RegulatoryCoverageEvidence
    ready: bool
    checks: dict[str, bool]
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_refresh(self) -> Self:
        if self.coverage_evidence.anchor_id != self.anchor.anchor_id:
            raise ValueError("refresh evidence must identify its anchor")
        if self.coverage_evidence.comparison_as_of != self.as_of:
            raise ValueError("refresh evidence must identify its comparison date")
        if self.ready != all(self.checks.values()):
            raise ValueError("anchor refresh readiness must match all checks")
        return self


class GmeDefinitionCheck(DomainModel):
    """Digest evidence for the official definition of the PUN index."""

    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def require_aware_check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("GME definition check time must be timezone-aware")
        return value


def projection_anchor_digest(anchor: DomesticProjectionAnchor) -> str:
    """Return a canonical SHA-256 digest for the complete typed anchor artifact."""
    payload = anchor.model_dump(mode="json")
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ProjectedSourceBundle(DomainModel):
    """Reusable, already acquired inputs for an offline deterministic comparison."""

    bundle_version: Literal[1] = 1
    as_of: date
    catalog: CurrentCatalogSnapshot
    market_history: GmeMarketHistory
    anchor: DomesticProjectionAnchor
    coverage_evidence: RegulatoryCoverageEvidence
    gme_definition_check: GmeDefinitionCheck | None = None

    @model_validator(mode="after")
    def validate_bundle_dates(self) -> Self:
        if self.market_history.as_of != self.as_of:
            raise ValueError("source bundle market history must match its comparison date")
        if self.coverage_evidence.comparison_as_of != self.as_of:
            raise ValueError("source bundle coverage must match its comparison date")
        return self


class ProjectedSourcePreflightResult(DomainModel):
    """Typed readiness of external source snapshots before customer calculation."""

    ready: bool
    as_of: date
    checks: dict[str, bool] = Field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_ready(self) -> Self:
        if self.ready != all(self.checks.values()):
            raise ValueError("source preflight readiness must match all source checks")
        return self


class ProjectedDomesticComparisonRequest(DomainModel):
    """Domestic BT input for a twelve-month estimate based on historical months."""

    current_contract: Contract
    consumption: ConsumptionProfile
    as_of: date
    classification: SupplyClassification
    eligibility: PortalEligibilityProfile
    continuation_assumption: bool = False

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        classification = self.classification
        supply = self.current_contract.supply
        if (
            classification.voltage_level != VoltageLevel.BT
            or classification.usage_code != "domestic"
            or classification.residential is None
            or supply.residential != classification.residential
            or supply.commodity.value != "electricity"
            or self.eligibility.voltage_level != VoltageLevel.BT
            or not self.eligibility.domestic
        ):
            raise ValueError("projected comparison requires domestic electricity BT")
        validate_consumption_periods(self.consumption, self.as_of)
        return self


class ProjectedComparisonAssumptions(DomainModel):
    """Machine-readable projection choices echoed on every Platform result."""

    historical_consumption_period: DatePeriod
    historical_market_period: DatePeriod
    future_period: DatePeriod
    consumption_method: Literal["repeat_previous_twelve_months"] = "repeat_previous_twelve_months"
    calendar_month_matching: Literal["same_calendar_month_number"] = "same_calendar_month_number"
    index_multipliers: tuple[Decimal, Decimal, Decimal] = (
        Decimal("0.80"),
        Decimal("1.00"),
        Decimal("1.20"),
    )
    regulatory_anchor_date: date
    regulatory_application: Literal["freeze_verified_anchor_for_future"] = (
        "freeze_verified_anchor_for_future"
    )
    fiscal_application: Literal["recalculate_per_future_month"] = "recalculate_per_future_month"
    current_contract_continued: bool
    future_external_items_repeated: Literal[False] = False
    future_values_verified: Literal[False] = False
    costs_are_estimates: Literal[True] = True

    @field_validator("index_multipliers", mode="before")
    @classmethod
    def validate_index_multipliers(cls, value: object) -> tuple[Decimal, Decimal, Decimal]:
        if not isinstance(value, (tuple, list)) or len(value) != 3:
            raise ValueError("projection requires the three fixed index multipliers")
        values = tuple(strict_decimal(item) for item in value)
        expected = (Decimal("0.80"), Decimal("1.00"), Decimal("1.20"))
        if values != expected:
            raise ValueError("projection index multipliers must be 0.80, 1.00 and 1.20")
        return values[0], values[1], values[2]


class ProjectedVerifiedInputs(DomainModel):
    """Provenance for official snapshots that feed a projected result."""

    catalog_snapshot_id: str = Field(min_length=1)
    catalog_dataset_date: date
    catalog_status: VerificationStatus
    market_status: VerificationStatus
    market_index_code: Literal["PUN"] = "PUN"
    market_period: DatePeriod
    market_report_provenance: tuple[Provenance, ...]
    regulatory_anchor_id: str = Field(min_length=1)
    regulatory_status: VerificationStatus
    regulatory_anchor_date: date
    regulatory_provenance: tuple[Provenance, ...]
    comparison_as_of: date | None = None
    regulatory_anchor_validity: DatePeriod | None = None
    regulatory_coverage_as_of: date | None = None
    regulatory_coverage_id: str | None = None

    @model_validator(mode="after")
    def validate_verified_sources(self) -> Self:
        if self.catalog_status != VerificationStatus.VERIFIED:
            raise ValueError("projected result requires a verified Portale Offerte catalog")
        comparison_as_of = self.comparison_as_of or self.regulatory_anchor_date
        if self.catalog_dataset_date > comparison_as_of:
            raise ValueError("projected catalog cannot be newer than the comparison date")
        if self.market_status != VerificationStatus.VERIFIED:
            raise ValueError("projected result requires verified GME history")
        if len(self.market_report_provenance) != 12:
            raise ValueError("projected result requires twelve source-backed market reports")
        if any(
            item.source != "GME" or not item.sha256 or item.effective_period is None
            for item in self.market_report_provenance
        ):
            raise ValueError("market provenance requires GME source, digest and month")
        recent = _recent_months(comparison_as_of)
        expected_periods = tuple(
            DatePeriod(start=month, end=_add_months(month, 1)) for month in recent
        )
        if (
            tuple(item.effective_period for item in self.market_report_provenance)
            != expected_periods
        ):
            raise ValueError("market provenance must cover the exact recent twelve-month window")
        expected_market_period = DatePeriod(start=recent[0], end=comparison_as_of.replace(day=1))
        if self.market_period != expected_market_period:
            raise ValueError("market period must match the exact recent twelve-month window")
        for item, month in zip(self.market_report_provenance, recent, strict=True):
            expected_identifier = f"MGP-monthly-baseload:{month:%Y-%m}"
            expected_url_suffix = f"{month:%Y%m}_Dati_di_sintesi_mensile.pdf"
            if (
                item.source_identifier != expected_identifier
                or item.url is None
                or not item.url.startswith("https://gme.mercatoelettrico.org/Portals/0/")
                or not item.url.endswith(expected_url_suffix)
            ):
                raise ValueError("market provenance must identify the matching official GME report")
        if self.regulatory_status != VerificationStatus.VERIFIED:
            raise ValueError("projected result requires a verified regulatory anchor")
        if not self.regulatory_provenance:
            raise ValueError("regulatory provenance is required")
        if (self.regulatory_coverage_as_of is None) != (self.regulatory_coverage_id is None):
            raise ValueError("regulatory coverage date and evidence id must be supplied together")
        if self.regulatory_coverage_as_of is not None:
            if self.regulatory_anchor_date > comparison_as_of:
                raise ValueError("regulatory anchor snapshot cannot postdate the comparison")
            if self.regulatory_coverage_as_of != comparison_as_of:
                raise ValueError("regulatory coverage must attest the comparison date")
            if self.regulatory_anchor_validity is None or not (
                self.regulatory_anchor_validity.start
                <= comparison_as_of
                < self.regulatory_anchor_validity.end
            ):
                raise ValueError("regulatory anchor validity must cover the comparison date")
        return self


class ProjectedScenarioComparison(DomainModel):
    scenario: CurrentScenario
    index_multiplier: Decimal
    comparison: PortalComparisonResult

    @field_validator("index_multiplier", mode="before")
    @classmethod
    def validate_multiplier(cls, value: object) -> Decimal:
        return strict_decimal(value)


class ProjectedDomesticComparisonResult(DomainModel):
    """All three future scenarios; every returned monetary result is an estimate."""

    result_id: str = Field(pattern=r"^projected-domestic-comparison:[0-9a-f]{64}$")
    as_of: date
    period: DatePeriod
    assumptions: ProjectedComparisonAssumptions
    verified_inputs: ProjectedVerifiedInputs
    scenarios: tuple[ProjectedScenarioComparison, ...]
    status: Literal["estimated"] = "estimated"

    @model_validator(mode="after")
    def validate_projection(self) -> Self:
        if self.period != future_period(self.as_of):
            raise ValueError("projected result must cover the next twelve complete months")
        if self.assumptions.future_period != self.period:
            raise ValueError("projection assumptions must name the result horizon")
        if self.verified_inputs.regulatory_coverage_as_of is None:
            # V1 results used one date for the anchor and comparison. Keep them readable.
            if (
                self.assumptions.regulatory_anchor_date != self.as_of
                or self.verified_inputs.regulatory_anchor_date != self.as_of
            ):
                raise ValueError("legacy projected results must keep the anchor comparison date")
        elif (
            self.verified_inputs.comparison_as_of != self.as_of
            or self.verified_inputs.regulatory_coverage_as_of != self.as_of
            or self.assumptions.regulatory_anchor_date
            != self.verified_inputs.regulatory_anchor_date
        ):
            raise ValueError("projected result must preserve separate anchor and comparison dates")
        history = _recent_months(self.as_of)
        expected_history = DatePeriod(start=history[0], end=self.as_of.replace(day=1))
        if (
            self.assumptions.historical_consumption_period != expected_history
            or self.assumptions.historical_market_period != expected_history
            or self.verified_inputs.market_period != expected_history
        ):
            raise ValueError("historical assumptions must preserve the exact source window")
        expected = (
            CurrentScenario.LOW_INDEX,
            CurrentScenario.BASE,
            CurrentScenario.HIGH_INDEX,
        )
        if tuple(item.scenario for item in self.scenarios) != expected:
            raise ValueError("projected result must contain low, base and high scenarios in order")
        if (
            tuple(item.index_multiplier for item in self.scenarios)
            != self.assumptions.index_multipliers
        ):
            raise ValueError("scenario multipliers must match the typed projection assumptions")
        for scenario in self.scenarios:
            comparison = scenario.comparison.comparison_result
            if comparison.current_pricing.period != self.period:
                raise ValueError("projected pricing must cover the declared estimate period")
            if (
                comparison.current_billing is None
                or comparison.current_billing.bill.period != self.period
            ):
                raise ValueError("projected billing must cover the declared estimate period")
        return self

    @property
    def base(self) -> PortalComparisonResult:
        return self.scenarios[1].comparison


class ProjectedDomesticPreflightResult(DomainModel):
    """Readiness result separates official source availability from calculation."""

    ready: bool
    official_data_ready: bool
    projection_calculable: bool
    as_of: date
    period: DatePeriod
    checks: dict[str, bool] = Field(default_factory=dict)
    reason_codes: tuple[str, ...] = ()
    normalized_offer_count: int = Field(default=0, ge=0)
    horizon_eligible_offer_count: int = Field(default=0, ge=0)
    excluded_offer_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_readiness(self) -> Self:
        if self.ready != (self.official_data_ready and self.projection_calculable):
            raise ValueError("preflight readiness must distinguish source and calculation gates")
        if self.period != future_period(self.as_of):
            raise ValueError("preflight horizon must cover the next twelve complete months")
        return self


class ProjectedDomesticRecommendationRequest(DomainModel):
    comparison: ProjectedDomesticComparisonResult
    preferences: RecommendationPreferences = Field(default_factory=RecommendationPreferences)
    minimum_savings: Decimal = Decimal("50.00")
    minimum_percentage_savings: Decimal = Decimal("5")

    @field_validator("minimum_savings", "minimum_percentage_savings", mode="before")
    @classmethod
    def validate_thresholds(cls, value: object) -> Decimal:
        result = strict_decimal(value)
        if result < 0:
            raise ValueError("recommendation thresholds must be non-negative")
        return result


class ProjectedDomesticRecommendationResult(DomainModel):
    recommendation: Recommendation
    comparison_id: str = Field(min_length=1)
    scenario: Literal["base"] = "base"
    based_on_estimates: Literal[True] = True
    assumptions: ProjectedComparisonAssumptions


def validate_consumption_periods(profile: ConsumptionProfile, as_of: date) -> None:
    """Require exactly twelve complete recent months for every supplied band."""
    cutoff = as_of.replace(day=1)
    absolute = cutoff.year * 12 + cutoff.month - 1
    start_absolute = absolute - 12
    year, month0 = divmod(start_absolute, 12)
    expected_start = date(year, month0 + 1, 1)
    if not profile.buckets:
        raise ValueError(
            "projected comparison requires twelve complete monthly consumption buckets"
        )
    months_by_band: dict[str, list[tuple[int, int]]] = {}
    for bucket in profile.buckets:
        start = bucket.interval.start
        end = bucket.interval.end
        if (
            bucket.granularity.value != "month"
            or start.day != 1
            or end.day != 1
            or start != datetime(start.year, start.month, 1, tzinfo=start.tzinfo)
            or end != datetime(end.year, end.month, 1, tzinfo=end.tzinfo)
        ):
            raise ValueError("projected consumption requires complete monthly buckets")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("projected consumption buckets must be timezone-aware")
        next_month = _add_months(start.date(), 1)
        if (end.year, end.month) != (next_month.year, next_month.month):
            raise ValueError("projected consumption bucket must cover one calendar month")
        if start.date() < expected_start or start.date() >= cutoff:
            raise ValueError("projected consumption must cover only the latest twelve months")
        if bucket.band not in {"ALL", "F1", "F2", "F3"}:
            raise ValueError("projected consumption supports total or F1/F2/F3 monthly buckets")
        months_by_band.setdefault(bucket.band, []).append((start.year, start.month))
    expected = set()
    for offset in range(12):
        index = start_absolute + offset
        target_year, target_month0 = divmod(index, 12)
        expected.add((target_year, target_month0 + 1))
    for band, actual in months_by_band.items():
        if len(actual) != 12 or set(actual) != expected:
            raise ValueError(f"consumption band {band} must contain the exact twelve recent months")
    if "ALL" in months_by_band and len(months_by_band) > 1:
        raise ValueError("consumption cannot mix total and named-band buckets")


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, 1)


def _recent_months(as_of: date) -> tuple[date, ...]:
    cutoff = as_of.replace(day=1)
    return tuple(_add_months(cutoff, offset) for offset in range(-12, 0))


__all__ = [
    "GmeDefinitionCheck",
    "ProjectedComparisonAssumptions",
    "ProjectedDomesticComparisonRequest",
    "ProjectedDomesticComparisonResult",
    "ProjectedDomesticPreflightResult",
    "ProjectedDomesticRecommendationRequest",
    "ProjectedDomesticRecommendationResult",
    "ProjectedScenarioComparison",
    "ProjectedSourceBundle",
    "ProjectedSourcePreflightResult",
    "ProjectedVerifiedInputs",
    "RegulatoryActFinding",
    "RegulatoryCoverageEvidence",
    "RegulatoryRegistry",
    "RegulatoryRegistryReview",
    "RegulatorySourceDigestCheck",
    "projection_anchor_digest",
    "validate_consumption_periods",
]
