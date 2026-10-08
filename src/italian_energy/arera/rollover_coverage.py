"""Fail-closed discovery and source verification for immutable candidates."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from enum import StrEnum
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.discovery import (
    DiscoveryActDisposition,
    DiscoveryChangeKind,
    RegulatoryDiscoveryReport,
    RegulatoryRegistryChannel,
)
from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.arera.rollover_models import (
    RegulatoryAnchorCandidate,
    RegulatoryEffectAssertion,
    RegulatoryEffectKind,
    RegulatoryFact,
    RegulatoryRolloverReason,
    RolloverPolicy,
    regulatory_anchor_artifact_digest,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod

_CIVIL_TIMEZONE = ZoneInfo("Europe/Rome")


def _civil_date(value: datetime) -> date:
    return value.astimezone(_CIVIL_TIMEZONE).date()


class RegulatoryReviewOutcome(StrEnum):
    """Explicit outcome of an auditable human review artifact."""

    IRRELEVANT_BY_VERSIONED_RULE = "irrelevant_by_versioned_rule"
    MAPPING_APPROVED = "mapping_approved"
    REJECTED = "rejected"


class RegulatoryManualReview(DomainModel):
    """Versioned, digest-bound decision for one discovered official act."""

    channel: RegulatoryRegistryChannel
    act_id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scope: DatePeriod
    outcome: RegulatoryReviewOutcome
    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    rationale: str = Field(min_length=1)
    rule_id: str | None = None
    rule_version: str | None = None
    parser_id: str | None = None
    parser_version: str | None = None
    mapping_id: str | None = None
    mapping_version: str | None = None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_review_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("regulatory manual review time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_review(self) -> RegulatoryManualReview:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in self.channel.official_hosts:
            raise ValueError("manual review URL must match its official registry channel")
        if self.outcome == RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE and (
            not self.rule_id or not self.rule_version
        ):
            raise ValueError("irrelevance review requires a versioned rule")
        if self.outcome == RegulatoryReviewOutcome.MAPPING_APPROVED and not all(
            (
                self.parser_id,
                self.parser_version,
                self.mapping_id,
                self.mapping_version,
            )
        ):
            raise ValueError("mapping approval requires parser and mapping versions")
        return self

    @property
    def decision_id(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class RegulatoryCandidateSourceCheck(DomainModel):
    """Digest observation of one source referenced by a candidate."""

    source_id: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def require_aware_check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate source check time must be timezone-aware")
        return value


class RegulatoryReviewSourceCheck(DomainModel):
    """Digest verification for the exact document inspected in a manual review."""

    review_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def require_aware_check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("review source check time must be timezone-aware")
        return value


class RegulatoryAnchorSourceCheck(DomainModel):
    """Digest observation for one source in an already published anchor."""

    source_id: str = Field(min_length=1)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    checked_at: datetime

    @field_validator("checked_at")
    @classmethod
    def require_aware_check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("anchor source check time must be timezone-aware")
        return value


class RegulatoryAnchorCoverageEvidence(DomainModel):
    """Dated proof that a published anchor remains usable for one civil date."""

    anchor_id: str = Field(min_length=1)
    anchor_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: date
    checked_at: datetime
    discovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_checks: tuple[RegulatoryAnchorSourceCheck, ...]
    review_ids: tuple[str, ...] = ()
    ready: bool
    reason_codes: tuple[RegulatoryRolloverReason, ...] = ()

    @field_validator("checked_at")
    @classmethod
    def require_aware_coverage_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("anchor coverage time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_evidence(self) -> RegulatoryAnchorCoverageEvidence:
        source_ids = tuple(item.source_id for item in self.source_checks)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("anchor source checks must have unique source IDs")
        if self.review_ids != tuple(sorted(set(self.review_ids))):
            raise ValueError("anchor coverage review IDs must be unique and canonical")
        if self.ready != (not self.reason_codes):
            raise ValueError("anchor coverage readiness must match its reason codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("anchor coverage reason codes must be unique")
        return self

    @property
    def comparison_as_of(self) -> date:
        """Compatibility-shaped date accessor for comparison consumers."""

        return self.as_of

    @property
    def evidence_id(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return f"regulatory-anchor-coverage:{hashlib.sha256(encoded).hexdigest()}"


class RegulatoryCandidateCoverageResult(DomainModel):
    """Immutable verification evidence required before staging a candidate."""

    candidate_id: str = Field(min_length=1)
    candidate_build_key: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: date
    checked_at: datetime
    discovery_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_checks: tuple[RegulatoryCandidateSourceCheck, ...]
    reviews: tuple[RegulatoryManualReview, ...] = ()
    review_source_checks: tuple[RegulatoryReviewSourceCheck, ...] = ()
    review_ids: tuple[str, ...] = ()
    ready: bool
    reason_codes: tuple[RegulatoryRolloverReason, ...] = ()

    @field_validator("checked_at")
    @classmethod
    def require_aware_coverage_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("candidate coverage time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_coverage_result(self) -> RegulatoryCandidateCoverageResult:
        source_ids = tuple(item.source_id for item in self.source_checks)
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("candidate source checks must have unique source IDs")
        if self.review_ids != tuple(sorted(set(self.review_ids))):
            raise ValueError("coverage review IDs must be unique and canonical")
        review_ids = tuple(sorted({item.decision_id for item in self.reviews}))
        if review_ids != self.review_ids:
            raise ValueError("coverage review artifacts must match their IDs")
        checked_review_ids = tuple(sorted({item.review_id for item in self.review_source_checks}))
        if not set(checked_review_ids).issubset(self.review_ids):
            raise ValueError("coverage review source checks must reference known artifacts")
        if self.ready != (not self.reason_codes):
            raise ValueError("candidate coverage readiness must match its reason codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("candidate coverage reason codes must be unique")
        return self


def _discovery_digest(discovery: RegulatoryDiscoveryReport) -> str:
    encoded = json.dumps(
        discovery.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _review_satisfies_finding(
    candidate: RegulatoryAnchorCandidate,
    review: RegulatoryManualReview | None,
    channel: RegulatoryRegistryChannel,
    act_id: str,
    as_of: date,
    checked_at: datetime,
) -> bool:
    if review is None or review.channel != channel or review.act_id != act_id:
        return False
    if review.decision_id not in candidate.decision_ids:
        return False
    if review.reviewed_at > checked_at or review.scope.start > candidate.anchor.validity.start:
        return False
    if review.scope.end < candidate.anchor.validity.end or _civil_date(review.reviewed_at) > as_of:
        return False
    if review.outcome == RegulatoryReviewOutcome.MAPPING_APPROVED:
        return any(
            fact.act_id == review.act_id
            and fact.source_sha256 == review.source_sha256
            and fact.parser_id == review.parser_id
            and fact.parser_version == review.parser_version
            for fact in candidate.facts
        ) and any(
            decision.mapping_id == review.mapping_id
            and decision.mapping_version == review.mapping_version
            for decision in candidate.mapping_decisions
        )
    return True


def verify_regulatory_candidate_coverage(
    *,
    candidate: RegulatoryAnchorCandidate,
    discovery: RegulatoryDiscoveryReport,
    source_checks: tuple[RegulatoryCandidateSourceCheck, ...],
    as_of: date,
    checked_at: datetime,
    reviews: tuple[RegulatoryManualReview, ...] = (),
    review_source_checks: tuple[RegulatoryReviewSourceCheck, ...] = (),
    policy: RolloverPolicy | None = None,
) -> RegulatoryCandidateCoverageResult:
    """Verify complete discovery and every candidate source without mutation."""

    active_policy = policy or RolloverPolicy()
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("candidate coverage time must be timezone-aware")

    reasons: list[RegulatoryRolloverReason] = []
    if discovery.as_of != as_of or discovery.as_of < candidate.anchor.as_of:
        reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
    if _civil_date(checked_at) != as_of:
        reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
    for snapshot in discovery.snapshots:
        if snapshot.reason_code is not None:
            reasons.append(snapshot.reason_code)
        elif not snapshot.complete:
            reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
    if any(
        snapshot.discovered_at > checked_at
        or (_civil_date(checked_at) - _civil_date(snapshot.discovered_at)).days
        > active_policy.coverage_max_age_days
        for snapshot in discovery.snapshots
    ):
        reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)

    review_by_key = {(item.channel, item.act_id): item for item in reviews}
    if len(review_by_key) != len(reviews):
        reasons.append(RegulatoryRolloverReason.MAPPING_FAILURE)
    review_ids = tuple(sorted({item.decision_id for item in reviews}))

    review_checks_by_id = {item.review_id: item for item in review_source_checks}
    if len(review_checks_by_id) != len(review_source_checks):
        reasons.append(RegulatoryRolloverReason.MAPPING_FAILURE)
    if set(review_checks_by_id) != {item.decision_id for item in reviews}:
        reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
    for review in reviews:
        check = review_checks_by_id.get(review.decision_id)
        if check is None:
            continue
        if (
            check.checked_at > checked_at
            or (_civil_date(checked_at) - _civil_date(check.checked_at)).days
            > active_policy.coverage_max_age_days
        ):
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
        if check.expected_sha256 != review.source_sha256:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        if check.observed_sha256 is None:
            reasons.append(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
        elif check.observed_sha256 != review.source_sha256:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)

    for finding in discovery.findings:
        if finding.disposition != DiscoveryActDisposition.REVIEW_REQUIRED:
            continue
        finding_review = review_by_key.get((finding.channel, finding.act_id))
        if (
            finding_review is not None
            and finding_review.outcome == RegulatoryReviewOutcome.REJECTED
        ):
            reasons.append(RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED)
            continue
        if not _review_satisfies_finding(
            candidate, finding_review, finding.channel, finding.act_id, as_of, checked_at
        ):
            reasons.append(RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE)
    for change in discovery.changes:
        if change.kind == DiscoveryChangeKind.NEW:
            continue
        change_review = review_by_key.get((change.channel, change.act_id))
        if change_review is not None and change_review.outcome == RegulatoryReviewOutcome.REJECTED:
            reasons.append(RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED)
            continue
        expected_review_digest = (
            change.observed_sha256
            if change.kind == DiscoveryChangeKind.CHANGED
            else change.previous_sha256
        )
        if change_review is not None and change_review.source_sha256 != expected_review_digest:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            continue
        if not _review_satisfies_finding(
            candidate, change_review, change.channel, change.act_id, as_of, checked_at
        ):
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)

    expected_sources = {item.source_id: item.sha256 for item in candidate.anchor.sources}
    observed_checks = {item.source_id: item for item in source_checks}
    if len(observed_checks) != len(source_checks):
        reasons.append(RegulatoryRolloverReason.MAPPING_FAILURE)
    if set(observed_checks) != set(expected_sources):
        reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
    for source_id, expected in expected_sources.items():
        source_check = observed_checks.get(source_id)
        if source_check is None:
            continue
        if source_check.checked_at > checked_at:
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
        if (
            _civil_date(checked_at) - _civil_date(source_check.checked_at)
        ).days > active_policy.coverage_max_age_days:
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
        if source_check.expected_sha256 != expected:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        if source_check.observed_sha256 is None:
            reasons.append(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
        elif source_check.observed_sha256 != expected:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)

    canonical_reasons = tuple(dict.fromkeys(reasons))
    return RegulatoryCandidateCoverageResult(
        candidate_id=candidate.candidate_id,
        candidate_build_key=candidate.build_key,
        as_of=as_of,
        checked_at=checked_at,
        discovery_sha256=_discovery_digest(discovery),
        source_checks=tuple(observed_checks[source_id] for source_id in sorted(observed_checks)),
        reviews=tuple(sorted(reviews, key=lambda item: item.decision_id)),
        review_source_checks=tuple(
            review_checks_by_id[review_id]
            for review_id in sorted(set(review_checks_by_id).intersection(review_ids))
        ),
        review_ids=review_ids,
        ready=not canonical_reasons,
        reason_codes=canonical_reasons,
    )


def _review_clears_current_finding(
    *,
    review: RegulatoryManualReview | None,
    channel: RegulatoryRegistryChannel,
    act_id: str,
    expected_digest: str | None,
    expected_url: str | None,
    anchor: DomesticProjectionAnchor,
    checked_at: datetime,
    review_checks: dict[str, RegulatoryReviewSourceCheck],
) -> bool:
    if (
        review is None
        or review.channel != channel
        or review.act_id != act_id
        or review.outcome != RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE
        or review.reviewed_at > checked_at
        or review.scope.start > anchor.validity.start
        or review.scope.end < anchor.validity.end
        or (expected_digest is not None and review.source_sha256 != expected_digest)
        or (expected_url is not None and review.source_url != expected_url)
    ):
        return False
    check = review_checks.get(review.decision_id)
    return bool(
        check
        and check.expected_sha256 == review.source_sha256
        and check.observed_sha256 == review.source_sha256
        and check.checked_at <= checked_at
    )


def verify_regulatory_anchor_coverage(
    *,
    anchor: DomesticProjectionAnchor,
    discovery: RegulatoryDiscoveryReport,
    source_checks: tuple[RegulatoryAnchorSourceCheck, ...],
    as_of: date,
    checked_at: datetime,
    facts: tuple[RegulatoryFact, ...] = (),
    effect_assertions: tuple[RegulatoryEffectAssertion, ...] = (),
    reviews: tuple[RegulatoryManualReview, ...] = (),
    review_source_checks: tuple[RegulatoryReviewSourceCheck, ...] = (),
    policy: RolloverPolicy | None = None,
) -> RegulatoryAnchorCoverageEvidence:
    """Verify that known sources and later-act discovery still cover current.

    A supported new act is harmless to this anchor only when its parsed facts
    do not overlap the current validity. An unknown or changed act requires a
    digest-bound irrelevant-by-versioned-rule review before readiness.
    """

    active_policy = policy or RolloverPolicy()
    if checked_at.tzinfo is None or checked_at.utcoffset() is None:
        raise ValueError("anchor coverage time must be timezone-aware")

    reasons: list[RegulatoryRolloverReason] = []
    if anchor.status != VerificationStatus.VERIFIED:
        reasons.append(RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED)
    if not (anchor.as_of <= as_of and anchor.validity.start <= as_of < anchor.validity.end):
        reasons.append(
            RegulatoryRolloverReason.CURRENT_ANCHOR_EXPIRED
            if as_of >= anchor.validity.end
            else RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE
        )
    if discovery.as_of != as_of:
        reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)
    for snapshot in discovery.snapshots:
        if snapshot.reason_code is not None:
            reasons.append(snapshot.reason_code)
        elif not snapshot.complete:
            reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        if (
            snapshot.discovered_at > checked_at
            or (_civil_date(checked_at) - _civil_date(snapshot.discovered_at)).days
            > active_policy.coverage_max_age_days
        ):
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)

    source_by_id = {source.source_id: source for source in anchor.sources}
    checks_by_id = {item.source_id: item for item in source_checks}
    if len(checks_by_id) != len(source_checks) or set(checks_by_id) != set(source_by_id):
        reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
    for source_id, source in source_by_id.items():
        check = checks_by_id.get(source_id)
        if check is None:
            continue
        if source.sha256 is None or check.expected_sha256 != source.sha256:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        if check.observed_sha256 is None:
            reasons.append(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
        elif check.observed_sha256 != source.sha256:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        if (
            check.checked_at > checked_at
            or (_civil_date(checked_at) - _civil_date(check.checked_at)).days
            > active_policy.coverage_max_age_days
        ):
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)

    review_by_key = {(item.channel, item.act_id): item for item in reviews}
    if len(review_by_key) != len(reviews):
        reasons.append(RegulatoryRolloverReason.MAPPING_FAILURE)
    review_checks = {item.review_id: item for item in review_source_checks}
    review_ids = tuple(sorted({item.decision_id for item in reviews}))
    if len(review_checks) != len(review_source_checks) or set(review_checks) != set(review_ids):
        reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
    for review in reviews:
        review_check = review_checks.get(review.decision_id)
        if review_check is None:
            continue
        if review_check.expected_sha256 != review.source_sha256:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        elif review_check.observed_sha256 is None:
            reasons.append(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
        elif review_check.observed_sha256 != review.source_sha256:
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        if (
            review_check.checked_at > checked_at
            or (_civil_date(checked_at) - _civil_date(review_check.checked_at)).days
            > active_policy.coverage_max_age_days
        ):
            reasons.append(RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE)

    for finding in discovery.findings:
        if finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE:
            continue
        record = next(
            (
                record
                for snapshot in discovery.snapshots
                for record in snapshot.records
                if record.channel == finding.channel and record.act_id == finding.act_id
            ),
            finding.source_record,
        )
        related_facts = tuple(fact for fact in facts if fact.act_id == finding.act_id)
        related_assertions = tuple(
            assertion for assertion in effect_assertions if assertion.act_id == finding.act_id
        )
        if finding.disposition == DiscoveryActDisposition.SUPPORTED:
            if not related_facts and not related_assertions:
                reasons.append(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
            elif any(
                fact.validity.start < anchor.validity.end
                and anchor.validity.start < fact.validity.end
                and (
                    fact.source_id not in source_by_id
                    or source_by_id[fact.source_id].sha256 != fact.source_sha256
                )
                for fact in related_facts
            ) or any(
                assertion.validity.start < anchor.validity.end
                and anchor.validity.start < assertion.validity.end
                and not any(
                    fact.effect.kind == RegulatoryEffectKind.CONFIRM_VALUE
                    and fact.effect.previous_anchor_id is not None
                    and fact.source_sha256 == assertion.source_sha256
                    and fact.parser_id == assertion.parser_id
                    and fact.parser_version == assertion.parser_version
                    and f"{assertion.act_id} {assertion.locator}" in fact.effect.provision
                    and fact.validity.start <= assertion.validity.start
                    and fact.validity.end >= assertion.validity.end
                    for fact in related_facts
                )
                for assertion in related_assertions
            ):
                reasons.append(RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY)
            continue
        finding_review = review_by_key.get((finding.channel, finding.act_id))
        if not _review_clears_current_finding(
            review=finding_review,
            channel=finding.channel,
            act_id=finding.act_id,
            expected_digest=None,
            expected_url=record.url if record is not None else None,
            anchor=anchor,
            checked_at=checked_at,
            review_checks=review_checks,
        ):
            reasons.append(RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE)

    for change in discovery.changes:
        change_review = review_by_key.get((change.channel, change.act_id))
        if not _review_clears_current_finding(
            review=change_review,
            channel=change.channel,
            act_id=change.act_id,
            expected_digest=None,
            expected_url=next(
                (
                    record.url
                    for snapshot in discovery.snapshots
                    for record in snapshot.records
                    if record.channel == change.channel and record.act_id == change.act_id
                ),
                None,
            ),
            anchor=anchor,
            checked_at=checked_at,
            review_checks=review_checks,
        ):
            reasons.append(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)

    canonical_reasons = tuple(dict.fromkeys(reasons))
    return RegulatoryAnchorCoverageEvidence(
        anchor_id=anchor.anchor_id,
        anchor_sha256=regulatory_anchor_artifact_digest(anchor),
        as_of=as_of,
        checked_at=checked_at,
        discovery_sha256=_discovery_digest(discovery),
        source_checks=tuple(checks_by_id[key] for key in sorted(checks_by_id)),
        review_ids=review_ids,
        ready=not canonical_reasons,
        reason_codes=canonical_reasons,
    )


__all__ = [
    "RegulatoryAnchorCoverageEvidence",
    "RegulatoryAnchorSourceCheck",
    "RegulatoryCandidateCoverageResult",
    "RegulatoryCandidateSourceCheck",
    "RegulatoryManualReview",
    "RegulatoryReviewOutcome",
    "RegulatoryReviewSourceCheck",
    "verify_regulatory_anchor_coverage",
    "verify_regulatory_candidate_coverage",
]
