from __future__ import annotations

import hashlib
from datetime import date, timedelta
from typing import Any

import pytest
from test_regulatory_candidate import AS_OF
from test_regulatory_coverage import CHECKED_AT, _discovery

from italian_energy.arera.act_review import (
    RegulatoryActReviewDecision,
    RegulatoryActReviewRequest,
    act_review_is_accepted,
    create_act_review_decision,
    observe_act_review,
)
from italian_energy.arera.discovery import OfficialRegistryRecord, RegulatoryRegistryChannel
from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.arera.rollover_coverage import (
    RegulatoryAnchorCoverageEvidence,
    RegulatoryAnchorSourceCheck,
    verify_regulatory_anchor_coverage,
)
from italian_energy.arera.source_revision import SourceRevisionOutcome
from italian_energy.integration.serialization import dump_envelope, load_envelope

BODY = b"<html>Exact official act for human review</html>"


def record() -> OfficialRegistryRecord:
    return OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
        act_id="095G0523",
        document_id="095G0523",
        title="Synthetic excise act",
        published_at=date(1995, 11, 29),
        registry_date=date(2026, 9, 29),
        url="https://api.normattiva.it/updates",
        latest_amending_act_ids=("26G00999",),
    )


def request(body: bytes | None = BODY, **changes: Any) -> RegulatoryActReviewRequest:
    return observe_act_review(
        load_domestic_projection_anchor(),
        record().model_copy(update=changes),
        body,
        observed_at=CHECKED_AT - timedelta(minutes=2),
    )


def decision(
    req: RegulatoryActReviewRequest | None = None,
    outcome: SourceRevisionOutcome = SourceRevisionOutcome.APPROVE_EQUIVALENT,
) -> RegulatoryActReviewDecision:
    return create_act_review_decision(
        req or request(),
        outcome=outcome,
        reviewer="admin:fixture",
        reviewed_at=CHECKED_AT - timedelta(minutes=1),
        rationale="Examined the exact official act.",
        equivalent_confirmed=outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT,
    )


def test_version_identity_includes_record_and_document_but_not_observation_clock() -> None:
    req = request()
    assert (
        req.request_id
        == observe_act_review(
            load_domestic_projection_anchor(), record(), BODY, observed_at=CHECKED_AT
        ).request_id
    )
    assert req.request_id != request(b"changed official bytes").request_id
    assert req.request_id != request(latest_amending_act_ids=("26G00888",)).request_id
    assert req.document_sha256 == hashlib.sha256(BODY).hexdigest()
    assert (
        req.source_url
        == "https://www.normattiva.it/eli/id/1995/11/29/095G0523/CONSOLIDATED/20260929"
    )


def test_approval_is_bound_to_current_anchor_version_and_date() -> None:
    req = request()
    dec = decision(req)
    anchor = load_domestic_projection_anchor()
    assert act_review_is_accepted(anchor, req, dec, AS_OF, CHECKED_AT)
    assert not act_review_is_accepted(anchor, request(b"new"), dec, AS_OF, CHECKED_AT)
    assert not act_review_is_accepted(
        anchor.model_copy(update={"anchor_id": "other"}), req, dec, AS_OF, CHECKED_AT
    )
    assert not act_review_is_accepted(
        anchor, req, dec, AS_OF, dec.reviewed_at - timedelta(seconds=1)
    )
    for outcome in [SourceRevisionOutcome.REJECT, SourceRevisionOutcome.REQUIRES_UPDATE]:
        assert not act_review_is_accepted(anchor, req, decision(req, outcome), AS_OF, CHECKED_AT)


def test_missing_source_and_unconfirmed_approval_remain_blocked() -> None:
    with pytest.raises(ValueError):
        decision(request(None))
    with pytest.raises(ValueError):
        create_act_review_decision(
            request(),
            outcome=SourceRevisionOutcome.APPROVE_EQUIVALENT,
            reviewer="admin",
            reviewed_at=CHECKED_AT,
            rationale="Examined",
            equivalent_confirmed=False,
        )


def test_new_schemas_roundtrip_without_raw_bytes() -> None:
    for obj in (request(), decision()):
        assert load_envelope(dump_envelope(obj)) == obj


