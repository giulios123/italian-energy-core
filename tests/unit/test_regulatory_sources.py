from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from italian_energy.arera.rollover_sources import AcquiredOfficialBytes

_URL = "https://www.arera.it/acts/fixture"
_BODY = b"official-source-fixture"
_FETCHED_AT = datetime(2026, 10, 4, 10, tzinfo=UTC)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"url": "https://untrusted.example/document"}, "allowlisted official HTTPS host"),
        ({"body": b""}, "empty or exceed the supported size"),
        ({"sha256": "0" * 64}, "digest does not match"),
        ({"fetched_at": datetime(2026, 10, 4, 10)}, "must be timezone-aware"),
        ({"final_url": "https://untrusted.example/redirect"}, "allowlisted official HTTPS host"),
        ({"content_type": " "}, "content type cannot be empty"),
        ({"byte_length": len(_BODY) + 1}, "byte length does not match"),
    ],
)
def test_raw_source_snapshot_rejects_invalid_provenance(
    overrides: dict[str, object], message: str
) -> None:
    values: dict[str, object] = {
        "url": _URL,
        "body": _BODY,
        "sha256": hashlib.sha256(_BODY).hexdigest(),
        "fetched_at": _FETCHED_AT,
    }
    values.update(overrides)

    with pytest.raises(ValueError, match=message):
        AcquiredOfficialBytes(**values)  # type: ignore[arg-type]


def test_raw_source_snapshot_freezes_exact_byte_length_and_final_url() -> None:
    source = AcquiredOfficialBytes(
        url=_URL,
        body=_BODY,
        sha256=hashlib.sha256(_BODY).hexdigest(),
        fetched_at=_FETCHED_AT,
    )

    assert source.byte_length == len(_BODY)
    assert source.final_url == _URL
