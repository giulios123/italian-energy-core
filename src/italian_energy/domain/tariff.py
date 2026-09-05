"""Fixed and indexed tariff structures."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import BandCode
from italian_energy.domain.formula import PriceExpression
from italian_energy.domain.money import Money, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import DatePeriod, Granularity


class ChargeBasis(StrEnum):
    PER_KWH = "per_kwh"
    PER_DAY = "per_day"
    PER_MONTH = "per_month"
    PER_PERIOD = "per_period"
    PER_KW_DAY = "per_kw_day"
    FLAT = "flat"
    PERCENTAGE = "percentage"


class BandPrice(DomainModel):
    band: BandCode
    rate: UnitRate


class ChargeRule(DomainModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    basis: ChargeBasis
    value: Money | UnitRate
    band: BandCode | None = None
    validity: DatePeriod | None = None
    discount: bool = False
    conditions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()


class FixedTariff(DomainModel):
    kind: Literal["fixed"] = "fixed"
    tariff_id: str = Field(min_length=1)
    validity: DatePeriod
    prices: tuple[BandPrice, ...]
    fixed_charges: tuple[ChargeRule, ...] = ()
    additional_charges: tuple[ChargeRule, ...] = ()
    discounts: tuple[ChargeRule, ...] = ()
    conditions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_bands(self) -> Self:
        if not self.prices:
            raise ValueError("fixed tariff requires at least one price")
        bands = [price.band for price in self.prices]
        if len(bands) != len(set(bands)):
            raise ValueError("tariff price bands must be unique")
        if "ALL" in bands and len(bands) > 1:
            raise ValueError("ALL cannot be mixed with named tariff bands")
        return self


class BandFormula(DomainModel):
    band: BandCode
    expression: PriceExpression


class IndexedTariff(DomainModel):
    kind: Literal["indexed"] = "indexed"
    tariff_id: str = Field(min_length=1)
    validity: DatePeriod
    granularity: Granularity
    formulas: tuple[BandFormula, ...]
    fixed_charges: tuple[ChargeRule, ...] = ()
    additional_charges: tuple[ChargeRule, ...] = ()
    discounts: tuple[ChargeRule, ...] = ()
    conditions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_bands(self) -> Self:
        if not self.formulas:
            raise ValueError("indexed tariff requires at least one formula")
        bands = [formula.band for formula in self.formulas]
        if len(bands) != len(set(bands)):
            raise ValueError("tariff formula bands must be unique")
        if "ALL" in bands and len(bands) > 1:
            raise ValueError("ALL cannot be mixed with named tariff bands")
        return self


Tariff = Annotated[FixedTariff | IndexedTariff, Field(discriminator="kind")]
