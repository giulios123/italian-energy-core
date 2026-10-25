"""Reuse immutable provenance serialization and equality within one comparison."""

import json
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from italian_energy.domain.provenance import Provenance


@dataclass
class _ProvenanceCache:
    serializations: dict[int, tuple[Provenance, bytes]] = field(default_factory=dict)
    identities: dict[int, tuple[Provenance, int]] = field(default_factory=dict)
    values: dict[Provenance, int] = field(default_factory=dict)
    groups: list[tuple[tuple[Provenance, ...], dict[bytes, Provenance]] | None] = field(
        default_factory=lambda: [None] * 256
    )


_cache: ContextVar[_ProvenanceCache | None] = ContextVar("provenance_cache", default=None)


@contextmanager
def provenance_scope() -> Iterator[None]:
    """Give each call its own cache, including nested calls and exceptions."""
    token = _cache.set(_ProvenanceCache())
    try:
        yield
    finally:
        _cache.reset(token)


def canonical_provenance(item: Provenance) -> bytes:
    cache = _cache.get()
    if cache is not None:
        cached = cache.serializations.get(id(item))
        if cached is not None:
            return cached[1]
    key = json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    if cache is not None:
        # Retain the object so IDs cannot be recycled inside the scope.
        cache.serializations[id(item)] = (item, key)
    return key


def merge_provenance(
    *groups: Iterable[Provenance], canonical: bool = False
) -> tuple[Provenance, ...]:
    """Preserve either first-seen model equality or canonical JSON ordering."""
    cache = _cache.get()
    if canonical:
        encoded_groups: list[dict[bytes, Provenance]] = []
        for group in groups:
            slot = (id(group) >> 4) % 256
            known_group = cache.groups[slot] if cache is not None else None
            if isinstance(group, tuple) and known_group is not None and known_group[0] is group:
                encoded_groups.append(known_group[1])
                continue
            encoded: dict[bytes, Provenance] = {}
            for item in group:
                encoded.setdefault(canonical_provenance(item), item)
            if cache is not None and isinstance(group, tuple):
                cache.groups[slot] = (group, encoded)
            encoded_groups.append(encoded)
        by_json: dict[bytes, Provenance] = {}
        # Sorting determines final order; reverse updates retain the first input object.
        for encoded in reversed(encoded_groups):
            by_json.update(encoded)
        return tuple(by_json[key] for key in sorted(by_json))
    if cache is None:
        return tuple(dict.fromkeys(item for group in groups for item in group))
    by_value: dict[int, Provenance] = {}
    for group in groups:
        for item in group:
            known = cache.identities.get(id(item))
            if known is None:
                identity = cache.values.setdefault(item, len(cache.values))
                cache.identities[id(item)] = (item, identity)
            else:
                identity = known[1]
            by_value.setdefault(identity, item)
    return tuple(by_value.values())