def coverage(
    decisions: tuple[RegulatoryActReviewDecision, ...] = (),
) -> RegulatoryAnchorCoverageEvidence:
    from italian_energy.arera.discovery import DiscoveryActDisposition, DiscoveryActFinding

    d = _discovery()
    finding = DiscoveryActFinding(
        channel=record().channel,
        act_id=record().act_id,
        disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
        rationale="No registered interpretation",
        source_record=record(),
    )
    d = d.model_copy(update={"findings": (*d.findings, finding)})
    a = load_domestic_projection_anchor()
    return verify_regulatory_anchor_coverage(
        anchor=a,
        discovery=d,
        source_checks=tuple(
            RegulatoryAnchorSourceCheck(
                source_id=s.source_id,
                expected_sha256=s.sha256 or "",
                observed_sha256=s.sha256,
                checked_at=CHECKED_AT,
            )
            for s in a.sources
        ),
        as_of=AS_OF,
        checked_at=CHECKED_AT,
        act_reviews=(request(),),
        act_review_decisions=decisions,
    )


def test_exact_admin_approval_clears_only_the_unknown_act_and_preserves_history() -> None:
    a = load_domestic_projection_anchor()
    original = a.model_dump_json()
    assert not coverage().ready
    accepted = coverage((decision(),))
    assert accepted.ready
    assert load_envelope(dump_envelope(accepted)) == accepted
    assert a.model_dump_json() == original


def test_offline_ready_without_approval_is_rejected() -> None:
    with pytest.raises(ValueError):
        type(coverage()).model_validate(
            coverage().model_dump(mode="python") | {"ready": True, "reason_codes": ()}
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_url", "https://www.normattiva.it/other"),
        ("source_id", "other-record"),
        ("observed_sha256", "0" * 64),
        ("detected_at", CHECKED_AT.replace(tzinfo=None)),
    ],
)
def test_request_rejects_forged_identity(field: str, value: Any) -> None:
    with pytest.raises(ValueError):
        RegulatoryActReviewRequest.model_validate(
            request().model_dump(mode="python") | {field: value}
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"reviewed_at": CHECKED_AT.replace(tzinfo=None)},
        {"reviewed_at": CHECKED_AT - timedelta(days=1)},
        {"scope": {"start": "2026-09-01", "end": "2027-01-01"}},
        {"scope": {"start": "2026-09-01", "end": "2026-10-01"}},
        {"outcome": SourceRevisionOutcome.REJECT},
        {"outcome": SourceRevisionOutcome.REVOKE, "equivalent_confirmed": False},
    ],
)
def test_decision_cannot_forge_dates_scope_or_confirmation(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RegulatoryActReviewDecision.model_validate(decision().model_dump(mode="python") | changes)


def test_revocation_is_a_negative_versioned_decision() -> None:
    previous = decision()
    revoked = create_act_review_decision(
        request(),
        outcome=SourceRevisionOutcome.REVOKE,
        reviewer="admin:fixture",
        reviewed_at=CHECKED_AT,
        rationale="Reopened for further verification.",
        supersedes_decision_id=previous.decision_id,
    )
    assert not act_review_is_accepted(
        load_domestic_projection_anchor(), request(), revoked, AS_OF, CHECKED_AT
    )
    with pytest.raises(ValueError):
        create_act_review_decision(
            request(),
            outcome=SourceRevisionOutcome.REJECT,
            reviewer="admin",
            reviewed_at=CHECKED_AT.replace(tzinfo=None),
            rationale="Invalid clock",
        )


def test_offline_model_copy_tampering_and_duplicate_decisions_do_not_clear_gate() -> None:
    from italian_energy.arera.rollover_coverage import act_review_evidence_is_accepted

    anchor = load_domestic_projection_anchor()
    original = coverage((decision(),))
    forged = decision().model_copy(update={"equivalent_confirmed": False})
    assert not act_review_is_accepted(anchor, request(), forged, AS_OF, CHECKED_AT)
    assert not act_review_evidence_is_accepted(
        anchor, original.model_copy(update={"act_review_decisions": ()})
    )
    variations: list[dict[str, Any]] = [
        {"act_reviews": (request(), request())},
        {"act_review_decisions": (decision(), decision())},
        {"act_review_decisions": (decision(request(b"different")),)},
        {"anchor_id": "different"},
    ]
    for changes in variations:
        with pytest.raises(ValueError):
            type(original).model_validate(original.model_dump(mode="python") | changes)


def test_approval_does_not_clear_incomplete_discovery_or_missing_anchor_source() -> None:
    from italian_energy.arera.rollover_models import RegulatoryRolloverReason

    anchor = load_domestic_projection_anchor()
    d = _discovery(channels=())
    checks = tuple(
        RegulatoryAnchorSourceCheck(
            source_id=s.source_id,
            expected_sha256=s.sha256 or "",
            observed_sha256=None if i == 0 else s.sha256,
            checked_at=CHECKED_AT,
        )
        for i, s in enumerate(anchor.sources)
    )
    result = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=d,
        source_checks=checks,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
        act_reviews=(request(),),
        act_review_decisions=(decision(),),
    )
    assert not result.ready
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in result.reason_codes
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in result.reason_codes


