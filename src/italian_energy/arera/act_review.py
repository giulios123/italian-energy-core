"""Version-bound administrative interpretation of otherwise unsupported official acts."""

from __future__ import annotations

import hashlib
from datetime import date, datetime
from typing import Self
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.discovery import OfficialRegistryRecord, RegulatoryRegistryChannel
from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.arera.rollover_models import regulatory_anchor_artifact_digest
from italian_energy.arera.source_revision import SourceRevisionOutcome, _digest
from italian_energy.domain.base import DomainModel
from italian_energy.domain.time import DatePeriod

_SHA = r"^[0-9a-f]{64}$"
_ROME = ZoneInfo("Europe/Rome")


def act_document_url(record: OfficialRegistryRecord) -> str:
    """Resolve the identified act, never GET the Normattiva POST search endpoint."""
    if record.channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES:
        version = record.registry_date or record.published_at
        return (
            f"https://www.normattiva.it/eli/id/{record.published_at:%Y/%m/%d}/"
            f"{quote(record.document_id, safe='')}/CONSOLIDATED/{version:%Y%m%d}"
        )
    return record.url


class RegulatoryActReviewRequest(DomainModel):
    anchor_id: str = Field(min_length=1)
    anchor_sha256: str = Field(pattern=_SHA)
    record: OfficialRegistryRecord
    validity: DatePeriod
    detected_at: datetime
    document_sha256: str | None = Field(default=None, pattern=_SHA)
    source_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    observed_sha256: str = Field(pattern=_SHA)

    @field_validator("detected_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.utcoffset() is None:
            raise ValueError("act observation must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_identity(self) -> Self:
        if (self.record.registry_date or self.record.published_at) > self.detected_at.astimezone(
            _ROME
        ).date():
            raise ValueError("act registry observation cannot be from the future")
        if self.source_id != f"{self.record.channel.value}:{self.record.act_id}":
            raise ValueError("act source must match the exact registry record")
        if self.source_url != act_document_url(self.record):
            raise ValueError("act URL must identify the exact official record")
        if self.observed_sha256 != _digest(
            {
                "record": self.record.model_dump(mode="json"),
                "document_sha256": self.document_sha256,
            }
        ):
            raise ValueError("act observation digest does not match its evidence")
        return self

    @property
    def request_id(self) -> str:
        return "regulatory-act-review:" + _digest(
            self.model_dump(mode="json", exclude={"detected_at"})
        )


class RegulatoryActReviewDecision(DomainModel):
    request: RegulatoryActReviewRequest
    outcome: SourceRevisionOutcome
    reviewer: str = Field(min_length=1, max_length=256)
    reviewed_at: datetime
    rationale: str = Field(min_length=10, max_length=4000)
    equivalent_confirmed: bool = Field(default=False, strict=True)
    scope: DatePeriod
    supersedes_decision_id: str | None = Field(default=None, pattern=_SHA)

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        if self.reviewed_at.utcoffset() is None or self.reviewed_at < self.request.detected_at:
            raise ValueError("review requires an aware time after observation")
        if not (
            self.request.validity.start
            <= self.scope.start
            < self.scope.end
            <= self.request.validity.end
        ):
            raise ValueError("act decision cannot extend the anchor validity")
        if self.outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT:
            if not self.equivalent_confirmed or self.request.document_sha256 is None:
                raise ValueError(
                    "act approval requires exact source bytes and explicit confirmation"
                )
            if self.scope.start < self.reviewed_at.astimezone(_ROME).date():
                raise ValueError("act approval cannot be retroactive")
        elif self.equivalent_confirmed:
            raise ValueError("negative decisions cannot attest equivalence")
        if self.outcome == SourceRevisionOutcome.REVOKE and self.supersedes_decision_id is None:
            raise ValueError("revocation must reference the superseded decision")
        return self

    @property
    def decision_id(self) -> str:
        return _digest(self.model_dump(mode="json"))


def observe_act_review(
    anchor: DomesticProjectionAnchor,
    record: OfficialRegistryRecord,
    body: bytes | None,
    *,
    observed_at: datetime,
) -> RegulatoryActReviewRequest:
    document_sha = hashlib.sha256(body).hexdigest() if body else None
    return RegulatoryActReviewRequest(
        anchor_id=anchor.anchor_id,
        anchor_sha256=regulatory_anchor_artifact_digest(anchor),
        record=record,
        validity=anchor.validity,
        detected_at=observed_at,
        document_sha256=document_sha,
        source_id=f"{record.channel.value}:{record.act_id}",
        source_url=act_document_url(record),
        observed_sha256=_digest(
            {"record": record.model_dump(mode="json"), "document_sha256": document_sha}
        ),
    )


def create_act_review_decision(
    request: RegulatoryActReviewRequest,
    *,
    outcome: SourceRevisionOutcome,
    reviewer: str,
    reviewed_at: datetime,
    rationale: str,
    equivalent_confirmed: bool = False,
    supersedes_decision_id: str | None = None,
) -> RegulatoryActReviewDecision:
    if reviewed_at.utcoffset() is None:
        raise ValueError("review requires a timezone-aware timestamp")
    start = (
        max(request.validity.start, reviewed_at.astimezone(_ROME).date())
        if outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT
        else request.validity.start
    )
    return RegulatoryActReviewDecision(
        request=request,
        outcome=outcome,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        rationale=rationale,
        equivalent_confirmed=equivalent_confirmed,
        scope=DatePeriod(start=start, end=request.validity.end),
        supersedes_decision_id=supersedes_decision_id,
    )


def act_decision_matches(
    request: RegulatoryActReviewRequest,
    decision: RegulatoryActReviewDecision,
    as_of: date,
    checked_at: datetime,
) -> bool:
    # Revalidate serialized values, including callers that used model_copy without validation.
    try:
        request = RegulatoryActReviewRequest.model_validate(request.model_dump(mode="python"))
        decision = RegulatoryActReviewDecision.model_validate(decision.model_dump(mode="python"))
    except ValueError:
        return False
    return bool(
        request.document_sha256
        and decision.request.request_id == request.request_id
        and decision.outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT
        and decision.reviewed_at <= checked_at
        and request.detected_at <= checked_at
        and decision.scope.start <= as_of < decision.scope.end
    )


def act_review_is_accepted(
    anchor: DomesticProjectionAnchor,
    request: RegulatoryActReviewRequest,
    decision: RegulatoryActReviewDecision,
    as_of: date,
    checked_at: datetime,
) -> bool:
    return (
        request.anchor_id == anchor.anchor_id
        and request.anchor_sha256 == regulatory_anchor_artifact_digest(anchor)
        and request.validity == anchor.validity
        and act_decision_matches(request, decision, as_of, checked_at)
    )
