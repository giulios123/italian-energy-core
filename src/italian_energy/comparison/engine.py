"""Deterministic comparison of normalized electricity offers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date
from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator, model_validator

from italian_energy.billing.coverage import (
    BillingCoverageDecision,
    BillingCoverageMatrix,
    CoverageLevel,
)
from italian_energy.billing.engine import BillingRequest
from italian_energy.billing.regulatory import (
    BillingError,
    RegulatoryBillingEngine,
    select_regulatory_profile,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import BillingResult, ExternalBillItem, PricingResult
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import Money, RoundingPolicy
from italian_energy.domain.offer import Contract, Offer
from italian_energy.domain.regulatory import (
    BillingMeasure,
    RegulatoryRuleSet,
    SupplyClassification,
    VerificationStatus,
)
from italian_energy.domain.time import DatePeriod
from italian_energy.pricing.engine import PricingRequest
from italian_energy.pricing.fixed import FixedPricingEngine, FixedPricingError
from italian_energy.pricing.indexed import IndexedPricingEngine, IndexedPricingError


class ComparisonError(ValueError):
    """Raised when a comparison cannot be evaluated safely."""


class OfferExclusionCode(StrEnum):
    NOT_CURRENT = "not_current"
    SAME_AS_CURRENT = "same_as_current"
    PERIOD_NOT_COVERED = "period_not_covered"
    PRICING_FAILED = "pricing_failed"
    BILLING_FAILED = "billing_failed"


class OfferExclusion(DomainModel):
    """A candidate excluded without invalidating the comparison baseline."""

    offer_id: str = Field(min_length=1)
    code: OfferExclusionCode
    detail: str = Field(min_length=1)


class ComparisonContext(DomainModel):
    current_contract: Contract
    consumption: ConsumptionProfile
    period: DatePeriod
    as_of: date
    classification: SupplyClassification
    rule_set: RegulatoryRuleSet
    coverage_matrix: BillingCoverageMatrix
    rounding_policy: RoundingPolicy
    percentage_rounding_policy: RoundingPolicy
    market_data: MarketData | None = None
    measurements: tuple[BillingMeasure, ...] = ()
    external_items: tuple[ExternalBillItem, ...] = ()

    def to_request(self, available_offers: tuple[Offer, ...]) -> ComparisonRequest:
        return ComparisonRequest(
            **self.model_dump(mode="python"), available_offers=available_offers
        )


class ComparisonRequest(ComparisonContext):
    available_offers: tuple[Offer, ...]

    @model_validator(mode="after")
    def validate_request(self) -> ComparisonRequest:
        ids = [offer.offer_id for offer in self.available_offers]
        if len(ids) != len(set(ids)):
            raise ValueError("comparison offer ids must be unique")
        keys = [item.reconciliation_key for item in self.external_items]
        if len(keys) != len(set(keys)):
            raise ValueError("comparison external item keys must be unique")
        for item in self.external_items:
            if item.status != VerificationStatus.VERIFIED or not item.provenance:
                raise ValueError("comparison external item must be verified and have provenance")
            if item.period.start < self.period.start or item.period.end > self.period.end:
                raise ValueError("comparison external item period must be contained in period")
        return self


class AlternativePricing(DomainModel):
    """All-in pricing result for one offer, kept compatible with the v0.1 shape."""

    offer_id: str = Field(min_length=1)
    pricing: PricingResult
    absolute_difference: Money
    percentage_difference: Decimal | None = None
    candidate_contract_id: str | None = None
    billing: BillingResult | None = None
    comparable_total: Money | None = None
    savings: Money | None = None

    @field_validator("percentage_difference", mode="before")
    @classmethod
    def validate_percentage(cls, value: object) -> Decimal | None:
        return None if value is None else strict_decimal(value)


class ComparisonResult(DomainModel):
    comparison_id: str = Field(min_length=1)
    current_contract_id: str = Field(min_length=1)
    current_pricing: PricingResult
    alternatives: tuple[AlternativePricing, ...] = ()
    ranking: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    current_billing: BillingResult | None = None
    current_comparable_total: Money | None = None
    coverage: BillingCoverageDecision | None = None
    excluded_offers: tuple[OfferExclusion, ...] = ()
    excluded_external_items: tuple[ExternalBillItem, ...] = ()
    excluded_external_total: Money = Money(amount=Decimal(0))

    @model_validator(mode="after")
    def validate_alternatives(self) -> ComparisonResult:
        ids = [alternative.offer_id for alternative in self.alternatives]
        if len(ids) != len(set(ids)):
            raise ValueError("comparison alternative offer ids must be unique")
        if tuple(ids) != self.ranking:
            raise ValueError("comparison ranking must match alternative order")
        return self


class ComparisonEngine(Protocol):
    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        """Compare deterministic pricing results for current and alternative offers."""


class DeterministicComparisonEngine:
    """Compare normalized offers using the fixed, indexed and billing engines."""

    def __init__(self) -> None:
        self._fixed = FixedPricingEngine()
        self._indexed = IndexedPricingEngine()
        self._billing = RegulatoryBillingEngine()

    def preflight(self, context: ComparisonContext) -> BillingCoverageDecision:
        """Validate candidate-independent comparison inputs before catalog acquisition."""
        return self._validate_global_request(context)

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        coverage = self._validate_global_request(request)
        try:
            current_pricing = self._price(request, request.current_contract)
        except (FixedPricingError, IndexedPricingError, ComparisonError) as exc:
            raise ComparisonError(f"current pricing failed: {exc}") from exc
        try:
            current_billing = self._bill(request, request.current_contract, current_pricing)
        except BillingError as exc:
            raise ComparisonError(f"current billing failed: {exc}") from exc
        current_total = current_billing.bill.breakdown.total
        warnings = list(current_pricing.warnings) + list(current_billing.warnings)
        if current_total.amount <= 0:
            warnings.append("current comparable total is non-positive; percentage is unavailable")

        alternatives: list[AlternativePricing] = []
        exclusions: list[OfferExclusion] = []
        current_source_offer = request.current_contract.source_offer_id
        for offer in sorted(request.available_offers, key=lambda item: item.offer_id):
            exclusion = self._candidate_exclusion(request, offer, current_source_offer)
            if exclusion is not None:
                exclusions.append(exclusion)
                continue
            candidate_contract = self._candidate_contract(request, offer)
            try:
                pricing = self._price(request, candidate_contract)
            except (FixedPricingError, IndexedPricingError, ComparisonError) as exc:
                exclusions.append(
                    OfferExclusion(
                        offer_id=offer.offer_id,
                        code=OfferExclusionCode.PRICING_FAILED,
                        detail=str(exc),
                    )
                )
                continue
            try:
                billing = self._bill(request, candidate_contract, pricing)
            except BillingError as exc:
                exclusions.append(
                    OfferExclusion(
                        offer_id=offer.offer_id,
                        code=OfferExclusionCode.BILLING_FAILED,
                        detail=str(exc),
                    )
                )
                continue
            total = billing.bill.breakdown.total
            savings = current_total - total
            percentage = self._percentage_difference(
                savings, current_total, request.percentage_rounding_policy
            )
            alternatives.append(
                AlternativePricing(
                    offer_id=offer.offer_id,
                    pricing=pricing,
                    absolute_difference=self._absolute_difference(current_total, total),
                    percentage_difference=percentage,
                    candidate_contract_id=candidate_contract.contract_id,
                    billing=billing,
                    comparable_total=total,
                    savings=savings,
                )
            )

        alternatives.sort(key=lambda item: (self._alternative_total(item), item.offer_id))
        ranking = tuple(item.offer_id for item in alternatives)
        exclusions.sort(key=lambda item: item.offer_id)
        external_items = tuple(
            sorted(request.external_items, key=lambda item: item.reconciliation_key)
        )
        assumptions = [
            "commercial eligibility is prevalidated by the caller",
            *current_pricing.assumptions,
            *current_billing.assumptions,
        ]
        if external_items:
            assumptions.append(
                "external bill items are excluded from comparable totals and ranking"
            )
        return ComparisonResult(
            comparison_id=self._comparison_id(request),
            current_contract_id=request.current_contract.contract_id,
            current_pricing=current_pricing,
            alternatives=tuple(alternatives),
            ranking=ranking,
            assumptions=_unique_strings(assumptions),
            warnings=_unique_strings(warnings),
            current_billing=current_billing,
            current_comparable_total=current_total,
            coverage=coverage,
            excluded_offers=tuple(exclusions),
            excluded_external_items=external_items,
            excluded_external_total=self._sum_external(external_items),
        )

    def _validate_global_request(self, request: ComparisonContext) -> BillingCoverageDecision:
        if not (
            request.current_contract.validity.start
            <= request.as_of
            < request.current_contract.validity.end
        ):
            raise ComparisonError("as_of is outside current contract validity")
        if request.rule_set.status != VerificationStatus.VERIFIED:
            raise ComparisonError("comparison ruleset is not verified")
        if not request.rule_set.provenance:
            raise ComparisonError("comparison ruleset provenance is missing")
        try:
            decision = request.coverage_matrix.resolve(
                request.classification,
                request.rule_set.ruleset_id,
                request.period,
                minimum_level=CoverageLevel.RULESET_VERIFIED,
            )
        except ValueError as exc:
            raise ComparisonError(f"comparison coverage validation failed: {exc}") from exc
        if decision.profile_code != request.classification.contract_type_code:
            raise ComparisonError("comparison coverage profile does not match classification")
        try:
            select_regulatory_profile(
                request.rule_set,
                request.classification,
                BillingRequest(
                    contract=request.current_contract,
                    consumption=request.consumption,
                    period=request.period,
                    pricing_result=None,
                    classification=request.classification,
                    rule_set=request.rule_set,
                    measurements=request.measurements,
                    rounding_policy=request.rounding_policy,
                ),
            )
        except BillingError as exc:
            raise ComparisonError(
                f"comparison regulatory profile validation failed: {exc}"
            ) from exc
        return decision

    def _candidate_exclusion(
        self,
        request: ComparisonRequest,
        offer: Offer,
        current_source_offer: str | None,
    ) -> OfferExclusion | None:
        if not (offer.subscription_period.start <= request.as_of < offer.subscription_period.end):
            return OfferExclusion(
                offer_id=offer.offer_id,
                code=OfferExclusionCode.NOT_CURRENT,
                detail="offer subscription period does not contain as_of",
            )
        if current_source_offer is not None and offer.offer_id == current_source_offer:
            return OfferExclusion(
                offer_id=offer.offer_id,
                code=OfferExclusionCode.SAME_AS_CURRENT,
                detail="offer is the source offer of the current contract",
            )
        if (
            request.period.start < offer.tariff.validity.start
            or request.period.end > offer.tariff.validity.end
        ):
            return OfferExclusion(
                offer_id=offer.offer_id,
                code=OfferExclusionCode.PERIOD_NOT_COVERED,
                detail="offer tariff validity does not contain requested period",
            )
        return None

    def _price(self, request: ComparisonRequest, contract: Contract) -> PricingResult:
        pricing_request = PricingRequest(
            contract=contract,
            consumption=request.consumption,
            period=request.period,
            rounding_policy=request.rounding_policy,
            market_data=request.market_data if contract.tariff.kind == "indexed" else None,
        )
        tariff = contract.tariff
        try:
            if tariff.kind == "fixed":
                return self._fixed.price(pricing_request)
            if tariff.kind == "indexed":
                return self._indexed.price(pricing_request)
        except (FixedPricingError, IndexedPricingError):
            raise
        raise ComparisonError(f"unsupported tariff kind {tariff.kind}")

    def _bill(
        self,
        request: ComparisonRequest,
        contract: Contract,
        pricing: PricingResult,
    ) -> BillingResult:
        return self._billing.evaluate(
            BillingRequest(
                contract=contract,
                consumption=request.consumption,
                period=request.period,
                pricing_result=pricing,
                classification=request.classification,
                rule_set=request.rule_set,
                measurements=request.measurements,
                rounding_policy=request.rounding_policy,
                external_items=(),
            )
        )

    @staticmethod
    def _candidate_contract(request: ComparisonRequest, offer: Offer) -> Contract:
        payload = {
            "offer": offer.model_dump(mode="json"),
            "supply": request.current_contract.supply.model_dump(mode="json"),
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()
        return Contract(
            contract_id=f"comparison-contract:{digest}",
            supply=request.current_contract.supply,
            tariff=offer.tariff,
            validity=offer.tariff.validity,
            source_offer_id=offer.offer_id,
            conditions=offer.conditions,
            provenance=offer.provenance,
        )

    @staticmethod
    def _comparison_id(request: ComparisonRequest) -> str:
        payload = request.model_dump(mode="json")
        payload["available_offers"] = sorted(
            payload["available_offers"], key=lambda item: item["offer_id"]
        )
        payload["external_items"] = sorted(
            payload["external_items"], key=lambda item: item["reconciliation_key"]
        )
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return f"comparison:{hashlib.sha256(encoded.encode()).hexdigest()}"

    @staticmethod
    def _percentage_difference(
        savings: Money, current_total: Money, policy: RoundingPolicy
    ) -> Decimal | None:
        if current_total.amount <= 0:
            return None
        with localcontext() as context:
            context.prec = max(28, len(str(current_total.amount)) + len(str(savings.amount)) + 16)
            raw = savings.amount / current_total.amount * Decimal(100)
            return Money(amount=raw).round(policy).amount

    @staticmethod
    def _absolute_difference(current_total: Money, alternative_total: Money) -> Money:
        difference = current_total - alternative_total
        return Money(amount=abs(difference.amount), currency=difference.currency)

    @staticmethod
    def _alternative_total(item: AlternativePricing) -> Decimal:
        if item.comparable_total is None:
            return item.pricing.breakdown.total.amount
        return item.comparable_total.amount

    @staticmethod
    def _sum_external(items: Iterable[ExternalBillItem]) -> Money:
        return sum((item.amount for item in items), Money(amount=Decimal(0)))


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return tuple(result)
