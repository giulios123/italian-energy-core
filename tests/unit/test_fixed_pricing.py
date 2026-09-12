import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.costs import PricingResult
from italian_energy.domain.formula import IndexReference
from italian_energy.domain.market import MarketData
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
from italian_energy.pricing import FixedPricingEngine, FixedPricingError, PricingRequest

ROME = ZoneInfo("Europe/Rome")
PERIOD = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 4))
POLICY = RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP)


def bucket(
    day: date,
    energy: str,
    band: str = "ALL",
    start_hour: int = 1,
    end_hour: int = 2,
) -> ConsumptionBucket:
    return ConsumptionBucket(
        interval=TimeInterval(
            start=datetime.combine(day, datetime.min.time(), ROME).replace(hour=start_hour),
            end=datetime.combine(day, datetime.min.time(), ROME).replace(hour=end_hour),
        ),
        energy=EnergyQuantity(kwh=Decimal(energy)),
        band=band,
        granularity=Granularity.HOUR,
    )


def tariff(
    prices: tuple[BandPrice, ...],
    *,
    fixed_charges: tuple[ChargeRule, ...] = (),
    additional_charges: tuple[ChargeRule, ...] = (),
    discounts: tuple[ChargeRule, ...] = (),
    conditions: tuple[str, ...] = (),
    provenance: tuple[Provenance, ...] = (),
    validity: DatePeriod = PERIOD,
) -> FixedTariff:
    return FixedTariff(
        tariff_id="fixed-test",
        validity=validity,
        prices=prices,
        fixed_charges=fixed_charges,
        additional_charges=additional_charges,
        discounts=discounts,
        conditions=conditions,
        provenance=provenance,
    )


def contract_for(
    fixed_tariff: FixedTariff,
    *,
    validity: DatePeriod = PERIOD,
    power: str | None = "3",
    conditions: tuple[str, ...] = (),
) -> Contract:
    return Contract(
        contract_id="contract-test",
        supply=SupplyPoint(
            supply_id="pod-test",
            market_zone="NORD",
            contracted_power=None if power is None else Power(kw=Decimal(power)),
        ),
        tariff=fixed_tariff,
        validity=validity,
        conditions=conditions,
    )


def request(
    contract: Contract,
    profile: ConsumptionProfile,
    period: DatePeriod = PERIOD,
    *,
    market_data: MarketData | None = None,
    regulatory_parameters: tuple[RegulatoryParameter, ...] = (),
) -> PricingRequest:
    return PricingRequest(
        contract=contract,
        consumption=profile,
        period=period,
        rounding_policy=POLICY,
        market_data=market_data,
        regulatory_parameters=regulatory_parameters,
    )


