from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from test_regulatory_candidate import AS_OF
from test_regulatory_coverage import CHECKED_AT, _discovery

from italian_energy.arera.discovery import RegulatoryDiscoveryReport
from italian_energy.arera.projection import (
    DomesticProjectionAnchor,
    load_domestic_projection_anchor,
)
from italian_energy.arera.rollover_coverage import (
    RegulatoryAnchorCoverageEvidence,
    RegulatoryAnchorCoverageEvidenceV2,
    RegulatoryAnchorSourceCheck,
    verify_regulatory_anchor_coverage,
)
from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.arera.source_revision import (
    RegulatorySourceRevisionDecision,
    RegulatorySourceRevisionRequest,
    SourceRevisionAssessment,
    SourceRevisionOutcome,
    create_source_revision_decision,
    observe_source_revision,
)
from italian_energy.integration.serialization import dump_envelope, load_envelope

BODY = b"<html><body>A new official document requiring human review.</body></html>"


def _request() -> RegulatorySourceRevisionRequest:
    anchor = load_domestic_projection_anchor()
    request = observe_source_revision(
        anchor, "vat_dpr_633", BODY, observed_at=CHECKED_AT - timedelta(minutes=2)
    )
    assert request is not None
    return request


def _decision(
    outcome: SourceRevisionOutcome = SourceRevisionOutcome.APPROVE_EQUIVALENT, **changes: Any
) -> RegulatorySourceRevisionDecision:
    return create_source_revision_decision(
        _request(),
        outcome=outcome,
        reviewer="admin:123",
        reviewed_at=CHECKED_AT - timedelta(minutes=1),
        rationale="Compared the official provision and confirmed the existing interpretation.",
        equivalent_confirmed=outcome == SourceRevisionOutcome.APPROVE_EQUIVALENT,
        **changes,
    )


def _coverage(
    *,
    decisions: tuple[RegulatorySourceRevisionDecision, ...] = (),
    observed: str | None = None,
    discovery: RegulatoryDiscoveryReport | None = None,
    anchor: DomesticProjectionAnchor | None = None,
    source_revisions: tuple[RegulatorySourceRevisionRequest, ...] | None = None,
) -> RegulatoryAnchorCoverageEvidence:
    anchor = anchor or load_domestic_projection_anchor()
    checks = tuple(
        RegulatoryAnchorSourceCheck(
            source_id=s.source_id,
            expected_sha256=s.sha256 or "",
            observed_sha256=(observed if observed is not None else hashlib.sha256(BODY).hexdigest())
            if s.source_id == "vat_dpr_633"
            else s.sha256,
            checked_at=CHECKED_AT,
        )
        for s in anchor.sources
    )
    return verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=discovery or _discovery(),
        source_checks=checks,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
        source_revisions=(_request(),) if source_revisions is None else source_revisions,
        source_revision_decisions=decisions,
    )


def test_changed_document_produces_bounded_request_without_accepting_it() -> None:
    request = _request()
    anchor = load_domestic_projection_anchor()
    assert request.anchor_id == anchor.anchor_id
    assert request.observed_sha256 == hashlib.sha256(BODY).hexdigest()
    assert request.assessment == SourceRevisionAssessment.MANUAL_REVIEW
    assert request.current_values[0].value == anchor.vat_rate_percent
    assert not _coverage().ready
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in _coverage().reason_codes


def test_request_identity_deduplicates_repeated_observations_of_same_version() -> None:
    first = _request()
    later = observe_source_revision(
        load_domestic_projection_anchor(),
        "vat_dpr_633",
        BODY,
        observed_at=CHECKED_AT + timedelta(minutes=3),
    )
    assert later is not None
    assert first.request_id == later.request_id
    assert first.detected_at != later.detected_at


def test_approval_accepts_exact_version_and_preserves_anchor_and_legacy_bytes() -> None:
    anchor = load_domestic_projection_anchor()
    frozen = anchor.model_dump_json()
    coverage = _coverage(decisions=(_decision(),))
    assert isinstance(coverage, RegulatoryAnchorCoverageEvidenceV2)
    assert coverage.ready
    assert coverage.source_revision_decisions == (_decision(),)
    assert anchor.model_dump_json() == frozen
    assert coverage.source_checks[0].expected_sha256 != ""
    encoded = dump_envelope(coverage)
    assert (
        json.loads(encoded)["schema_id"] == "italian-energy/regulatory-anchor-coverage-evidence/v2"
    )
    assert load_envelope(encoded) == coverage


