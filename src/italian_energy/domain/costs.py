"""Cost breakdown and bill/result models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.money import Money, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import DatePeriod


class CostComponent(DomainModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: Money
    quantity: Decimal | None = None
    unit_rate: UnitRate | None = None
    period: DatePeriod
    formula: str = Field(min_length=1)
    provenance: tuple[Provenance, ...] = ()

    @field_validator("quantity", mode="before")
    @classmethod
    def validate_quantity(cls, value: object) -> Decimal | None:
        return None if value is None else strict_decimal(value)


class CostBreakdown(DomainModel):
    components: tuple[CostComponent, ...] = ()
    total: Money
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_total(self) -> CostBreakdown:
        computed = sum(
            (component.amount for component in self.components), Money(amount=Decimal(0))
        )
        if computed != self.total:
            raise ValueError("cost breakdown total must equal component sum")
        return self


class PricingResult(DomainModel):
    pricing_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    period: DatePeriod
    breakdown: CostBreakdown
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()


class Bill(DomainModel):
    bill_id: str = Field(min_length=1)
    contract_id: str = Field(min_length=1)
    period: DatePeriod
    breakdown: CostBreakdown
    issued_at: datetime | None = None
    declared_total: Money | None = None
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_declared_total(self) -> Bill:
        if self.declared_total is not None and self.declared_total != self.breakdown.total:
            raise ValueError("declared bill total must equal breakdown total")
        return self
