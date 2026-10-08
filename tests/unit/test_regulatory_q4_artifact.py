"""Golden contract checks for the live Q4 regulatory candidate artifact."""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from test_projected_service import _catalog, _history, _indexed_request

import italian_energy.integration.projected_service as projected_service
from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.arera.rollover_coverage import RegulatoryAnchorCoverageEvidence
from italian_energy.arera.rollover_models import (
    RegulatoryAnchorCandidate,
    regulatory_anchor_artifact_digest,
)
from italian_energy.arera.rollover_state import RegulatoryRolloverEvent, RolloverEventKind
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.integration.projected_service import ProjectedDomesticEnergyService
from italian_energy.integration.serialization import dump_envelope, load_envelope

_CANDIDATE_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "italian_energy"
    / "data"
    / "billing"
    / "arera-domestic-bt-projection-anchor-2026-q4-candidate.json"
)
_Q4_ANCHOR_PATH = _CANDIDATE_PATH.with_name("arera-domestic-bt-projection-anchor-2026-q4.json")
_Q4_COVERAGE_PATH = _CANDIDATE_PATH.with_name("arera-domestic-bt-coverage-2026-10-08.json")
_Q4_PROMOTION_EVENT_PATH = _CANDIDATE_PATH.with_name(
    "arera-domestic-bt-promotion-event-2026-10-08.json"
)


def test_q4_candidate_is_canonical_auditable_and_not_promoted() -> None:
    encoded = _CANDIDATE_PATH.read_bytes()
    envelope = json.loads(encoded)
    candidate = load_envelope(encoded)

    assert envelope["schema_id"] == "italian-energy/regulatory-candidate/v2"
    assert "content" not in envelope["payload"]
    assert isinstance(candidate, RegulatoryAnchorCandidate)
    assert dump_envelope(candidate) == encoded.rstrip(b"\n")
    assert candidate.candidate_id == (
        "regulatory-anchor-candidate:"
        "8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e"
    )
    assert candidate.validation_result.passed
    assert candidate.anchor.status == VerificationStatus.UNVERIFIED
    assert candidate.anchor.validity == DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))
    assert candidate.anchor.as_of.isoformat() == "2026-10-08"

    current_values = {
        (item.segment, item.component_code, item.quota): item.value
        for item in load_domestic_projection_anchor().charges
    }
    q4_values = {
        (item.segment, item.component_code, item.quota): item.value
        for item in candidate.anchor.charges
    }
    assert q4_values == current_values
    assert candidate.anchor.excise_rate == Decimal("0.0227")
    assert candidate.anchor.vat_rate_percent == Decimal("10")

    sources = {source.source_id: source.sha256 for source in candidate.anchor.sources}
    assert sources["arera_343"] == (
        "685691673341be23f479823c61b18c37fe24360f629ff3f8b3c5c847888db30e"
    )
    assert sources["adm_excise_20261006"] == (
        "260f21ce3995f1440955d81f05544329c7f13749cc37d323d67efef66b55ef6b"
    )
    source_records = {source.source_id: source for source in candidate.anchor.sources}
    assert source_records["vat_dpr_633"].sha256 == (
        "3131100857ef19810e425b0330d2521fb698391419c5c5068ba72dd4b8cf148c"
    )
    assert source_records["vat_dpr_633_art16"].sha256 == (
        "8aa066590d1e5e86e6a539367743a3563ec97e73b5c8047e72d74da2215b361e"
    )
    assert source_records["vat_dpr_633"].url.endswith("!vig=2026-10-08")
    assert source_records["vat_dpr_633_art16"].url.endswith("!vig=2026-10-08")
    assert set(candidate.anchor.excise_source_ids) == {
        "adm_excise_20260926",
        "adm_excise_20261006",
    }
    assert {
        fact.effect.previous_anchor_id
        for fact in candidate.facts
        if fact.effect.kind.value == "confirm_value"
    } == {load_domestic_projection_anchor().anchor_id}