@pytest.mark.parametrize(
    "field,value",
    (
        ("anchor_id", "different-anchor"),
        ("anchor_sha256", "0" * 64),
        ("source_id", "different-source"),
        ("source_url", "https://www.normattiva.it/different-document"),
        ("expected_sha256", "1" * 64),
        ("observed_sha256", "2" * 64),
    ),
)
def test_approval_cannot_be_reused_for_another_binding(field: str, value: str) -> None:
    decision = _decision()
    wrong = decision.model_copy(
        update={"request": decision.request.model_copy(update={field: value})}
    )
    assert not _coverage(decisions=(wrong,)).ready


def test_next_document_change_requires_a_new_review() -> None:
    assert not _coverage(decisions=(_decision(),), observed="f" * 64).ready


@pytest.mark.parametrize("outcome", (SourceRevisionOutcome.REJECT, SourceRevisionOutcome.REVOKE))
def test_rejection_and_revocation_do_not_accept_changed_document(
    outcome: SourceRevisionOutcome,
) -> None:
    extra = (
        {"supersedes_decision_id": _decision().decision_id}
        if outcome == SourceRevisionOutcome.REVOKE
        else {}
    )
    assert not _coverage(decisions=(_decision(outcome, **extra),)).ready


def test_expired_or_future_approval_does_not_open_gate() -> None:
    decision = _decision()
    future = decision.model_copy(update={"reviewed_at": CHECKED_AT + timedelta(seconds=1)})
    assert not _coverage(decisions=(future,)).ready
    earlier = decision.model_copy(
        update={
            "reviewed_at": CHECKED_AT - timedelta(days=1),
            "request": decision.request.model_copy(
                update={"detected_at": CHECKED_AT - timedelta(days=2)}
            ),
            "scope": decision.scope.model_copy(
                update={"start": AS_OF - timedelta(days=1), "end": AS_OF}
            ),
        }
    )
    assert not _coverage(decisions=(earlier,)).ready


def test_approval_does_not_clear_incomplete_discovery_or_other_source_failure() -> None:
    incomplete = _discovery(channels=())
    result = _coverage(decisions=(_decision(),), discovery=incomplete)
    assert not result.ready
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in result.reason_codes


def test_approval_requires_explicit_attestation_and_real_reviewer_metadata() -> None:
    request = _request()
    for changes in ({"equivalent_confirmed": False}, {"rationale": ""}, {"reviewer": ""}):
        arguments: dict[str, Any] = dict(
            outcome=SourceRevisionOutcome.APPROVE_EQUIVALENT,
            reviewer="admin:123",
            reviewed_at=CHECKED_AT,
            rationale="Verified exact document.",
            equivalent_confirmed=True,
        )
        arguments.update(changes)
        with pytest.raises((ValueError, ValidationError)):
            create_source_revision_decision(request, **arguments)


def test_known_economic_change_cannot_be_approved_as_equivalent() -> None:
    request = _request().model_copy(update={"assessment": SourceRevisionAssessment.CHANGED})
    with pytest.raises(ValueError, match="economic"):
        create_source_revision_decision(
            request,
            outcome=SourceRevisionOutcome.APPROVE_EQUIVALENT,
            reviewer="admin:123",
            reviewed_at=CHECKED_AT,
            rationale="Reviewed",
            equivalent_confirmed=True,
        )


def test_old_coverage_serialization_has_no_new_default_fields() -> None:
    anchor = load_domestic_projection_anchor()
    checks = tuple(
        RegulatoryAnchorSourceCheck(
            source_id=s.source_id,
            expected_sha256=s.sha256 or "",
            observed_sha256=s.sha256,
            checked_at=CHECKED_AT,
        )
        for s in anchor.sources
    )
    coverage = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=_discovery(),
        source_checks=checks,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
    )
    encoded = dump_envelope(coverage)
    assert (
        json.loads(encoded)["schema_id"] == "italian-energy/regulatory-anchor-coverage-evidence/v1"
    )
    assert "source_revision" not in encoded.decode()
    assert dump_envelope(load_envelope(encoded)) == encoded


def test_explicit_historical_document_reference_preserves_real_acquisition_time() -> None:
    from test_regulatory_parsers import _normattiva_vat_source

    from italian_energy.arera.rollover_parsers import (
        ParserDisposition,
        default_regulatory_parser_registry,
    )

    source = _normattiva_vat_source(table=True, url_date=date(2026, 10, 4))
    original_clock = source.acquired.fetched_at
    historical = replace(source, reference_as_of=date(2026, 10, 4))
    result = default_regulatory_parser_registry().parse(historical)
    assert result.disposition == ParserDisposition.PARSED
    assert result.facts[0].fetched_at == original_clock
    assert source.acquired.fetched_at == original_clock


