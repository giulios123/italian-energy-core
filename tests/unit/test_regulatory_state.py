from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from threading import Barrier

import pytest
from pydantic import ValidationError
from test_regulatory_candidate import AS_OF, CREATED_AT, VALIDITY, _complete_facts
from test_regulatory_coverage import _candidate, _checks, _discovery, _verify

from italian_energy.arera.discovery import RegulatoryRegistryChannel
from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.arera.rollover_coverage import RegulatoryCandidateCoverageResult
from italian_energy.arera.rollover_mapping import build_regulatory_anchor_candidate
from italian_energy.arera.rollover_models import (
    RegulatoryAnchorCandidate,
    RegulatoryRolloverReason,
    RolloverPolicy,
)
from italian_energy.arera.rollover_repository import (
    InMemoryRegulatoryRepository,
    RegulatoryRepository,
    RegulatoryRepositoryError,
    StageResult,
    regulatory_candidate_semantic_digest,
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
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod

NEXT_DAY = date(2026, 10, 1)
PROMOTED_AT = datetime(2026, 10, 1, 12, tzinfo=UTC)
STAGED_AT = datetime(2026, 9, 30, 13, tzinfo=UTC)
POLICY = RolloverPolicy()


def _coverage(
    candidate: RegulatoryAnchorCandidate, as_of: date = AS_OF
) -> RegulatoryCandidateCoverageResult:
    checked_at = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC).replace(hour=12)
    return _verify(
        candidate,
        discovery=_discovery(as_of=as_of, discovered_at=checked_at),
        checks=_checks(candidate, checked_at),
        checked_at=checked_at,
        as_of=as_of,
    )


def _repository() -> InMemoryRegulatoryRepository:
    return InMemoryRegulatoryRepository(load_domestic_projection_anchor(), initialized_at=STAGED_AT)


def _candidate_variant() -> RegulatoryAnchorCandidate:
    return build_regulatory_anchor_candidate(
        current_anchor=load_domestic_projection_anchor(),
        validity=VALIDITY,
        as_of=AS_OF,
        created_at=CREATED_AT,
        facts=_complete_facts(),
        mapping_version="synthetic-mapping-2.0.0",
    )


def _stage(
    repository: InMemoryRegulatoryRepository,
    candidate: RegulatoryAnchorCandidate | None = None,
    *,
    expected_generation: int = 0,
) -> StageResult:
    chosen = candidate or _candidate()
    return repository.stage(
        chosen,
        _coverage(chosen),
        as_of=AS_OF,
        staged_at=STAGED_AT,
        expected_generation=expected_generation,
        expected_current_anchor_id=load_domestic_projection_anchor().anchor_id,
        policy=POLICY,
    )


def test_repository_initializes_verified_current_and_reads_protocol() -> None:
    repository = _repository()

    assert isinstance(repository, RegulatoryRepository)
    assert repository.read_state().generation == 0
    assert repository.read_state().staged_candidate_id is None
    assert repository.read_current_anchor() == load_domestic_projection_anchor()
    assert repository.historical_anchors() == ()


def test_candidate_put_if_absent_preserves_first_snapshot_across_reruns() -> None:
    repository = _repository()
    candidate = _candidate()
    later_candidate = candidate.model_copy(
        update={"created_at": datetime(2026, 9, 30, 14, tzinfo=UTC)}
    )

    first = repository.put_candidate_if_absent(candidate)
    rerun = repository.put_candidate_if_absent(later_candidate)

    assert first == candidate
    assert rerun is first
    assert repository.get_candidate(candidate.candidate_id) is first
    assert regulatory_candidate_semantic_digest(candidate) == regulatory_candidate_semantic_digest(
        later_candidate
    )


def test_repository_retains_exact_raw_response_immutably_by_observation() -> None:
    repository = _repository()
    content = b"official response bytes"
    source = AcquiredOfficialBytes(
        url="https://www.arera.it/atti-e-provvedimenti",
        body=content,
        sha256=sha256(content).hexdigest(),
        fetched_at=datetime(2026, 9, 30, 12, tzinfo=UTC),
        final_url="https://www.arera.it/atti-e-provvedimenti",
        content_type="text/html; charset=utf-8",
        byte_length=len(content),
    )

    repository.save_raw_source(source)
    repository.save_raw_source(source)

    assert repository.raw_source_observations() == (source,)
    assert repository.raw_source_observations()[0].body == content


