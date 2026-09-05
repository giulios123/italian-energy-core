"""Billing Engine protocol and immutable request."""

from __future__ import annotations

from typing import Protocol

from italian_energy.domain.base import DomainModel
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import Bill
from italian_energy.domain.offer import Contract
from italian_energy.domain.time import DatePeriod


class BillingRequest(DomainModel):
    contract: Contract
    consumption: ConsumptionProfile
    period: DatePeriod
    observed_bill: Bill | None = None


class BillingEngine(Protocol):
    def bill(self, request: BillingRequest) -> Bill:
        """Produce or reconstruct a bill for the requested period."""