def test_promoted_q4_anchor_is_selected_by_its_half_open_validity() -> None:
    q3 = load_domestic_projection_anchor(as_of=date(2026, 9, 30))
    q4_at_start = load_domestic_projection_anchor(as_of=date(2026, 10, 1))
    q4 = load_domestic_projection_anchor(as_of=date(2026, 10, 8))

    assert q3.anchor_id == "arera-domestic-bt-anchor:2026-q3:2026-09-27"
    assert q4.anchor_id.startswith("regulatory-anchor:")
    assert q4_at_start == q4
    assert q4.status == VerificationStatus.VERIFIED
    assert q4.validity == DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))
    assert q4.anchor_id == json.loads(_Q4_ANCHOR_PATH.read_bytes())["anchor_id"]
    assert ProjectedDomesticEnergyService.acquire_regulatory_anchor(as_of=date(2026, 10, 8)) == q4
    with pytest.raises(ValueError, match="no unique packaged domestic projection anchor"):
        load_domestic_projection_anchor(as_of=date(2027, 1, 1))


def test_q4_live_coverage_artifact_is_ready_and_digest_bound() -> None:
    coverage = load_envelope(_Q4_COVERAGE_PATH.read_bytes())
    anchor = load_domestic_projection_anchor(as_of=date(2026, 10, 8))

    assert isinstance(coverage, RegulatoryAnchorCoverageEvidence)
    assert coverage.ready
    assert coverage.as_of == date(2026, 10, 8)
    assert coverage.anchor_id == anchor.anchor_id
    assert coverage.anchor_sha256 == regulatory_anchor_artifact_digest(anchor)
    assert coverage.discovery_sha256


def test_q4_promotion_event_records_the_single_successor_transition() -> None:
    event = load_envelope(_Q4_PROMOTION_EVENT_PATH.read_bytes())

    assert isinstance(event, RegulatoryRolloverEvent)
    assert event.kind == RolloverEventKind.ANCHOR_PROMOTED
    assert event.previous_anchor_id == "arera-domestic-bt-anchor:2026-q3:2026-09-27"
    assert (
        event.current_anchor_id
        == load_domestic_projection_anchor(as_of=date(2026, 10, 8)).anchor_id
    )
    assert event.candidate_id == (
        "regulatory-anchor-candidate:"
        "8171d18ee60eac067092ee0e7653c475499da9966fdbcfda55c8770846337e1e"
    )
    assert event.occurred_at.date() >= date(2026, 10, 8)


def test_q4_comparison_uses_persisted_evidence_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    coverage = load_envelope(_Q4_COVERAGE_PATH.read_bytes())
    anchor = load_domestic_projection_anchor(as_of=date(2026, 10, 8))
    assert isinstance(coverage, RegulatoryAnchorCoverageEvidence)
    as_of = coverage.as_of
    request = _indexed_request().model_copy(
        update={"as_of": as_of, "continuation_assumption": True}
    )
    shifted_buckets = []
    for bucket in request.consumption.buckets:
        start_month = bucket.interval.start.month % 12 + 1
        start_year = bucket.interval.start.year + (bucket.interval.start.month == 12)
        end_month = bucket.interval.end.month % 12 + 1
        end_year = bucket.interval.end.year + (bucket.interval.end.month == 12)
        interval = bucket.interval.model_copy(
            update={
                "start": bucket.interval.start.replace(year=start_year, month=start_month),
                "end": bucket.interval.end.replace(year=end_year, month=end_month),
            }
        )
        shifted_buckets.append(bucket.model_copy(update={"interval": interval}))
    request = request.model_copy(
        update={
            "consumption": request.consumption.model_copy(
                update={"buckets": tuple(shifted_buckets)}
            )
        }
    )

    def forbidden_network_access(*args: object, **kwargs: object) -> bytes:
        raise AssertionError("comparison must not acquire regulatory sources")

    monkeypatch.setattr(projected_service, "fetch_official_source", forbidden_network_access)
    now = coverage.checked_at + timedelta(seconds=10)
    result = ProjectedDomesticEnergyService(clock=lambda: now).compare(
        request,
        _catalog(as_of),
        _history(as_of),
        anchor,
        coverage,
    )

    assert result.status == "estimated"
    assert result.verified_inputs.regulatory_anchor_id == anchor.anchor_id