def test_same_build_key_with_different_mapping_output_is_determinism_failure() -> None:
    repository = _repository()
    candidate = _candidate()
    changed_decision = candidate.mapping_decisions[0].model_copy(
        update={"value": candidate.mapping_decisions[0].value + Decimal("1")}
    )
    changed = candidate.model_copy(
        update={"mapping_decisions": (changed_decision, *candidate.mapping_decisions[1:])}
    )
    repository.put_candidate_if_absent(candidate)

    with pytest.raises(RegulatoryRepositoryError) as caught:
        repository.put_candidate_if_absent(changed)

    assert caught.value.reason_code == RegulatoryRolloverReason.DETERMINISM_VIOLATION


def test_staging_is_idempotent_and_keeps_current_anchor_unchanged() -> None:
    repository = _repository()
    candidate = _candidate()
    current = repository.read_current_anchor()

    first = _stage(repository, candidate)
    rerun = repository.stage(
        candidate,
        _coverage(candidate),
        as_of=AS_OF,
        staged_at=STAGED_AT,
        expected_generation=0,
        expected_current_anchor_id=current.anchor_id,
        policy=POLICY,
    )

    assert first.outcome == StageOutcome.STAGED
    assert rerun.outcome == StageOutcome.ALREADY_STAGED
    assert repository.read_current_anchor() == current
    assert rerun.state.generation == 1
    assert len(repository.events()) == 1
    assert repository.events()[0].kind == RolloverEventKind.CANDIDATE_STAGED


def test_staging_competitors_use_cas_and_only_one_pointer_event() -> None:
    repository = _repository()
    candidate = _candidate()
    barrier = Barrier(2)

    def stage_once() -> StageOutcome:
        barrier.wait()
        return _stage(repository, candidate).outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: stage_once(), range(2)))

    assert set(outcomes) == {StageOutcome.STAGED, StageOutcome.ALREADY_STAGED}
    assert repository.read_state().generation == 1
    assert len(repository.events()) == 1


def test_different_candidate_cannot_replace_an_existing_staged_candidate() -> None:
    repository = _repository()
    first = _candidate()
    second = _candidate_variant()
    _stage(repository, first)

    with pytest.raises(RegulatoryRepositoryError) as caught:
        _stage(repository, second, expected_generation=1)

    assert caught.value.reason_code == RegulatoryRolloverReason.PROMOTION_CONFLICT
    assert repository.read_state().staged_candidate_id == first.candidate_id
    assert len(repository.events()) == 1


def test_staged_candidate_can_be_revoked_without_mutating_current_anchor() -> None:
    repository = _repository()
    candidate = _candidate()
    current = repository.read_current_anchor()
    _stage(repository, candidate)
    revoked = repository.revoke_staged(
        candidate.candidate_id,
        (RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,),
        occurred_at=PROMOTED_AT,
        expected_generation=1,
        expected_current_anchor_id=current.anchor_id,
    )

    assert revoked.current_anchor_id == current.anchor_id
    assert revoked.staged_candidate_id is None
    assert revoked.generation == 2
    assert repository.read_current_anchor() == current
    assert repository.events()[-1].kind == RolloverEventKind.CANDIDATE_REVOKED
    assert repository.events()[-1].reason_codes == (
        RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
    )

    with pytest.raises(RegulatoryRepositoryError) as duplicate:
        repository.revoke_staged(
            candidate.candidate_id,
            (RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,),
            occurred_at=PROMOTED_AT,
            expected_generation=1,
            expected_current_anchor_id=current.anchor_id,
        )
    assert duplicate.value.reason_code == RegulatoryRolloverReason.PROMOTION_CONFLICT
    with pytest.raises(ValueError, match="requires a reason code"):
        repository.revoke_staged(
            candidate.candidate_id,
            (),
            occurred_at=PROMOTED_AT,
            expected_generation=2,
            expected_current_anchor_id=current.anchor_id,
        )