def test_monorario_rounds_each_component_and_keeps_assumptions_and_provenance() -> None:
    tariff_source = Provenance(
        source="fixture",
        source_identifier="tariff",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    charge_source = Provenance(
        source="fixture",
        source_identifier="charge",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    daily = tuple(
        ChargeRule(
            code=code,
            description=code,
            basis=ChargeBasis.PER_DAY,
            value=UnitRate(amount=Decimal("0.125"), unit=RateUnit.EUR_PER_DAY),
            provenance=(charge_source,),
        )
        for code in ("daily-a", "daily-b")
    )
    activation = ChargeRule(
        code="activation",
        description="activation discount",
        basis=ChargeBasis.FLAT,
        value=Money(amount=Decimal("-0.125")),
        discount=True,
        conditions=("requires direct debit",),
        provenance=(charge_source,),
    )
    fixed = tariff(
        (
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("0.125"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
        fixed_charges=daily,
        discounts=(activation,),
        conditions=("commercial condition",),
        provenance=(tariff_source,),
    )
    contract = contract_for(fixed, conditions=("contract condition",))
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2))
    result = FixedPricingEngine().price(
        request(
            contract,
            ConsumptionProfile(profile_id="profile", buckets=(bucket(date(2026, 1, 1), "1"),)),
            period,
        )
    )

    assert [component.amount.amount for component in result.breakdown.components] == [
        Decimal("0.13"),
        Decimal("0.13"),
        Decimal("0.13"),
        Decimal("-0.13"),
    ]
    assert result.breakdown.total.amount == Decimal("0.26")
    assert result.assumptions == (
        "contract condition",
        "commercial condition",
        "requires direct debit",
    )
    assert result.breakdown.components[0].provenance == (tariff_source,)
    assert result.breakdown.components[-1].provenance == (tariff_source, charge_source)
    canonical = json.dumps(
        request(
            contract,
            ConsumptionProfile(profile_id="profile", buckets=(bucket(date(2026, 1, 1), "1"),)),
            period,
        ).model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert result.pricing_id == f"fixed:{sha256(canonical).hexdigest()}"
    assert PricingRequest.model_validate_json(
        request(
            contract,
            ConsumptionProfile(profile_id="profile", buckets=(bucket(date(2026, 1, 1), "1"),)),
            period,
        ).model_dump_json()
    ) == request(
        contract,
        ConsumptionProfile(profile_id="profile", buckets=(bucket(date(2026, 1, 1), "1"),)),
        period,
    )
    request_payload = request(
        contract,
        ConsumptionProfile(profile_id="profile", buckets=(bucket(date(2026, 1, 1), "1"),)),
        period,
    ).model_dump()
    request_payload.pop("rounding_policy")
    with pytest.raises(ValidationError, match="rounding_policy"):
        PricingRequest.model_validate(request_payload)
    assert PricingResult.model_validate_json(result.model_dump_json()) == result
    assert (
        FixedPricingEngine().price(
            request(
                contract,
                ConsumptionProfile(profile_id="profile", buckets=(bucket(date(2026, 1, 1), "1"),)),
                period,
            )
        )
        == result
    )


def test_multiband_and_all_tariff_matching() -> None:
    fixed = tariff(
        (
            BandPrice(band="F1", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),
            BandPrice(band="F2", rate=UnitRate(amount=Decimal("0.30"), unit=RateUnit.EUR_PER_KWH)),
        )
    )
    profile = ConsumptionProfile(
        profile_id="bands",
        buckets=(
            bucket(date(2026, 1, 1), "1", "F1"),
            bucket(date(2026, 1, 2), "2", "F2"),
        ),
    )
    result = FixedPricingEngine().price(request(contract_for(fixed), profile))
    assert [component.quantity for component in result.breakdown.components] == [
        Decimal("1"),
        Decimal("2"),
    ]
    assert result.breakdown.total.amount == Decimal("0.80")

    all_tariff = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),)
    )
    all_result = FixedPricingEngine().price(request(contract_for(all_tariff), profile))
    assert all_result.breakdown.total.amount == Decimal("0.60")


def test_per_kwh_charge_can_target_a_named_band() -> None:
    rule = ChargeRule(
        code="f1-charge",
        description="F1 charge",
        basis=ChargeBasis.PER_KWH,
        value=UnitRate(amount=Decimal("0.10"), unit=RateUnit.EUR_PER_KWH),
        band="F1",
    )
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),),
        additional_charges=(rule,),
    )
    profile = ConsumptionProfile(
        profile_id="bands",
        buckets=(bucket(date(2026, 1, 1), "1", "F1"), bucket(date(2026, 1, 2), "2", "F2")),
    )
    result = FixedPricingEngine().price(request(contract_for(fixed), profile))
    assert [component.code for component in result.breakdown.components] == [
        "energy:ALL",
        "additional:f1-charge",
    ]
    assert result.breakdown.components[-1].quantity == Decimal("1")
    assert result.breakdown.total.amount == Decimal("0.70")

    all_profile = ConsumptionProfile(
        profile_id="all",
        buckets=(bucket(date(2026, 1, 1), "1"),),
    )
    with pytest.raises(FixedPricingError, match="named consumption"):
        FixedPricingEngine().price(request(contract_for(fixed), all_profile))


