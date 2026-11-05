"""Digest-bound human review of changed official documents, without changing anchors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from html.parser import HTMLParser
from typing import Protocol, Self
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.discovery import RegulatoryRegistryChannel
from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.arera.rollover_models import regulatory_anchor_artifact_digest
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.time import DatePeriod

_ROME = ZoneInfo("Europe/Rome")
_SHA = r"^[0-9a-f]{64}$"
_OFFICIAL_HOSTS = frozenset(
    host for channel in RegulatoryRegistryChannel for host in channel.official_hosts
)


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


class SourceRevisionAssessment(StrEnum):
    EQUIVALENT = "equivalent"
    CHANGED = "changed"
    MANUAL_REVIEW = "manual_review"


class SourceRevisionOutcome(StrEnum):
    APPROVE_EQUIVALENT = "approve_equivalent"
    REJECT = "reject"
    REVOKE = "revoke"


class SourceRevisionValue(DomainModel):
    field: str = Field(min_length=1)
    value: Decimal
    unit: str = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def exact_value(cls, value: object) -> Decimal:
        return strict_decimal(value)


class RegulatorySourceRevisionRequest(DomainModel):
    anchor_id: str = Field(min_length=1)
    anchor_sha256: str = Field(pattern=_SHA)
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    document: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=_SHA)
    observed_sha256: str = Field(pattern=_SHA)
    validity: DatePeriod
    detected_at: datetime
    current_values: tuple[SourceRevisionValue, ...]
    observed_values: tuple[SourceRevisionValue, ...] = ()
    assessment: SourceRevisionAssessment = SourceRevisionAssessment.MANUAL_REVIEW
    assessment_detail: str = Field(min_length=1)
    parser_id: str | None = None
    parser_version: str | None = None
    preview_text: str = Field(default="", max_length=12000)

    @field_validator("detected_at")
    @classmethod
    def aware_detection(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source revision detection must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
            raise ValueError("source revision requires an official HTTPS URL")
        if self.expected_sha256 == self.observed_sha256:
            raise ValueError("source revision must identify changed bytes")
        if (self.parser_id is None) != (self.parser_version is None):
            raise ValueError("source revision parser ID and version must be recorded together")
        return self

    @property
    def request_id(self) -> str:
        # The first observation is retained by storage; a later fetch of the same
        # version must not generate another task merely because its clock differs.
        payload = self.model_dump(
            mode="json",
            include={
                "anchor_id",
                "anchor_sha256",
                "source_id",
                "source_url",
                "expected_sha256",
                "observed_sha256",
                "validity",
            },
        )
        return "regulatory-source-revision:" + _digest(payload)


class RegulatorySourceRevisionDecision(DomainModel):
    request: RegulatorySourceRevisionRequest
    outcome: SourceRevisionOutcome
    reviewer: str = Field(min_length=1, max_length=256)
    reviewed_at: datetime
    rationale: str = Field(min_length=1, max_length=4000)
    equivalent_confirmed: bool = Field(default=False, strict=True)
    scope: DatePeriod
    supersedes_decision_id: str | None = Field(default=None, pattern=_SHA)

    @field_validator("reviewed_at")
    @classmethod
    def aware_review(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source revision review must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.reviewed_at < self.request.detected_at:
            raise ValueError("review cannot precede the document observation")
        if not (
            self.request.validity.start
            <= self.scope.start
            < self.scope.end
            <= self.request.validity.end
        ):
            raise ValueError("source revision review cannot extend anchor validity")
        if self.outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT:
            if not self.equivalent_confirmed:
                raise ValueError(
                    "source revision approval requires an explicit equivalence attestation"
                )
            if self.request.assessment == SourceRevisionAssessment.CHANGED:
                raise ValueError("different economic values cannot be approved as equivalent")
            if self.scope.start < self.reviewed_at.astimezone(_ROME).date():
                raise ValueError("source revision approval cannot be retroactive")
        elif self.equivalent_confirmed:
            raise ValueError("negative source decisions cannot attest equivalence")
        if self.outcome == SourceRevisionOutcome.REVOKE and self.supersedes_decision_id is None:
            raise ValueError("revocation must reference the decision it supersedes")
        return self

    @property
    def decision_id(self) -> str:
        return _digest(self.model_dump(mode="json"))


def create_source_revision_decision(
    request: RegulatorySourceRevisionRequest,
    *,
    outcome: SourceRevisionOutcome,
    reviewer: str,
    reviewed_at: datetime,
    rationale: str,
    equivalent_confirmed: bool = False,
    supersedes_decision_id: str | None = None,
) -> RegulatorySourceRevisionDecision:
    day = reviewed_at.astimezone(_ROME).date()
    start = (
        max(request.validity.start, day)
        if outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT
        else request.validity.start
    )
    return RegulatorySourceRevisionDecision(
        request=request,
        outcome=outcome,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        rationale=rationale,
        equivalent_confirmed=equivalent_confirmed,
        scope=DatePeriod(start=start, end=request.validity.end),
        supersedes_decision_id=supersedes_decision_id,
    )


class _TextPreview(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def _values_for_source(
    anchor: DomesticProjectionAnchor, source_id: str
) -> tuple[SourceRevisionValue, ...]:
    values = [
        SourceRevisionValue(field=charge.code, value=charge.value, unit=charge.unit.value)
        for charge in anchor.charges
        if any(ref.source_id == source_id for ref in charge.references)
    ]
    if source_id in anchor.vat_source_ids:
        values.append(
            SourceRevisionValue(field="vat_rate_percent", value=anchor.vat_rate_percent, unit="%")
        )
    if source_id in anchor.excise_source_ids:
        values.append(
            SourceRevisionValue(field="excise_rate", value=anchor.excise_rate, unit="EUR/kWh")
        )
    return tuple(values)


def _assess_vat(
    anchor: DomesticProjectionAnchor,
    source_id: str,
    body: bytes,
    observed_at: datetime,
) -> tuple[
    SourceRevisionAssessment, str, tuple[SourceRevisionValue, ...], str | None, str | None, str
]:
    # Reuse the certified parser, with the exact source metadata and actual fetch
    # clock. An unknown layout is shown for human review, never guessed.
    from italian_energy.arera.discovery import OfficialRegistryRecord
    from italian_energy.arera.official_registry_adapters import (
        OfficialRegistryHTTPResponse,
        OfficialRegulatoryDocumentAcquirer,
    )
    from italian_energy.arera.rollover_parsers import default_regulatory_parser_registry

    source = next(s for s in anchor.sources if s.source_id == source_id)
    try:
        if source.published_at is None:
            raise ValueError("revision source has no publication date")
        vig = date.fromisoformat(source.url.rsplit("!vig=", 1)[1])
        response = OfficialRegistryHTTPResponse(
            source.url, source.url, "text/html", body, observed_at
        )

        class _ObservedTransport:
            def request(self, url: str, **kwargs: object) -> OfficialRegistryHTTPResponse:
                if url != source.url:
                    raise ValueError("revision parser requested another source")
                return response

        document = OfficialRegulatoryDocumentAcquirer(_ObservedTransport()).acquire_document(
            OfficialRegistryRecord(
                channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
                act_id=source.source_identifier,
                title=source.document,
                published_at=source.published_at,
                registry_date=vig,
                url=source.url,
                document_id=source.document,
            )
        )
        parsed = default_regulatory_parser_registry().parse(replace(document, reference_as_of=vig))
        if parsed.facts:
            values = tuple(
                SourceRevisionValue(field="vat_rate_percent", value=f.value, unit=f.unit.value)
                for f in parsed.facts
            )
            same = all(
                f.value == anchor.vat_rate_percent
                and f.validity.start <= anchor.validity.start
                and f.validity.end >= anchor.validity.end
                for f in parsed.facts
            )
            return (
                SourceRevisionAssessment.EQUIVALENT if same else SourceRevisionAssessment.CHANGED,
                "Certified parser extracted the existing domestic VAT interpretation."
                if same
                else "Certified parser extracted different economic values or applicability.",
                values,
                parsed.parser_id,
                parsed.parser_version,
                "\n\n".join(f.raw_value_token for f in parsed.facts)[:12000],
            )
        detail = parsed.detail
    except (ValueError, IndexError, UnicodeError):
        detail = (
            "The existing parser cannot certify this version; explicit human review is required."
        )
    return SourceRevisionAssessment.MANUAL_REVIEW, detail, (), None, None, ""


def observe_source_revision(
    anchor: DomesticProjectionAnchor,
    source_id: str,
    body: bytes,
    *,
    observed_at: datetime,
) -> RegulatorySourceRevisionRequest | None:
    source = next((s for s in anchor.sources if s.source_id == source_id), None)
    if source is None or source.sha256 is None:
        raise ValueError("source revision requires a known digest-bound anchor source")
    if not body or len(body) > 24_000_000:
        raise ValueError("source revision bytes are empty or too large")
    observed = hashlib.sha256(body).hexdigest()
    if observed == source.sha256:
        return None
    assessment = SourceRevisionAssessment.MANUAL_REVIEW
    detail = (
        "Raw document bytes changed; the administrator must verify "
        "the existing economic interpretation."
    )
    values: tuple[SourceRevisionValue, ...] = ()
    parser_id: str | None = None
    parser_version: str | None = None
    preview = ""
    if source_id in {"vat_dpr_633", "vat_dpr_633_art16"}:
        assessment, detail, values, parser_id, parser_version, preview = _assess_vat(
            anchor, source_id, body, observed_at
        )
    if not preview and body.lstrip().startswith((b"<", b"<!")):
        parsed = _TextPreview()
        parsed.feed(body.decode("utf-8", errors="replace"))
        preview = " ".join(" ".join(parsed.parts).split())[:12000]
    return RegulatorySourceRevisionRequest(
        anchor_id=anchor.anchor_id,
        anchor_sha256=regulatory_anchor_artifact_digest(anchor),
        source_id=source_id,
        source_url=source.url,
        source_label=source.source,
        document=source.document,
        expected_sha256=source.sha256,
        observed_sha256=observed,
        validity=anchor.validity,
        detected_at=observed_at,
        current_values=_values_for_source(anchor, source_id),
        observed_values=values,
        assessment=assessment,
        assessment_detail=detail,
        parser_id=parser_id,
        parser_version=parser_version,
        preview_text=preview,
    )


class SourceRevisionCheck(Protocol):
    @property
    def source_id(self) -> str: ...

    @property
    def expected_sha256(self) -> str: ...

    @property
    def observed_sha256(self) -> str | None: ...

    @property
    def checked_at(self) -> datetime: ...


def source_revision_approval_matches(
    anchor: DomesticProjectionAnchor,
    check: SourceRevisionCheck,
    decision: RegulatorySourceRevisionDecision,
    *,
    current_request: RegulatorySourceRevisionRequest | None,
    as_of: date,
    checked_at: datetime,
) -> bool:
    request = decision.request
    source = next((s for s in anchor.sources if s.source_id == check.source_id), None)
    return bool(
        source is not None
        and current_request is not None
        and current_request.request_id == request.request_id
        and current_request.assessment != SourceRevisionAssessment.CHANGED
        and current_request.detected_at <= check.checked_at
        and source.sha256 is not None
        and decision.outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT
        and decision.equivalent_confirmed is True
        and request.assessment != SourceRevisionAssessment.CHANGED
        and request.anchor_id == anchor.anchor_id
        and request.anchor_sha256 == regulatory_anchor_artifact_digest(anchor)
        and request.source_id == source.source_id
        and request.source_url == source.url
        and request.expected_sha256 == source.sha256 == check.expected_sha256
        and request.observed_sha256 == check.observed_sha256
        and request.validity == anchor.validity
        and request.detected_at <= decision.reviewed_at <= check.checked_at <= checked_at
        and decision.reviewed_at.astimezone(_ROME).date() <= as_of
        and request.validity.start
        <= decision.scope.start
        <= as_of
        < decision.scope.end
        <= request.validity.end
    )


__all__ = [
    "RegulatorySourceRevisionDecision",
    "RegulatorySourceRevisionRequest",
    "SourceRevisionAssessment",
    "SourceRevisionOutcome",
    "SourceRevisionValue",
    "create_source_revision_decision",
    "observe_source_revision",
    "source_revision_approval_matches",
]
