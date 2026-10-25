import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from italian_energy.domain.provenance import Provenance
from italian_energy.provenance import canonical_provenance, merge_provenance, provenance_scope


def source(identifier: str = "a") -> Provenance:
    return Provenance(
        source="test",
        source_identifier=identifier,
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_ordered_merge_preserves_value_equality_and_first_object() -> None:
    first = source()
    equal = first.model_copy(deep=True)
    different = source("b")
    timezone_equal = first.model_copy(
        update={"retrieved_at": datetime(2026, 1, 1, 1, tzinfo=timezone(timedelta(hours=1)))}
    )
    assert first == timezone_equal
    for scoped in (False, True):
        with provenance_scope() if scoped else nullcontext():
            merged = merge_provenance((first, different), (equal, timezone_equal))
            assert merged == (first, different)
            assert merged[0] is first


def test_canonical_merge_matches_original_sort_and_encoding() -> None:
    items = [source("è"), source("b"), source("a"), source("b")]
    expected: dict[bytes, Provenance] = {}
    for item in items:
        key = json.dumps(
            item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        expected.setdefault(key, item)
    with provenance_scope():
        assert merge_provenance(items, canonical=True) == tuple(
            expected[key] for key in sorted(expected)
        )
    assert merge_provenance(()) == ()


def test_serialization_reused_only_inside_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    item = source()
    calls: list[Provenance] = []
    original = Provenance.model_dump

    def observe(self: Provenance, *args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Provenance, "model_dump", observe)
    with provenance_scope():
        first = canonical_provenance(item)
        assert canonical_provenance(item) == first
        assert len(calls) == 1
        with provenance_scope():
            assert canonical_provenance(item) == first
        assert len(calls) == 2
        canonical_provenance(item)
        assert len(calls) == 2
    canonical_provenance(item)
    assert len(calls) == 3


def test_scope_resets_on_error_and_threads_are_independent() -> None:
    item = source()

    def run(_: object) -> bytes:
        with provenance_scope():
            return canonical_provenance(item)

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert len(set(executor.map(run, range(4)))) == 1
    try:
        with provenance_scope():
            canonical_provenance(item)
            raise ValueError("test")
    except ValueError:
        pass
    assert canonical_provenance(item) == run(None)


def test_canonical_request_matches_original_for_pricing_and_billing() -> None:
    from test_billing_artifacts import request as billing_request

    from italian_energy.billing.engine import BillingRequest
    from italian_energy.canonical import canonical_request, serialization_scope
    from italian_energy.pricing.engine import PricingRequest

    billing: BillingRequest = billing_request(resident=True)
    assert billing.rounding_policy is not None
    pricing = PricingRequest(
        contract=billing.contract,
        consumption=billing.consumption,
        period=billing.period,
        rounding_policy=billing.rounding_policy,
    )
    for request in (billing, pricing):
        for excluded in (frozenset(), frozenset({"observed_bill"})):
            expected = json.dumps(
                request.model_dump(mode="json", exclude=set(excluded)),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
            assert canonical_request(request, exclude=excluded) == expected
            with serialization_scope():
                assert canonical_request(request, exclude=excluded) == expected
                assert canonical_request(request, exclude=excluded) == expected


def test_request_fragments_keep_changed_inputs_and_scenarios_distinct() -> None:
    from datetime import date
    from decimal import Decimal

    from test_billing_artifacts import request as billing_request

    from italian_energy.canonical import canonical_request, serialization_scope
    from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
    from italian_energy.domain.money import RateUnit
    from italian_energy.domain.time import Granularity, TimeInterval
    from italian_energy.pricing.engine import PricingRequest

    billing = billing_request(resident=False)
    assert billing.rounding_policy is not None
    provenance = source("fonte è")
    market = MarketData(
        indexes=(
            MarketIndex(
                code="PUN",
                name="PUN",
                unit=RateUnit.EUR_PER_KWH,
                granularity=Granularity.MONTH,
                provenance=(provenance,),
            ),
        ),
        points=(
            MarketDataPoint(
                index_code="PUN",
                value=Decimal("0.10"),
                interval=TimeInterval(
                    start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 2, 1, tzinfo=UTC)
                ),
            ),
        ),
    )
    pricing = PricingRequest(
        contract=billing.contract,
        consumption=billing.consumption,
        period=billing.period,
        rounding_policy=billing.rounding_policy,
        market_data=market,
    )
    changed = pricing.model_copy(update={"market_data": market.model_copy(update={"points": ()})})
    changed_contract = pricing.model_copy(
        update={"contract": billing.contract.model_copy(update={"contract_id": "è-altro"})}
    )
    results = []
    with serialization_scope():
        for request in (
            pricing,
            changed,
            changed_contract,
            billing,
            billing.model_copy(update={"regulatory_projection_as_of": date(2026, 1, 1)}),
            pricing,
        ):
            expected = json.dumps(
                request.model_dump(mode="json"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
            assert canonical_request(request) == expected
            results.append(expected)
    assert len(set(results)) == 5
    assert results[0] == results[-1]


def test_request_cache_does_not_retain_previous_monthly_pricing_result() -> None:
    import gc
    import weakref

    from test_billing_artifacts import request as billing_request

    from italian_energy.canonical import canonical_request, serialization_scope

    baseline = billing_request(resident=True)
    assert baseline.pricing_result is not None
    first = baseline.pricing_result.model_copy(update={"pricing_id": "first"})
    reference = weakref.ref(first)
    first_request = baseline.model_copy(update={"pricing_result": first})
    next_request = baseline.model_copy(
        update={
            "pricing_result": baseline.pricing_result.model_copy(update={"pricing_id": "second"})
        }
    )
    with serialization_scope():
        canonical_request(first_request)
        canonical_request(next_request)
        del first, first_request
        gc.collect()
        assert reference() is None
        excluded = frozenset({"contract", "pricing_result", "observed_bill"})
        expected = json.dumps(
            next_request.model_dump(mode="json", exclude=set(excluded)),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
        assert canonical_request(next_request, exclude=excluded) == expected


def test_request_scope_restores_after_nested_error() -> None:
    from test_billing_artifacts import request as billing_request

    from italian_energy.canonical import canonical_request, serialization_scope

    request = billing_request(resident=True)
    expected = canonical_request(request)
    with serialization_scope():
        assert canonical_request(request) == expected
        with pytest.raises(ValueError, match="nested"), serialization_scope():
            assert canonical_request(request) == expected
            raise ValueError("nested")
        assert canonical_request(request) == expected
    assert canonical_request(request) == expected


def test_warm_value_identity_keeps_first_object_of_each_merge() -> None:
    first = source()
    copy = first.model_copy(deep=True)
    with provenance_scope():
        assert merge_provenance((first,))[0] is first
        assert merge_provenance((copy, first))[0] is copy
        assert merge_provenance((first, copy))[0] is first


def test_canonical_group_reuse_preserves_first_object_and_generator_inputs() -> None:
    first = source("a")
    clone = first.model_copy(deep=True)
    other = source("b")
    left, right = (first, other), (clone,)
    with provenance_scope():
        assert merge_provenance(left, right, canonical=True)[0] is first
        assert merge_provenance(right, left, canonical=True)[0] is clone
        assert merge_provenance(left, right, canonical=True)[0] is first
        assert merge_provenance(iter(right), iter(left), canonical=True)[0] is clone