def test_annual_charges_use_monthly_twelfths_and_partial_days() -> None:
    annual = ChargeRule(
        code="annual",
        description="annual commercial charge",
        basis=ChargeBasis.PER_YEAR,
        value=UnitRate(amount=Decimal("120"), unit=RateUnit.EUR_PER_YEAR),
    )
    power_annual = ChargeRule(
        code="power-annual",
        description="annual power charge",
        basis=ChargeBasis.PER_KW_YEAR,
        value=UnitRate(amount=Decimal("10"), unit=RateUnit.EUR_PER_KW_YEAR),
    )
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 3, 15))
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(annual, power_annual),
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2026, 12, 31)),
    )
    contract = contract_for(
        fixed,
        validity=DatePeriod(start=date(2026, 1, 1), end=date(2026, 12, 31)),
        power="3",
    )
    result = FixedPricingEngine().price(
        request(
            contract,
            ConsumptionProfile(profile_id="empty"),
            period,
        )
    )

    # January and February are complete; the first 14 days of March are partial.
    factor = Decimal(2) / Decimal(12) + Decimal(14) / Decimal(365)
    assert result.breakdown.components[0].amount.amount == (Decimal("120") * factor).quantize(
        Decimal("0.01")
    )
    assert result.breakdown.components[1].amount.amount == (
        Decimal("10") * Decimal("3") * factor
    ).quantize(Decimal("0.01"))


def test_annual_power_charge_requires_contracted_power() -> None:
    rule = ChargeRule(
        code="power-annual",
        description="annual power charge",
        basis=ChargeBasis.PER_KW_YEAR,
        value=UnitRate(amount=Decimal("10"), unit=RateUnit.EUR_PER_KW_YEAR),
    )
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(rule,),
    )
    with pytest.raises(FixedPricingError, match="PER_KW_YEAR requires contracted power"):
        FixedPricingEngine().price(
            request(contract_for(fixed, power=None), ConsumptionProfile(profile_id="empty"))
        )


def test_band_mapping_and_boundary_errors_are_fail_closed() -> None:
    fixed = tariff(
        (BandPrice(band="F1", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),)
    )
    all_profile = ConsumptionProfile(
        profile_id="all",
        buckets=(bucket(date(2026, 1, 1), "1"),),
    )
    with pytest.raises(FixedPricingError, match="named bands"):
        FixedPricingEngine().price(request(contract_for(fixed), all_profile))

    profile_with_unknown = ConsumptionProfile(
        profile_id="unknown",
        buckets=(bucket(date(2026, 1, 1), "1", "F2"),),
    )
    with pytest.raises(FixedPricingError, match="no fixed price"):
        FixedPricingEngine().price(request(contract_for(fixed), profile_with_unknown))

    cross_boundary = ConsumptionBucket(
        interval=TimeInterval(
            start=datetime(2026, 1, 3, 23, tzinfo=ROME),
            end=datetime(2026, 1, 4, 1, tzinfo=ROME),
        ),
        energy=EnergyQuantity(kwh=Decimal("1")),
        granularity=Granularity.HOUR,
    )
    profile = ConsumptionProfile(profile_id="cross", buckets=(cross_boundary,))
    with pytest.raises(FixedPricingError, match="crosses"):
        FixedPricingEngine().price(
            request(
                contract_for(
                    tariff(
                        (
                            BandPrice(
                                band="ALL",
                                rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH),
                            ),
                        )
                    )
                ),
                profile,
            )
        )


