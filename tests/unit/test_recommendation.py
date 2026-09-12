from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from italian_energy.comparison import AlternativePricing, ComparisonResult
from italian_energy.domain.costs import (
    Bill,
    BillingResult,
    CostBreakdown,
    CostComponent,
    ExternalBillItem,
    PricingResult,
)
from italian_energy.domain.formula import ClampPrice, IndexReference
from italian_energy.domain.money import Money, RateUnit, UnitRate
from italian_energy.domain.offer import Offer
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import BillingCategory, VerificationStatus
from italian_energy.domain.tariff import (
    BandFormula,
    BandPrice,
    ChargeBasis,
    ChargeRule,
    FixedTariff,
    IndexedTariff,
)
from italian_energy.domain.time import DatePeriod, Granularity
from italian_energy.portal_offers.models import (
    NormalizedPortalOffer,
    PortalCatalog,
    PortalComparisonResult,
    PortalFileSnapshot,
    PortalOfferRecord,
    PortalOffersImportResult,
    PortalOffersSnapshot,
    PortalOfferType,
    PortalSourceRole,
)
from italian_energy.portal_offers.recommendation import PortalRecommendationAdapter
from italian_energy.recommendation import (
    CandidateDiscountProfile,
    CandidateTariffKind,
    DeterministicRecommendationEngine,
    PriceRisk,
    Recommendation,
    RecommendationCandidate,
    RecommendationCandidateEvidence,
    RecommendationDecision,
    RecommendationError,
    RecommendationExclusionCode,
    RecommendationPreferences,
    RecommendationReasonCode,
    RecommendationRequest,
    RecommendationTariffPreference,
    TemporaryDiscountPolicy,
    VolatilityTolerance,
    indexed_tariff_is_capped,
)

PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
PROVENANCE = (
    Provenance(
        source="fixture",
        source_identifier="recommendation",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    ),
)


def _pricing(contract_id: str, total: str) -> PricingResult:
    amount = Money(amount=Decimal(total))
    return PricingResult(
        pricing_id=f"pricing-{contract_id}",
        contract_id=contract_id,
        period=PERIOD,
        breakdown=CostBreakdown(
            components=(
                CostComponent(
                    code="total",
                    description="total",
                    amount=amount,
                    period=PERIOD,
                    formula="fixture",
                ),
            ),
            total=amount,
        ),
    )


def _billing(contract_id: str, total: str) -> BillingResult:
    amount = Money(amount=Decimal(total))
    return BillingResult(
        billing_id=f"billing-{contract_id}",
        bill=Bill(
            bill_id=f"bill-{contract_id}",
            contract_id=contract_id,
            period=PERIOD,
            breakdown=CostBreakdown(
                components=(
                    CostComponent(
                        code="total",
                        description="total",
                        amount=amount,
                        period=PERIOD,
                        formula="fixture",
                    ),
                ),
                total=amount,
            ),
        ),
    )


def _comparison(*, alternatives: tuple[tuple[str, str, str], ...]) -> ComparisonResult:
    current = Money(amount=Decimal("100.00"))
    converted = []
    for offer_id, total, savings in alternatives:
        converted.append(
            AlternativePricing(
                offer_id=offer_id,
                pricing=_pricing(f"contract-{offer_id}", total),
                absolute_difference=Money(amount=abs(current.amount - Decimal(total))),
                percentage_difference=Decimal(savings),
                candidate_contract_id=f"contract-{offer_id}",
                billing=_billing(f"contract-{offer_id}", total),
                comparable_total=Money(amount=Decimal(total)),
                savings=Money(amount=Decimal(savings)),
            )
        )
    return ComparisonResult(
        comparison_id="comparison-fixture",
        current_contract_id="current-contract",
        current_pricing=_pricing("current-contract", "100.00"),
        alternatives=tuple(converted),
        ranking=tuple(item[0] for item in alternatives),
        current_billing=_billing("current-contract", "100.00"),
        current_comparable_total=current,
    )


