"""Daily Core orchestration for preparing and promoting regulatory anchors.

Network access is isolated behind explicit registry and document ports. The
service keeps parsing, mapping, validation, coverage, state changes, and the
offline readiness gate inside Core.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from italian_energy.arera.discovery import (
    DiscoveryActDisposition,
    DiscoveryActFinding,
    DiscoveryFailure,
    DiscoverySnapshot,
    OfficialRegistryRecord,
    RegistryCursor,
    RegistryIndexAdapter,
    RegulatoryDiscoveryReport,
    RegulatoryRegistryChannel,
    discover_regulatory_sources,
    incremental_search_period,
)
from italian_energy.arera.official_registry_adapters import (
    OfficialRegistryTransport,
    OfficialRegulatoryDocumentAcquirer,
    RecordingOfficialRegistryTransport,
    UrllibOfficialRegistryTransport,
    default_official_registry_adapters,
    normattiva_vat_reference_records,
)
from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.arera.rollover_coverage import (
    RegulatoryAnchorCoverageEvidence,
    RegulatoryAnchorSourceCheck,
    RegulatoryCandidateCoverageResult,
    RegulatoryCandidateSourceCheck,
    RegulatoryManualReview,
    RegulatoryReviewSourceCheck,
    verify_regulatory_anchor_coverage,
    verify_regulatory_candidate_coverage,
)
from italian_energy.arera.rollover_mapping import build_regulatory_anchor_candidate
from italian_energy.arera.rollover_models import (
    DEFAULT_ROLLOVER_POLICY,
    RegulatoryAnchorCandidate,
    RegulatoryEffectAssertion,
    RegulatoryFact,
    RegulatoryRolloverReason,
    RolloverPolicy,
    regulatory_anchor_artifact_digest,
)
from italian_energy.arera.rollover_parsers import (
    ParserDisposition,
    RegulatoryParserRegistry,
    RegulatorySourceDocument,
    default_regulatory_parser_registry,
)
from italian_energy.arera.rollover_repository import (
    RegulatoryRepository,
    RegulatoryRepositoryError,
)
from italian_energy.arera.rollover_scope import scope_domestic_projection_discovery
from italian_energy.arera.rollover_state import (
    PromotionOutcome,
    RegulatoryRolloverAttempt,
    RolloverAttemptStatus,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod

_ROMAN = ZoneInfo("Europe/Rome")


class RegulatoryRolloverSourcePort(Protocol):
    """Explicit transport adapter; it supplies bytes and source metadata only."""

    def acquire_document(self, record: OfficialRegistryRecord) -> RegulatorySourceDocument: ...

    def fetch_source(self, url: str) -> bytes: ...


class RegulatoryRolloverAction(StrEnum):
    """Outcome of one daily rollover orchestration."""

    PREPARATION_NOT_REQUIRED = "preparation_not_required"
    PREPARING = "preparing"
    REVIEW_REQUIRED = "review_required"
    BLOCKED = "blocked"
    STAGED = "staged"
    PROMOTION_READY = "promotion_ready"
    PROMOTED = "promoted"
    ALREADY_PROMOTED = "already_promoted"


class RegulatorySourcePreflightResult(DomainModel):
    """Offline comparison gate bound to the active anchor and coverage date."""

    ready: bool
    as_of: date
    anchor_id: str | None = None
    anchor_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checks: dict[str, bool]
    reason_codes: tuple[RegulatoryRolloverReason, ...] = ()

    @model_validator(mode="after")
    def validate_readiness(self) -> RegulatorySourcePreflightResult:
        if self.ready != all(self.checks.values()):
            raise ValueError("source preflight readiness must match every check")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("source preflight reasons must be unique")
        return self


class RegulatoryRolloverReport(DomainModel):
    """Audit-safe result of one daily preparation/verification/promotion run."""

    as_of: date
    action: RegulatoryRolloverAction
    current_anchor_id: str
    current_anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    staged_candidate_id: str | None = None
    candidate_id: str | None = None
    attempt_id: str | None = None
    days_to_expiry: int
    discovery: RegulatoryDiscoveryReport
    candidate: RegulatoryAnchorCandidate | None = None
    current_coverage: RegulatoryAnchorCoverageEvidence
    candidate_coverage: RegulatoryCandidateCoverageResult | None = None
    cursor_updates: tuple[RegistryCursor, ...]
    reason_codes: tuple[RegulatoryRolloverReason, ...] = ()
    promotion_outcome: PromotionOutcome | None = None

    @model_validator(mode="after")
    def validate_report(self) -> RegulatoryRolloverReport:
        if self.current_coverage.as_of != self.as_of:
            raise ValueError("rollover report current coverage must match its date")
        if self.discovery.as_of != self.as_of:
            raise ValueError("rollover report discovery must match its date")
        if self.candidate is not None and self.candidate_id != self.candidate.candidate_id:
            raise ValueError("rollover report candidate ID must match its artifact")
        if self.candidate_coverage is not None and (
            self.candidate_id != self.candidate_coverage.candidate_id
        ):
            raise ValueError("rollover report coverage must match its candidate")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("rollover report reasons must be unique")
        return self


def _discovery_digest(report: RegulatoryDiscoveryReport) -> str:
    encoded = json.dumps(
        report.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _attempt_identity(current_anchor_id: str, target_valid_from: date, fingerprint: str) -> str:
    payload = f"{current_anchor_id}|{target_valid_from.isoformat()}|{fingerprint}"
    return f"regulatory-rollover-attempt:{hashlib.sha256(payload.encode()).hexdigest()}"


def _input_fingerprint(
    discovery: RegulatoryDiscoveryReport,
    facts: tuple[RegulatoryFact, ...],
    effect_assertions: tuple[RegulatoryEffectAssertion, ...],
    reviews: tuple[RegulatoryManualReview, ...],
) -> str:
    payload = {
        "discovery": _discovery_digest(discovery),
        "facts": [
            item.model_dump(mode="json", exclude={"fetched_at"})
            for item in sorted(facts, key=lambda fact: fact.fact_id)
        ],
        "effect_assertions": [
            item.model_dump(mode="json", exclude={"fetched_at"})
            for item in sorted(effect_assertions, key=lambda assertion: assertion.assertion_id)
        ],
        "reviews": sorted(item.decision_id for item in reviews),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class RegulatoryRolloverService:
    """Orchestrate daily Core rollover while leaving live adapters injectable."""

    def __init__(
        self,
        repository: RegulatoryRepository,
        *,
        registry_adapters: tuple[RegistryIndexAdapter, ...] = (),
        source_port: RegulatoryRolloverSourcePort | None = None,
        parser_registry: RegulatoryParserRegistry | None = None,
        classifier: Callable[[OfficialRegistryRecord], DiscoveryActFinding] | None = None,
        known_source_records: Callable[[date], tuple[OfficialRegistryRecord, ...]] | None = None,
        policy: RolloverPolicy = DEFAULT_ROLLOVER_POLICY,
        initial_search_start: date | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._repository = repository
        self._registry_adapters = registry_adapters
        self._source_port = source_port
        self._parser_registry = parser_registry or default_regulatory_parser_registry()
        self._classifier = classifier
        self._known_source_records = known_source_records
        self._policy = policy
        self._initial_search_start = initial_search_start
        self._clock = clock or (lambda: datetime.now(_ROMAN))

    def _clock_after(self, previous: datetime) -> datetime:
        """Return an aware audit time no earlier than the completed operation."""

        current = self._clock()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("rollover clock must return a timezone-aware timestamp")
        return max(previous, current)

    def refresh_regulatory_state(
        self,
        as_of: date,
        *,
        previous_cursors: tuple[RegistryCursor, ...] | None = None,
        previous_snapshots: tuple[DiscoverySnapshot, ...] | None = None,
        reviews: tuple[RegulatoryManualReview, ...] | None = None,
    ) -> RegulatoryRolloverReport:
        """Refresh current coverage, prepare/stage a successor, or promote it.

        Callers own scheduling and durable storage. The returned discovery
        cursors are committable only when all required registry scans completed.
        """

        now = self._clock()
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("rollover clock must return a timezone-aware timestamp")
        if now.astimezone(_ROMAN).date() != as_of:
            raise ValueError("rollover as_of must match the Europe/Rome civil date")

        state = self._repository.read_state()
        current = self._repository.read_current_anchor()
        active_cursors = (
            self._repository.read_discovery_cursors()
            if previous_cursors is None
            else previous_cursors
        )
        active_snapshots = (
            self._repository.read_discovery_snapshots()
            if previous_snapshots is None
            else previous_snapshots
        )
        active_reviews = self._repository.read_manual_reviews() if reviews is None else reviews
        search_start = self._search_start(current, active_cursors)
        search_period = incremental_search_period(
            as_of=as_of,
            last_covered_through=min(
                (item.covered_through for item in active_cursors), default=None
            ),
            overlap_days=self._policy.discovery_overlap_days,
            initial_search_start=search_start,
        )
        discovery = discover_regulatory_sources(
            self._registry_adapters,
            search_period,
            now,
            previous_cursors=active_cursors,
            previous_snapshots=active_snapshots,
            classifier=self._classifier,
        )
        if self._classifier is None:
            discovery = scope_domestic_projection_discovery(
                discovery,
                previous_snapshots=active_snapshots,
            )
        self._repository.save_discovery_report(discovery)
        records_by_key = {
            (record.channel, record.act_id): record
            for snapshot in discovery.snapshots
            for record in snapshot.records
        }
        known_records = (
            () if self._known_source_records is None else self._known_source_records(as_of)
        )
        facts, effect_assertions, parse_reasons = self._parse_supported_records(
            discovery, records_by_key, known_records=known_records
        )
        now = self._clock_after(now)
        review_checks = self._review_source_checks(active_reviews, now)
        current_source_checks = self._anchor_source_checks(current, now)
        now = self._clock_after(
            max(
                (
                    now,
                    *(item.checked_at for item in review_checks),
                    *(item.checked_at for item in current_source_checks),
                )
            )
        )
        current_coverage = verify_regulatory_anchor_coverage(
            anchor=current,
            discovery=discovery,
            source_checks=current_source_checks,
            as_of=as_of,
            checked_at=now,
            facts=facts,
            effect_assertions=effect_assertions,
            reviews=active_reviews,
            review_source_checks=review_checks,
            policy=self._policy,
        )

        days_to_expiry = (current.validity.end - as_of).days
        reasons = list((*parse_reasons, *current_coverage.reason_codes))
        staged_id = state.staged_candidate_id
        candidate: RegulatoryAnchorCandidate | None = None
        candidate_coverage: RegulatoryCandidateCoverageResult | None = None
        attempt_id: str | None = None
        promotion_outcome: PromotionOutcome | None = None

        if staged_id is not None:
            candidate = self._repository.get_candidate(staged_id)
            if candidate is None:
                reasons.append(RegulatoryRolloverReason.NEXT_ANCHOR_MISSING)
                return self._report(
                    as_of,
                    RegulatoryRolloverAction.BLOCKED,
                    current,
                    days_to_expiry,
                    discovery,
                    current_coverage,
                    candidate_id=staged_id,
                    candidate_coverage=None,
                    cursor_updates=discovery.cursor_updates,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            attempt_id = _attempt_identity(
                current.anchor_id, candidate.anchor.validity.start, candidate.build_key
            )
            candidate_coverage = self._verify_candidate(
                candidate, discovery, as_of, now, active_reviews, review_checks
            )
            reasons.extend(candidate_coverage.reason_codes)
            if not candidate_coverage.ready:
                if self._permanent_staged_failure(candidate_coverage.reason_codes):
                    try:
                        self._repository.revoke_staged(
                            candidate.candidate_id,
                            candidate_coverage.reason_codes,
                            occurred_at=now,
                            expected_generation=state.generation,
                            expected_current_anchor_id=current.anchor_id,
                        )
                    except RegulatoryRepositoryError as exc:
                        reasons.append(exc.reason_code)
                    failure_status = self._failure_status(candidate_coverage.reason_codes)
                    if failure_status == RolloverAttemptStatus.PREPARING:
                        failure_status = RolloverAttemptStatus.REJECTED
                    self._record_attempt(
                        attempt_id=attempt_id,
                        current_anchor_id=current.anchor_id,
                        target_valid_from=candidate.anchor.validity.start,
                        fingerprint=candidate.build_key,
                        candidate_id=candidate.candidate_id,
                        status=failure_status,
                        reason_codes=candidate_coverage.reason_codes,
                        updated_at=now,
                    )
                action = self._blocked_action(candidate_coverage.reason_codes)
                return self._report(
                    as_of,
                    action,
                    current,
                    days_to_expiry,
                    discovery,
                    current_coverage,
                    candidate=candidate,
                    candidate_coverage=candidate_coverage,
                    candidate_id=candidate.candidate_id,
                    attempt_id=attempt_id,
                    cursor_updates=discovery.cursor_updates,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            if as_of < candidate.anchor.validity.start:
                return self._report(
                    as_of,
                    RegulatoryRolloverAction.STAGED,
                    current,
                    days_to_expiry,
                    discovery,
                    current_coverage,
                    candidate=candidate,
                    candidate_coverage=candidate_coverage,
                    candidate_id=candidate.candidate_id,
                    attempt_id=attempt_id,
                    cursor_updates=discovery.cursor_updates,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            try:
                promotion_time = self._clock_after(candidate_coverage.checked_at)
                promoted = self._repository.promote(
                    candidate.candidate_id,
                    candidate_coverage,
                    as_of=as_of,
                    promoted_at=promotion_time,
                    expected_generation=state.generation,
                    expected_current_anchor_id=current.anchor_id,
                    policy=self._policy,
                )
            except RegulatoryRepositoryError as exc:
                reasons.append(exc.reason_code)
                return self._report(
                    as_of,
                    RegulatoryRolloverAction.BLOCKED,
                    current,
                    days_to_expiry,
                    discovery,
                    current_coverage,
                    candidate=candidate,
                    candidate_coverage=candidate_coverage,
                    candidate_id=candidate.candidate_id,
                    attempt_id=attempt_id,
                    cursor_updates=discovery.cursor_updates,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            promotion_outcome = promoted.outcome
            now = promotion_time
            current = promoted.anchor
            if promotion_outcome != PromotionOutcome.NOT_DUE:
                self._record_attempt(
                    attempt_id=attempt_id,
                    current_anchor_id=state.current_anchor_id,
                    target_valid_from=candidate.anchor.validity.start,
                    fingerprint=candidate.build_key,
                    candidate_id=candidate.candidate_id,
                    status=RolloverAttemptStatus.PROMOTED,
                    reason_codes=(),
                    updated_at=now,
                )
                current_source_checks = self._anchor_source_checks(current, now)
                current_coverage = verify_regulatory_anchor_coverage(
                    anchor=current,
                    discovery=discovery,
                    source_checks=current_source_checks,
                    as_of=as_of,
                    checked_at=now,
                    facts=candidate.facts,
                    effect_assertions=effect_assertions,
                    reviews=active_reviews,
                    review_source_checks=review_checks,
                    policy=self._policy,
                )
            action = {
                PromotionOutcome.PROMOTED: RegulatoryRolloverAction.PROMOTED,
                PromotionOutcome.ALREADY_PROMOTED: RegulatoryRolloverAction.ALREADY_PROMOTED,
                PromotionOutcome.NOT_DUE: RegulatoryRolloverAction.STAGED,
            }[promotion_outcome]
            return self._report(
                as_of,
                action,
                current,
                (current.validity.end - as_of).days,
                discovery,
                current_coverage,
                candidate=candidate,
                candidate_coverage=candidate_coverage,
                candidate_id=candidate.candidate_id,
                attempt_id=attempt_id,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
                promotion_outcome=promotion_outcome,
            )

        late_recovery = as_of >= current.validity.end
        if late_recovery and not self._recovery_discovery_is_complete(
            discovery, current.validity.end, as_of
        ):
            reasons.append(RegulatoryRolloverReason.CURRENT_ANCHOR_EXPIRED)
            reasons.append(RegulatoryRolloverReason.NEXT_ANCHOR_MISSING)
            return self._report(
                as_of,
                RegulatoryRolloverAction.BLOCKED,
                current,
                days_to_expiry,
                discovery,
                current_coverage,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )

        preparation_due = (
            days_to_expiry <= self._policy.prepare_lead_days
            or bool(parse_reasons)
            or bool(discovery.changes)
            or any(
                item.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
                for item in discovery.findings
            )
            or any(
                item.disposition == DiscoveryActDisposition.SUPPORTED
                and any(
                    fact.validity.start <= current.validity.end < fact.validity.end
                    for fact in facts
                )
                for item in discovery.findings
            )
        )
        if not preparation_due:
            return self._report(
                as_of,
                RegulatoryRolloverAction.PREPARATION_NOT_REQUIRED,
                current,
                days_to_expiry,
                discovery,
                current_coverage,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )

        target_start = current.validity.end
        if parse_reasons:
            fingerprint = _input_fingerprint(discovery, facts, effect_assertions, active_reviews)
            attempt_id = _attempt_identity(current.anchor_id, target_start, fingerprint)
            attempt = self._record_attempt(
                attempt_id=attempt_id,
                current_anchor_id=current.anchor_id,
                target_valid_from=target_start,
                fingerprint=fingerprint,
                candidate_id=None,
                status=self._failure_status(parse_reasons),
                reason_codes=tuple(dict.fromkeys(parse_reasons)),
                updated_at=now,
            )
            _ = attempt
            reasons.extend(parse_reasons)
            return self._report(
                as_of,
                self._blocked_action(tuple(parse_reasons)),
                current,
                days_to_expiry,
                discovery,
                current_coverage,
                attempt_id=attempt_id,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )

        try:
            candidate = self._build_candidate(
                current,
                as_of,
                now,
                facts,
                active_reviews,
                allow_late_recovery=late_recovery,
                effect_assertions=effect_assertions,
            )
        except ValueError as exc:
            reason = (
                exc.reason_code
                if hasattr(exc, "reason_code")
                else RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED
            )
            failure_reasons = [reason]
            if any(
                item.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
                for item in discovery.findings
            ):
                failure_reasons.append(RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE)
            reasons.extend(failure_reasons)
            fingerprint = _input_fingerprint(discovery, facts, effect_assertions, active_reviews)
            attempt_id = _attempt_identity(current.anchor_id, target_start, fingerprint)
            self._record_attempt(
                attempt_id=attempt_id,
                current_anchor_id=current.anchor_id,
                target_valid_from=target_start,
                fingerprint=fingerprint,
                candidate_id=None,
                status=self._failure_status(tuple(failure_reasons)),
                reason_codes=tuple(dict.fromkeys(failure_reasons)),
                updated_at=now,
            )
            return self._report(
                as_of,
                self._blocked_action(tuple(failure_reasons)),
                current,
                days_to_expiry,
                discovery,
                current_coverage,
                attempt_id=attempt_id,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )

        attempt_id = _attempt_identity(current.anchor_id, target_start, candidate.build_key)
        candidate = self._repository.put_candidate_if_absent(candidate)
        source_checks = self._candidate_source_checks(candidate, now)
        candidate_coverage = self._verify_candidate(
            candidate, discovery, as_of, now, active_reviews, review_checks, source_checks
        )
        reasons.extend(candidate_coverage.reason_codes)
        self._record_attempt(
            attempt_id=attempt_id,
            current_anchor_id=current.anchor_id,
            target_valid_from=target_start,
            fingerprint=candidate.build_key,
            candidate_id=candidate.candidate_id,
            status=(
                RolloverAttemptStatus.VERIFIED
                if candidate_coverage.ready
                else self._failure_status(candidate_coverage.reason_codes)
            ),
            reason_codes=candidate_coverage.reason_codes,
            updated_at=now,
        )
        if not candidate_coverage.ready:
            return self._report(
                as_of,
                self._blocked_action(candidate_coverage.reason_codes),
                current,
                days_to_expiry,
                discovery,
                current_coverage,
                candidate=candidate,
                candidate_coverage=candidate_coverage,
                candidate_id=candidate.candidate_id,
                attempt_id=attempt_id,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )

        try:
            now = self._clock_after(candidate_coverage.checked_at)
            staged_result = self._repository.stage(
                candidate,
                candidate_coverage,
                as_of=as_of,
                staged_at=now,
                expected_generation=state.generation,
                expected_current_anchor_id=current.anchor_id,
                policy=self._policy,
            )
            self._record_attempt(
                attempt_id=attempt_id,
                current_anchor_id=current.anchor_id,
                target_valid_from=target_start,
                fingerprint=candidate.build_key,
                candidate_id=candidate.candidate_id,
                status=RolloverAttemptStatus.STAGED,
                reason_codes=(),
                updated_at=now,
            )
        except RegulatoryRepositoryError as exc:
            reasons.append(exc.reason_code)
            return self._report(
                as_of,
                RegulatoryRolloverAction.BLOCKED,
                current,
                days_to_expiry,
                discovery,
                current_coverage,
                candidate=candidate,
                candidate_coverage=candidate_coverage,
                candidate_id=candidate.candidate_id,
                attempt_id=attempt_id,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
            )
        if as_of >= candidate.anchor.validity.start:
            try:
                promotion_time = self._clock_after(now)
                promoted = self._repository.promote(
                    candidate.candidate_id,
                    candidate_coverage,
                    as_of=as_of,
                    promoted_at=promotion_time,
                    expected_generation=staged_result.state.generation,
                    expected_current_anchor_id=current.anchor_id,
                    policy=self._policy,
                )
            except RegulatoryRepositoryError as exc:
                reasons.append(exc.reason_code)
                return self._report(
                    as_of,
                    RegulatoryRolloverAction.BLOCKED,
                    current,
                    days_to_expiry,
                    discovery,
                    current_coverage,
                    candidate=candidate,
                    candidate_coverage=candidate_coverage,
                    candidate_id=candidate.candidate_id,
                    attempt_id=attempt_id,
                    cursor_updates=discovery.cursor_updates,
                    reason_codes=tuple(dict.fromkeys(reasons)),
                )
            current = promoted.anchor
            now = promotion_time
            self._record_attempt(
                attempt_id=attempt_id,
                current_anchor_id=staged_result.state.current_anchor_id,
                target_valid_from=candidate.anchor.validity.start,
                fingerprint=candidate.build_key,
                candidate_id=candidate.candidate_id,
                status=RolloverAttemptStatus.PROMOTED,
                reason_codes=(),
                updated_at=now,
            )
            current_source_checks = tuple(
                RegulatoryAnchorSourceCheck(
                    source_id=item.source_id,
                    expected_sha256=item.expected_sha256,
                    observed_sha256=item.observed_sha256,
                    checked_at=item.checked_at,
                )
                for item in candidate_coverage.source_checks
            )
            current_coverage = verify_regulatory_anchor_coverage(
                anchor=current,
                discovery=discovery,
                source_checks=current_source_checks,
                as_of=as_of,
                checked_at=now,
                facts=candidate.facts,
                effect_assertions=effect_assertions,
                reviews=active_reviews,
                review_source_checks=review_checks,
                policy=self._policy,
            )
            return self._report(
                as_of,
                RegulatoryRolloverAction.PROMOTED,
                current,
                (current.validity.end - as_of).days,
                discovery,
                current_coverage,
                candidate=candidate,
                candidate_coverage=candidate_coverage,
                candidate_id=candidate.candidate_id,
                attempt_id=attempt_id,
                cursor_updates=discovery.cursor_updates,
                reason_codes=tuple(dict.fromkeys(reasons)),
                promotion_outcome=promoted.outcome,
            )

        return self._report(
            as_of,
            RegulatoryRolloverAction.STAGED,
            current,
            days_to_expiry,
            discovery,
            current_coverage,
            candidate=candidate,
            candidate_coverage=candidate_coverage,
            candidate_id=candidate.candidate_id,
            attempt_id=attempt_id,
            cursor_updates=discovery.cursor_updates,
            reason_codes=tuple(dict.fromkeys(reasons)),
        )

    def source_preflight(
        self,
        as_of: date,
        coverage: RegulatoryAnchorCoverageEvidence | None,
    ) -> RegulatorySourcePreflightResult:
        """Return readiness without network, parsing, or anchor mutation."""

        current = self._repository.read_current_anchor()
        now = self._clock()
        state = self._repository.read_state()
        coverage_age_days = (
            (as_of - coverage.checked_at.astimezone(_ROMAN).date()).days
            if coverage is not None
            else None
        )
        valid = (
            current.status == VerificationStatus.VERIFIED
            and current.as_of <= as_of
            and current.validity.start <= as_of < current.validity.end
        )
        checks = {
            "current_anchor_verified": current.status == VerificationStatus.VERIFIED,
            "current_anchor_valid_at_as_of": valid,
            "coverage_present": coverage is not None,
            "coverage_matches_current": bool(
                coverage
                and coverage.anchor_id == current.anchor_id
                and coverage.anchor_sha256 == regulatory_anchor_artifact_digest(current)
            ),
            "coverage_matches_as_of": bool(coverage and coverage.as_of == as_of),
            "coverage_fresh": bool(
                coverage
                and coverage.checked_at <= now
                and coverage_age_days is not None
                and 0 <= coverage_age_days <= self._policy.coverage_max_age_days
            ),
            "coverage_ready": bool(coverage and coverage.ready),
            "no_expired_staged_gap": state.staged_candidate_id is not None
            or as_of < current.validity.end,
        }
        reasons: list[RegulatoryRolloverReason] = []
        if not valid:
            reasons.append(
                RegulatoryRolloverReason.CURRENT_ANCHOR_EXPIRED
                if as_of >= current.validity.end
                else RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE
            )
        if coverage is None:
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
        else:
            if coverage.anchor_id != current.anchor_id or (
                coverage.anchor_sha256 != regulatory_anchor_artifact_digest(current)
            ):
                reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            if coverage.as_of != as_of or not checks["coverage_fresh"]:
                reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
            reasons.extend(coverage.reason_codes)
        if not checks["no_expired_staged_gap"]:
            reasons.append(RegulatoryRolloverReason.NEXT_ANCHOR_MISSING)
        canonical_reasons = tuple(dict.fromkeys(reasons))
        return RegulatorySourcePreflightResult(
            ready=all(checks.values()),
            as_of=as_of,
            anchor_id=current.anchor_id,
            anchor_sha256=regulatory_anchor_artifact_digest(current),
            checks=checks,
            reason_codes=canonical_reasons,
        )

    def resolve_active(
        self, as_of: date, coverage: RegulatoryAnchorCoverageEvidence | None
    ) -> DomesticProjectionAnchor | None:
        """Select only the current immutable anchor when offline readiness holds."""

        if not self.source_preflight(as_of, coverage).ready:
            return None
        return self._repository.read_current_anchor()

    def _search_start(
        self, current: DomesticProjectionAnchor, cursors: tuple[RegistryCursor, ...]
    ) -> date:
        if cursors:
            return min(item.covered_through for item in cursors)
        return self._initial_search_start or current.validity.start

    def _parse_supported_records(
        self,
        discovery: RegulatoryDiscoveryReport,
        records_by_key: dict[tuple[RegulatoryRegistryChannel, str], OfficialRegistryRecord],
        *,
        known_records: tuple[OfficialRegistryRecord, ...] = (),
    ) -> tuple[
        tuple[RegulatoryFact, ...],
        tuple[RegulatoryEffectAssertion, ...],
        tuple[RegulatoryRolloverReason, ...],
    ]:
        facts: list[RegulatoryFact] = []
        effect_assertions: list[RegulatoryEffectAssertion] = []
        reasons: list[RegulatoryRolloverReason] = []
        supported = tuple(
            finding
            for finding in discovery.findings
            if finding.disposition == DiscoveryActDisposition.SUPPORTED
        )
        records_to_parse: dict[
            tuple[RegulatoryRegistryChannel, str, str], OfficialRegistryRecord
        ] = {}
        for finding in supported:
            record = records_by_key.get((finding.channel, finding.act_id)) or finding.source_record
            if record is None:
                reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
                continue
            identity = (record.channel, record.act_id, record.document_id)
            previous_record = records_to_parse.get(identity)
            if previous_record is not None and previous_record != record:
                reasons.append(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
                continue
            records_to_parse[identity] = record
        for record in known_records:
            identity = (record.channel, record.act_id, record.document_id)
            previous_record = records_to_parse.get(identity)
            if previous_record is not None and previous_record != record:
                reasons.append(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
                continue
            records_to_parse[identity] = record

        for identity in sorted(
            records_to_parse,
            key=lambda item: (item[0].value, item[1], item[2]),
        ):
            record = records_to_parse[identity]
            if self._source_port is None:
                reasons.append(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
                continue
            try:
                document = self._source_port.acquire_document(record)
            except DiscoveryFailure as exc:
                reasons.append(exc.reason)
                continue
            except OSError:
                reasons.append(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
                continue
            except (TypeError, ValueError):
                reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                continue
            if (
                document.channel != record.channel
                or document.act_id != record.act_id
                or document.document_id != record.document_id
                or document.record_url != record.url
                or document.published_at != record.published_at
            ):
                reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                continue
            parsed = self._parser_registry.parse(document)
            if parsed.disposition != ParserDisposition.PARSED:
                reasons.append(parsed.reason_code or RegulatoryRolloverReason.PARSER_FAILURE)
                continue
            facts.extend(parsed.facts)
            effect_assertions.extend(parsed.effect_assertions)
        fact_by_id: dict[str, RegulatoryFact] = {}
        for fact in facts:
            previous_fact = fact_by_id.get(fact.fact_id)
            if previous_fact is not None and previous_fact != fact:
                reasons.append(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
            fact_by_id[fact.fact_id] = fact
        assertion_by_id: dict[str, RegulatoryEffectAssertion] = {}
        for assertion in effect_assertions:
            previous_assertion = assertion_by_id.get(assertion.assertion_id)
            if previous_assertion is not None and previous_assertion != assertion:
                reasons.append(RegulatoryRolloverReason.DETERMINISM_VIOLATION)
            assertion_by_id[assertion.assertion_id] = assertion
        return (
            tuple(sorted(fact_by_id.values(), key=lambda item: item.fact_id)),
            tuple(sorted(assertion_by_id.values(), key=lambda item: item.assertion_id)),
            tuple(dict.fromkeys(reasons)),
        )

    def _build_candidate(
        self,
        current: DomesticProjectionAnchor,
        as_of: date,
        now: datetime,
        facts: tuple[RegulatoryFact, ...],
        reviews: tuple[RegulatoryManualReview, ...],
        *,
        allow_late_recovery: bool = False,
        effect_assertions: tuple[RegulatoryEffectAssertion, ...] = (),
    ) -> RegulatoryAnchorCandidate:
        starts = current.validity.end
        candidate_ends = sorted(
            {
                *(fact.validity.end for fact in facts if fact.validity.end > starts),
                *(
                    assertion.validity.end
                    for assertion in effect_assertions
                    if assertion.validity.start <= starts and assertion.validity.end > starts
                ),
            },
            reverse=True,
        )
        if not candidate_ends:
            from italian_energy.arera.rollover_validation import CandidateBuildFailure

            raise CandidateBuildFailure(
                RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
                "no normalized facts establish a successor period",
            )
        last_error: ValueError | None = None
        for end in candidate_ends:
            try:
                return build_regulatory_anchor_candidate(
                    current_anchor=current,
                    validity=DatePeriod(start=starts, end=end),
                    as_of=as_of,
                    created_at=now,
                    facts=facts,
                    decision_ids=tuple(sorted(item.decision_id for item in reviews)),
                    allow_late_recovery=allow_late_recovery,
                    effect_assertions=effect_assertions,
                )
            except ValueError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise ValueError("candidate build did not produce a verified period")

    @staticmethod
    def _recovery_discovery_is_complete(
        discovery: RegulatoryDiscoveryReport,
        expired_at: date,
        as_of: date,
    ) -> bool:
        """Require all registry scans to span the entire missed-validity gap."""

        recovery_end = date.fromordinal(as_of.toordinal() + 1)
        return discovery.scans_complete and all(
            snapshot.search_period.start <= expired_at
            and snapshot.search_period.end >= recovery_end
            for snapshot in discovery.snapshots
        )

    def _candidate_source_checks(
        self, candidate: RegulatoryAnchorCandidate, checked_at: datetime
    ) -> tuple[RegulatoryCandidateSourceCheck, ...]:
        observed: list[tuple[str, str, str | None]] = []
        for source in candidate.anchor.sources:
            if source.sha256 is None:
                observed.append((source.source_id, "0" * 64, None))
                continue
            observed.append((source.source_id, source.sha256, self._fetch_digest(source.url)))
        completed_at = self._clock_after(checked_at)
        return tuple(
            RegulatoryCandidateSourceCheck(
                source_id=source_id,
                expected_sha256=expected_sha256,
                observed_sha256=observed_sha256,
                checked_at=completed_at,
            )
            for source_id, expected_sha256, observed_sha256 in observed
        )

    def _anchor_source_checks(
        self, anchor: DomesticProjectionAnchor, checked_at: datetime
    ) -> tuple[RegulatoryAnchorSourceCheck, ...]:
        observed: list[tuple[str, str, str | None]] = []
        for source in anchor.sources:
            if source.sha256 is None:
                continue
            observed.append((source.source_id, source.sha256, self._fetch_digest(source.url)))
        completed_at = self._clock_after(checked_at)
        return tuple(
            RegulatoryAnchorSourceCheck(
                source_id=source_id,
                expected_sha256=expected_sha256,
                observed_sha256=observed_sha256,
                checked_at=completed_at,
            )
            for source_id, expected_sha256, observed_sha256 in observed
        )

    def _review_source_checks(
        self,
        reviews: tuple[RegulatoryManualReview, ...],
        checked_at: datetime,
    ) -> tuple[RegulatoryReviewSourceCheck, ...]:
        observed = tuple(
            (
                review,
                self._fetch_digest(review.source_url),
            )
            for review in sorted(reviews, key=lambda item: item.decision_id)
        )
        completed_at = self._clock_after(checked_at)
        return tuple(
            RegulatoryReviewSourceCheck(
                review_id=review.decision_id,
                expected_sha256=review.source_sha256,
                observed_sha256=observed_sha256,
                checked_at=completed_at,
            )
            for review, observed_sha256 in observed
        )

    def _fetch_digest(self, url: str) -> str | None:
        if self._source_port is None:
            return None
        try:
            body = self._source_port.fetch_source(url)
        except DiscoveryFailure:
            return None
        except (OSError, TypeError, ValueError):
            return None
        return hashlib.sha256(body).hexdigest()

    def _verify_candidate(
        self,
        candidate: RegulatoryAnchorCandidate,
        discovery: RegulatoryDiscoveryReport,
        as_of: date,
        checked_at: datetime,
        reviews: tuple[RegulatoryManualReview, ...],
        review_checks: tuple[RegulatoryReviewSourceCheck, ...],
        source_checks: tuple[RegulatoryCandidateSourceCheck, ...] | None = None,
    ) -> RegulatoryCandidateCoverageResult:
        checks = source_checks or self._candidate_source_checks(candidate, checked_at)
        evidence_checked_at = max(
            (
                checked_at,
                *(item.checked_at for item in checks),
                *(item.checked_at for item in review_checks),
            )
        )
        result = verify_regulatory_candidate_coverage(
            candidate=candidate,
            discovery=discovery,
            source_checks=checks,
            as_of=as_of,
            checked_at=evidence_checked_at,
            reviews=reviews,
            review_source_checks=review_checks,
            policy=self._policy,
        )
        included_acts = {fact.act_id for fact in candidate.facts}
        unaccounted_supported = any(
            finding.disposition == DiscoveryActDisposition.SUPPORTED
            and finding.act_id not in included_acts
            for finding in discovery.findings
        )
        if not unaccounted_supported:
            return result
        reasons = tuple(
            dict.fromkeys(
                (*result.reason_codes, RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            )
        )
        return RegulatoryCandidateCoverageResult.model_validate(
            {
                **result.model_dump(mode="python"),
                "ready": False,
                "reason_codes": reasons,
            }
        )

    def _record_attempt(
        self,
        *,
        attempt_id: str,
        current_anchor_id: str,
        target_valid_from: date,
        fingerprint: str,
        candidate_id: str | None,
        status: RolloverAttemptStatus,
        reason_codes: tuple[RegulatoryRolloverReason, ...],
        updated_at: datetime,
    ) -> RegulatoryRolloverAttempt:
        history = self._repository.attempt_history(attempt_id)
        if not history:
            self._repository.record_attempt(
                RegulatoryRolloverAttempt(
                    attempt_id=attempt_id,
                    current_anchor_id=current_anchor_id,
                    target_valid_from=target_valid_from,
                    input_fingerprint=fingerprint,
                    status=RolloverAttemptStatus.PREPARING,
                    updated_at=updated_at,
                )
            )
        return self._repository.record_attempt(
            RegulatoryRolloverAttempt(
                attempt_id=attempt_id,
                current_anchor_id=current_anchor_id,
                target_valid_from=target_valid_from,
                input_fingerprint=fingerprint,
                status=status,
                candidate_id=candidate_id,
                reason_codes=reason_codes,
                updated_at=updated_at,
            )
        )

    @staticmethod
    def _failure_status(
        reasons: tuple[RegulatoryRolloverReason, ...],
    ) -> RolloverAttemptStatus:
        if any(
            reason
            in {
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                RegulatoryRolloverReason.MAPPING_FAILURE,
            }
            for reason in reasons
        ):
            return RolloverAttemptStatus.REVIEW_REQUIRED
        if any(
            reason
            in {
                RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
                RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
                RegulatoryRolloverReason.DETERMINISM_VIOLATION,
            }
            for reason in reasons
        ):
            return RolloverAttemptStatus.REJECTED
        return RolloverAttemptStatus.PREPARING

    @staticmethod
    def _permanent_staged_failure(
        reasons: tuple[RegulatoryRolloverReason, ...],
    ) -> bool:
        permanent_reasons = {
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
            RegulatoryRolloverReason.PARSER_FAILURE,
            RegulatoryRolloverReason.MAPPING_FAILURE,
            RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
            RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
            RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
            RegulatoryRolloverReason.DETERMINISM_VIOLATION,
        }
        return bool(permanent_reasons.intersection(reasons))

    @staticmethod
    def _blocked_action(
        reasons: tuple[RegulatoryRolloverReason, ...],
    ) -> RegulatoryRolloverAction:
        if RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in reasons or (
            RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY in reasons
        ):
            return RegulatoryRolloverAction.REVIEW_REQUIRED
        return RegulatoryRolloverAction.BLOCKED

    @staticmethod
    def _report(
        as_of: date,
        action: RegulatoryRolloverAction,
        current: DomesticProjectionAnchor,
        days_to_expiry: int,
        discovery: RegulatoryDiscoveryReport,
        current_coverage: RegulatoryAnchorCoverageEvidence,
        *,
        candidate: RegulatoryAnchorCandidate | None = None,
        candidate_coverage: RegulatoryCandidateCoverageResult | None = None,
        candidate_id: str | None = None,
        attempt_id: str | None = None,
        cursor_updates: tuple[RegistryCursor, ...] = (),
        reason_codes: tuple[RegulatoryRolloverReason, ...] = (),
        promotion_outcome: PromotionOutcome | None = None,
    ) -> RegulatoryRolloverReport:
        return RegulatoryRolloverReport(
            as_of=as_of,
            action=action,
            current_anchor_id=current.anchor_id,
            current_anchor_sha256=regulatory_anchor_artifact_digest(current),
            staged_candidate_id=candidate_id if action == RegulatoryRolloverAction.STAGED else None,
            candidate_id=candidate_id,
            attempt_id=attempt_id,
            days_to_expiry=days_to_expiry,
            discovery=discovery,
            candidate=candidate,
            current_coverage=current_coverage,
            candidate_coverage=candidate_coverage,
            cursor_updates=cursor_updates,
            reason_codes=reason_codes,
            promotion_outcome=promotion_outcome,
        )


def create_official_regulatory_service(
    repository: RegulatoryRepository,
    *,
    policy: RolloverPolicy = DEFAULT_ROLLOVER_POLICY,
    initial_search_start: date | None = None,
    clock: Callable[[], datetime] | None = None,
    transport_factory: Callable[[], OfficialRegistryTransport] | None = None,
) -> RegulatoryRolloverService:
    """Construct the production Core workflow from its persistence port alone.

    The factory owns official registry adapters and exact-byte acquisition.
    Platform supplies only its implementation of ``RegulatoryRepository``;
    parser, mapping, validity, coverage, and promotion policy remain in Core.
    """

    base_transport_factory = transport_factory or UrllibOfficialRegistryTransport
    observer = repository.save_raw_source

    def observed_transport() -> OfficialRegistryTransport:
        return RecordingOfficialRegistryTransport(base_transport_factory(), observer)

    adapters = default_official_registry_adapters(
        transport_factory=observed_transport,
    )
    source_port = OfficialRegulatoryDocumentAcquirer(observed_transport())
    return RegulatoryRolloverService(
        repository,
        registry_adapters=adapters,
        source_port=source_port,
        known_source_records=normattiva_vat_reference_records,
        policy=policy,
        initial_search_start=initial_search_start,
        clock=clock,
    )


__all__ = [
    "RegulatoryRolloverAction",
    "RegulatoryRolloverReport",
    "RegulatoryRolloverService",
    "RegulatoryRolloverSourcePort",
    "RegulatorySourcePreflightResult",
    "create_official_regulatory_service",
]
