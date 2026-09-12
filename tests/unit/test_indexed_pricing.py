import json
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.formula import (
    AddPrice,
    ClampPrice,
    IndexReference,
    MultiplyPrice,
    PriceConstant,
    ScalarConstant,
)
from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.money import (
    EnergyQuantity,
    Money,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import RegulatoryParameter
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import (
    BandFormula,
    BandPrice,
    ChargeBasis,
    ChargeRule,
    FixedTariff,
    IndexedTariff,
)
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval
from italian_energy.pricing import IndexedPricingEngine, IndexedPricingError, PricingRequest

ROME = ZoneInfo("Europe/Rome")
PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 3))
POLICY = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)


def interval(day: int, hour: int, end_hour: int | None = None) -> TimeInterval:
    return TimeInterval(
        start=datetime(2026, 1, day, hour, tzinfo=ROME),
        end=datetime(2026, 1, day, end_hour if end_hour is not None else hour + 1, tzinfo=ROME),
    )


def bucket(
    day: int, energy: str, *, hour: int = 0, granularity: Granularity = Granularity.HOUR
) -> ConsumptionBucket:
    return ConsumptionBucket(
        interval=interval(day, hour),
        energy=EnergyQuantity(kwh=Decimal(energy)),
        granularity=granularity,
    )


def index(
    *, unit: RateUnit = RateUnit.EUR_PER_MWH, provenance: tuple[Provenance, ...] = ()
) -> MarketIndex:
    return MarketIndex(
        code="PUN",
        name="Synthetic PUN",
        unit=unit,
        granularity=Granularity.HOUR,
        provenance=provenance,
    )


def point(
    day: int, hour: int, value: str, provenance: tuple[Provenance, ...] = ()
) -> MarketDataPoint:
    return MarketDataPoint(
        index_code="PUN", interval=interval(day, hour), value=Decimal(value), provenance=provenance
    )


def request(
    expression: object,
    profile: ConsumptionProfile,
    *,
    period: DatePeriod = PERIOD,
    market_data: MarketData | None = None,
    charge_rules: tuple[ChargeRule, ...] = (),
) -> PricingRequest:
    tariff = IndexedTariff(
        tariff_id="indexed-test",
        validity=period,
        granularity=Granularity.HOUR,
        formulas=(BandFormula(band="ALL", expression=expression),),  # type: ignore[arg-type]
        fixed_charges=charge_rules,
    )
    contract = Contract(
        contract_id="contract-test",
        supply=SupplyPoint(
            supply_id="pod-test",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
        ),
        tariff=tariff,
        validity=period,
    )
    return PricingRequest(
        contract=contract,
        consumption=profile,
        period=period,
        rounding_policy=POLICY,
        market_data=market_data,
    )


def test_hourly_eur_mwh_is_converted_after_weighted_evaluation() -> None:
    expression = AddPrice(
        left=IndexReference(
            index_code="PUN", unit=RateUnit.EUR_PER_MWH, granularity=Granularity.HOUR
        ),
        right=PriceConstant(rate=UnitRate(amount=Decimal("200"), unit=RateUnit.EUR_PER_MWH)),
    )
    profile = ConsumptionProfile(profile_id="profile", buckets=(bucket(1, "1"), bucket(2, "2")))
    data = MarketData(indexes=(index(),), points=(point(1, 0, "1000"), point(2, 0, "2000")))

    result = IndexedPricingEngine().price(request(expression, profile, market_data=data))

    assert result.pricing_id.startswith("indexed:")
    assert result.breakdown.total.amount == Decimal("5.60")
    component = result.breakdown.components[0]
    assert component.quantity == Decimal("3")
    assert component.unit_rate is not None
    assert component.unit_rate.amount == Decimal("5.60") / Decimal("3")


def test_ast_multiply_and_clamp_are_evaluated_in_decimal() -> None:
    expression = ClampPrice(
        operand=MultiplyPrice(
            price=IndexReference(
                index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
            ),
            scalar=ScalarConstant(name="factor", value=Decimal("2")),
        ),
        floor=UnitRate(amount=Decimal("1.50"), unit=RateUnit.EUR_PER_KWH),
        cap=UnitRate(amount=Decimal("1.80"), unit=RateUnit.EUR_PER_KWH),
    )
    profile = ConsumptionProfile(profile_id="profile", buckets=(bucket(1, "1"),))
    data = MarketData(
        indexes=(index(unit=RateUnit.EUR_PER_KWH),),
        points=(point(1, 0, "1.00"),),
    )

    result = IndexedPricingEngine().price(request(expression, profile, market_data=data))

    assert result.breakdown.total.amount == Decimal("1.80")


