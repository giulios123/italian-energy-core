"""Typed, non-executable AST for indexed tariff formulas."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.time import Granularity


class IndexReference(DomainModel):
    kind: Literal["index_reference"] = "index_reference"
    index_code: str = Field(min_length=1)
    unit: RateUnit
    granularity: Granularity


class PriceConstant(DomainModel):
    kind: Literal["price_constant"] = "price_constant"
    rate: UnitRate


class ScalarConstant(DomainModel):
    kind: Literal["scalar_constant"] = "scalar_constant"
    value: Decimal
    name: str = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> Decimal:
        return strict_decimal(value)


class NamedCoefficient(DomainModel):
    kind: Literal["coefficient"] = "coefficient"
    code: str = Field(min_length=1)
    value: Decimal
    role: str = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: object) -> Decimal:
        return strict_decimal(value)


ScalarExpression = Annotated[ScalarConstant | NamedCoefficient, Field(discriminator="kind")]


class AddPrice(DomainModel):
    kind: Literal["add"] = "add"
    left: PriceExpression
    right: PriceExpression

    @model_validator(mode="after")
    def validate_units(self) -> AddPrice:
        if price_expression_unit(self.left) != price_expression_unit(self.right):
            raise ValueError("price addition requires equal units")
        return self


class MultiplyPrice(DomainModel):
    kind: Literal["multiply"] = "multiply"
    price: PriceExpression
    scalar: ScalarExpression


class ClampPrice(DomainModel):
    kind: Literal["clamp"] = "clamp"
    operand: PriceExpression
    floor: UnitRate | None = None
    cap: UnitRate | None = None

    @model_validator(mode="after")
    def validate_clamp(self) -> ClampPrice:
        unit = price_expression_unit(self.operand)
        if self.floor is None and self.cap is None:
            raise ValueError("clamp requires floor or cap")
        if self.floor is not None and self.floor.unit != unit:
            raise ValueError("floor unit must match operand unit")
        if self.cap is not None and self.cap.unit != unit:
            raise ValueError("cap unit must match operand unit")
        if self.floor is not None and self.cap is not None and self.floor.amount > self.cap.amount:
            raise ValueError("floor cannot exceed cap")
        return self


PriceExpression = Annotated[
    IndexReference | PriceConstant | AddPrice | MultiplyPrice | ClampPrice,
    Field(discriminator="kind"),
]


def price_expression_unit(expression: PriceExpression) -> RateUnit:
    if isinstance(expression, IndexReference):
        return expression.unit
    if isinstance(expression, PriceConstant):
        return expression.rate.unit
    if isinstance(expression, AddPrice):
        return price_expression_unit(expression.left)
    if isinstance(expression, MultiplyPrice):
        return price_expression_unit(expression.price)
    if isinstance(expression, ClampPrice):
        return price_expression_unit(expression.operand)
    raise TypeError(f"unsupported price expression: {type(expression)!r}")


for _model in (AddPrice, MultiplyPrice, ClampPrice):
    _model.model_rebuild()