def test_ledger_deduplicates_replayed_event_identity() -> None:
    repository = _repository()
    candidate = _candidate()
    current = repository.read_current_anchor()
    _stage(repository, candidate)
    repository._append_event(
        kind=RolloverEventKind.CANDIDATE_STAGED,
        occurred_at=STAGED_AT,
        generation=1,
        previous_anchor_id=current.anchor_id,
        current_anchor_id=current.anchor_id,
        candidate_id=candidate.candidate_id,
    )

    assert len(repository.events()) == 1


def test_stage_rejects_stale_bad_coverage_and_wrong_current_generation() -> None:
    repository = _repository()
    candidate = _candidate()
    current = repository.read_current_anchor()
    coverage = _coverage(candidate)

    with pytest.raises(RegulatoryRepositoryError) as stale:
        repository.stage(
            candidate,
            coverage,
            as_of=NEXT_DAY,
            staged_at=PROMOTED_AT,
            expected_generation=0,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )
    with pytest.raises(RegulatoryRepositoryError) as conflict:
        repository.stage(
            candidate,
            coverage,
            as_of=AS_OF,
            staged_at=STAGED_AT,
            expected_generation=1,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )
    with pytest.raises(RegulatoryRepositoryError) as wrong_current:
        repository.stage(
            candidate,
            coverage,
            as_of=AS_OF,
            staged_at=STAGED_AT,
            expected_generation=0,
            expected_current_anchor_id="another-anchor",
            policy=POLICY,
        )

    assert stale.value.reason_code == RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE
    assert conflict.value.reason_code == RegulatoryRolloverReason.PROMOTION_CONFLICT
    assert wrong_current.value.reason_code == RegulatoryRolloverReason.PROMOTION_CONFLICT
    assert repository.read_state().generation == 0


def test_stage_checks_candidate_coverage_identity_and_operation_clock() -> None:
    candidate = _candidate()
    repository = _repository()
    current = repository.read_current_anchor()
    wrong_coverage = _coverage(_candidate_variant())
    coverage = _coverage(candidate)
    early_stage_time = datetime(2026, 9, 30, 11, tzinfo=UTC)

    with pytest.raises(RegulatoryRepositoryError) as wrong_identity:
        repository.stage(
            candidate,
            wrong_coverage,
            as_of=AS_OF,
            staged_at=STAGED_AT,
            expected_generation=0,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )
    with pytest.raises(RegulatoryRepositoryError) as future_evidence:
        repository.stage(
            candidate,
            coverage,
            as_of=AS_OF,
            staged_at=early_stage_time,
            expected_generation=0,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )

    assert wrong_identity.value.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
    assert future_evidence.value.reason_code == RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE


def test_stage_fails_closed_if_coverage_is_not_ready_without_reason_detail() -> None:
    candidate = _candidate()
    repository = _repository()
    blocked = _coverage(candidate).model_copy(update={"ready": False, "reason_codes": ()})

    with pytest.raises(RegulatoryRepositoryError) as caught:
        repository.stage(
            candidate,
            blocked,
            as_of=AS_OF,
            staged_at=STAGED_AT,
            expected_generation=0,
            expected_current_anchor_id=repository.read_current_anchor().anchor_id,
            policy=POLICY,
        )

    assert caught.value.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE


def test_stage_rejects_candidate_not_adjacent_to_repository_current() -> None:
    candidate = _candidate()
    current_payload = candidate.anchor.model_dump(mode="python")
    current_payload.update(
        {
            "anchor_id": "synthetic-current-a",
            "as_of": date(2026, 9, 29),
            "validity": DatePeriod(start=date(2026, 7, 1), end=date(2026, 9, 30)),
            "status": VerificationStatus.VERIFIED,
        }
    )
    current_anchor = type(candidate.anchor).model_validate(current_payload)
    repository = InMemoryRegulatoryRepository(current_anchor, initialized_at=STAGED_AT)

    with pytest.raises(RegulatoryRepositoryError) as caught:
        repository.stage(
            candidate,
            _coverage(candidate),
            as_of=AS_OF,
            staged_at=STAGED_AT,
            expected_generation=0,
            expected_current_anchor_id=current_anchor.anchor_id,
            policy=POLICY,
        )

    assert caught.value.reason_code == RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL


def test_attempt_history_is_append_only_idempotent_and_state_machine_guarded() -> None:
    repository = _repository()
    base = RegulatoryRolloverAttempt(
        attempt_id="cycle-a-target-b-v1",
        current_anchor_id=load_domestic_projection_anchor().anchor_id,
        target_valid_from=VALIDITY.start,
        input_fingerprint="a" * 64,
        status=RolloverAttemptStatus.PREPARING,
        updated_at=STAGED_AT,
    )
    verified = base.model_copy(
        update={
            "status": RolloverAttemptStatus.VERIFIED,
            "candidate_id": _candidate().candidate_id,
            "updated_at": datetime(2026, 9, 30, 14, tzinfo=UTC),
        }
    )
    staged = verified.model_copy(
        update={
            "status": RolloverAttemptStatus.STAGED,
            "updated_at": datetime(2026, 9, 30, 15, tzinfo=UTC),
        }
    )

    assert repository.record_attempt(base) == base
    assert repository.record_attempt(base) == base
    assert repository.record_attempt(verified) == verified
    assert repository.record_attempt(staged) == staged
    assert repository.attempt_history(base.attempt_id) == (base, verified, staged)

    changed_input = staged.model_copy(update={"input_fingerprint": "b" * 64})
    with pytest.raises(RegulatoryRepositoryError) as changed:
        repository.record_attempt(changed_input)
    invalid_transition = base.model_copy(
        update={
            "status": RolloverAttemptStatus.PREPARING,
            "updated_at": datetime(2026, 9, 30, 16, tzinfo=UTC),
        }
    )
    with pytest.raises(RegulatoryRepositoryError) as invalid:
        repository.record_attempt(invalid_transition)

    assert changed.value.reason_code == RegulatoryRolloverReason.DETERMINISM_VIOLATION
    assert invalid.value.reason_code == RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED


def test_attempt_history_rejects_backwards_timestamp_and_nonpreparing_start() -> None:
    repository = _repository()
    current_id = load_domestic_projection_anchor().anchor_id
    verified = RegulatoryRolloverAttempt(
        attempt_id="invalid-start",
        current_anchor_id=current_id,
        target_valid_from=VALIDITY.start,
        input_fingerprint="a" * 64,
        status=RolloverAttemptStatus.VERIFIED,
        updated_at=STAGED_AT,
    )
    with pytest.raises(RegulatoryRepositoryError) as start:
        repository.record_attempt(verified)
    preparing = verified.model_copy(update={"status": RolloverAttemptStatus.PREPARING})
    repository.record_attempt(preparing)
    backwards = preparing.model_copy(update={"updated_at": datetime(2026, 9, 30, 12, tzinfo=UTC)})
    with pytest.raises(RegulatoryRepositoryError) as stale:
        repository.record_attempt(backwards)

    assert start.value.reason_code == RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED
    assert stale.value.reason_code == RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE


def test_not_due_promotion_is_noop_then_due_promotion_is_atomic_and_immutable() -> None:
    repository = _repository()
    candidate = _candidate()
    old_anchor = repository.read_current_anchor()
    _stage(repository, candidate)
    not_due = repository.promote(
        candidate.candidate_id,
        _coverage(candidate),
        as_of=AS_OF,
        promoted_at=STAGED_AT,
        expected_generation=1,
        expected_current_anchor_id=old_anchor.anchor_id,
        policy=POLICY,
    )
    next_coverage = _coverage(candidate, NEXT_DAY)
    promoted = repository.promote(
        candidate.candidate_id,
        next_coverage,
        as_of=NEXT_DAY,
        promoted_at=PROMOTED_AT,
        expected_generation=1,
        expected_current_anchor_id=old_anchor.anchor_id,
        policy=POLICY,
    )

    assert not_due.outcome == PromotionOutcome.NOT_DUE
    assert not_due.state.current_anchor_id == old_anchor.anchor_id
    assert promoted.outcome == PromotionOutcome.PROMOTED
    assert promoted.anchor.status.value == "verified"
    assert promoted.anchor.anchor_id == f"regulatory-anchor:{candidate.build_key}"
    assert promoted.anchor.validity == VALIDITY
    assert repository.read_current_anchor() == promoted.anchor
    assert repository.get_anchor(old_anchor.anchor_id) == old_anchor
    assert repository.historical_anchors() == (old_anchor,)
    assert repository.coverage_for_anchor(promoted.anchor.anchor_id) == (next_coverage,)
    assert tuple(event.kind for event in repository.events()) == (
        RolloverEventKind.CANDIDATE_STAGED,
        RolloverEventKind.ANCHOR_PROMOTED,
    )