def test_external_buckets_are_ignored_and_period_must_be_covered() -> None:
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),)
    )
    profile = ConsumptionProfile(
        profile_id="subset",
        buckets=(
            bucket(date(2025, 12, 31), "100"),
            bucket(date(2026, 1, 1), "2"),
            bucket(date(2026, 1, 4), "100"),
        ),
    )
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 3))
    result = FixedPricingEngine().price(request(contract_for(fixed), profile, period))
    assert result.breakdown.total.amount == Decimal("0.40")

    outside = DatePeriod(start=date(2025, 12, 1), end=date(2026, 1, 3))
    with pytest.raises(FixedPricingError, match="contained"):
        FixedPricingEngine().price(request(contract_for(fixed), profile, outside))


def test_daily_charge_uses_civil_days_across_dst() -> None:
    period = DatePeriod(start=date(2026, 3, 28), end=date(2026, 4, 1))
    fixed = tariff(
        (
            BandPrice(
                band="ALL",
                rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH),
            ),
        ),
        fixed_charges=(
            ChargeRule(
                code="daily",
                description="daily",
                basis=ChargeBasis.PER_DAY,
                value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
            ),
        ),
        validity=period,
    )
    result = FixedPricingEngine().price(
        request(
            contract_for(fixed, validity=period),
            ConsumptionProfile(profile_id="dst"),
            period,
        )
    )
    assert result.breakdown.total.amount == Decimal("4.00")


def test_per_kw_day_pricing_uses_contracted_power() -> None:
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 3))
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(
            ChargeRule(
                code="capacity",
                description="capacity",
                basis=ChargeBasis.PER_KW_DAY,
                value=UnitRate(amount=Decimal("0.50"), unit=RateUnit.EUR_PER_KW_DAY),
            ),
        ),
        validity=period,
    )
    result = FixedPricingEngine().price(
        request(
            contract_for(fixed, validity=period, power="3"),
            ConsumptionProfile(profile_id="empty"),
            period,
        )
    )
    assert result.breakdown.total.amount == Decimal("3.00")
    assert len(result.breakdown.components) == 1
    assert result.breakdown.components[0].quantity == Decimal("6")


def test_kw_day_requires_power_and_supported_units_are_checked() -> None:
    rule = ChargeRule(
        code="capacity",
        description="capacity",
        basis=ChargeBasis.PER_KW_DAY,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KW_DAY),
    )
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(rule,),
    )
    with pytest.raises(FixedPricingError, match="contracted power"):
        FixedPricingEngine().price(
            request(
                contract_for(fixed, power=None),
                ConsumptionProfile(profile_id="empty"),
            )
        )

    invalid_energy = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_MWH)),)
    )
    with pytest.raises(FixedPricingError, match="EUR/kWh"):
        FixedPricingEngine().price(
            request(contract_for(invalid_energy), ConsumptionProfile(profile_id="empty"))
        )

    wrong_rate = ChargeRule(
        code="wrong-rate",
        description="wrong-rate",
        basis=ChargeBasis.PER_DAY,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
    )
    wrong_tariff = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(wrong_rate,),
    )
    with pytest.raises(FixedPricingError, match="EUR/day"):
        FixedPricingEngine().price(
            request(contract_for(wrong_tariff), ConsumptionProfile(profile_id="empty"))
        )

    banded_daily = ChargeRule(
        code="banded-daily",
        description="banded-daily",
        basis=ChargeBasis.PER_DAY,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
        band="F1",
    )
    banded_tariff = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(banded_daily,),
    )
    with pytest.raises(FixedPricingError, match="only for PER_KWH"):
        FixedPricingEngine().price(
            request(contract_for(banded_tariff), ConsumptionProfile(profile_id="empty"))
        )

    bad_flat = ChargeRule.model_construct(
        code="bad-flat",
        description="bad-flat",
        basis=ChargeBasis.FLAT,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY),
        discount=False,
        conditions=(),
        provenance=(),
        band=None,
        validity=None,
    )
    bad_flat_tariff = FixedTariff.model_construct(
        tariff_id="bad-flat-tariff",
        validity=PERIOD,
        prices=(
            BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),
        ),
        fixed_charges=(bad_flat,),
        additional_charges=(),
        discounts=(),
        conditions=(),
        provenance=(),
    )
    with pytest.raises(FixedPricingError, match="requires Money"):
        FixedPricingEngine().price(
            request(contract_for(bad_flat_tariff), ConsumptionProfile(profile_id="empty"))
        )