def test_future_reference_date_cannot_certify_a_document() -> None:
    from test_regulatory_parsers import _normattiva_vat_source

    from italian_energy.arera.rollover_parsers import (
        ParserDisposition,
        default_regulatory_parser_registry,
    )

    source = _normattiva_vat_source(table=True, url_date=date(2026, 10, 9))
    result = default_regulatory_parser_registry().parse(
        replace(source, reference_as_of=date(2026, 10, 9))
    )
    assert result.disposition == ParserDisposition.REVIEW_REQUIRED


def test_daily_rollover_exposes_request_then_reuses_exact_admin_decision_offline() -> None:
    from test_regulatory_rollover_service import _service

    service, repository, port = _service()
    anchor = repository.read_current_anchor()
    original = anchor.model_dump_json()
    source = next(s for s in anchor.sources if s.source_id == "vat_dpr_633")
    port._bodies_by_url[source.url] = BODY
    blocked = service.refresh_regulatory_state(AS_OF)
    assert isinstance(blocked.current_coverage, RegulatoryAnchorCoverageEvidenceV2)
    request = blocked.current_coverage.source_revisions[0]
    assert request.source_id == source.source_id
    assert not service.source_preflight(AS_OF, blocked.current_coverage).ready
    decision = create_source_revision_decision(
        request,
        outcome=SourceRevisionOutcome.APPROVE_EQUIVALENT,
        reviewer="admin:123",
        reviewed_at=port.now,
        rationale="Verified the exact synthetic document.",
        equivalent_confirmed=True,
    )
    approved = service.refresh_regulatory_state(AS_OF, source_revision_decisions=(decision,))
    assert service.source_preflight(AS_OF, approved.current_coverage).ready
    assert repository.read_current_anchor().model_dump_json() == original
    encoded = dump_envelope(approved)
    assert json.loads(encoded)["schema_id"] == "italian-energy/regulatory-rollover-report/v3"
    assert dump_envelope(load_envelope(encoded)) == encoded


def test_vat_assessment_preserves_the_real_acquisition_clock() -> None:
    anchor = load_domestic_projection_anchor(date(2026, 11, 4))
    body = (
        Path(__file__).parents[1]
        / "fixtures/regulatory_rollover/normattiva-dpr633-table-a-synthetic.html"
    ).read_bytes()
    now = datetime(2026, 11, 4, 12, tzinfo=UTC)
    request = observe_source_revision(anchor, "vat_dpr_633", body, observed_at=now)
    assert request is not None
    assert request.assessment == SourceRevisionAssessment.EQUIVALENT
    assert request.observed_values[0].value == Decimal("10")
    assert request.parser_id is not None
    assert "103)" in request.preview_text
    assert request.detected_at == now
    different = observe_source_revision(
        anchor.model_copy(update={"vat_rate_percent": Decimal("12")}),
        "vat_dpr_633",
        body,
        observed_at=now,
    )
    assert different is not None and different.assessment == SourceRevisionAssessment.CHANGED


def test_revision_preview_is_plain_text_and_does_not_include_scripts_or_styles() -> None:
    body = (
        b"<html><script>secret script</script><style>secret style</style>"
        b"<p>Official text</p></html>"
    )
    request = observe_source_revision(
        load_domestic_projection_anchor(), "vat_dpr_633", body, observed_at=CHECKED_AT
    )
    assert request is not None
    assert request.preview_text == "Official text"


