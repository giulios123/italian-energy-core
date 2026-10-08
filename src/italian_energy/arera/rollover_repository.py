"""Repository contract and thread-safe in-memory rollover implementation.

Production persistence belongs to the Platform adapter. This implementation is
the executable reference for immutable writes, idempotency, and CAS semantics.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from threading import RLock
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from italian_energy.arera.discovery import (
    DiscoverySnapshot,
    RegistryCursor,
    RegulatoryDiscoveryReport,
)
from italian_energy.arera.projection import (
    DomesticProjectionAnchor,
)
from italian_energy.arera.rollover_coverage import (
    RegulatoryCandidateCoverageResult,
    RegulatoryManualReview,
)
from italian_energy.arera.rollover_models import (
    RegulatoryAnchorCandidate,
    RegulatoryRolloverReason,
    RolloverPolicy,
    canonical_json_bytes,
)
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.arera.rollover_state import (
    PromotionOutcome,
    RegulatoryRolloverAttempt,
    RegulatoryRolloverEvent,
    RegulatoryRolloverState,
    RolloverAttemptStatus,
    RolloverEventKind,
    StageOutcome,
    rollover_event_id,
    validate_attempt_transition,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.regulatory import VerificationStatus

_CIVIL_TIMEZONE = ZoneInfo("Europe/Rome")


class RegulatoryRepositoryError(Exception):
    """Typed repository/precondition failure with a stable domain reason."""

    def __init__(self, reason_code: RegulatoryRolloverReason) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code.value)


class StageResult(DomainModel):
    outcome: StageOutcome
    state: RegulatoryRolloverState
    candidate: RegulatoryAnchorCandidate


class PromotionResult(DomainModel):
    outcome: PromotionOutcome
    state: RegulatoryRolloverState
    anchor: DomesticProjectionAnchor


@runtime_checkable
class RegulatoryRepository(Protocol):
    """Atomic Core-facing storage contract; implementations must use CAS."""

    def read_state(self) -> RegulatoryRolloverState: ...

    def read_current_anchor(self) -> DomesticProjectionAnchor: ...

    def get_anchor(self, anchor_id: str) -> DomesticProjectionAnchor | None: ...

    def get_candidate(self, candidate_id: str) -> RegulatoryAnchorCandidate | None: ...

    def put_candidate_if_absent(
        self, candidate: RegulatoryAnchorCandidate
    ) -> RegulatoryAnchorCandidate: ...

    def record_attempt(self, attempt: RegulatoryRolloverAttempt) -> RegulatoryRolloverAttempt: ...

    def attempt_history(self, attempt_id: str) -> tuple[RegulatoryRolloverAttempt, ...]: ...

    def stage(
        self,
        candidate: RegulatoryAnchorCandidate,
        coverage: RegulatoryCandidateCoverageResult,
        *,
        as_of: date,
        staged_at: datetime,
        expected_generation: int,
        expected_current_anchor_id: str,
        policy: RolloverPolicy,
    ) -> StageResult: ...

    def promote(
        self,
        candidate_id: str,
        coverage: RegulatoryCandidateCoverageResult,
        *,
        as_of: date,
        promoted_at: datetime,
        expected_generation: int,
        expected_current_anchor_id: str,
        policy: RolloverPolicy,
    ) -> PromotionResult: ...

    def revoke_staged(
        self,
        candidate_id: str,
        reason_codes: tuple[RegulatoryRolloverReason, ...],
        *,
        occurred_at: datetime,
        expected_generation: int,
        expected_current_anchor_id: str,
    ) -> RegulatoryRolloverState: ...

    def historical_anchors(self) -> tuple[DomesticProjectionAnchor, ...]: ...

    def events(self) -> tuple[RegulatoryRolloverEvent, ...]: ...

    def coverage_for_anchor(
        self, anchor_id: str
    ) -> tuple[RegulatoryCandidateCoverageResult, ...]: ...

    def read_discovery_cursors(self) -> tuple[RegistryCursor, ...]: ...

    def read_discovery_snapshots(self) -> tuple[DiscoverySnapshot, ...]: ...

    def read_manual_reviews(self) -> tuple[RegulatoryManualReview, ...]: ...

    def save_discovery_report(self, report: RegulatoryDiscoveryReport) -> None: ...

    def put_manual_review(self, review: RegulatoryManualReview) -> RegulatoryManualReview: ...

    def save_raw_source(self, source: AcquiredOfficialBytes) -> None: ...


def regulatory_candidate_semantic_digest(candidate: RegulatoryAnchorCandidate) -> str:
    """Exclude acquisition/creation clocks while binding every semantic output."""

    payload = candidate.model_dump(mode="json")
    payload.pop("created_at", None)
    payload["validation_result"].pop("validated_at", None)
    for source in payload["anchor"]["sources"]:
        source.pop("retrieved_at", None)
    for fact in payload["facts"]:
        fact.pop("fetched_at", None)
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _coverage_digest(coverage: RegulatoryCandidateCoverageResult) -> str:
    return hashlib.sha256(canonical_json_bytes(coverage)).hexdigest()


class InMemoryRegulatoryRepository:
    """Reference implementation with atomic in-process compare-and-swap."""

    def __init__(
        self,
        current_anchor: DomesticProjectionAnchor,
        *,
        initialized_at: datetime,
    ) -> None:
        if initialized_at.tzinfo is None or initialized_at.utcoffset() is None:
            raise ValueError("repository initialization time must be timezone-aware")
        if current_anchor.status != VerificationStatus.VERIFIED:
            raise ValueError("repository current anchor must already be verified")
        self._lock = RLock()
        self._anchors: dict[str, DomesticProjectionAnchor] = {
            current_anchor.anchor_id: current_anchor
        }
        self._candidates: dict[str, RegulatoryAnchorCandidate] = {}
        self._candidate_semantic_digests: dict[str, str] = {}
        self._attempts: dict[str, list[RegulatoryRolloverAttempt]] = {}
        self._coverage: dict[str, list[RegulatoryCandidateCoverageResult]] = {}
        self._discovery_runs: list[RegulatoryDiscoveryReport] = []
        self._discovery_cursors: dict[str, RegistryCursor] = {}
        self._discovery_snapshots: dict[str, DiscoverySnapshot] = {}
        self._manual_reviews: dict[str, RegulatoryManualReview] = {}
        self._raw_sources: dict[str, AcquiredOfficialBytes] = {}
        self._events: list[RegulatoryRolloverEvent] = []
        self._event_ids: set[str] = set()
        self._state = RegulatoryRolloverState(
            current_anchor_id=current_anchor.anchor_id,
            generation=0,
            updated_at=initialized_at,
        )

    def read_state(self) -> RegulatoryRolloverState:
        with self._lock:
            return self._state

    def read_current_anchor(self) -> DomesticProjectionAnchor:
        with self._lock:
            return self._anchors[self._state.current_anchor_id]

    def get_anchor(self, anchor_id: str) -> DomesticProjectionAnchor | None:
        with self._lock:
            return self._anchors.get(anchor_id)

    def get_candidate(self, candidate_id: str) -> RegulatoryAnchorCandidate | None:
        with self._lock:
            return self._candidates.get(candidate_id)

    def put_candidate_if_absent(
        self, candidate: RegulatoryAnchorCandidate
    ) -> RegulatoryAnchorCandidate:
        """Insert once; same semantic key returns the original frozen object."""

        with self._lock:
            try:
                candidate = RegulatoryAnchorCandidate.model_validate(
                    candidate.model_dump(mode="python")
                )
            except (TypeError, ValueError, ValidationError) as exc:
                raise RegulatoryRepositoryError(
                    RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED
                ) from exc
            existing = self._candidates.get(candidate.candidate_id)
            candidate_fingerprint = regulatory_candidate_semantic_digest(candidate)
            if existing is not None:
                previous_fingerprint = self._candidate_semantic_digests[candidate.candidate_id]
                if previous_fingerprint != candidate_fingerprint:
                    raise RegulatoryRepositoryError(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
                return existing
            self._candidates[candidate.candidate_id] = candidate
            self._candidate_semantic_digests[candidate.candidate_id] = candidate_fingerprint
            return candidate

    def record_attempt(self, attempt: RegulatoryRolloverAttempt) -> RegulatoryRolloverAttempt:
        """Append one attempt snapshot while enforcing the explicit state machine."""

        with self._lock:
            history = self._attempts.setdefault(attempt.attempt_id, [])
            previous = history[-1] if history else None
            if previous is None:
                if attempt.status != RolloverAttemptStatus.PREPARING:
                    raise RegulatoryRepositoryError(
                        RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED
                    )
                history.append(attempt)
                return attempt
            if (
                previous.current_anchor_id != attempt.current_anchor_id
                or previous.target_valid_from != attempt.target_valid_from
                or previous.input_fingerprint != attempt.input_fingerprint
            ):
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
            if attempt == previous:
                return previous
            if attempt.updated_at < previous.updated_at:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
            try:
                validate_attempt_transition(previous.status, attempt.status)
            except ValueError as exc:
                raise RegulatoryRepositoryError(
                    RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED
                ) from exc
            history.append(attempt)
            return attempt

    def attempt_history(self, attempt_id: str) -> tuple[RegulatoryRolloverAttempt, ...]:
        with self._lock:
            return tuple(self._attempts.get(attempt_id, ()))

    def stage(
        self,
        candidate: RegulatoryAnchorCandidate,
        coverage: RegulatoryCandidateCoverageResult,
        *,
        as_of: date,
        staged_at: datetime,
        expected_generation: int,
        expected_current_anchor_id: str,
        policy: RolloverPolicy,
    ) -> StageResult:
        """Verify and CAS the staged pointer while leaving current untouched."""

        self._require_aware(staged_at, "stage time")
        with self._lock:
            candidate = self.put_candidate_if_absent(candidate)
            self._require_coverage_match(candidate, coverage)
            self._record_coverage(candidate.candidate_id, coverage)
            self._require_fresh_coverage(coverage, as_of, staged_at)
            if not coverage.ready:
                raise RegulatoryRepositoryError(
                    coverage.reason_codes[0]
                    if coverage.reason_codes
                    else RegulatoryRolloverReason.INCOMPLETE_COVERAGE
                )
            current = self._anchors[self._state.current_anchor_id]
            if candidate.anchor.validity.start != current.validity.end:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL)
            if self._state.staged_candidate_id == candidate.candidate_id:
                return StageResult(
                    outcome=StageOutcome.ALREADY_STAGED,
                    state=self._state,
                    candidate=candidate,
                )
            if self._state.staged_candidate_id is not None:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.PROMOTION_CONFLICT)
            self._require_expected_state(expected_generation, expected_current_anchor_id)
            previous_id = self._state.current_anchor_id
            next_generation = self._state.generation + 1
            self._state = RegulatoryRolloverState(
                current_anchor_id=previous_id,
                staged_candidate_id=candidate.candidate_id,
                generation=next_generation,
                updated_at=staged_at,
            )
            self._append_event(
                kind=RolloverEventKind.CANDIDATE_STAGED,
                occurred_at=staged_at,
                generation=next_generation,
                previous_anchor_id=previous_id,
                current_anchor_id=previous_id,
                candidate_id=candidate.candidate_id,
            )
            return StageResult(
                outcome=StageOutcome.STAGED,
                state=self._state,
                candidate=candidate,
            )

    def promote(
        self,
        candidate_id: str,
        coverage: RegulatoryCandidateCoverageResult,
        *,
        as_of: date,
        promoted_at: datetime,
        expected_generation: int,
        expected_current_anchor_id: str,
        policy: RolloverPolicy,
    ) -> PromotionResult:
        """Atomically publish a verified staged anchor exactly at its validity."""

        self._require_aware(promoted_at, "promotion time")
        with self._lock:
            candidate = self._candidates.get(candidate_id)
            if candidate is None:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.NEXT_ANCHOR_MISSING)
            published_id = f"regulatory-anchor:{candidate.build_key}"
            current = self._anchors[self._state.current_anchor_id]
            if current.anchor_id == published_id and self._state.staged_candidate_id is None:
                return PromotionResult(
                    outcome=PromotionOutcome.ALREADY_PROMOTED,
                    state=self._state,
                    anchor=current,
                )
            if self._state.staged_candidate_id != candidate_id:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.PROMOTION_CONFLICT)
            self._require_expected_state(expected_generation, expected_current_anchor_id)
            if as_of < candidate.anchor.validity.start:
                return PromotionResult(
                    outcome=PromotionOutcome.NOT_DUE,
                    state=self._state,
                    anchor=current,
                )
            if as_of >= candidate.anchor.validity.end:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL)
            self._require_coverage_match(candidate, coverage)
            self._record_coverage(candidate.candidate_id, coverage)
            self._require_fresh_coverage(coverage, as_of, promoted_at)
            if not coverage.ready:
                raise RegulatoryRepositoryError(
                    coverage.reason_codes[0]
                    if coverage.reason_codes
                    else RegulatoryRolloverReason.INCOMPLETE_COVERAGE
                )
            if current.validity.end != candidate.anchor.validity.start:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL)

            anchor_payload = candidate.anchor.model_dump(mode="python")
            anchor_payload.update(
                {"anchor_id": published_id, "status": VerificationStatus.VERIFIED}
            )
            published = DomesticProjectionAnchor.model_validate(anchor_payload)
            next_generation = self._state.generation + 1
            previous_id = current.anchor_id
            self._anchors[published.anchor_id] = published
            self._coverage.setdefault(published.anchor_id, []).append(coverage)
            self._state = RegulatoryRolloverState(
                current_anchor_id=published.anchor_id,
                staged_candidate_id=None,
                generation=next_generation,
                updated_at=promoted_at,
            )
            self._append_event(
                kind=RolloverEventKind.ANCHOR_PROMOTED,
                occurred_at=promoted_at,
                generation=next_generation,
                previous_anchor_id=previous_id,
                current_anchor_id=published.anchor_id,
                candidate_id=candidate.candidate_id,
            )
            return PromotionResult(
                outcome=PromotionOutcome.PROMOTED,
                state=self._state,
                anchor=published,
            )

    def revoke_staged(
        self,
        candidate_id: str,
        reason_codes: tuple[RegulatoryRolloverReason, ...],
        *,
        occurred_at: datetime,
        expected_generation: int,
        expected_current_anchor_id: str,
    ) -> RegulatoryRolloverState:
        """Revoke a staged pointer after later evidence invalidates its coverage."""

        self._require_aware(occurred_at, "revocation time")
        if not reason_codes:
            raise ValueError("staged candidate revocation requires a reason code")
        with self._lock:
            if self._state.staged_candidate_id != candidate_id:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.PROMOTION_CONFLICT)
            self._require_expected_state(expected_generation, expected_current_anchor_id)
            current_id = self._state.current_anchor_id
            next_generation = self._state.generation + 1
            self._state = RegulatoryRolloverState(
                current_anchor_id=current_id,
                staged_candidate_id=None,
                generation=next_generation,
                updated_at=occurred_at,
            )
            self._append_event(
                kind=RolloverEventKind.CANDIDATE_REVOKED,
                occurred_at=occurred_at,
                generation=next_generation,
                previous_anchor_id=current_id,
                current_anchor_id=current_id,
                candidate_id=candidate_id,
                reason_codes=reason_codes,
            )
            return self._state

    def historical_anchors(self) -> tuple[DomesticProjectionAnchor, ...]:
        with self._lock:
            return tuple(
                anchor
                for anchor_id, anchor in sorted(self._anchors.items())
                if anchor_id != self._state.current_anchor_id
            )

    def events(self) -> tuple[RegulatoryRolloverEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def coverage_for_anchor(self, anchor_id: str) -> tuple[RegulatoryCandidateCoverageResult, ...]:
        with self._lock:
            return tuple(self._coverage.get(anchor_id, ()))

    def read_discovery_cursors(self) -> tuple[RegistryCursor, ...]:
        with self._lock:
            return tuple(self._discovery_cursors[key] for key in sorted(self._discovery_cursors))

    def read_discovery_snapshots(self) -> tuple[DiscoverySnapshot, ...]:
        with self._lock:
            return tuple(
                self._discovery_snapshots[key] for key in sorted(self._discovery_snapshots)
            )

    def read_manual_reviews(self) -> tuple[RegulatoryManualReview, ...]:
        with self._lock:
            return tuple(self._manual_reviews[key] for key in sorted(self._manual_reviews))

    def save_discovery_report(self, report: RegulatoryDiscoveryReport) -> None:
        """Append a report and advance only cursors backed by complete scans."""

        with self._lock:
            report_digest = hashlib.sha256(canonical_json_bytes(report)).hexdigest()
            if all(
                hashlib.sha256(canonical_json_bytes(item)).hexdigest() != report_digest
                for item in self._discovery_runs
            ):
                self._discovery_runs.append(report)
            for snapshot in report.snapshots:
                if snapshot.complete and snapshot.next_cursor is not None:
                    self._discovery_cursors[snapshot.channel.value] = snapshot.next_cursor
                    self._discovery_snapshots[snapshot.channel.value] = snapshot

    def put_manual_review(self, review: RegulatoryManualReview) -> RegulatoryManualReview:
        """Store one digest-bound review artifact immutably by decision ID."""

        with self._lock:
            existing = self._manual_reviews.get(review.decision_id)
            if existing is not None and existing != review:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
            self._manual_reviews[review.decision_id] = review
            return review

    def save_raw_source(self, source: AcquiredOfficialBytes) -> None:
        """Retain exact response bytes by immutable response-observation identity."""

        payload = {
            "url": source.url,
            "final_url": source.final_url,
            "sha256": source.sha256,
            "fetched_at": source.fetched_at.isoformat(),
            "content_type": source.content_type,
            "byte_length": source.byte_length,
        }
        key = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        with self._lock:
            previous = self._raw_sources.get(key)
            if previous is not None and previous.body != source.body:
                raise RegulatoryRepositoryError(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
            self._raw_sources.setdefault(key, source)

    def raw_source_observations(self) -> tuple[AcquiredOfficialBytes, ...]:
        """Expose immutable observations to repository-level tests only."""

        with self._lock:
            return tuple(self._raw_sources[key] for key in sorted(self._raw_sources))

    def _record_coverage(
        self, candidate_id: str, coverage: RegulatoryCandidateCoverageResult
    ) -> None:
        records = self._coverage.setdefault(candidate_id, [])
        coverage_digest = _coverage_digest(coverage)
        if all(_coverage_digest(previous) != coverage_digest for previous in records):
            records.append(coverage)

    @staticmethod
    def _require_coverage_match(
        candidate: RegulatoryAnchorCandidate,
        coverage: RegulatoryCandidateCoverageResult,
    ) -> None:
        if (
            coverage.candidate_id != candidate.candidate_id
            or coverage.candidate_build_key != candidate.build_key
        ):
            raise RegulatoryRepositoryError(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)

    @staticmethod
    def _require_fresh_coverage(
        coverage: RegulatoryCandidateCoverageResult,
        as_of: date,
        operation_at: datetime,
    ) -> None:
        if (
            coverage.as_of != as_of
            or coverage.checked_at.astimezone(_CIVIL_TIMEZONE).date() != as_of
        ):
            raise RegulatoryRepositoryError(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
        if coverage.checked_at > operation_at:
            raise RegulatoryRepositoryError(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)

    @staticmethod
    def _require_aware(value: datetime, label: str) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(f"{label} must be timezone-aware")

    def _require_expected_state(self, generation: int, current_anchor_id: str) -> None:
        if (
            self._state.generation != generation
            or self._state.current_anchor_id != current_anchor_id
        ):
            raise RegulatoryRepositoryError(RegulatoryRolloverReason.PROMOTION_CONFLICT)

    def _append_event(
        self,
        *,
        kind: RolloverEventKind,
        occurred_at: datetime,
        generation: int,
        previous_anchor_id: str,
        current_anchor_id: str,
        candidate_id: str,
        reason_codes: tuple[RegulatoryRolloverReason, ...] = (),
    ) -> None:
        event_id = rollover_event_id(
            kind=kind,
            occurred_at=occurred_at,
            generation=generation,
            previous_anchor_id=previous_anchor_id,
            current_anchor_id=current_anchor_id,
            candidate_id=candidate_id,
            reason_codes=reason_codes,
        )
        if event_id in self._event_ids:
            return
        self._events.append(
            RegulatoryRolloverEvent(
                event_id=event_id,
                kind=kind,
                occurred_at=occurred_at,
                generation=generation,
                previous_anchor_id=previous_anchor_id,
                current_anchor_id=current_anchor_id,
                candidate_id=candidate_id,
                reason_codes=reason_codes,
            )
        )
        self._event_ids.add(event_id)


__all__ = [
    "InMemoryRegulatoryRepository",
    "PromotionResult",
    "RegulatoryRepository",
    "RegulatoryRepositoryError",
    "StageResult",
    "regulatory_candidate_semantic_digest",
]