def test_empty_profile_requires_index_definition_but_not_points() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_MWH, granularity=Granularity.HOUR
    )
    result = IndexedPricingEngine().price(
        request(
            expression,
            ConsumptionProfile(profile_id="empty"),
            market_data=MarketData(indexes=(index(),)),
        )
    )
    assert result.breakdown.components == ()


def test_missing_market_data_and_missing_point_fail_closed() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_MWH, granularity=Granularity.HOUR
    )
    profile = ConsumptionProfile(profile_id="profile", buckets=(bucket(1, "1"),))
    with pytest.raises(IndexedPricingError, match="requires market data"):
        IndexedPricingEngine().price(request(expression, profile))
    with pytest.raises(IndexedPricingError, match="coverage is missing"):
        IndexedPricingEngine().price(
            request(expression, profile, market_data=MarketData(indexes=(index(),)))
        )


def test_aggregated_consumption_and_unsupported_granularity_fail() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_MWH, granularity=Granularity.HOUR
    )
    profile = ConsumptionProfile(
        profile_id="profile",
        buckets=(
            ConsumptionBucket(
                interval=TimeInterval(
                    start=datetime(2026, 1, 1, tzinfo=ROME),
                    end=datetime(2026, 1, 2, tzinfo=ROME),
                ),
                energy=EnergyQuantity(kwh=Decimal("1")),
                granularity=Granularity.DAY,
            ),
        ),
    )
    data = MarketData(indexes=(index(),), points=(point(1, 0, "1000"),))
    with pytest.raises(IndexedPricingError, match="too aggregated"):
        IndexedPricingEngine().price(request(expression, profile, market_data=data))


def test_commercial_charges_match_fixed_semantics() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    charge = ChargeRule(
        code="daily",
        description="daily",
        basis=ChargeBasis.PER_DAY,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
    )
    profile = ConsumptionProfile(profile_id="empty")
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    result = IndexedPricingEngine().price(
        request(expression, profile, market_data=data, charge_rules=(charge,))
    )
    assert result.breakdown.total.amount == Decimal("2.00")


def test_indexed_annual_charges_use_shared_proration() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    annual = ChargeRule(
        code="annual",
        description="annual",
        basis=ChargeBasis.PER_YEAR,
        value=UnitRate(amount=Decimal("120"), unit=RateUnit.EUR_PER_YEAR),
    )
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 3, 15))
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    result = IndexedPricingEngine().price(
        request(
            expression,
            ConsumptionProfile(profile_id="empty"),
            period=period,
            market_data=data,
            charge_rules=(annual,),
        )
    )
    factor = Decimal(2) / Decimal(12) + Decimal(14) / Decimal(365)
    assert result.breakdown.total.amount == (Decimal("120") * factor).quantize(Decimal("0.01"))


def test_missing_provenance_emits_deterministic_warning() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_MWH, granularity=Granularity.HOUR
    )
    profile = ConsumptionProfile(profile_id="profile", buckets=(bucket(1, "1"),))
    data = MarketData(indexes=(index(),), points=(point(1, 0, "1000"),))
    result = IndexedPricingEngine().price(request(expression, profile, market_data=data))
    assert result.warnings == (
        "market index PUN has no provenance",
        "market data points for index PUN have no provenance",
    )
    assert result.breakdown.warnings == result.warnings


def test_indexed_pricing_id_is_canonical_and_model_is_immutable() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_MWH, granularity=Granularity.HOUR
    )
    profile = ConsumptionProfile(profile_id="profile", buckets=(bucket(1, "1"),))
    data = MarketData(indexes=(index(),), points=(point(1, 0, "1000"),))
    req = request(expression, profile, market_data=data)
    result = IndexedPricingEngine().price(req)
    canonical = json.dumps(
        req.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    assert result.pricing_id == f"indexed:{sha256(canonical).hexdigest()}"
    assert PricingRequest.model_validate_json(req.model_dump_json()) == req
    with pytest.raises(ValidationError):
        result.breakdown.total = Money(amount=Decimal("1"))  # type: ignore[misc]


def test_multiple_indexes_and_invalid_unit_are_rejected() -> None:
    with pytest.raises(ValidationError):
        AddPrice(
            left=IndexReference(
                index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
            ),
            right=PriceConstant(rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_MWH)),
        )
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    profile = ConsumptionProfile(profile_id="profile", buckets=(bucket(1, "1"),))
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_MWH),), points=(point(1, 0, "1000"),))
    with pytest.raises(IndexedPricingError, match="unit"):
        IndexedPricingEngine().price(request(expression, profile, market_data=data))