def _evidence(
    offer_id: str,
    *,
    kind: CandidateTariffKind = CandidateTariffKind.FIXED,
    risk: PriceRisk = PriceRisk.FIXED,
    months: int | None = 12,
    discount: CandidateDiscountProfile = CandidateDiscountProfile.NONE,
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> RecommendationCandidateEvidence:
    return RecommendationCandidateEvidence(
        offer_id=offer_id,
        tariff_kind=kind,
        price_risk=risk,
        contract_duration_months=months,
        discount_profile=discount,
        status=status,
        provenance=PROVENANCE if status == VerificationStatus.VERIFIED else (),
    )


def test_recommendation_selects_cheapest_candidate_above_threshold() -> None:
    request = RecommendationRequest(
        comparison=_comparison(
            alternatives=(("cheap", "88.00", "12.00"), ("mid", "90.00", "10.00"))
        ),
        preferences=RecommendationPreferences(minimum_savings=Money(amount=Decimal("10.00"))),
    )

    result = DeterministicRecommendationEngine().recommend(request)

    assert result.decision == RecommendationDecision.SWITCH
    assert result.selected_offer_id == "cheap"
    assert tuple(item.offer_id for item in result.shortlist) == ("cheap", "mid")
    assert result.comparison_id == request.comparison.comparison_id


def test_preferences_filter_risk_duration_and_discount() -> None:
    comparison = _comparison(
        alternatives=(
            ("indexed", "80.00", "20.00"),
            ("short", "82.00", "18.00"),
            ("discount", "84.00", "16.00"),
            ("fixed", "90.00", "10.00"),
        )
    )
    request = RecommendationRequest(
        comparison=comparison,
        preferences=RecommendationPreferences(
            volatility_tolerance=VolatilityTolerance.LOW,
            minimum_contract_months=6,
            temporary_discount_policy=TemporaryDiscountPolicy.AVOID,
            minimum_savings=Money(amount=Decimal("5.00")),
        ),
        candidate_evidence=(
            _evidence("indexed", kind=CandidateTariffKind.INDEXED, risk=PriceRisk.INDEXED_UNCAPPED),
            _evidence("short", months=3),
            _evidence("discount", discount=CandidateDiscountProfile.TEMPORARY),
            _evidence("fixed"),
        ),
    )

    result = DeterministicRecommendationEngine().recommend(request)

    assert result.selected_offer_id == "fixed"
    assert [item.offer_id for item in result.shortlist] == ["fixed"]
    assert {item.offer_id: item.code for item in result.excluded_candidates} == {
        "indexed": RecommendationExclusionCode.VOLATILITY_EXCEEDED,
        "short": RecommendationExclusionCode.DURATION_TOO_SHORT,
        "discount": RecommendationExclusionCode.DISCOUNT_POLICY_MISMATCH,
    }


def test_medium_volatility_requires_an_outer_cap_and_missing_evidence_isolated() -> None:
    comparison = _comparison(
        alternatives=(("capped", "90.00", "10.00"), ("missing", "80.00", "20.00"))
    )
    request = RecommendationRequest(
        comparison=comparison,
        preferences=RecommendationPreferences(
            volatility_tolerance=VolatilityTolerance.MEDIUM,
            minimum_savings=Money(amount=Decimal("1.00")),
        ),
        candidate_evidence=(
            _evidence("capped", kind=CandidateTariffKind.INDEXED, risk=PriceRisk.INDEXED_CAPPED),
        ),
    )

    result = DeterministicRecommendationEngine().recommend(request)

    assert result.selected_offer_id == "capped"
    assert result.excluded_candidates[0].offer_id == "missing"
    assert result.excluded_candidates[0].code == RecommendationExclusionCode.MISSING_EVIDENCE


def test_unverified_evidence_is_excluded_and_legacy_fields_are_supported() -> None:
    request = RecommendationRequest(
        comparison=_comparison(alternatives=(("indexed", "80.00", "20.00"),)),
        preferences=RecommendationPreferences(
            fixed_preference=True,
            minimum_savings=Money(amount=Decimal("1.00")),
        ),
        candidate_evidence=(
            _evidence(
                "indexed",
                kind=CandidateTariffKind.INDEXED,
                risk=PriceRisk.INDEXED_UNCAPPED,
                status=VerificationStatus.UNVERIFIED,
            ),
        ),
    )

    result = DeterministicRecommendationEngine().recommend(request)

    assert result.decision == RecommendationDecision.STAY_CURRENT
    assert result.excluded_candidates[0].code == RecommendationExclusionCode.EVIDENCE_NOT_VERIFIED


def test_threshold_is_inclusive_and_missing_threshold_keeps_current() -> None:
    comparison = _comparison(alternatives=(("equal", "90.00", "10.00"),))
    equal = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=RecommendationPreferences(minimum_savings=Money(amount=Decimal("10.00"))),
        )
    )
    missing = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(comparison=comparison)
    )

    assert equal.selected_offer_id == "equal"
    assert missing.decision == RecommendationDecision.STAY_CURRENT
    assert missing.selected_offer_id is None