def test_indexed_tariffs_are_rejected_and_tariff_validity_is_checked() -> None:
    indexed = IndexedTariff(
        tariff_id="indexed",
        validity=PERIOD,
        granularity=Granularity.DAY,
        formulas=(
            BandFormula(
                band="ALL",
                expression=IndexReference(
                    index_code="PUN",
                    unit=RateUnit.EUR_PER_KWH,
                    granularity=Granularity.DAY,
                ),
            ),
        ),
    )
    indexed_contract = Contract(
        contract_id="indexed-contract",
        supply=SupplyPoint(supply_id="pod", market_zone="NORD"),
        tariff=indexed,
        validity=PERIOD,
    )
    with pytest.raises(FixedPricingError, match="fixed tariff"):
        FixedPricingEngine().price(
            request(indexed_contract, ConsumptionProfile(profile_id="empty"))
        )

    broad = DatePeriod(start=date(2025, 1, 1), end=date(2027, 1, 1))
    narrow = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 4))
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        validity=narrow,
    )
    with pytest.raises(FixedPricingError, match="tariff validity"):
        FixedPricingEngine().price(
            request(
                contract_for(fixed, validity=broad), ConsumptionProfile(profile_id="empty"), broad
            )
        )


def test_charge_validity_and_partial_bucket_are_checked() -> None:
    charge_period = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 3))
    rule = ChargeRule(
        code="limited",
        description="limited",
        basis=ChargeBasis.PER_KWH,
        value=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH),
        validity=charge_period,
    )
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        additional_charges=(rule,),
    )
    profile = ConsumptionProfile(
        profile_id="limited",
        buckets=(bucket(date(2026, 1, 1), "3"), bucket(date(2026, 1, 2), "2")),
    )
    result = FixedPricingEngine().price(request(contract_for(fixed), profile))
    assert result.breakdown.total.amount == Decimal("2.00")

    crossing = ConsumptionBucket(
        interval=TimeInterval(
            start=datetime(2026, 1, 1, 23, tzinfo=ROME),
            end=datetime(2026, 1, 2, 1, tzinfo=ROME),
        ),
        energy=EnergyQuantity(kwh=Decimal("1")),
        granularity=Granularity.HOUR,
    )
    with pytest.raises(FixedPricingError, match="cuts through"):
        FixedPricingEngine().price(
            request(
                contract_for(fixed),
                ConsumptionProfile(profile_id="cross-charge", buckets=(crossing,)),
            )
        )

    no_overlap = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2))
    result = FixedPricingEngine().price(
        request(
            contract_for(fixed),
            ConsumptionProfile(profile_id="no-overlap"),
            no_overlap,
        )
    )
    assert result.breakdown.components == ()


