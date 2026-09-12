"""Deterministic, consultive interpretation of comparison results."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from italian_energy.comparison.engine import ComparisonResult
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.formula import ClampPrice
from italian_energy.domain.money import Money
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import VerificationStatus


class RecommendationError(ValueError):
    """Raised when a recommendation cannot be evaluated safely."""


class RecommendationTariffPreference(StrEnum):
    ANY = "any"
    FIXED = "fixed"
    INDEXED = "indexed"


class VolatilityTolerance(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TemporaryDiscountPolicy(StrEnum):
    ANY = "any"
    REQUIRE = "require"
    AVOID = "avoid"


class CandidateTariffKind(StrEnum):
    FIXED = "fixed"
    INDEXED = "indexed"


class PriceRisk(StrEnum):
    FIXED = "fixed"
    INDEXED_CAPPED = "indexed_capped"
    INDEXED_UNCAPPED = "indexed_uncapped"


class CandidateDiscountProfile(StrEnum):
    NONE = "none"
    PERMANENT = "permanent"
    TEMPORARY = "temporary"
    UNKNOWN = "unknown"


class RecommendationDecision(StrEnum):
    SWITCH = "switch"
    STAY_CURRENT = "stay_current"


class RecommendationReasonCode(StrEnum):
    MEETS_POLICY = "meets_policy"
    MEETS_MINIMUM_SAVINGS = "meets_minimum_savings"
    SELECTED_LOWEST_COMPARABLE_COST = "selected_lowest_comparable_cost"
    NO_SWITCH_THRESHOLD = "no_switch_threshold"
    NO_ELIGIBLE_ALTERNATIVE = "no_eligible_alternative"


class RecommendationExclusionCode(StrEnum):
    MISSING_EVIDENCE = "missing_evidence"
    EVIDENCE_NOT_VERIFIED = "evidence_not_verified"
    TARIFF_PREFERENCE_MISMATCH = "tariff_preference_mismatch"
    VOLATILITY_EXCEEDED = "volatility_exceeded"
    DURATION_UNKNOWN = "duration_unknown"
    DURATION_TOO_SHORT = "duration_too_short"
    DISCOUNT_UNKNOWN = "discount_unknown"
    DISCOUNT_POLICY_MISMATCH = "discount_policy_mismatch"
    MINIMUM_SAVINGS_NOT_MET = "minimum_savings_not_met"


class RecommendationCandidateEvidence(DomainModel):
    """Verified, structured facts used to apply a recommendation policy."""

    offer_id: str = Field(min_length=1)
    tariff_kind: CandidateTariffKind
    price_risk: PriceRisk
    contract_duration_months: int | None = Field(default=None, ge=1)
    discount_profile: CandidateDiscountProfile
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_risk_and_provenance(self) -> RecommendationCandidateEvidence:
        if self.tariff_kind == CandidateTariffKind.FIXED and self.price_risk != PriceRisk.FIXED:
            raise ValueError("fixed candidate evidence must have fixed price risk")
        if self.tariff_kind == CandidateTariffKind.INDEXED and self.price_risk == PriceRisk.FIXED:
            raise ValueError("indexed candidate evidence cannot have fixed price risk")
        if self.status == VerificationStatus.VERIFIED and not self.provenance:
            raise ValueError("verified candidate evidence requires provenance")
        return self


class RecommendationPreferences(DomainModel):
    """Hard, structured constraints for the deterministic selector."""

    tariff_preference: RecommendationTariffPreference = RecommendationTariffPreference.ANY
    fixed_preference: bool | None = None
    volatility_tolerance: VolatilityTolerance | None = None
    minimum_contract_months: int | None = Field(default=None, ge=0)
    temporary_discount_policy: TemporaryDiscountPolicy = TemporaryDiscountPolicy.ANY
    require_temporary_discounts: bool | None = None
    minimum_savings: Money | None = None

    @model_validator(mode="after")
    def validate_legacy_aliases(self) -> RecommendationPreferences:
        if self.fixed_preference and self.tariff_preference not in {
            RecommendationTariffPreference.ANY,
            RecommendationTariffPreference.FIXED,
        }:
            raise ValueError("fixed_preference conflicts with tariff_preference")
        if self.require_temporary_discounts and self.temporary_discount_policy not in {
            TemporaryDiscountPolicy.ANY,
            TemporaryDiscountPolicy.REQUIRE,
        }:
            raise ValueError("require_temporary_discounts conflicts with discount policy")
        if (
            self.tariff_preference == RecommendationTariffPreference.INDEXED
            and self.volatility_tolerance == VolatilityTolerance.LOW
        ):
            raise ValueError("indexed tariff preference conflicts with low volatility tolerance")
        if self.minimum_savings is not None and self.minimum_savings.amount < 0:
            raise ValueError("minimum savings must be non-negative")
        return self

    @property
    def effective_tariff_preference(self) -> RecommendationTariffPreference:
        if self.fixed_preference:
            return RecommendationTariffPreference.FIXED
        return self.tariff_preference

    @property
    def effective_discount_policy(self) -> TemporaryDiscountPolicy:
        if self.require_temporary_discounts:
            return TemporaryDiscountPolicy.REQUIRE
        return self.temporary_discount_policy

    @property
    def evidence_required(self) -> bool:
        return any(
            (
                self.effective_tariff_preference != RecommendationTariffPreference.ANY,
                self.volatility_tolerance is not None,
                self.minimum_contract_months is not None,
                self.effective_discount_policy != TemporaryDiscountPolicy.ANY,
            )
        )

    def canonical_payload(self) -> dict[str, object]:
        return {
            "tariff_preference": self.effective_tariff_preference.value,
            "volatility_tolerance": (
                None if self.volatility_tolerance is None else self.volatility_tolerance.value
            ),
            "minimum_contract_months": self.minimum_contract_months,
            "temporary_discount_policy": self.effective_discount_policy.value,
            "minimum_savings": (
                None
                if self.minimum_savings is None
                else self.minimum_savings.model_dump(mode="json")
            ),
        }


class RecommendationRequest(DomainModel):
    comparison: ComparisonResult
    preferences: RecommendationPreferences = RecommendationPreferences()
    candidate_evidence: tuple[RecommendationCandidateEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_ids(self) -> RecommendationRequest:
        ids = [item.offer_id for item in self.candidate_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("recommendation candidate evidence ids must be unique")
        comparison_ids = {item.offer_id for item in self.comparison.alternatives}
        if not set(ids).issubset(comparison_ids):
            raise ValueError("recommendation evidence references an unknown offer")
        return self


class RecommendationCandidate(DomainModel):
    offer_id: str = Field(min_length=1)
    comparable_total: Money
    savings: Money
    percentage_savings: Decimal | None = None
    evidence: RecommendationCandidateEvidence | None = None
    reason_codes: tuple[RecommendationReasonCode, ...] = ()

    @field_validator("percentage_savings", mode="before")
    @classmethod
    def validate_percentage(cls, value: object) -> Decimal | None:
        return None if value is None else strict_decimal(value)


class RecommendationExclusion(DomainModel):
    offer_id: str = Field(min_length=1)
    code: RecommendationExclusionCode
    detail: str = Field(min_length=1)


class Recommendation(DomainModel):
    recommendation_id: str = Field(min_length=1)
    comparison_id: str = Field(min_length=1)
    selected_offer_id: str | None = None
    decision: RecommendationDecision | None = None
    shortlist: tuple[RecommendationCandidate, ...] = ()
    excluded_candidates: tuple[RecommendationExclusion, ...] = ()
    reason_codes: tuple[RecommendationReasonCode, ...] = ()
    rationale: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_decision(self) -> Recommendation:
        if self.decision == RecommendationDecision.SWITCH:
            if self.selected_offer_id is None:
                raise ValueError("switch recommendation requires selected offer")
            if not self.shortlist or self.shortlist[0].offer_id != self.selected_offer_id:
                raise ValueError("selected offer must be first in recommendation shortlist")
        if (
            self.decision == RecommendationDecision.STAY_CURRENT
            and self.selected_offer_id is not None
        ):
            raise ValueError("stay-current recommendation cannot select an offer")
        return self


class RecommendationEngine(Protocol):
    def recommend(self, request: RecommendationRequest) -> Recommendation:
        """Interpret a comparison without changing its economic outputs."""


class DeterministicRecommendationEngine:
    """Apply hard preferences to an already calculated comparison."""

    def recommend(self, request: RecommendationRequest) -> Recommendation:
        self._validate_comparison(request.comparison)
        evidence = {item.offer_id: item for item in request.candidate_evidence}
        shortlist: list[RecommendationCandidate] = []
        exclusions: list[RecommendationExclusion] = []
        for alternative in request.comparison.alternatives:
            candidate_evidence = evidence.get(alternative.offer_id)
            exclusion = self._exclude(
                alternative.offer_id,
                alternative.savings,
                candidate_evidence,
                request.preferences,
            )
            if exclusion is not None:
                exclusions.append(exclusion)
                continue
            reasons = [RecommendationReasonCode.MEETS_POLICY]
            if request.preferences.minimum_savings is not None:
                reasons.append(RecommendationReasonCode.MEETS_MINIMUM_SAVINGS)
            shortlist.append(
                RecommendationCandidate(
                    offer_id=alternative.offer_id,
                    comparable_total=self._required_total(
                        alternative.offer_id, alternative.comparable_total
                    ),
                    savings=self._required_savings(alternative.offer_id, alternative.savings),
                    percentage_savings=alternative.percentage_difference,
                    evidence=candidate_evidence,
                    reason_codes=tuple(reasons),
                )
            )

        decision = RecommendationDecision.STAY_CURRENT
        selected_offer_id: str | None = None
        reason_codes: list[RecommendationReasonCode] = []
        rationale: list[str] = []
        if request.preferences.minimum_savings is None:
            reason_codes.append(RecommendationReasonCode.NO_SWITCH_THRESHOLD)
            rationale.append("stay current: minimum savings threshold is not configured")
        elif shortlist:
            decision = RecommendationDecision.SWITCH
            selected_offer_id = shortlist[0].offer_id
            shortlist[0] = shortlist[0].model_copy(
                update={
                    "reason_codes": (
                        *shortlist[0].reason_codes,
                        RecommendationReasonCode.SELECTED_LOWEST_COMPARABLE_COST,
                    )
                }
            )
            reason_codes.extend(
                (
                    RecommendationReasonCode.MEETS_MINIMUM_SAVINGS,
                    RecommendationReasonCode.SELECTED_LOWEST_COMPARABLE_COST,
                )
            )
            rationale.append(
                "switch selected: lowest comparable cost among candidates meeting the policy"
            )
        else:
            reason_codes.append(RecommendationReasonCode.NO_ELIGIBLE_ALTERNATIVE)
            rationale.append("stay current: no alternative meets the configured policy")

        assumptions = [
            "recommendation interprets comparison outputs without recalculating economics",
            "shortlist order follows the comparison ranking",
        ]
        if request.comparison.excluded_external_items:
            assumptions.append(
                "comparison external items remain excluded from recommendation economics"
            )
        risk_notes = (
            ["indexed price risk is classified structurally and is not a market forecast"]
            if any(
                item.evidence is not None
                and item.evidence.tariff_kind == CandidateTariffKind.INDEXED
                for item in shortlist
            )
            else []
        )
        return Recommendation(
            recommendation_id=self._recommendation_id(request),
            comparison_id=request.comparison.comparison_id,
            selected_offer_id=selected_offer_id,
            decision=decision,
            shortlist=tuple(shortlist),
            excluded_candidates=tuple(exclusions),
            reason_codes=tuple(_unique(reason_codes)),
            rationale=tuple(rationale),
            risk_notes=tuple(risk_notes),
            assumptions=tuple(_unique(assumptions)),
        )

    @staticmethod
    def _validate_comparison(comparison: ComparisonResult) -> None:
        if comparison.current_billing is None or comparison.current_comparable_total is None:
            raise RecommendationError("comparison economic data is incomplete")
        current_total = comparison.current_comparable_total
        if comparison.current_billing.bill.breakdown.total != current_total:
            raise RecommendationError("comparison current total is inconsistent")
        for alternative in comparison.alternatives:
            if (
                alternative.billing is None
                or alternative.comparable_total is None
                or alternative.savings is None
            ):
                raise RecommendationError("comparison economic data is incomplete")
            if alternative.billing.bill.breakdown.total != alternative.comparable_total:
                raise RecommendationError(
                    f"comparison total is inconsistent for {alternative.offer_id}"
                )
            try:
                expected_savings = current_total - alternative.comparable_total
            except ValueError as exc:
                raise RecommendationError("comparison totals use different currencies") from exc
            if expected_savings != alternative.savings:
                raise RecommendationError(
                    f"comparison savings are inconsistent for {alternative.offer_id}"
                )

    @staticmethod
    def _required_total(offer_id: str, value: Money | None) -> Money:
        if value is None:
            raise RecommendationError(f"comparison total is missing for {offer_id}")
        return value

    @staticmethod
    def _required_savings(offer_id: str, value: Money | None) -> Money:
        if value is None:
            raise RecommendationError(f"comparison savings are missing for {offer_id}")
        return value

    @classmethod
    def _exclude(
        cls,
        offer_id: str,
        savings: Money | None,
        evidence: RecommendationCandidateEvidence | None,
        preferences: RecommendationPreferences,
    ) -> RecommendationExclusion | None:
        needs_evidence = preferences.evidence_required
        if needs_evidence and evidence is None:
            return RecommendationExclusion(
                offer_id=offer_id,
                code=RecommendationExclusionCode.MISSING_EVIDENCE,
                detail="required candidate evidence is missing",
            )
        if needs_evidence and (
            evidence is None
            or evidence.status != VerificationStatus.VERIFIED
            or not evidence.provenance
        ):
            return RecommendationExclusion(
                offer_id=offer_id,
                code=RecommendationExclusionCode.EVIDENCE_NOT_VERIFIED,
                detail="required candidate evidence is not verified",
            )
        if savings is None:
            raise RecommendationError(f"comparison savings are missing for {offer_id}")
        if evidence is not None:
            preference = preferences.effective_tariff_preference
            if (
                preference != RecommendationTariffPreference.ANY
                and evidence.tariff_kind.value != preference.value
            ):
                return RecommendationExclusion(
                    offer_id=offer_id,
                    code=RecommendationExclusionCode.TARIFF_PREFERENCE_MISMATCH,
                    detail="candidate tariff type does not match tariff preference",
                )
            tolerance = preferences.volatility_tolerance
            if tolerance == VolatilityTolerance.LOW and evidence.price_risk != PriceRisk.FIXED:
                return RecommendationExclusion(
                    offer_id=offer_id,
                    code=RecommendationExclusionCode.VOLATILITY_EXCEEDED,
                    detail="candidate price risk exceeds low volatility tolerance",
                )
            if (
                tolerance == VolatilityTolerance.MEDIUM
                and evidence.price_risk == PriceRisk.INDEXED_UNCAPPED
            ):
                return RecommendationExclusion(
                    offer_id=offer_id,
                    code=RecommendationExclusionCode.VOLATILITY_EXCEEDED,
                    detail="candidate indexed price is not capped",
                )
            minimum_months = preferences.minimum_contract_months
            if minimum_months is not None:
                if evidence.contract_duration_months is None:
                    return RecommendationExclusion(
                        offer_id=offer_id,
                        code=RecommendationExclusionCode.DURATION_UNKNOWN,
                        detail="candidate contract duration is not verified",
                    )
                if evidence.contract_duration_months < minimum_months:
                    return RecommendationExclusion(
                        offer_id=offer_id,
                        code=RecommendationExclusionCode.DURATION_TOO_SHORT,
                        detail="candidate contract duration is below the minimum",
                    )
            discount_policy = preferences.effective_discount_policy
            if discount_policy == TemporaryDiscountPolicy.REQUIRE:
                if evidence.discount_profile == CandidateDiscountProfile.UNKNOWN:
                    return RecommendationExclusion(
                        offer_id=offer_id,
                        code=RecommendationExclusionCode.DISCOUNT_UNKNOWN,
                        detail="candidate discount profile is not verified",
                    )
                if evidence.discount_profile != CandidateDiscountProfile.TEMPORARY:
                    return RecommendationExclusion(
                        offer_id=offer_id,
                        code=RecommendationExclusionCode.DISCOUNT_POLICY_MISMATCH,
                        detail="candidate has no required temporary discount",
                    )
            if discount_policy == TemporaryDiscountPolicy.AVOID:
                if evidence.discount_profile == CandidateDiscountProfile.UNKNOWN:
                    return RecommendationExclusion(
                        offer_id=offer_id,
                        code=RecommendationExclusionCode.DISCOUNT_UNKNOWN,
                        detail="candidate discount profile is not verified",
                    )
                if evidence.discount_profile == CandidateDiscountProfile.TEMPORARY:
                    return RecommendationExclusion(
                        offer_id=offer_id,
                        code=RecommendationExclusionCode.DISCOUNT_POLICY_MISMATCH,
                        detail="candidate has a temporary discount",
                    )
        minimum_savings = preferences.minimum_savings
        if minimum_savings is not None:
            if savings.currency != minimum_savings.currency:
                raise RecommendationError(
                    "minimum savings and comparison savings use different currencies"
                )
            if savings.amount < minimum_savings.amount:
                return RecommendationExclusion(
                    offer_id=offer_id,
                    code=RecommendationExclusionCode.MINIMUM_SAVINGS_NOT_MET,
                    detail="candidate savings are below the configured minimum",
                )
        return None

    @staticmethod
    def _recommendation_id(request: RecommendationRequest) -> str:
        comparison = request.comparison.model_dump(mode="json")
        comparison["alternatives"] = sorted(
            comparison["alternatives"], key=lambda item: item["offer_id"]
        )
        comparison["ranking"] = [item["offer_id"] for item in comparison["alternatives"]]
        comparison["excluded_offers"] = sorted(
            comparison["excluded_offers"], key=lambda item: item["offer_id"]
        )
        payload = {
            "comparison": comparison,
            "preferences": request.preferences.canonical_payload(),
            "candidate_evidence": sorted(
                (item.model_dump(mode="json") for item in request.candidate_evidence),
                key=lambda item: item["offer_id"],
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"recommendation:{hashlib.sha256(encoded.encode()).hexdigest()}"


def has_outer_cap(expression: object) -> bool:
    """Return true only when the whole expression is capped at its root."""

    return isinstance(expression, ClampPrice) and expression.cap is not None


def indexed_tariff_is_capped(tariff: object) -> bool:
    """Conservatively classify an indexed tariff's every band formula."""

    formulas = getattr(tariff, "formulas", ())
    return bool(formulas) and all(has_outer_cap(item.expression) for item in formulas)


def _unique[T](values: list[T]) -> list[T]:
    result: list[T] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


# Short public names for consumers that do not need the Recommendation prefix.
TariffPreference = RecommendationTariffPreference
DiscountPolicy = TemporaryDiscountPolicy