def test_promoting_after_current_interval_mutation_is_rejected() -> None:
    repository = _repository()
    candidate = _candidate()
    current = repository.read_current_anchor()
    _stage(repository, candidate)
    repository._anchors[current.anchor_id] = current.model_copy(
        update={
            "validity": DatePeriod(start=current.validity.start, end=NEXT_DAY + timedelta(days=1))
        }
    )

    with pytest.raises(RegulatoryRepositoryError) as caught:
        repository.promote(
            candidate.candidate_id,
            _coverage(candidate, NEXT_DAY),
            as_of=NEXT_DAY,
            promoted_at=PROMOTED_AT,
            expected_generation=1,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )

    assert caught.value.reason_code == RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL


def test_promotion_rerun_and_two_workers_create_one_anchor_and_event() -> None:
    repository = _repository()
    candidate = _candidate()
    old_anchor = repository.read_current_anchor()
    _stage(repository, candidate)
    coverage = _coverage(candidate, NEXT_DAY)
    barrier = Barrier(2)

    def promote_once() -> PromotionOutcome:
        barrier.wait()
        return repository.promote(
            candidate.candidate_id,
            coverage,
            as_of=NEXT_DAY,
            promoted_at=PROMOTED_AT,
            expected_generation=1,
            expected_current_anchor_id=old_anchor.anchor_id,
            policy=POLICY,
        ).outcome

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(lambda _: promote_once(), range(2)))

    assert set(outcomes) == {PromotionOutcome.PROMOTED, PromotionOutcome.ALREADY_PROMOTED}
    assert repository.read_state().generation == 2
    assert repository.read_state().staged_candidate_id is None
    assert repository.read_current_anchor().anchor_id == f"regulatory-anchor:{candidate.build_key}"
    assert len(repository.events()) == 2


def test_promotion_requires_staging_matching_candidate_and_fresh_ready_coverage() -> None:
    repository = _repository()
    candidate = _candidate()
    with pytest.raises(RegulatoryRepositoryError) as absent:
        repository.promote(
            candidate.candidate_id,
            _coverage(candidate, NEXT_DAY),
            as_of=NEXT_DAY,
            promoted_at=PROMOTED_AT,
            expected_generation=0,
            expected_current_anchor_id=repository.read_current_anchor().anchor_id,
            policy=POLICY,
        )
    _stage(repository, candidate)
    blocked_coverage = _verify(
        candidate,
        discovery=_discovery(
            act_channel=RegulatoryRegistryChannel.ARERA_ACTS,
            as_of=NEXT_DAY,
            discovered_at=PROMOTED_AT,
        ),
        checks=_checks(candidate, PROMOTED_AT),
        as_of=NEXT_DAY,
        checked_at=PROMOTED_AT,
    )
    with pytest.raises(RegulatoryRepositoryError) as blocked:
        repository.promote(
            candidate.candidate_id,
            blocked_coverage,
            as_of=NEXT_DAY,
            promoted_at=PROMOTED_AT,
            expected_generation=1,
            expected_current_anchor_id=repository.read_current_anchor().anchor_id,
            policy=POLICY,
        )

    assert absent.value.reason_code == RegulatoryRolloverReason.NEXT_ANCHOR_MISSING
    assert blocked.value.reason_code == RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE
    assert repository.read_state().generation == 1


def test_promotion_rejects_conflicting_pointer_and_expired_candidate() -> None:
    repository = _repository()
    candidate = _candidate()
    _stage(repository, candidate)
    current = repository.read_current_anchor()
    other = _candidate_variant()
    repository.put_candidate_if_absent(other)

    with pytest.raises(RegulatoryRepositoryError) as conflict:
        repository.promote(
            other.candidate_id,
            _coverage(other, NEXT_DAY),
            as_of=NEXT_DAY,
            promoted_at=PROMOTED_AT,
            expected_generation=1,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )
    with pytest.raises(RegulatoryRepositoryError) as expired:
        repository.promote(
            candidate.candidate_id,
            _coverage(candidate, NEXT_DAY),
            as_of=VALIDITY.end,
            promoted_at=datetime(2027, 1, 1, 12, tzinfo=UTC),
            expected_generation=1,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )

    assert conflict.value.reason_code == RegulatoryRolloverReason.PROMOTION_CONFLICT
    assert expired.value.reason_code == RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL


