"""Explicit live acquisition and digest verification for regulatory anchors."""

from __future__ import annotations

import hashlib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlsplit

from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.integration.projected import RegulatorySourceDigestCheck

_MAX_SOURCE_BYTES = 24_000_000
_OFFICIAL_HOSTS = {
    "adm.gov.it",
    "www.adm.gov.it",
    "arera.it",
    "www.arera.it",
    "gazzettaufficiale.it",
    "www.gazzettaufficiale.it",
    "gme.mercatoelettrico.org",
    "normattiva.it",
    "www.normattiva.it",
}


@dataclass(frozen=True, slots=True)
class OfficialHTTPResponse:
    """Exact bounded HTTP response metadata and bytes from an official source."""

    requested_url: str
    final_url: str
    content_type: str
    body: bytes
    fetched_at: datetime


def fetch_official_source_response(url: str) -> OfficialHTTPResponse:
    """Fetch bytes and transport provenance from an allowlisted official HTTPS host."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
        raise ValueError("projection source URL is not on an allowlisted official HTTPS host")
    request = urllib.request.Request(
        url, headers={"User-Agent": "italian-energy-core/0.13", "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            final = urlsplit(final_url)
            if final.scheme != "https" or final.hostname not in _OFFICIAL_HOSTS:
                raise ValueError("official source redirected outside an official HTTPS host")
            content = cast(bytes, response.read(_MAX_SOURCE_BYTES + 1))
            headers = getattr(response, "headers", None)
            content_type = (
                headers.get("Content-Type", "application/octet-stream")
                if headers is not None
                else "application/octet-stream"
            )
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("official source acquisition failed") from exc
    if not content or len(content) > _MAX_SOURCE_BYTES:
        raise ValueError("official source response is empty or exceeds the supported size")
    if not isinstance(content_type, str) or not content_type.strip():
        raise ValueError("official source response has no valid content type")
    return OfficialHTTPResponse(
        requested_url=url,
        final_url=final_url,
        content_type=content_type,
        body=content,
        fetched_at=datetime.now(UTC),
    )


def fetch_official_source(url: str) -> bytes:
    """Fetch bounded bytes from an allowlisted official HTTPS host."""

    return fetch_official_source_response(url).body


def acquire_official_source_snapshot(
    url: str,
    fetch_source: Callable[[str], bytes] | None = None,
    clock: Callable[[], datetime] | None = None,
) -> AcquiredOfficialBytes:
    """Fetch an official index/document and freeze its raw digest and time."""

    if fetch_source is None:
        response = fetch_official_source_response(url)
        content = response.body
        final_url = response.final_url
        content_type = response.content_type
        fetched_at = response.fetched_at
    else:
        content = fetch_source(url)
        final_url = url
        content_type = "application/octet-stream"
        now = clock or (lambda: datetime.now(UTC))
        fetched_at = now()
    if clock is not None:
        fetched_at = clock()
    return AcquiredOfficialBytes(
        url=url,
        body=content,
        sha256=hashlib.sha256(content).hexdigest(),
        fetched_at=fetched_at,
        final_url=final_url,
        content_type=content_type,
        byte_length=len(content),
    )


def verify_anchor_source_digests(
    anchor: DomesticProjectionAnchor,
    fetch_source: Callable[[str], bytes] = fetch_official_source,
    clock: Callable[[], datetime] | None = None,
) -> tuple[RegulatorySourceDigestCheck, ...]:
    """Download every source listed by an anchor and return typed digest checks."""
    now = clock or (lambda: datetime.now(UTC))
    checks: list[RegulatorySourceDigestCheck] = []
    for source in anchor.sources:
        checked_at = now()
        try:
            content = fetch_source(source.url)
        except (OSError, ValueError):
            observed_sha256 = None
        else:
            observed_sha256 = hashlib.sha256(content).hexdigest()
        checks.append(
            RegulatorySourceDigestCheck(
                source_id=source.source_id,
                expected_sha256=source.sha256,
                observed_sha256=observed_sha256,
                checked_at=checked_at,
            )
        )
    return tuple(checks)


__all__ = [
    "AcquiredOfficialBytes",
    "OfficialHTTPResponse",
    "acquire_official_source_snapshot",
    "fetch_official_source",
    "fetch_official_source_response",
    "verify_anchor_source_digests",
]