def test_recommendation_id_is_invariant_to_evidence_order_and_comparison_is_unchanged() -> None:
    comparison = _comparison(alternatives=(("a", "90.00", "10.00"), ("b", "91.00", "9.00")))
    prefs = RecommendationPreferences(minimum_savings=Money(amount=Decimal("1.00")))
    first = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=prefs,
            candidate_evidence=(_evidence("a"), _evidence("b")),
        )
    )
    second = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=prefs,
            candidate_evidence=(_evidence("b"), _evidence("a")),
        )
    )

    assert first.recommendation_id == second.recommendation_id
    assert first.selected_offer_id == "a"
    assert comparison.ranking == ("a", "b")


def test_incomplete_comparison_is_rejected() -> None:
    incomplete = _comparison(alternatives=(("a", "90.00", "10.00"),)).model_copy(
        update={"current_comparable_total": None}
    )

    with pytest.raises(RecommendationError, match="incomplete"):
        DeterministicRecommendationEngine().recommend(RecommendationRequest(comparison=incomplete))


def test_preference_conflicts_and_decimal_validation_are_rejected() -> None:
    with pytest.raises(ValidationError):
        RecommendationPreferences(
            fixed_preference=True,
            tariff_preference=RecommendationTariffPreference.INDEXED,
        )
    with pytest.raises(ValidationError):
        RecommendationPreferences(minimum_savings=Money(amount=Decimal("-1")))
    with pytest.raises((ValidationError, TypeError)):
        from italian_energy.recommendation import RecommendationCandidate

        RecommendationCandidate(
            offer_id="a",
            comparable_total=Money(amount=Decimal("1")),
            savings=Money(amount=Decimal("1")),
            percentage_savings=1.1,  # type: ignore[arg-type]
        )


def test_request_rejects_duplicate_or_unknown_evidence() -> None:
    comparison = _comparison(alternatives=(("a", "90.00", "10.00"),))
    with pytest.raises(ValidationError, match="unique"):
        RecommendationRequest(
            comparison=comparison,
            candidate_evidence=(_evidence("a"), _evidence("a")),
        )
    with pytest.raises(ValidationError, match="unknown"):
        RecommendationRequest(
            comparison=comparison,
            candidate_evidence=(_evidence("other"),),
        )


def test_evidence_validators_reject_inconsistent_risk_and_provenance() -> None:
    with pytest.raises(ValidationError, match="fixed price risk"):
        _evidence("a", risk=PriceRisk.INDEXED_CAPPED)
    with pytest.raises(ValidationError, match="verified candidate evidence"):
        RecommendationCandidateEvidence(
            offer_id="a",
            tariff_kind=CandidateTariffKind.FIXED,
            price_risk=PriceRisk.FIXED,
            discount_profile=CandidateDiscountProfile.NONE,
            status=VerificationStatus.VERIFIED,
        )
    with pytest.raises(ValidationError, match="indexed candidate evidence"):
        RecommendationCandidateEvidence(
            offer_id="a",
            tariff_kind=CandidateTariffKind.INDEXED,
            price_risk=PriceRisk.FIXED,
            discount_profile=CandidateDiscountProfile.NONE,
        )