@pytest.mark.parametrize(
    "basis, value",
    [
        (ChargeBasis.PER_MONTH, UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY)),
        (ChargeBasis.PER_PERIOD, Money(amount=Decimal("1"))),
        (ChargeBasis.PERCENTAGE, UnitRate(amount=Decimal("1"), unit=RateUnit.PERCENT)),
    ],
)
def test_unsupported_indexed_charge_bases_are_rejected(
    basis: ChargeBasis, value: Money | UnitRate
) -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    rule = ChargeRule(code="unsupported", description="unsupported", basis=basis, value=value)
    profile = ConsumptionProfile(profile_id="empty")
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    with pytest.raises(IndexedPricingError, match="not supported"):
        IndexedPricingEngine().price(
            request(expression, profile, market_data=data, charge_rules=(rule,))
        )


def test_indexed_request_rejects_regulatory_parameters_and_non_indexed_tariff() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    profile = ConsumptionProfile(profile_id="empty")
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    req = request(expression, profile, market_data=data)
    parameter = RegulatoryParameter(
        code="VAT", value=Decimal("10"), unit="percent", validity=PERIOD
    )
    with pytest.raises(IndexedPricingError, match="regulatory"):
        IndexedPricingEngine().price(req.model_copy(update={"regulatory_parameters": (parameter,)}))

    fixed = FixedTariff(
        tariff_id="fixed",
        validity=PERIOD,
        prices=(
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
    )
    fixed_contract = req.contract.model_copy(update={"tariff": fixed})
    with pytest.raises(IndexedPricingError, match="indexed tariff"):
        IndexedPricingEngine().price(req.model_copy(update={"contract": fixed_contract}))


def test_indexed_period_and_tariff_validation_are_fail_closed() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    profile = ConsumptionProfile(profile_id="empty")
    contract = request(expression, profile, market_data=data).contract
    with pytest.raises(IndexedPricingError, match="contract validity"):
        IndexedPricingEngine().price(
            request(expression, profile, market_data=data).model_copy(
                update={"period": DatePeriod(start=date(2025, 1, 1), end=date(2026, 1, 2))}
            )
        )
    narrow = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 3))
    narrow_tariff = contract.tariff.model_copy(update={"validity": narrow})
    narrow_contract = contract.model_copy(update={"tariff": narrow_tariff})
    with pytest.raises(IndexedPricingError, match="tariff validity"):
        IndexedPricingEngine().price(
            request(expression, profile, market_data=data).model_copy(
                update={"contract": narrow_contract}
            )
        )


def test_formula_and_index_granularity_validation() -> None:
    profile = ConsumptionProfile(profile_id="empty")
    empty_data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    no_reference = PriceConstant(rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH))
    with pytest.raises(IndexedPricingError, match="requires an index"):
        IndexedPricingEngine().price(request(no_reference, profile, market_data=empty_data))

    missing = IndexReference(
        index_code="MISSING", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    with pytest.raises(IndexedPricingError, match="MISSING is missing"):
        IndexedPricingEngine().price(request(missing, profile, market_data=empty_data))

    wrong_reference = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.DAY
    )
    with pytest.raises(IndexedPricingError, match="does not match tariff"):
        IndexedPricingEngine().price(request(wrong_reference, profile, market_data=empty_data))

    wrong_index = MarketData(
        indexes=(
            MarketIndex(
                code="PUN",
                name="daily",
                unit=RateUnit.EUR_PER_KWH,
                granularity=Granularity.DAY,
            ),
        )
    )
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    with pytest.raises(IndexedPricingError, match="does not match tariff"):
        IndexedPricingEngine().price(request(expression, profile, market_data=wrong_index))


