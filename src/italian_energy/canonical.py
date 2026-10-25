"""Byte-identical canonical request JSON with call-scoped immutable fragments."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from italian_energy.domain.base import DomainModel

_REUSABLE = frozenset(
    {
        "contract",
        "consumption",
        "market_data",
        "classification",
        "rule_set",
        "rounding_policy",
        "pricing_result",
    }
)
_fragments: ContextVar[
    dict[tuple[type[DomainModel], str, int], tuple[DomainModel, bytes]] | None
] = ContextVar("request_fragments", default=None)


@contextmanager
def serialization_scope() -> Iterator[None]:
    token = _fragments.set({})
    try:
        yield
    finally:
        _fragments.reset(token)


def _encode(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


@lru_cache(maxsize=64)
def _field_prefix(name: str) -> bytes:
    # Only schema field names; no request values or economic data live globally.
    return _encode(name) + b":"


def canonical_request(request: DomainModel, *, exclude: frozenset[str] = frozenset()) -> bytes:
    cache = _fragments.get()
    if cache is None:
        return _encode(request.model_dump(mode="json", exclude=set(exclude)))
    encoded: dict[str, bytes] = {}
    reusable: dict[str, tuple[tuple[type[DomainModel], str, int], DomainModel]] = {}
    for name in _REUSABLE - exclude:
        value = getattr(request, name, None)
        if isinstance(value, DomainModel):
            key = (type(request), name, 0 if name == "pricing_result" else id(value))
            reusable[name] = (key, value)
            cached = cache.get(key)
            if cached is not None and cached[0] is value:
                encoded[name] = cached[1]
    payload = request.model_dump(mode="json", exclude=set(exclude) | encoded.keys())
    for name, value in payload.items():
        encoded[name] = _encode(value)
        if name in reusable:
            key, model = reusable[name]
            cache[key] = (model, encoded[name])
    return b"{" + b",".join(_field_prefix(name) + encoded[name] for name in sorted(encoded)) + b"}"
