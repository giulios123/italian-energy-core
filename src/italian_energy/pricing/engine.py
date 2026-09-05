"""Pricing Engine protocol and immutable request."""

from __future__ import annotations

from typing import Protocol

from italian_energy.domain.base import DomainModel
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import PricingResult
from italian_energy.domain.market import MarketData
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import RegulatoryParameter
from italian_energy.domain.time import DatePeriod


class PricingRequest(DomainModel):
    contract: Contract
    consumption: ConsumptionProfile
    period: DatePeriod
    market_data: MarketData | None = None
    regulatory_parameters: tuple[RegulatoryParameter, ...] = ()


class PricingEngine(Protocol):
    def price(self, request: PricingRequest) -> PricingResult:
        """Return a deterministic cost breakdown for the request."""