def test_band_matching_and_charge_validation_errors() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    profile_all = ConsumptionProfile(profile_id="all", buckets=(bucket(1, "1"),))
    named_tariff = IndexedTariff(
        tariff_id="named",
        validity=PERIOD,
        granularity=Granularity.HOUR,
        formulas=(BandFormula(band="F1", expression=expression),),
    )
    contract = Contract(
        contract_id="named-contract",
        supply=SupplyPoint(supply_id="pod", market_zone="NORD"),
        tariff=named_tariff,
        validity=PERIOD,
    )
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),), points=(point(1, 0, "1"),))
    with pytest.raises(IndexedPricingError, match="named bands"):
        IndexedPricingEngine().price(
            request(expression, profile_all, market_data=data).model_copy(
                update={"contract": contract}
            )
        )

    # The named-band mismatch is checked by constructing a bucket with F2.
    f2_bucket = bucket(1, "1").model_copy(update={"band": "F2"})
    with pytest.raises(IndexedPricingError, match="no indexed formula"):
        IndexedPricingEngine().price(
            request(
                expression,
                ConsumptionProfile(profile_id="f2", buckets=(f2_bucket,)),
                market_data=data,
            ).model_copy(update={"contract": contract})
        )

    banded_daily = ChargeRule(
        code="banded",
        description="banded",
        basis=ChargeBasis.PER_DAY,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
        band="F1",
    )
    with pytest.raises(IndexedPricingError, match="only for PER_KWH"):
        IndexedPricingEngine().price(
            request(expression, profile_all, market_data=data, charge_rules=(banded_daily,))
        )

    bad_flat = ChargeRule.model_construct(
        code="flat",
        description="flat",
        basis=ChargeBasis.FLAT,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
        band=None,
        validity=None,
        discount=False,
        conditions=(),
        provenance=(),
    )
    with pytest.raises(IndexedPricingError, match="requires Money"):
        IndexedPricingEngine().price(
            request(expression, profile_all, market_data=data, charge_rules=(bad_flat,))
        )


@pytest.mark.parametrize(
    "basis, expected_unit",
    [
        (ChargeBasis.PER_KWH, RateUnit.EUR_PER_KWH),
        (ChargeBasis.PER_DAY, RateUnit.EUR_PER_DAY),
        (ChargeBasis.PER_KW_DAY, RateUnit.EUR_PER_KW_DAY),
    ],
)
def test_indexed_charge_units_are_validated(basis: ChargeBasis, expected_unit: RateUnit) -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    wrong_unit = (
        RateUnit.EUR_PER_DAY if expected_unit != RateUnit.EUR_PER_DAY else RateUnit.EUR_PER_KWH
    )
    rule = ChargeRule(
        code="wrong",
        description="wrong",
        basis=basis,
        value=UnitRate(amount=Decimal("1"), unit=wrong_unit),
    )
    with pytest.raises(IndexedPricingError, match="requires"):
        IndexedPricingEngine().price(
            request(
                expression,
                ConsumptionProfile(profile_id="empty"),
                market_data=MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),)),
                charge_rules=(rule,),
            )
        )


def test_indexed_charge_flat_and_discount_components_and_boundary_errors() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    flat = ChargeRule(
        code="flat",
        description="flat",
        basis=ChargeBasis.FLAT,
        value=Money(amount=Decimal("2")),
    )
    discount = ChargeRule(
        code="discount",
        description="discount",
        basis=ChargeBasis.FLAT,
        value=Money(amount=Decimal("-1")),
        discount=True,
    )
    tariff = IndexedTariff(
        tariff_id="charges",
        validity=PERIOD,
        granularity=Granularity.HOUR,
        formulas=(BandFormula(band="ALL", expression=expression),),
        fixed_charges=(flat,),
        discounts=(discount,),
    )
    contract = Contract(
        contract_id="charges-contract",
        supply=SupplyPoint(supply_id="pod", market_zone="NORD"),
        tariff=tariff,
        validity=PERIOD,
    )
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    req = request(expression, ConsumptionProfile(profile_id="empty"), market_data=data).model_copy(
        update={"contract": contract}
    )
    result = IndexedPricingEngine().price(req)
    assert result.breakdown.total.amount == Decimal("1.00")

    later = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 3))
    later_flat = flat.model_copy(
        update={"validity": DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2))}
    )
    later_tariff = tariff.model_copy(update={"fixed_charges": (later_flat,)})
    later_contract = contract.model_copy(update={"tariff": later_tariff})
    later_result = IndexedPricingEngine().price(
        req.model_copy(update={"contract": later_contract, "period": later})
    )
    assert later_result.breakdown.total.amount == Decimal("0")


