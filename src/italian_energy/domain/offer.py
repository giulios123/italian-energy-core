"""Commercial offer and accepted contract snapshots."""

from __future__ import annotations

from datetime import date

from pydantic import Field

from italian_energy.domain.base import DomainModel
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import Tariff
from italian_energy.domain.time import DatePeriod


class Offer(DomainModel):
    offer_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    subscription_period: DatePeriod
    tariff: Tariff
    conditions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()


class Contract(DomainModel):
    contract_id: str = Field(min_length=1)
    supply: SupplyPoint
    tariff: Tariff
    validity: DatePeriod
    source_offer_id: str | None = None
    signed_on: date | None = None
    conditions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()
