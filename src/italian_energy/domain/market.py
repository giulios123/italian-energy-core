"""Market index definitions and time series data."""

from __future__ import annotations

from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.money import RateUnit
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import Granularity, TimeInterval


class MarketIndex(DomainModel):
    code: str = Field(min_length=1)
    name: str = Field(min_length=1)
    unit: RateUnit
    granularity: Granularity
    timezone: str = "Europe/Rome"
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_timezone(self) -> MarketIndex:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(f"unknown timezone: {self.timezone}") from exc
        return self


class MarketDataPoint(DomainModel):
    index_code: str = Field(min_length=1)
    interval: TimeInterval
    value: Decimal
    provenance: tuple[Provenance, ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> Decimal:
        return strict_decimal(value)


class MarketData(DomainModel):
    indexes: tuple[MarketIndex, ...] = ()
    points: tuple[MarketDataPoint, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> MarketData:
        codes = [index.code for index in self.indexes]
        if len(codes) != len(set(codes)):
            raise ValueError("market index codes must be unique")
        known = set(codes)
        seen: set[tuple[str, object, object]] = set()
        for point in self.points:
            if point.index_code not in known:
                raise ValueError(f"market point references unknown index {point.index_code}")
            key = (point.index_code, point.interval.start, point.interval.end)
            if key in seen:
                raise ValueError("duplicate market data interval")
            seen.add(key)
        return self
