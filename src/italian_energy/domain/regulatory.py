"""Versioned regulatory parameters without embedding unverified values."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.money import Money, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import DatePeriod


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    REVIEW_REQUIRED = "review_required"
    VERIFIED = "verified"


class VoltageLevel(StrEnum):
    BT = "BT"
    MT = "MT"
    AT = "AT"
    AAT = "AAT"


class BillingCategory(StrEnum):
    SALES = "sales"
    NETWORK = "network"
    SYSTEM_CHARGES = "system_charges"
    EXCISE = "excise"
    VAT = "vat"
    BONUS = "bonus"
    OTHER = "other"
    PRODUCT_SERVICE = "product_service"
    TV_FEE = "tv_fee"


class BillingQuota(StrEnum):
    CONSUMPTION = "consumption"
    FIXED = "fixed"
    POWER = "power"
    TAX = "tax"
    PASS_THROUGH = "pass_through"


class BillingBasis(StrEnum):
    PER_KWH = "per_kwh"
    PER_KVARH = "per_kvarh"
    PER_DAY = "per_day"
    PER_MONTH = "per_month"
    PER_YEAR = "per_year"
    PER_KW_DAY = "per_kw_day"
    PER_KW_MONTH = "per_kw_month"
    PER_KW_YEAR = "per_kw_year"
    FLAT = "flat"
    PERCENTAGE = "percentage"


class ProrationPolicy(StrEnum):
    ACTUAL_DAYS = "actual_days"
    CALENDAR_MONTH_FRACTION = "calendar_month_fraction"
    CALENDAR_YEAR_FRACTION = "calendar_year_fraction"
    MONTHLY_TWELFTHS_PARTIAL_365 = "monthly_twelfths_partial_365"
    FULL_PERIOD = "full_period"


class BillingMeasureUnit(StrEnum):
    KWH = "kWh"
    KVARH = "kvarh"
    KW = "kW"


class SupplyClassification(DomainModel):
    """Explicit applicability context for a regulatory rule profile."""

    contract_type_code: str = Field(min_length=1)
    voltage_level: VoltageLevel
    usage_code: str = Field(min_length=1)
    residential: bool | None = None
    tax_profile_code: str | None = None
    eligibility_codes: tuple[str, ...] = ()


class BillingMeasure(DomainModel):
    """Verified physical measurement required by a billing rule."""

    code: str = Field(min_length=1)
    value: Decimal
    unit: BillingMeasureUnit
    period: DatePeriod
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    provenance: tuple[Provenance, ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Decimal:
        return strict_decimal(value)

    @model_validator(mode="after")
    def validate_non_negative(self) -> BillingMeasure:
        if self.value < 0:
            raise ValueError("billing measure value must be non-negative")
        return self


class RegulatoryParameter(DomainModel):
    code: str = Field(min_length=1)
    value: Decimal
    unit: str = Field(min_length=1)
    validity: DatePeriod
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    provenance: tuple[Provenance, ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Decimal:
        return strict_decimal(value)


class MeasureReference(DomainModel):
    kind: Literal["measure_reference"] = "measure_reference"
    code: str = Field(min_length=1)
    unit: BillingMeasureUnit


class QuantityConstant(DomainModel):
    kind: Literal["quantity_constant"] = "quantity_constant"
    value: Decimal

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Decimal:
        return strict_decimal(value)


class AddQuantity(DomainModel):
    kind: Literal["quantity_add"] = "quantity_add"
    left: QuantityExpression
    right: QuantityExpression


class SubtractQuantity(DomainModel):
    kind: Literal["quantity_subtract"] = "quantity_subtract"
    left: QuantityExpression
    right: QuantityExpression


class MultiplyQuantity(DomainModel):
    kind: Literal["quantity_multiply"] = "quantity_multiply"
    quantity: QuantityExpression
    scalar: Decimal

    @field_validator("scalar", mode="before")
    @classmethod
    def validate_scalar(cls, value: Any) -> Decimal:
        return strict_decimal(value)


class MinQuantity(DomainModel):
    kind: Literal["quantity_min"] = "quantity_min"
    left: QuantityExpression
    right: QuantityExpression


class MaxQuantity(DomainModel):
    kind: Literal["quantity_max"] = "quantity_max"
    left: QuantityExpression
    right: QuantityExpression


class ClampQuantity(DomainModel):
    kind: Literal["quantity_clamp"] = "quantity_clamp"
    operand: QuantityExpression
    floor: Decimal | None = None
    cap: Decimal | None = None

    @field_validator("floor", "cap", mode="before")
    @classmethod
    def validate_bound(cls, value: Any) -> Decimal | None:
        return None if value is None else strict_decimal(value)

    @model_validator(mode="after")
    def validate_bounds(self) -> ClampQuantity:
        if self.floor is None and self.cap is None:
            raise ValueError("quantity clamp requires floor or cap")
        if self.floor is not None and self.cap is not None and self.floor > self.cap:
            raise ValueError("quantity clamp floor cannot exceed cap")
        return self


QuantityExpression = Annotated[
    MeasureReference
    | QuantityConstant
    | AddQuantity
    | SubtractQuantity
    | MultiplyQuantity
    | MinQuantity
    | MaxQuantity
    | ClampQuantity,
    Field(discriminator="kind"),
]


class RegulatoryRuleBase(DomainModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: BillingCategory
    quota: BillingQuota
    validity: DatePeriod
    parameter_codes: tuple[str, ...] = ()
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    conditions: tuple[str, ...] = ()
    provenance: tuple[Provenance, ...] = ()


class LinearRegulatoryRule(RegulatoryRuleBase):
    kind: Literal["linear"] = "linear"
    basis: BillingBasis
    value: Money | UnitRate
    measure_code: str | None = None
    proration: ProrationPolicy | None = None
    credit: bool = False


class ThresholdRegulatoryRule(RegulatoryRuleBase):
    kind: Literal["threshold"] = "threshold"
    quantity: QuantityExpression
    rate: UnitRate
    credit: bool = False


class PercentageRegulatoryRule(RegulatoryRuleBase):
    kind: Literal["percentage"] = "percentage"
    rate: UnitRate
    base_codes: tuple[str, ...] = ()
    base_categories: tuple[BillingCategory, ...] = ()
    credit: bool = False

    @model_validator(mode="after")
    def validate_base_codes(self) -> PercentageRegulatoryRule:
        if not self.base_codes and not self.base_categories:
            raise ValueError("percentage rule requires base codes or categories")
        if len(self.base_codes) != len(set(self.base_codes)):
            raise ValueError("percentage base codes must be unique")
        if len(self.base_categories) != len(set(self.base_categories)):
            raise ValueError("percentage base categories must be unique")
        return self


RegulatoryRule = Annotated[
    LinearRegulatoryRule | ThresholdRegulatoryRule | PercentageRegulatoryRule,
    Field(discriminator="kind"),
]


class RegulatoryProfile(DomainModel):
    profile_code: str = Field(min_length=1)
    contract_type_code: str | None = None
    voltage_level: VoltageLevel | None = None
    usage_code: str | None = None
    residential: bool | None = None
    tax_profile_code: str | None = None
    required_eligibility_codes: tuple[str, ...] = ()
    min_contracted_power_kw: Decimal | None = None
    max_contracted_power_kw: Decimal | None = None
    min_contracted_power_inclusive: bool = True
    max_contracted_power_inclusive: bool = True
    rules: tuple[RegulatoryRule, ...] = ()

    @field_validator("min_contracted_power_kw", "max_contracted_power_kw", mode="before")
    @classmethod
    def validate_power_bound(cls, value: Any) -> Decimal | None:
        return None if value is None else strict_decimal(value)

    @model_validator(mode="after")
    def validate_profile(self) -> RegulatoryProfile:
        if not self.rules:
            raise ValueError("regulatory profile requires rules")
        codes = [rule.code for rule in self.rules]
        if len(codes) != len(set(codes)):
            raise ValueError("regulatory rule codes must be unique within a profile")
        if (
            self.min_contracted_power_kw is not None
            and self.max_contracted_power_kw is not None
            and (
                self.min_contracted_power_kw > self.max_contracted_power_kw
                or (
                    self.min_contracted_power_kw == self.max_contracted_power_kw
                    and not (
                        self.min_contracted_power_inclusive and self.max_contracted_power_inclusive
                    )
                )
            )
        ):
            raise ValueError("minimum contracted power cannot exceed maximum")
        return self


class RegulatoryRuleSet(DomainModel):
    ruleset_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    validity: DatePeriod
    parameters: tuple[RegulatoryParameter, ...] = ()
    profiles: tuple[RegulatoryProfile, ...]
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_ruleset(self) -> RegulatoryRuleSet:
        if not self.profiles:
            raise ValueError("regulatory rule set requires profiles")
        profile_codes = [profile.profile_code for profile in self.profiles]
        if len(profile_codes) != len(set(profile_codes)):
            raise ValueError("regulatory profile codes must be unique")
        parameter_codes = [parameter.code for parameter in self.parameters]
        if len(parameter_codes) != len(set(parameter_codes)):
            raise ValueError("regulatory parameter codes must be unique")
        return self


for _model in (
    AddQuantity,
    SubtractQuantity,
    MultiplyQuantity,
    MinQuantity,
    MaxQuantity,
    ClampQuantity,
    ThresholdRegulatoryRule,
    RegulatoryProfile,
):
    _model.model_rebuild()