def test_each_structured_exclusion_code_is_deterministic() -> None:
    comparison = _comparison(
        alternatives=(
            ("tariff", "90.00", "10.00"),
            ("unknown-duration", "91.00", "9.00"),
            ("unknown-discount", "92.00", "8.00"),
            ("below", "99.00", "1.00"),
            ("uncapped", "89.00", "11.00"),
        )
    )
    request = RecommendationRequest(
        comparison=comparison,
        preferences=RecommendationPreferences(
            tariff_preference=RecommendationTariffPreference.FIXED,
            volatility_tolerance=VolatilityTolerance.MEDIUM,
            minimum_contract_months=6,
            temporary_discount_policy=TemporaryDiscountPolicy.REQUIRE,
            minimum_savings=Money(amount=Decimal("5.00")),
        ),
        candidate_evidence=(
            _evidence("tariff", kind=CandidateTariffKind.INDEXED, risk=PriceRisk.INDEXED_CAPPED),
            _evidence("unknown-duration", months=None, discount=CandidateDiscountProfile.TEMPORARY),
            _evidence("unknown-discount", discount=CandidateDiscountProfile.UNKNOWN),
            _evidence("below", discount=CandidateDiscountProfile.TEMPORARY),
            _evidence(
                "uncapped",
                kind=CandidateTariffKind.INDEXED,
                risk=PriceRisk.INDEXED_UNCAPPED,
                discount=CandidateDiscountProfile.TEMPORARY,
            ),
        ),
    )

    result = DeterministicRecommendationEngine().recommend(request)

    assert {item.offer_id: item.code for item in result.excluded_candidates} == {
        "tariff": RecommendationExclusionCode.TARIFF_PREFERENCE_MISMATCH,
        "unknown-duration": RecommendationExclusionCode.DURATION_UNKNOWN,
        "unknown-discount": RecommendationExclusionCode.DISCOUNT_UNKNOWN,
        "below": RecommendationExclusionCode.MINIMUM_SAVINGS_NOT_MET,
        "uncapped": RecommendationExclusionCode.TARIFF_PREFERENCE_MISMATCH,
    }


def test_indexed_preference_and_low_tolerance_conflict() -> None:
    with pytest.raises(ValidationError, match="indexed tariff preference"):
        RecommendationPreferences(
            tariff_preference=RecommendationTariffPreference.INDEXED,
            volatility_tolerance=VolatilityTolerance.LOW,
        )
    with pytest.raises(ValidationError, match="discount policy"):
        RecommendationPreferences(
            require_temporary_discounts=True,
            temporary_discount_policy=TemporaryDiscountPolicy.AVOID,
        )


def test_comparison_consistency_failures_are_global() -> None:
    engine = DeterministicRecommendationEngine()
    comparison = _comparison(alternatives=(("a", "90.00", "10.00"),))
    current_mismatch = comparison.model_copy(
        update={"current_billing": _billing("current-contract", "99.00")}
    )
    alternative = comparison.alternatives[0]
    alternative_mismatch = comparison.model_copy(
        update={
            "alternatives": (
                alternative.model_copy(update={"comparable_total": Money(amount=Decimal("91"))}),
            )
        }
    )
    savings_mismatch = comparison.model_copy(
        update={
            "alternatives": (
                alternative.model_copy(update={"savings": Money(amount=Decimal("9"))}),
            )
        }
    )
    with pytest.raises(RecommendationError, match="current total"):
        engine.recommend(RecommendationRequest(comparison=current_mismatch))
    with pytest.raises(RecommendationError, match="total is inconsistent"):
        engine.recommend(RecommendationRequest(comparison=alternative_mismatch))
    with pytest.raises(RecommendationError, match="savings are inconsistent"):
        engine.recommend(RecommendationRequest(comparison=savings_mismatch))
    missing_total = comparison.model_copy(
        update={"alternatives": (alternative.model_copy(update={"comparable_total": None}),)}
    )
    missing_savings = comparison.model_copy(
        update={"alternatives": (alternative.model_copy(update={"savings": None}),)}
    )
    with pytest.raises(RecommendationError, match="economic data"):
        engine.recommend(RecommendationRequest(comparison=missing_total))
    with pytest.raises(RecommendationError, match="economic data"):
        engine.recommend(RecommendationRequest(comparison=missing_savings))
    with pytest.raises(RecommendationError, match="total is missing"):
        engine._required_total("a", None)
    with pytest.raises(RecommendationError, match="savings are missing"):
        engine._required_savings("a", None)
    with pytest.raises(RecommendationError, match="savings are missing"):
        engine._exclude("a", None, None, RecommendationPreferences())


