"""Deterministic comparison result models and protocol."""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from pydantic import Field, field_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import PricingResult
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import Money
from italian_energy.domain.offer import Contract, Offer
from italian_energy.domain.time import DatePeriod


class ComparisonRequest(DomainModel):
    current_contract: Contract
    consumption: ConsumptionProfile
    available_offers: tuple[Offer, ...]
    period: DatePeriod
    market_data: MarketData | None = None


class AlternativePricing(DomainModel):
    offer_id: str = Field(min_length=1)
    pricing: PricingResult
    absolute_difference: Money
    percentage_difference: Decimal | None = None

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


class ComparisonEngine(Protocol):
    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        """Compare deterministic pricing results for current and alternative offers."""