@pytest.mark.parametrize(
    "basis", [ChargeBasis.PER_MONTH, ChargeBasis.PER_PERIOD, ChargeBasis.PERCENTAGE]
)
def test_unsupported_charge_bases_and_inputs_are_rejected(basis: ChargeBasis) -> None:
    value: Money | UnitRate = (
        Money(amount=Decimal("1"))
        if basis == ChargeBasis.PER_PERIOD
        else UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_DAY)
    )
    rule = ChargeRule(code="unsupported", description="unsupported", basis=basis, value=value)
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(rule,),
    )
    with pytest.raises(FixedPricingError, match="not supported"):
        FixedPricingEngine().price(
            request(contract_for(fixed), ConsumptionProfile(profile_id="empty"))
        )

    with pytest.raises(FixedPricingError, match="market data"):
        FixedPricingEngine().price(
            request(
                contract_for(
                    tariff(
                        (
                            BandPrice(
                                band="ALL",
                                rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH),
                            ),
                        )
                    )
                ),
                ConsumptionProfile(profile_id="empty"),
                market_data=MarketData(),
            )
        )
    parameter = RegulatoryParameter(
        code="VAT",
        value=Decimal("22"),
        unit="percent",
        validity=PERIOD,
    )
    with pytest.raises(FixedPricingError, match="regulatory"):
        FixedPricingEngine().price(
            request(
                contract_for(
                    tariff(
                        (
                            BandPrice(
                                band="ALL",
                                rate=UnitRate(amount=Decimal("0"), unit=RateUnit.EUR_PER_KWH),
                            ),
                        )
                    )
                ),
                ConsumptionProfile(profile_id="empty"),
                regulatory_parameters=(parameter,),
            )
        )


def test_flat_charge_is_applied_once_when_period_is_partitioned() -> None:
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 3))
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("1"), unit=RateUnit.EUR_PER_KWH)),),
        fixed_charges=(
            ChargeRule(
                code="activation",
                description="activation",
                basis=ChargeBasis.FLAT,
                value=Money(amount=Decimal("5")),
            ),
        ),
        validity=period,
    )
    profile = ConsumptionProfile(
        profile_id="partition",
        buckets=(
            bucket(date(2026, 1, 1), "1"),
            bucket(date(2026, 1, 2), "2"),
        ),
    )
    full = FixedPricingEngine().price(
        request(contract_for(fixed, validity=period), profile, period)
    )
    first_period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2))
    second_period = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 3))
    first = FixedPricingEngine().price(
        request(contract_for(fixed, validity=period), profile, first_period)
    )
    second = FixedPricingEngine().price(
        request(contract_for(fixed, validity=period), profile, second_period)
    )
    assert full.breakdown.total.amount == Decimal("8.00")
    assert first.breakdown.total.amount + second.breakdown.total.amount == Decimal("8.00")
    assert [component.code for component in first.breakdown.components].count(
        "fixed:activation"
    ) == 1
    assert [component.code for component in second.breakdown.components].count(
        "fixed:activation"
    ) == 0


def test_discount_sign_and_charge_value_invariants() -> None:
    with pytest.raises(ValidationError, match="non-positive"):
        ChargeRule(
            code="bad-discount",
            description="bad",
            basis=ChargeBasis.FLAT,
            value=Money(amount=Decimal("1")),
            discount=True,
        )
    with pytest.raises(ValidationError, match="non-negative"):
        ChargeRule(
            code="bad-charge",
            description="bad",
            basis=ChargeBasis.FLAT,
            value=Money(amount=Decimal("-1")),
        )


@given(st.integers(min_value=0, max_value=100), st.integers(min_value=0, max_value=100))
def test_variable_energy_cost_is_additive_when_period_is_partitioned(
    first_kwh: int, second_kwh: int
) -> None:
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 3))
    first_period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 2))
    second_period = DatePeriod(start=date(2026, 1, 2), end=date(2026, 1, 3))
    fixed = tariff(
        (BandPrice(band="ALL", rate=UnitRate(amount=Decimal("0.20"), unit=RateUnit.EUR_PER_KWH)),),
        validity=period,
    )
    contract = contract_for(fixed, validity=period)
    profile = ConsumptionProfile(
        profile_id="property",
        buckets=(
            bucket(date(2026, 1, 1), str(first_kwh)),
            bucket(date(2026, 1, 2), str(second_kwh)),
        ),
    )
    engine = FixedPricingEngine()
    full = engine.price(request(contract, profile, period))
    first = engine.price(request(contract, profile, first_period))
    second = engine.price(request(contract, profile, second_period))
    assert full.breakdown.total.amount == (
        first.breakdown.total.amount + second.breakdown.total.amount
    )
