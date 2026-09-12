"""Adapter from verified Portale Offerte results to Recommendation evidence."""

from __future__ import annotations

from italian_energy.domain.offer import Offer
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.tariff import Tariff
from italian_energy.portal_offers.models import PortalComparisonResult
from italian_energy.recommendation import (
    CandidateDiscountProfile,
    CandidateTariffKind,
    PriceRisk,
    RecommendationCandidateEvidence,
    RecommendationError,
    RecommendationPreferences,
    RecommendationRequest,
    indexed_tariff_is_capped,
)


class PortalRecommendationAdapter:
    """Build generic recommendation input without re-running economic engines."""

    def build_request(
        self,
        result: PortalComparisonResult,
        preferences: RecommendationPreferences | None = None,
    ) -> RecommendationRequest:
        import_result = result.import_result
        if (
            import_result.status != VerificationStatus.VERIFIED
            or import_result.snapshot.status != VerificationStatus.VERIFIED
        ):
            raise RecommendationError("verified portal import is required for recommendation")
        normalized = {item.offer.offer_id: item for item in import_result.normalized}
        evidence: list[RecommendationCandidateEvidence] = []
        for alternative in result.comparison_result.alternatives:
            item = normalized.get(alternative.offer_id)
            if item is None:
                # The generic engine will expose this as an isolated missing-evidence exclusion.
                continue
            provenance = item.offer.provenance or item.source_record.source_provenance
            status = import_result.status if provenance else VerificationStatus.UNVERIFIED
            evidence.append(
                RecommendationCandidateEvidence(
                    offer_id=item.offer.offer_id,
                    tariff_kind=_tariff_kind(item.offer),
                    price_risk=_price_risk(item.offer.tariff),
                    contract_duration_months=item.source_record.duration_months,
                    discount_profile=_discount_profile(item.offer),
                    status=status,
                    provenance=provenance,
                )
            )
        return RecommendationRequest(
            comparison=result.comparison_result,
            preferences=preferences or RecommendationPreferences(),
            candidate_evidence=tuple(evidence),
        )


def _tariff_kind(offer: Offer) -> CandidateTariffKind:
    return CandidateTariffKind(offer.tariff.kind)


def _price_risk(tariff: Tariff) -> PriceRisk:
    if tariff.kind == "fixed":
        return PriceRisk.FIXED
    return (
        PriceRisk.INDEXED_CAPPED if indexed_tariff_is_capped(tariff) else PriceRisk.INDEXED_UNCAPPED
    )


def _discount_profile(offer: Offer) -> CandidateDiscountProfile:
    discounts = offer.tariff.discounts
    if not discounts:
        return CandidateDiscountProfile.NONE
    validity = offer.tariff.validity
    if any(
        rule.validity is not None
        and (rule.validity.start > validity.start or rule.validity.end < validity.end)
        for rule in discounts
    ):
        return CandidateDiscountProfile.TEMPORARY
    return CandidateDiscountProfile.PERMANENT