def test_refresh_emits_requests_and_admin_approval_clears_current_preflight_only() -> None:
    from test_regulatory_rollover_service import _service

    service, repository, source_port = _service(include_unsupported=True)
    report = service.refresh_regulatory_state(AS_OF)
    from italian_energy.arera.rollover_coverage import RegulatoryAnchorCoverageEvidenceV3

    assert isinstance(report.current_coverage, RegulatoryAnchorCoverageEvidenceV3)
    requests = report.current_coverage.act_reviews
    assert len(requests) == 1 and requests[0].document_sha256 is not None
    assert not service.source_preflight(AS_OF, report.current_coverage).ready
    approved = create_act_review_decision(
        requests[0],
        outcome=SourceRevisionOutcome.APPROVE_EQUIVALENT,
        reviewer="admin:fixture",
        reviewed_at=CHECKED_AT,
        rationale="No effects on the current anchor.",
        equivalent_confirmed=True,
    )
    refreshed = service.refresh_regulatory_state(
        AS_OF, act_review_decisions=(approved,), previous_cursors=(), previous_snapshots=()
    )
    assert refreshed.current_coverage.ready
    assert service.source_preflight(AS_OF, refreshed.current_coverage).ready
    assert load_envelope(dump_envelope(refreshed)) == refreshed
    assert refreshed.candidate_coverage is not None and not refreshed.candidate_coverage.ready
    # Another observation of changed bytes reopens the decision without changing any rule.
    source_port._bodies_by_url[requests[0].source_url] = b"new official version"
    changed = service.refresh_regulatory_state(
        AS_OF, act_review_decisions=(approved,), previous_cursors=(), previous_snapshots=()
    )
    assert not changed.current_coverage.ready
    assert not service.source_preflight(AS_OF, changed.current_coverage).ready
    assert changed.current_coverage.anchor_id == repository.read_current_anchor().anchor_id


def test_both_offline_preflights_reject_erased_or_negative_review_evidence() -> None:
    from italian_energy.arera.rollover_coverage import act_review_evidence_is_accepted
    from italian_energy.arera.rollover_repository import InMemoryRegulatoryRepository
    from italian_energy.integration.projected_service import ProjectedDomesticEnergyService
    from italian_energy.integration.regulatory_rollover_service import RegulatoryRolloverService

    anchor = load_domestic_projection_anchor()
    evidence = coverage((decision(),))
    repo = InMemoryRegulatoryRepository(anchor, initialized_at=CHECKED_AT)
    service = RegulatoryRolloverService(repo, clock=lambda: CHECKED_AT)
    variations: list[dict[str, Any]] = [
        {"act_reviews": ()},
        {"act_review_decisions": ()},
        {"act_review_decisions": (decision(outcome=SourceRevisionOutcome.REJECT),)},
    ]
    for changes in variations:
        bad = evidence.model_copy(update=changes)
        assert not act_review_evidence_is_accepted(anchor, bad)
        assert not service.source_preflight(AS_OF, bad).ready
        assert ProjectedDomesticEnergyService(clock=lambda: CHECKED_AT)._coverage_evidence_reasons(
            anchor, AS_OF, bad
        )
