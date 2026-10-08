from __future__ import annotations

import urllib.error
import urllib.request
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import pytest

import italian_energy.integration.regulatory_acquisition as acquisition


class _Response:
    def __init__(
        self, url: str, content: bytes, content_type: str = "application/octet-stream"
    ) -> None:
        self._url = url
        self._content = content
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _size: int) -> bytes:
        return self._content


def test_regulatory_source_fetch_enforces_host_redirect_and_size_guards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = "https://www.arera.it/source.pdf"
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response(source, b"official bytes"),
    )
    assert acquisition.fetch_official_source(source) == b"official bytes"

    with pytest.raises(ValueError, match="allowlisted official HTTPS host"):
        acquisition.fetch_official_source("http://example.com/source.pdf")

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response("https://example.com/source.pdf", b"bytes"),
    )
    with pytest.raises(ValueError, match="redirected outside"):
        acquisition.fetch_official_source(source)

    monkeypatch.setattr(acquisition, "_MAX_SOURCE_BYTES", 2)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response(source, b""),
    )
    with pytest.raises(ValueError, match="empty or exceeds"):
        acquisition.fetch_official_source(source)

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response(source, b"long"),
    )
    with pytest.raises(ValueError, match="empty or exceeds"):
        acquisition.fetch_official_source(source)

    def offline(_request: Any, timeout: float) -> _Response:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", offline)
    with pytest.raises(ValueError, match="acquisition failed"):
        acquisition.fetch_official_source(source)


def test_source_snapshot_freezes_raw_digest_url_and_aware_fetch_time() -> None:
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    snapshot = acquisition.acquire_official_source_snapshot(
        "https://www.arera.it/index",
        fetch_source=lambda _url: b"synthetic index bytes",
        clock=lambda: now,
    )

    assert snapshot.url == "https://www.arera.it/index"
    assert snapshot.body == b"synthetic index bytes"
    assert snapshot.sha256 == sha256(snapshot.body).hexdigest()
    assert snapshot.fetched_at == now
    assert snapshot.final_url == snapshot.url
    assert snapshot.content_type == "application/octet-stream"
    assert snapshot.byte_length == len(snapshot.body)


def test_source_snapshot_records_redirect_mime_and_exact_byte_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested = "https://www.arera.it/source"
    final = "https://www.arera.it/files/source.xlsx"
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda _request, timeout: _Response(
            final,
            b"exact official bytes",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    )

    snapshot = acquisition.acquire_official_source_snapshot(
        requested,
        clock=lambda: datetime(2026, 9, 30, 12, tzinfo=UTC),
    )

    assert snapshot.url == requested
    assert snapshot.final_url == final
    assert snapshot.content_type == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert snapshot.byte_length == len(b"exact official bytes")
    assert snapshot.sha256 == sha256(snapshot.body).hexdigest()


def test_source_snapshot_rejects_insecure_url_and_naive_clock() -> None:
    with pytest.raises(ValueError, match="allowlisted official HTTPS host"):
        acquisition.acquire_official_source_snapshot(
            "http://example.com/index",
            fetch_source=lambda _url: b"bytes",
            clock=lambda: datetime(2026, 9, 30),
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        acquisition.acquire_official_source_snapshot(
            "https://www.arera.it/index",
            fetch_source=lambda _url: b"bytes",
            clock=lambda: datetime(2026, 9, 30),
        )
