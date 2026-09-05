"""Civil and market time primitives."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum

from pydantic import model_validator

from italian_energy.domain.base import DomainModel


class Granularity(StrEnum):
    QUARTER_HOUR = "quarter_hour"
    HOUR = "hour"
    DAY = "day"
    MONTH = "month"
    BILLING_PERIOD = "billing_period"
    YEAR = "year"


class DatePeriod(DomainModel):
    start: date
    end: date

    @model_validator(mode="after")
    def validate_order(self) -> DatePeriod:
        if self.end <= self.start:
            raise ValueError("date period must have end > start")
        return self


class TimeInterval(DomainModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def validate_interval(self) -> TimeInterval:
        if self.start.tzinfo is None or self.start.utcoffset() is None:
            raise ValueError("time interval start must be timezone-aware")
        if self.end.tzinfo is None or self.end.utcoffset() is None:
            raise ValueError("time interval end must be timezone-aware")
        if self.end <= self.start:
            raise ValueError("time interval must have end > start")
        return self
