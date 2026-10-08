"""Typed rollover lifecycle, pointer state, and append-only event records."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum

from pydantic import Field, field_validator

from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.domain.base import DomainModel


class RolloverAttemptStatus(StrEnum):
    """Persisted states for one versioned preparation attempt."""

    PREPARING = "preparing"
    VERIFIED = "verified"
    STAGED = "staged"
    PROMOTED = "promoted"
    REVIEW_REQUIRED = "review_required"
    REJECTED = "rejected"


class RolloverEventKind(StrEnum):
    """Append-only state changes recorded by a repository."""

    CANDIDATE_STAGED = "candidate_staged"
    CANDIDATE_REVOKED = "candidate_revoked"
    ANCHOR_PROMOTED = "anchor_promoted"


class StageOutcome(StrEnum):
    STAGED = "staged"
    ALREADY_STAGED = "already_staged"


class PromotionOutcome(StrEnum):
    PROMOTED = "promoted"
    ALREADY_PROMOTED = "already_promoted"
    NOT_DUE = "not_due"


_ALLOWED_TRANSITIONS: dict[RolloverAttemptStatus, frozenset[RolloverAttemptStatus]] = {
    RolloverAttemptStatus.PREPARING: frozenset(
        {
            RolloverAttemptStatus.VERIFIED,
            RolloverAttemptStatus.REVIEW_REQUIRED,
            RolloverAttemptStatus.REJECTED,
        }
    ),
    RolloverAttemptStatus.VERIFIED: frozenset(
        {RolloverAttemptStatus.STAGED, RolloverAttemptStatus.REJECTED}
    ),
    RolloverAttemptStatus.STAGED: frozenset(
        {
            RolloverAttemptStatus.PROMOTED,
            RolloverAttemptStatus.REVIEW_REQUIRED,
            RolloverAttemptStatus.REJECTED,
        }
    ),
    RolloverAttemptStatus.REVIEW_REQUIRED: frozenset(),
    RolloverAttemptStatus.REJECTED: frozenset(),
    RolloverAttemptStatus.PROMOTED: frozenset(),
}


def validate_attempt_transition(
    current: RolloverAttemptStatus, target: RolloverAttemptStatus
) -> None:
    """Raise when an attempt tries to skip or reverse a lifecycle state."""

    if current == target:
        return
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise ValueError(f"invalid regulatory rollover transition: {current} -> {target}")


class RegulatoryRolloverAttempt(DomainModel):
    """One immutable-input attempt keyed by current anchor and target period."""

    attempt_id: str = Field(min_length=1)
    current_anchor_id: str = Field(min_length=1)
    target_valid_from: date
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: RolloverAttemptStatus
    candidate_id: str | None = None
    reason_codes: tuple[RegulatoryRolloverReason, ...] = ()
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_aware_update_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("rollover attempt time must be timezone-aware")
        return value


class RegulatoryRolloverState(DomainModel):
    """Atomic current/staged pointer; anchors themselves remain immutable."""

    current_anchor_id: str = Field(min_length=1)
    staged_candidate_id: str | None = None
    generation: int = Field(ge=0)
    updated_at: datetime

    @field_validator("updated_at")
    @classmethod
    def require_aware_state_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("regulatory state update time must be timezone-aware")
        return value


class RegulatoryRolloverEvent(DomainModel):
    """Append-only stage/promotion record bound to one state generation."""

    event_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: RolloverEventKind
    occurred_at: datetime
    generation: int = Field(ge=1)
    previous_anchor_id: str = Field(min_length=1)
    current_anchor_id: str = Field(min_length=1)
    candidate_id: str = Field(min_length=1)
    reason_codes: tuple[RegulatoryRolloverReason, ...] = ()

    @field_validator("occurred_at")
    @classmethod
    def require_aware_event_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("regulatory event time must be timezone-aware")
        return value


def rollover_event_id(
    *,
    kind: RolloverEventKind,
    occurred_at: datetime,
    generation: int,
    previous_anchor_id: str,
    current_anchor_id: str,
    candidate_id: str,
    reason_codes: tuple[RegulatoryRolloverReason, ...] = (),
) -> str:
    """Compute a canonical identity for one immutable ledger event."""

    payload = {
        "kind": kind.value,
        "occurred_at": occurred_at.isoformat(),
        "generation": generation,
        "previous_anchor_id": previous_anchor_id,
        "current_anchor_id": current_anchor_id,
        "candidate_id": candidate_id,
        "reason_codes": [item.value for item in reason_codes],
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "PromotionOutcome",
    "RegulatoryRolloverAttempt",
    "RegulatoryRolloverEvent",
    "RegulatoryRolloverState",
    "RolloverAttemptStatus",
    "RolloverEventKind",
    "StageOutcome",
    "rollover_event_id",
    "validate_attempt_transition",
]