def test_recommendation_model_invariants_and_indexed_risk_note() -> None:
    candidate = RecommendationCandidate(
        offer_id="a",
        comparable_total=Money(amount=Decimal("90")),
        savings=Money(amount=Decimal("10")),
        reason_codes=(RecommendationReasonCode.MEETS_POLICY,),
    )
    with pytest.raises(ValidationError, match="selected offer"):
        Recommendation(
            recommendation_id="rec",
            comparison_id="cmp",
            decision=RecommendationDecision.SWITCH,
            selected_offer_id="other",
            shortlist=(candidate,),
        )
    with pytest.raises(ValidationError, match="stay-current"):
        Recommendation(
            recommendation_id="rec",
            comparison_id="cmp",
            decision=RecommendationDecision.STAY_CURRENT,
            selected_offer_id="a",
        )
    indexed = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=_comparison(alternatives=(("a", "90.00", "10.00"),)),
            preferences=RecommendationPreferences(minimum_savings=Money(amount=Decimal("1"))),
            candidate_evidence=(
                _evidence("a", kind=CandidateTariffKind.INDEXED, risk=PriceRisk.INDEXED_UNCAPPED),
            ),
        )
    )
    assert indexed.risk_notes


def test_medium_uncapped_and_discount_policy_exclusions() -> None:
    comparison = _comparison(
        alternatives=(
            ("uncapped", "90.00", "10.00"),
            ("permanent", "91.00", "9.00"),
            ("unknown", "92.00", "8.00"),
        )
    )
    medium = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=RecommendationPreferences(
                volatility_tolerance=VolatilityTolerance.MEDIUM,
                minimum_savings=Money(amount=Decimal("1")),
            ),
            candidate_evidence=(
                _evidence(
                    "uncapped",
                    kind=CandidateTariffKind.INDEXED,
                    risk=PriceRisk.INDEXED_UNCAPPED,
                ),
                _evidence("permanent"),
                _evidence("unknown"),
            ),
        )
    )
    assert medium.excluded_candidates[0].code == RecommendationExclusionCode.VOLATILITY_EXCEEDED
    require = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=RecommendationPreferences(
                require_temporary_discounts=True,
                minimum_savings=Money(amount=Decimal("1")),
            ),
            candidate_evidence=(
                _evidence(
                    "uncapped",
                    kind=CandidateTariffKind.INDEXED,
                    risk=PriceRisk.INDEXED_UNCAPPED,
                ),
                _evidence("permanent"),
                _evidence("unknown", discount=CandidateDiscountProfile.UNKNOWN),
            ),
        )
    )
    assert {item.offer_id: item.code for item in require.excluded_candidates} == {
        "uncapped": RecommendationExclusionCode.DISCOUNT_POLICY_MISMATCH,
        "permanent": RecommendationExclusionCode.DISCOUNT_POLICY_MISMATCH,
        "unknown": RecommendationExclusionCode.DISCOUNT_UNKNOWN,
    }
    avoid = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=RecommendationPreferences(
                temporary_discount_policy=TemporaryDiscountPolicy.AVOID,
                minimum_savings=Money(amount=Decimal("1")),
            ),
            candidate_evidence=(_evidence("unknown", discount=CandidateDiscountProfile.UNKNOWN),),
        )
    )
    assert (
        next(item.code for item in avoid.excluded_candidates if item.offer_id == "unknown")
        == RecommendationExclusionCode.DISCOUNT_UNKNOWN
    )