def test_indexed_charge_bucket_boundary_and_missing_power_errors() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    charge_period = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 3))
    charge = ChargeRule(
        code="limited",
        description="limited",
        basis=ChargeBasis.PER_KWH,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
        validity=charge_period,
    )
    crossing = ConsumptionBucket(
        interval=TimeInterval(
            start=datetime(2026, 1, 1, 23, tzinfo=ROME),
            end=datetime(2026, 1, 2, 1, tzinfo=ROME),
        ),
        energy=EnergyQuantity(kwh=Decimal("0")),
        granularity=Granularity.HOUR,
    )
    profile = ConsumptionProfile(profile_id="cross", buckets=(crossing,))
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    with pytest.raises(IndexedPricingError, match="cuts through"):
        IndexedPricingEngine().price(
            request(expression, profile, market_data=data, charge_rules=(charge,))
        )

    capacity = ChargeRule(
        code="capacity",
        description="capacity",
        basis=ChargeBasis.PER_KW_DAY,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_DAY),
    )
    req = request(
        expression,
        ConsumptionProfile(profile_id="empty"),
        market_data=data,
        charge_rules=(capacity,),
    )
    contract = req.contract.model_copy(
        update={"supply": SupplyPoint(supply_id="pod", market_zone="NORD")}
    )
    with pytest.raises(IndexedPricingError, match="contracted power"):
        IndexedPricingEngine().price(req.model_copy(update={"contract": contract}))


def test_selection_errors_and_zero_energy_buckets_are_handled() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),))
    crossing = ConsumptionBucket(
        interval=TimeInterval(
            start=datetime(2026, 1, 2, 23, tzinfo=ROME),
            end=datetime(2026, 1, 3, 1, tzinfo=ROME),
        ),
        energy=EnergyQuantity(kwh=Decimal("1")),
        granularity=Granularity.HOUR,
    )
    with pytest.raises(IndexedPricingError, match="crosses requested period"):
        IndexedPricingEngine().price(
            request(
                expression,
                ConsumptionProfile(profile_id="cross", buckets=(crossing,)),
                market_data=data,
            )
        )

    zero = bucket(1, "0", hour=1)
    positive = bucket(1, "1", hour=0)
    data_with_point = MarketData(
        indexes=(index(unit=RateUnit.EUR_PER_KWH),), points=(point(1, 0, "1"),)
    )
    result = IndexedPricingEngine().price(
        request(
            expression,
            ConsumptionProfile(profile_id="zero", buckets=(zero, positive)),
            market_data=data_with_point,
        )
    )
    assert result.breakdown.total.amount == Decimal("1.00")


def test_unsupported_granularity_and_result_unit_fail() -> None:
    expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    req = request(
        expression,
        ConsumptionProfile(profile_id="empty"),
        market_data=MarketData(indexes=(index(unit=RateUnit.EUR_PER_KWH),)),
    )
    bad_tariff = req.contract.tariff.model_copy(update={"granularity": Granularity.BILLING_PERIOD})
    bad_contract = req.contract.model_copy(update={"tariff": bad_tariff})
    with pytest.raises(IndexedPricingError, match="granularity"):
        IndexedPricingEngine().price(req.model_copy(update={"contract": bad_contract}))

    wrong_expression = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_DAY, granularity=Granularity.HOUR
    )
    wrong_data = MarketData(indexes=(index(unit=RateUnit.EUR_PER_DAY),), points=(point(1, 0, "1"),))
    with pytest.raises(IndexedPricingError, match="must result"):
        IndexedPricingEngine().price(
            request(
                wrong_expression,
                ConsumptionProfile(profile_id="one", buckets=(bucket(1, "1"),)),
                market_data=wrong_data,
            )
        )


