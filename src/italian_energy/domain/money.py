"""Money and unit-aware economic value objects."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_DOWN, ROUND_FLOOR, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal


class Currency(StrEnum):
    EUR = "EUR"


class RateUnit(StrEnum):
    EUR_PER_KWH = "EUR/kWh"
    EUR_PER_MWH = "EUR/MWh"
    EUR_PER_KVARH = "EUR/kvarh"
    EUR_PER_KW_DAY = "EUR/kW/day"
    EUR_PER_KW_MONTH = "EUR/kW/month"
    EUR_PER_KW_YEAR = "EUR/kW/year"
    EUR_PER_DAY = "EUR/day"
    EUR_PER_MONTH = "EUR/month"
    EUR_PER_YEAR = "EUR/year"
    PERCENT = "%"


class RoundingMode(StrEnum):
    HALF_EVEN = "ROUND_HALF_EVEN"
    HALF_UP = "ROUND_HALF_UP"
    DOWN = "ROUND_DOWN"
    FLOOR = "ROUND_FLOOR"
    CEILING = "ROUND_CEILING"

    @property
    def decimal_mode(self) -> str:
        return {
            RoundingMode.HALF_EVEN: ROUND_HALF_EVEN,
            RoundingMode.HALF_UP: ROUND_HALF_UP,
            RoundingMode.DOWN: ROUND_DOWN,
            RoundingMode.FLOOR: ROUND_FLOOR,
            RoundingMode.CEILING: ROUND_CEILING,
        }[self]


class RoundingPolicy(DomainModel):
    """Explicit monetary rounding policy; never applied implicitly."""

    scale: int = Field(ge=0, le=8)
    mode: RoundingMode = RoundingMode.HALF_EVEN


class Money(DomainModel):
    amount: Decimal
    currency: Currency = Currency.EUR

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Decimal:
        return strict_decimal(value)

    def _same_currency(self, other: Money) -> None:
        if self.currency != other.currency:
            raise ValueError("money values must use the same currency")

    def __add__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(amount=self.amount + other.amount, currency=self.currency)

    def __sub__(self, other: Money) -> Money:
        self._same_currency(other)
        return Money(amount=self.amount - other.amount, currency=self.currency)

    def round(self, policy: RoundingPolicy) -> Money:
        quantum = Decimal(1).scaleb(-policy.scale)
        return Money(
            amount=self.amount.quantize(quantum, rounding=policy.mode.decimal_mode),
            currency=self.currency,
        )


class EnergyQuantity(DomainModel):
    kwh: Decimal = Field(ge=0)

    @field_validator("kwh", mode="before")
    @classmethod
    def validate_kwh(cls, value: Any) -> Decimal:
        return strict_decimal(value)


class Power(DomainModel):
    kw: Decimal = Field(ge=0)

    @field_validator("kw", mode="before")
    @classmethod
    def validate_kw(cls, value: Any) -> Decimal:
        return strict_decimal(value)


class UnitRate(DomainModel):
    amount: Decimal
    unit: RateUnit

    @field_validator("amount", mode="before")
    @classmethod
    def validate_amount(cls, value: Any) -> Decimal:
        return strict_decimal(value)