def test_external_items_are_preserved_as_recommendation_assumption() -> None:
    item = ExternalBillItem(
        code="tv",
        description="TV",
        category=BillingCategory.TV_FEE,
        amount=Money(amount=Decimal("10")),
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=PROVENANCE,
        reconciliation_key="tv",
    )
    comparison = _comparison(alternatives=(("a", "90.00", "10.00"),)).model_copy(
        update={"excluded_external_items": (item,)}
    )
    result = DeterministicRecommendationEngine().recommend(
        RecommendationRequest(
            comparison=comparison,
            preferences=RecommendationPreferences(minimum_savings=Money(amount=Decimal("1"))),
        )
    )
    assert any("external items" in item for item in result.assumptions)


def test_indexed_cap_classifier_is_conservative() -> None:
    indexed = IndexedTariff(
        tariff_id="indexed",
        validity=PERIOD,
        granularity=Granularity.MONTH,
        formulas=(
            BandFormula(
                band="ALL",
                expression=ClampPrice(
                    operand=IndexReference(
                        index_code="PUN",
                        unit=RateUnit.EUR_PER_KWH,
                        granularity=Granularity.MONTH,
                    ),
                    cap=UnitRate(amount=Decimal("0.30"), unit=RateUnit.EUR_PER_KWH),
                ),
            ),
        ),
    )
    assert indexed_tariff_is_capped(indexed)
    assert not indexed_tariff_is_capped(
        FixedTariff(
            tariff_id="fixed",
            validity=PERIOD,
            prices=(
                BandPrice(
                    band="ALL",
                    rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
                ),
            ),
        )
    )


def _fixed_offer(offer_id: str, *, temporary: bool = False) -> Offer:
    discount: tuple[ChargeRule, ...] = ()
    if temporary:
        discount = (
            ChargeRule(
                code="temporary",
                description="temporary",
                basis=ChargeBasis.PER_YEAR,
                value=UnitRate(amount=Decimal("-10"), unit=RateUnit.EUR_PER_YEAR),
                discount=True,
                validity=DatePeriod(start=date(2026, 1, 1), end=date(2026, 4, 1)),
                provenance=PROVENANCE,
            ),
        )
    return Offer(
        offer_id=offer_id,
        supplier_id="supplier",
        name=offer_id,
        subscription_period=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        tariff=FixedTariff(
            tariff_id=f"tariff-{offer_id}",
            validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
            prices=(
                BandPrice(
                    band="ALL",
                    rate=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
                ),
            ),
            discounts=discount,
            provenance=PROVENANCE,
        ),
        provenance=PROVENANCE,
    )


def _portal_result(offer: Offer, *, duration: int = 12) -> PortalComparisonResult:
    source_record = PortalOfferRecord(
        catalog=PortalCatalog.MARKET_FREE,
        source_offer_id=offer.offer_id.removeprefix("portal:market_free:"),
        supplier_id="supplier",
        name=offer.name,
        offer_type=PortalOfferType.FIXED,
        subscription_period=offer.subscription_period,
        tariff_validity=offer.tariff.validity,
        duration_months=duration,
        customer_type="01",
        source_provenance=PROVENANCE,
    )
    files = tuple(
        PortalFileSnapshot(
            role=role,
            catalog=PortalCatalog.MARKET_FREE
            if "market_free" in role.value
            else PortalCatalog.PLACET,
            original_url=f"https://example.test/{role.value}",
            final_url=f"https://example.test/{role.value}",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            content_type="text/csv",
            size=0,
            sha256="0" * 64,
            status=VerificationStatus.VERIFIED,
        )
        for role in (
            PortalSourceRole.MARKET_FREE_OFFERS,
            PortalSourceRole.MARKET_FREE_PARAMETERS,
            PortalSourceRole.PLACET_OFFERS,
            PortalSourceRole.PLACET_PARAMETERS,
        )
    )
    snapshot = PortalOffersSnapshot(
        dataset_date=date(2026, 1, 1),
        files=files,
        snapshot_id="portal-snapshot:" + "1" * 64,
        status=VerificationStatus.VERIFIED,
        parser_version="test",
    )
    import_result = PortalOffersImportResult(
        snapshot=snapshot,
        status=VerificationStatus.VERIFIED,
        import_id="portal-import:" + "2" * 64,
        records=(source_record,),
        normalized=(NormalizedPortalOffer(offer=offer, source_record=source_record),),
        eligible_offers=(offer,),
        received_count=1,
        eligible_count=1,
        excluded_count=0,
    )
    comparison = _comparison(alternatives=((offer.offer_id, "90.00", "10.00"),))
    return PortalComparisonResult(
        portal_result_id="portal-comparison:" + "3" * 64,
        import_result=import_result,
        comparison_result=comparison,
    )