def test_point_canonical_boundaries_for_supported_granularities() -> None:
    engine = IndexedPricingEngine()
    quarter_index = MarketIndex(
        code="Q", name="quarter", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.QUARTER_HOUR
    )
    engine._validate_point(
        MarketDataPoint(
            index_code="Q",
            interval=TimeInterval(
                start=datetime(2026, 1, 1, 0, 0, tzinfo=ROME),
                end=datetime(2026, 1, 1, 0, 15, tzinfo=ROME),
            ),
            value=Decimal("1"),
        ),
        quarter_index,
    )
    hour_index = MarketIndex(
        code="H", name="hour", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    engine._validate_point(
        MarketDataPoint(index_code="H", interval=interval(1, 0), value=Decimal("1")), hour_index
    )
    day_index = MarketIndex(
        code="D", name="day", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.DAY
    )
    engine._validate_point(
        MarketDataPoint(
            index_code="D",
            interval=TimeInterval(
                start=datetime(2026, 1, 1, tzinfo=ROME),
                end=datetime(2026, 1, 2, tzinfo=ROME),
            ),
            value=Decimal("1"),
        ),
        day_index,
    )
    month_index = MarketIndex(
        code="M", name="month", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.MONTH
    )
    engine._validate_point(
        MarketDataPoint(
            index_code="M",
            interval=TimeInterval(
                start=datetime(2026, 1, 1, tzinfo=ROME),
                end=datetime(2026, 2, 1, tzinfo=ROME),
            ),
            value=Decimal("1"),
        ),
        month_index,
    )


@pytest.mark.parametrize(
    "index_granularity, start, end, message",
    [
        (
            Granularity.QUARTER_HOUR,
            datetime(2026, 1, 1, 0, 5, tzinfo=ROME),
            datetime(2026, 1, 1, 0, 20, tzinfo=ROME),
            "quarter-hour boundary",
        ),
        (
            Granularity.QUARTER_HOUR,
            datetime(2026, 1, 1, tzinfo=ROME),
            datetime(2026, 1, 1, 0, 10, tzinfo=ROME),
            "15 minutes",
        ),
        (
            Granularity.HOUR,
            datetime(2026, 1, 1, 0, 30, tzinfo=ROME),
            datetime(2026, 1, 1, 1, 30, tzinfo=ROME),
            "hour boundary",
        ),
        (
            Granularity.HOUR,
            datetime(2026, 1, 1, tzinfo=ROME),
            datetime(2026, 1, 1, 0, 30, tzinfo=ROME),
            "one hour",
        ),
        (
            Granularity.DAY,
            datetime(2026, 1, 1, 1, tzinfo=ROME),
            datetime(2026, 1, 2, tzinfo=ROME),
            "civil day",
        ),
        (
            Granularity.MONTH,
            datetime(2026, 1, 2, tzinfo=ROME),
            datetime(2026, 2, 1, tzinfo=ROME),
            "month boundary",
        ),
        (
            Granularity.MONTH,
            datetime(2026, 1, 1, tzinfo=ROME),
            datetime(2026, 1, 31, tzinfo=ROME),
            "civil month",
        ),
    ],
)
def test_non_canonical_market_points_are_rejected(
    index_granularity: Granularity,
    start: datetime,
    end: datetime,
    message: str,
) -> None:
    market_index = MarketIndex(
        code="X", name="invalid", unit=RateUnit.EUR_PER_KWH, granularity=index_granularity
    )
    with pytest.raises(IndexedPricingError, match=message):
        IndexedPricingEngine._validate_point(
            MarketDataPoint(
                index_code="X",
                interval=TimeInterval(start=start, end=end),
                value=Decimal("1"),
            ),
            market_index,
        )


def test_ast_edge_paths_and_provenance_are_deterministic() -> None:
    reference = IndexReference(
        index_code="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.HOUR
    )
    assert IndexedPricingEngine._index_references(AddPrice(left=reference, right=reference)) == (
        reference,
    )
    with pytest.raises(IndexedPricingError, match="missing value"):
        IndexedPricingEngine._evaluate(reference, {})
    malformed_add = AddPrice.model_construct(
        left=reference,
        right=PriceConstant(rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY)),
    )
    with pytest.raises(IndexedPricingError, match="equal units"):
        IndexedPricingEngine._evaluate(
            malformed_add, {"PUN": UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)}
        )
    floor_only = ClampPrice(
        operand=PriceConstant(rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)),
        floor=UnitRate(amount=Decimal("2"), unit=RateUnit.EUR_PER_KWH),
    )
    cap_only = ClampPrice(
        operand=PriceConstant(rate=UnitRate(amount=Decimal("3"), unit=RateUnit.EUR_PER_KWH)),
        cap=UnitRate(amount=Decimal("2"), unit=RateUnit.EUR_PER_KWH),
    )
    assert IndexedPricingEngine._evaluate(floor_only, {}).amount == Decimal("2")
    assert IndexedPricingEngine._evaluate(cap_only, {}).amount == Decimal("2")
    with pytest.raises(IndexedPricingError, match="unsupported price expression"):
        IndexedPricingEngine._evaluate(object(), {})  # type: ignore[arg-type]
    source = Provenance(
        source="fixture", source_identifier="index", retrieved_at=datetime(2026, 1, 1, tzinfo=ROME)
    )
    expression = reference
    profile = ConsumptionProfile(profile_id="one", buckets=(bucket(1, "1"),))
    data = MarketData(
        indexes=(index(unit=RateUnit.EUR_PER_KWH, provenance=(source,)),),
        points=(point(1, 0, "1", (source,)),),
    )
    result = IndexedPricingEngine().price(request(expression, profile, market_data=data))
    assert result.warnings == ()
    assert result.provenance == (source,)
