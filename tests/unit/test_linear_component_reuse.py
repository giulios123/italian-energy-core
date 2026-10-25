"""Projected linear reuse must preserve complete bills and all varying inputs."""

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, NoReturn

import pytest
from test_billing_artifacts import request as billing_request
from test_projected_contract import AS_OF, _request
from test_projected_service import _catalog, _coverage, _history, _indexed_request

from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.billing.regulatory import RegulatoryBillingEngine, linear_component_scope
from italian_energy.domain.costs import CostComponent
from italian_energy.domain.money import EnergyQuantity, Power, RoundingPolicy
from italian_energy.integration import ProjectedDomesticEnergyService


class UncachedBilling(RegulatoryBillingEngine):
    pass


@pytest.mark.parametrize("indexed", [False, True])
def test_projection_is_identical_to_uncached_billing(
    indexed: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    counts: Counter[str] = Counter()
    original = RegulatoryBillingEngine._linear_component

    def observe(self: RegulatoryBillingEngine, *args: Any, **kwargs: Any) -> CostComponent:
        counts[type(self).__name__] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(RegulatoryBillingEngine, "_linear_component", observe)
    cached = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    uncached = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    uncached._billing = UncachedBilling()
    request = _indexed_request() if indexed else _request()
    anchor = load_domestic_projection_anchor()
    args = (request, _catalog(AS_OF), _history(AS_OF), anchor, _coverage(anchor, AS_OF))
    expected = uncached.compare(*args)
    actual = cached.compare(*args)
    assert actual.model_dump_json() == expected.model_dump_json()
    assert counts["RegulatoryBillingEngine"] < counts["UncachedBilling"] / 2
    before = counts["RegulatoryBillingEngine"]
    assert cached.compare(*args).model_dump_json() == expected.model_dump_json()
    assert counts["RegulatoryBillingEngine"] == before * 2


def test_changed_monthly_inputs_are_never_reused_incorrectly() -> None:
    engine, reference = RegulatoryBillingEngine(), UncachedBilling()
    resident = billing_request(resident=True)
    nonresident = billing_request(resident=False)
    assert resident.rounding_policy is not None
    first_bucket = resident.consumption.buckets[0]
    changed_consumption = resident.consumption.model_copy(
        update={
            "buckets": (
                first_bucket.model_copy(update={"energy": EnergyQuantity(kwh=Decimal("200"))}),
            )
        }
    )
    changed_supply = resident.contract.supply.model_copy(
        update={"contracted_power": Power(kw=Decimal("6"))}
    )
    requests = [
        resident,
        nonresident,
        resident.model_copy(update={"consumption": changed_consumption}),
        resident.model_copy(
            update={"contract": resident.contract.model_copy(update={"supply": changed_supply})}
        ),
        resident.model_copy(
            update={"rounding_policy": RoundingPolicy(scale=3, mode=resident.rounding_policy.mode)}
        ),
        resident,
    ]
    with linear_component_scope():
        for request in requests:
            assert (
                engine.evaluate(request).model_dump_json()
                == reference.evaluate(request).model_dump_json()
            )
    assert (
        engine.evaluate(resident).model_dump_json()
        == reference.evaluate(resident).model_dump_json()
    )


def test_failures_are_retried_and_scope_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = RegulatoryBillingEngine()
    request = billing_request(resident=True)
    calls = 0

    def fail(*args: object, **kwargs: object) -> NoReturn:
        nonlocal calls
        calls += 1
        raise ValueError("linear failed")

    monkeypatch.setattr(RegulatoryBillingEngine, "_linear_component", fail)
    with linear_component_scope():
        for _ in range(2):
            with pytest.raises(ValueError, match="linear failed"):
                engine.evaluate(request)
    assert calls == 2


def test_linear_cache_varies_measure_rule_window_period_and_parameter_provenance() -> None:
    from datetime import date

    from test_billing import PERIOD, SOURCE, linear, request, ruleset

    from italian_energy.domain.money import RateUnit, UnitRate
    from italian_energy.domain.regulatory import (
        BillingBasis,
        BillingMeasure,
        BillingMeasureUnit,
        RegulatoryParameter,
        VerificationStatus,
    )
    from italian_energy.domain.time import DatePeriod

    rule = linear(
        "reactive",
        BillingBasis.PER_KVARH,
        UnitRate(amount=Decimal("0.12345"), unit=RateUnit.EUR_PER_KVARH),
        measure_code="m",
    )
    rule = rule.model_copy(update={"parameter_codes": ("r",)})
    parameter = RegulatoryParameter(
        code="r",
        value=Decimal("1"),
        unit="EUR/kvarh",
        validity=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    measure = BillingMeasure(
        code="m",
        value=Decimal("10"),
        unit=BillingMeasureUnit.KVARH,
        period=PERIOD,
        status=VerificationStatus.VERIFIED,
        provenance=(SOURCE,),
    )
    base = request(
        rules=(rule,), measures=(measure,), rule_set=ruleset(rule, parameters=(parameter,))
    )
    assert base.rounding_policy is not None
    half = DatePeriod(start=date(2026, 1, 1), end=date(2026, 1, 16))
    new_source = SOURCE.model_copy(update={"source_identifier": "different-parameter"})
    changed_parameter = parameter.model_copy(update={"provenance": (new_source,)})
    changed_rule = rule.model_copy(
        update={"value": UnitRate(amount=Decimal("2"), unit=RateUnit.EUR_PER_KVARH)}
    )
    cases = [
        (base, rule, PERIOD, (parameter,)),
        (
            base.model_copy(
                update={"measurements": (measure.model_copy(update={"value": Decimal("20")}),)}
            ),
            rule,
            PERIOD,
            (parameter,),
        ),
        (base, rule, half, (parameter,)),
        (base.model_copy(update={"period": half}), rule, half, (parameter,)),
        (base, rule, PERIOD, (changed_parameter,)),
        (base, changed_rule, PERIOD, (parameter,)),
        (base, rule, PERIOD, (parameter,)),
    ]
    engine, reference = RegulatoryBillingEngine(), UncachedBilling()
    outputs = []
    with linear_component_scope():
        for current, current_rule, window, parameters in cases:
            buckets = engine._selected_buckets(current)
            result = engine._linear_component_reusing(
                current, current_rule, window, buckets, base.rounding_policy, parameters
            )
            expected = reference._linear_component(
                current, current_rule, window, buckets, base.rounding_policy, parameters
            )
            assert result.model_dump_json() == expected.model_dump_json()
            outputs.append(result.model_dump_json())
        assert len(set(outputs)) == 5
        missing = base.model_copy(update={"measurements": ()})
        with pytest.raises(ValueError, match="missing"):
            engine._linear_component_reusing(
                missing,
                rule,
                PERIOD,
                engine._selected_buckets(missing),
                base.rounding_policy,
                (parameter,),
            )