def test_portal_adapter_derives_structured_evidence_without_text_interpretation() -> None:
    offer = _fixed_offer("portal:market_free:offer-1", temporary=True)
    request = PortalRecommendationAdapter().build_request(_portal_result(offer))

    assert len(request.candidate_evidence) == 1
    evidence = request.candidate_evidence[0]
    assert evidence.offer_id == offer.offer_id
    assert evidence.tariff_kind == CandidateTariffKind.FIXED
    assert evidence.contract_duration_months == 12
    assert evidence.discount_profile == CandidateDiscountProfile.TEMPORARY
    assert evidence.status == VerificationStatus.VERIFIED


def test_portal_adapter_handles_unverified_import_missing_mapping_and_discount_profiles() -> None:
    offer = _fixed_offer("portal:market_free:offer-2")
    result = _portal_result(offer)
    with pytest.raises(RecommendationError, match="verified portal import"):
        PortalRecommendationAdapter().build_request(
            result.model_copy(
                update={
                    "import_result": result.import_result.model_copy(
                        update={"status": VerificationStatus.UNVERIFIED}
                    )
                }
            )
        )
    other_comparison = _comparison(alternatives=(("other", "90.00", "10.00"),))
    missing_comparison = result.comparison_result.model_copy(
        update={"alternatives": other_comparison.alternatives, "ranking": ("other",)}
    )
    missing = PortalRecommendationAdapter().build_request(
        result.model_copy(update={"comparison_result": missing_comparison})
    )
    assert missing.candidate_evidence == ()
    no_discount = PortalRecommendationAdapter().build_request(result)
    assert no_discount.candidate_evidence[0].discount_profile == CandidateDiscountProfile.NONE

    temporary = _fixed_offer("portal:market_free:offer-3", temporary=True)
    temporary_rule = temporary.tariff.discounts[0]
    permanent_tariff = temporary.tariff.model_copy(
        update={
            "discounts": (
                temporary_rule.model_copy(update={"validity": temporary.tariff.validity}),
            )
        }
    )
    permanent = temporary.model_copy(
        update={"offer_id": "portal:market_free:offer-3", "tariff": permanent_tariff}
    )
    permanent_result = _portal_result(permanent)
    assert (
        PortalRecommendationAdapter()
        .build_request(permanent_result)
        .candidate_evidence[0]
        .discount_profile
        == CandidateDiscountProfile.PERMANENT
    )


def test_portal_adapter_classifies_indexed_and_uses_source_provenance_fallback() -> None:
    indexed = Offer(
        offer_id="portal:market_free:indexed-1",
        supplier_id="supplier",
        name="indexed",
        subscription_period=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
        tariff=IndexedTariff(
            tariff_id="indexed-1",
            validity=DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
            granularity=Granularity.MONTH,
            formulas=(
                BandFormula(
                    band="ALL",
                    expression=IndexReference(
                        index_code="PUN",
                        unit=RateUnit.EUR_PER_KWH,
                        granularity=Granularity.MONTH,
                    ),
                ),
            ),
        ),
    )
    request = PortalRecommendationAdapter().build_request(_portal_result(indexed))
    assert request.candidate_evidence[0].price_risk == PriceRisk.INDEXED_UNCAPPED
    assert request.candidate_evidence[0].status == VerificationStatus.VERIFIED