def test_repository_rejects_nonadjacent_candidate_and_naive_times() -> None:
    candidate = _candidate()
    repository = _repository()
    changed_period = DatePeriod(start=date(2026, 10, 2), end=date(2027, 1, 2))
    malformed_anchor = candidate.anchor.model_copy(update={"validity": changed_period})
    malformed = candidate.model_copy(update={"anchor": malformed_anchor})
    coverage = _coverage(candidate)

    with pytest.raises(RegulatoryRepositoryError) as caught:
        repository.stage(
            malformed,
            coverage,
            as_of=AS_OF,
            staged_at=STAGED_AT,
            expected_generation=0,
            expected_current_anchor_id=repository.read_current_anchor().anchor_id,
            policy=POLICY,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        InMemoryRegulatoryRepository(
            load_domestic_projection_anchor(), initialized_at=datetime(2026, 9, 30)
        )

    assert caught.value.reason_code == RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED


@pytest.mark.parametrize(
    ("current", "target", "valid"),
    (
        (RolloverAttemptStatus.PREPARING, RolloverAttemptStatus.VERIFIED, True),
        (RolloverAttemptStatus.VERIFIED, RolloverAttemptStatus.STAGED, True),
        (RolloverAttemptStatus.STAGED, RolloverAttemptStatus.PROMOTED, True),
        (RolloverAttemptStatus.PREPARING, RolloverAttemptStatus.STAGED, False),
        (RolloverAttemptStatus.PROMOTED, RolloverAttemptStatus.REVIEW_REQUIRED, False),
    ),
)
def test_attempt_state_machine_rejects_skipped_or_reversed_transitions(
    current: RolloverAttemptStatus, target: RolloverAttemptStatus, valid: bool
) -> None:
    if valid:
        validate_attempt_transition(current, target)
    else:
        with pytest.raises(ValueError, match="invalid regulatory rollover transition"):
            validate_attempt_transition(current, target)


def test_state_models_require_aware_timestamps() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryRolloverState(
            current_anchor_id="anchor-a",
            generation=0,
            updated_at=datetime(2026, 9, 30),
        )
    assert candidate.anchor.validity.start == VALIDITY.start
    assert VALIDITY.start > AS_OF

    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryRolloverAttempt(
            attempt_id="attempt-fixture",
            current_anchor_id="anchor-a",
            target_valid_from=VALIDITY.start,
            input_fingerprint="a" * 64,
            status=RolloverAttemptStatus.PREPARING,
            updated_at=datetime(2026, 9, 30),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryRolloverEvent(
            event_id="a" * 64,
            kind=RolloverEventKind.ANCHOR_PROMOTED,
            occurred_at=datetime(2026, 9, 30),
            generation=1,
            previous_anchor_id="anchor-a",
            current_anchor_id="anchor-b",
            candidate_id=candidate.candidate_id,
        )


def test_attempt_can_repeat_current_state_and_event_identity_is_canonical() -> None:
    validate_attempt_transition(RolloverAttemptStatus.PREPARING, RolloverAttemptStatus.PREPARING)

    def event_id() -> str:
        return rollover_event_id(
            kind=RolloverEventKind.ANCHOR_PROMOTED,
            occurred_at=PROMOTED_AT,
            generation=2,
            previous_anchor_id="anchor-a",
            current_anchor_id="anchor-b",
            candidate_id="candidate-b",
        )

    assert event_id() == event_id()


def test_repository_requires_verified_current_and_aware_operation_time() -> None:
    current = load_domestic_projection_anchor()
    unverified = current.model_copy(update={"status": VerificationStatus.UNVERIFIED})
    repository = _repository()
    candidate = _candidate()

    with pytest.raises(ValueError, match="already be verified"):
        InMemoryRegulatoryRepository(unverified, initialized_at=STAGED_AT)
    with pytest.raises(ValueError, match="timezone-aware"):
        repository.stage(
            candidate,
            _coverage(candidate),
            as_of=AS_OF,
            staged_at=datetime(2026, 9, 30),
            expected_generation=0,
            expected_current_anchor_id=current.anchor_id,
            policy=POLICY,
        )
