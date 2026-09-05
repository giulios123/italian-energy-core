"""Supply point model."""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from italian_energy.domain.base import DomainModel
from italian_energy.domain.money import Power


class Commodity(StrEnum):
    ELECTRICITY = "electricity"


class SupplyPoint(DomainModel):
    supply_id: str = Field(min_length=1)
    commodity: Commodity = Commodity.ELECTRICITY
    market_zone: str = Field(min_length=1)
    contracted_power: Power | None = None
    residential: bool | None = None