@pytest.mark.parametrize(
    "changes",
    (
        {"source_url": "https://example.invalid/document"},
        {"observed_sha256": _request().expected_sha256},
        {"detected_at": datetime(2026, 9, 30)},
        {"parser_id": "only-id", "parser_version": None},
    ),
)
def test_revision_request_rejects_unofficial_or_inconsistent_evidence(
    changes: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        RegulatorySourceRevisionRequest.model_validate(
            _request().model_dump(mode="python") | changes
        )


@pytest.mark.parametrize(
    "changes",
    (
        {"reviewed_at": datetime(2026, 9, 30)},
        {"reviewed_at": CHECKED_AT - timedelta(days=1)},
        {"outcome": SourceRevisionOutcome.REJECT},
        {"outcome": SourceRevisionOutcome.REVOKE, "equivalent_confirmed": False},
    ),
)
def test_review_rejects_invalid_audit_metadata(changes: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        RegulatorySourceRevisionDecision.model_validate(
            _decision().model_dump(mode="python") | changes
        )


def test_unchanged_source_does_not_generate_a_review_and_unknown_source_is_rejected() -> None:
    anchor = load_domestic_projection_anchor()
    original = next(s for s in anchor.sources if s.source_id == "vat_dpr_633")
    same = anchor.model_copy(
        update={
            "sources": tuple(
                s.model_copy(update={"sha256": hashlib.sha256(BODY).hexdigest()})
                if s.source_id == original.source_id
                else s
                for s in anchor.sources
            )
        }
    )
    assert observe_source_revision(same, original.source_id, BODY, observed_at=CHECKED_AT) is None
    with pytest.raises(ValueError, match="known"):
        observe_source_revision(anchor, "unknown-source", BODY, observed_at=CHECKED_AT)
    with pytest.raises(ValueError, match="empty"):
        observe_source_revision(anchor, original.source_id, b"", observed_at=CHECKED_AT)


def test_projected_gate_revalidates_approval_instead_of_trusting_ready_flag() -> None:
    from italian_energy.integration.projected_service import ProjectedDomesticEnergyService

    anchor = load_domestic_projection_anchor()
    service = ProjectedDomesticEnergyService(clock=lambda: CHECKED_AT)
    coverage = _coverage(decisions=(_decision(),))
    assert service._coverage_evidence_reasons(anchor, AS_OF, coverage) == ()
    assert isinstance(coverage, RegulatoryAnchorCoverageEvidenceV2)
    forged = coverage.model_copy(update={"source_revision_decisions": (), "ready": True})
    assert "regulatory_source_changed" in service._coverage_evidence_reasons(anchor, AS_OF, forged)


def test_duplicate_or_orphan_current_decisions_cannot_be_serialized_as_valid_coverage() -> None:
    coverage = _coverage(decisions=(_decision(),))
    assert isinstance(coverage, RegulatoryAnchorCoverageEvidenceV2)
    for changes in (
        {"source_revision_decisions": (_decision(), _decision())},
        {"source_revisions": ()},
    ):
        with pytest.raises(ValidationError):
            RegulatoryAnchorCoverageEvidenceV2.model_validate(
                coverage.model_dump(mode="python") | changes
            )


def test_approval_requires_a_current_revision_assessment() -> None:
    assert not _coverage(decisions=(_decision(),), source_revisions=()).ready


def test_current_economic_findings_override_prior_source_approval() -> None:
    from italian_energy.integration.projected_service import ProjectedDomesticEnergyService

    changed = _request().model_copy(update={"assessment": SourceRevisionAssessment.CHANGED})
    coverage = _coverage(decisions=(_decision(),), source_revisions=(changed,))
    assert not coverage.ready
    service = ProjectedDomesticEnergyService(clock=lambda: CHECKED_AT)
    assert "regulatory_source_changed" in service._coverage_evidence_reasons(
        load_domestic_projection_anchor(), AS_OF, coverage
    )


def test_shorter_source_validity_is_an_economic_change_even_when_value_matches() -> None:
    anchor = load_domestic_projection_anchor(date(2026, 11, 4))
    body = (
        (
            Path(__file__).parents[1]
            / "fixtures/regulatory_rollover/normattiva-dpr633-table-a-synthetic.html"
        )
        .read_bytes()
        .replace(b"31-12-2026", b"30-11-2026")
    )
    request = observe_source_revision(
        anchor, "vat_dpr_633", body, observed_at=datetime(2026, 11, 4, 12, tzinfo=UTC)
    )
    assert request is not None and request.assessment == SourceRevisionAssessment.CHANGED


def test_equivalence_attestation_must_be_an_actual_boolean() -> None:
    with pytest.raises(ValidationError):
        RegulatorySourceRevisionDecision.model_validate(
            _decision().model_dump(mode="json") | {"equivalent_confirmed": "true"}
        )


def test_rollover_offline_gate_rechecks_revision_evidence_instead_of_trusting_ready() -> None:
    from test_regulatory_rollover_service import _service

    service, repository, port = _service()
    source = next(
        s for s in repository.read_current_anchor().sources if s.source_id == "vat_dpr_633"
    )
    port._bodies_by_url[source.url] = BODY
    report = service.refresh_regulatory_state(AS_OF)
    forged = report.current_coverage.model_copy(update={"ready": True, "reason_codes": ()})
    assert not service.source_preflight(AS_OF, forged).ready
