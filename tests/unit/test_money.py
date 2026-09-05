from decimal import Decimal
from typing import cast

import pytest
from pydantic import ValidationError

from italian_energy.domain.common import strict_decimal
from italian_energy.domain.money import (
    Currency,
    EnergyQuantity,
    Money,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)


def test_money_rejects_float() -> None:
    with pytest.raises((TypeError, ValidationError)):
        Money.model_validate({"amount": 1.2})


def test_money_keeps_decimal_and_rounds_only_explicitly() -> None:
    value = Money(amount=Decimal("1.235"))
    assert value.amount == Decimal("1.235")
    rounded = value.round(RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP))
    assert rounded.amount == Decimal("1.24")
    assert value.amount == Decimal("1.235")


def test_money_addition_requires_same_currency() -> None:
    assert Money(amount=Decimal("1.20")) + Money(amount=Decimal("0.30")) == Money(
        amount=Decimal("1.50")
    )


def test_money_rejects_non_finite_and_currency_mismatch() -> None:
    with pytest.raises((TypeError, ValueError, ValidationError)):
        Money.model_validate({"amount": "NaN"})
    invalid_currency = Money.model_construct(amount=Decimal("1"), currency=cast(Currency, "USD"))
    with pytest.raises(ValueError, match="same currency"):
        Money(amount=Decimal("1")) + invalid_currency


def test_energy_and_power_reject_float_and_negative_values() -> None:
    with pytest.raises((TypeError, ValidationError)):
        EnergyQuantity.model_validate({"kwh": 1.1})
    with pytest.raises(ValidationError):
        EnergyQuantity(kwh=Decimal("-1"))
    with pytest.raises(ValidationError):
        Power(kw=Decimal("-1"))
    with pytest.raises((TypeError, ValueError)):
        UnitRate.model_validate({"amount": 1.2, "unit": RateUnit.EUR_PER_KWH})
    assert Money(amount=Decimal("2")) - Money(amount=Decimal("1")) == Money(amount=Decimal("1"))


def test_strict_decimal_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="invalid decimal"):
        strict_decimal("not-a-number")
    with pytest.raises(TypeError, match="must be Decimal"):
        strict_decimal(object())
