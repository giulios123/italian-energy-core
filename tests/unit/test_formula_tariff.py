from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from italian_energy.domain.formula import (
    AddPrice,
    ClampPrice,
    IndexReference,
    MultiplyPrice,
    NamedCoefficient,
    PriceConstant,
    price_expression_unit,
)
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.tariff import BandFormula, BandPrice, FixedTariff, IndexedTariff
from italian_energy.domain.time import DatePeriod, Granularity

PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1))


def test_indexed_formula_is_typed_and_serializable() -> None:
    index = IndexReference(
        index_code="PUN_M",
        unit=RateUnit.EUR_PER_MWH,
        granularity=Granularity.MONTH,
    )
    coefficient = NamedCoefficient(code="LOSS", value=Decimal("1.10"), role="loss_factor")
    expression = AddPrice(
        left=MultiplyPrice(price=index, scalar=coefficient),
        right=PriceConstant(rate=UnitRate(amount=Decimal("0.015"), unit=RateUnit.EUR_PER_MWH)),
    )
    assert price_expression_unit(expression) == RateUnit.EUR_PER_MWH
    assert AddPrice.model_validate_json(expression.model_dump_json()) == expression


def test_clamp_rejects_floor_above_cap() -> None:
    index = IndexReference(index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.DAY)
    with pytest.raises(ValidationError, match="floor"):
        ClampPrice(
            operand=index,
            floor=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH),
            cap=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
        )


def test_formula_rejects_incompatible_units_and_empty_clamp() -> None:
    left = IndexReference(index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.DAY)
    right = PriceConstant(rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_MWH))
    with pytest.raises(ValidationError, match="equal units"):
        AddPrice(left=left, right=right)
    with pytest.raises(ValidationError, match="floor or cap"):
        ClampPrice(operand=left)
    with pytest.raises(ValidationError, match="operand unit"):
        ClampPrice(operand=left, floor=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_MWH))
    with pytest.raises(ValidationError, match="operand unit"):
        ClampPrice(operand=left, cap=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_MWH))
    with pytest.raises((TypeError, ValidationError)):
        from italian_energy.domain.formula import ScalarConstant

        ScalarConstant.model_validate({"name": "bad", "value": 1.1})
    with pytest.raises(TypeError, match="unsupported"):
        price_expression_unit(object())  # type: ignore[arg-type]


def test_fixed_and_indexed_tariffs_reject_mixed_all_bands() -> None:
    prices = (
        BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),
        BandPrice(band="F1", rate=UnitRate(amount=Decimal("0.21"), unit=RateUnit.EUR_PER_KWH)),
    )
    with pytest.raises(ValidationError, match="ALL"):
        FixedTariff(tariff_id="fixed-1", validity=PERIOD, prices=prices)

    with pytest.raises(ValidationError, match="ALL"):
        IndexedTariff(
            tariff_id="indexed-1",
            validity=PERIOD,
            granularity=Granularity.MONTH,
            formulas=(
                BandFormula(
                    band="ALL",
                    expression=IndexReference(
                        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.MONTH
                    ),
                ),
                BandFormula(
                    band="F1",
                    expression=IndexReference(
                        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.MONTH
                    ),
                ),
            ),
        )


def test_tariffs_reject_empty_and_duplicate_bands() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        FixedTariff(tariff_id="fixed-empty", validity=PERIOD, prices=())
    price = BandPrice(band="F1", rate=UnitRate(amount=Decimal("0.2"), unit=RateUnit.EUR_PER_KWH))
    with pytest.raises(ValidationError, match="unique"):
        FixedTariff(tariff_id="fixed-duplicate", validity=PERIOD, prices=(price, price))
    with pytest.raises(ValidationError, match="at least one"):
        IndexedTariff(
            tariff_id="indexed-empty", validity=PERIOD, granularity=Granularity.MONTH, formulas=()
        )
    formula = BandFormula(
        band="F1",
        expression=IndexReference(
            index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.MONTH
        ),
    )
    with pytest.raises(ValidationError, match="unique"):
        IndexedTariff(
            tariff_id="indexed-duplicate",
            validity=PERIOD,
            granularity=Granularity.MONTH,
            formulas=(formula, formula),
        )
