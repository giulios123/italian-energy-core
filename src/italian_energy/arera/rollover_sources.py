"""Immutable acquisition bytes used by the regulatory rollover parsers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlsplit

_MAX_SOURCE_BYTES = 24_000_000
_OFFICIAL_HOSTS = frozenset(
    {
        "adm.gov.it",
        "www.adm.gov.it",
        "arera.it",
        "www.arera.it",
        "gazzettaufficiale.it",
        "www.gazzettaufficiale.it",
        "gme.mercatoelettrico.org",
        "normattiva.it",
        "www.normattiva.it",
        "api.normattiva.it",
    }
)


@dataclass(frozen=True, slots=True)
class AcquiredOfficialBytes:
    """Raw official-source observation; raw bytes stay outside Core envelopes."""

    url: str
    body: bytes
    sha256: str
    fetched_at: datetime
    final_url: str | None = None
    content_type: str = "application/octet-stream"
    byte_length: int | None = None

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
            raise ValueError("acquired source URL is not on an allowlisted official HTTPS host")
        if not self.body or len(self.body) > _MAX_SOURCE_BYTES:
            raise ValueError("acquired source bytes are empty or exceed the supported size")
        if hashlib.sha256(self.body).hexdigest() != self.sha256:
            raise ValueError("acquired source digest does not match its bytes")
        if self.fetched_at.tzinfo is None or self.fetched_at.utcoffset() is None:
            raise ValueError("acquired source fetched_at must be timezone-aware")
        resolved_final_url = self.final_url or self.url
        final = urlsplit(resolved_final_url)
        if final.scheme != "https" or final.hostname not in _OFFICIAL_HOSTS:
            raise ValueError("acquired final URL is not on an allowlisted official HTTPS host")
        if not self.content_type.strip():
            raise ValueError("acquired source content type cannot be empty")
        if self.byte_length is not None and self.byte_length != len(self.body):
            raise ValueError("acquired source byte length does not match its bytes")
        object.__setattr__(self, "final_url", resolved_final_url)
        object.__setattr__(self, "byte_length", len(self.body))


__all__ = ["AcquiredOfficialBytes"]
