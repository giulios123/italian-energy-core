"""Billing Engine protocol and immutable request."""

from __future__ import annotations

from typing import Protocol

from italian_energy.domain.base import DomainModel
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import (
    Bill,
    BillingResult,
    ExternalBillItem,
    ObservedBill,
    PricingResult,
)
from italian_energy.domain.money import RoundingPolicy
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import BillingMeasure, RegulatoryRuleSet, SupplyClassification
from italian_energy.domain.time import DatePeriod


class BillingRequest(DomainModel):
    contract: Contract
    consumption: ConsumptionProfile
    period: DatePeriod
    observed_bill: Bill | ObservedBill | None = None
    pricing_result: PricingResult | None = None
    classification: SupplyClassification | None = None
    rule_set: RegulatoryRuleSet | None = None
    measurements: tuple[BillingMeasure, ...] = ()
    external_items: tuple[ExternalBillItem, ...] = ()
    rounding_policy: RoundingPolicy | None = None


class BillingEngine(Protocol):
    def bill(self, request: BillingRequest) -> Bill:
        """Produce or reconstruct a bill for the requested period."""


class DetailedBillingEngine(Protocol):
    def evaluate(self, request: BillingRequest) -> BillingResult:
        """Produce a bill and an optional explicit reconciliation report."""
