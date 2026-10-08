from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError
from test_regulatory_candidate import AS_OF, CREATED_AT, VALIDITY, _complete_facts

from italian_energy.arera.discovery import (
    DISCOVERY_CHANNELS,
    DiscoveryActDisposition,
    DiscoveryChangeKind,
    DiscoveryFailure,
    DiscoveryRecordChange,
    OfficialRegistryRecord,
    RegistryIndexPage,
    RegulatoryDiscoveryReport,
    RegulatoryRegistryChannel,
    discover_regulatory_sources,
)
from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.arera.rollover_coverage import (
    RegulatoryAnchorSourceCheck,
    RegulatoryCandidateCoverageResult,
    RegulatoryCandidateSourceCheck,
    RegulatoryManualReview,
    RegulatoryReviewOutcome,
    RegulatoryReviewSourceCheck,
    verify_regulatory_anchor_coverage,
    verify_regulatory_candidate_coverage,
)
from italian_energy.arera.rollover_mapping import build_regulatory_anchor_candidate
from italian_energy.arera.rollover_models import (
    RegulatoryAnchorCandidate,
    RegulatoryEffectAssertion,
    RegulatoryFact,
    RegulatoryRolloverReason,
)
from italian_energy.domain.regulatory import BillingQuota
from italian_energy.domain.time import DatePeriod

SEARCH_PERIOD = DatePeriod(start=AS_OF, end=AS_OF + timedelta(days=1))
CHECKED_AT = datetime(2026, 9, 30, 12, tzinfo=UTC)
ACT_ID = "R-new-fixture-2026"
ACT_SHA256 = hashlib.sha256(b"synthetic new act").hexdigest()


def _index_url(channel: RegulatoryRegistryChannel) -> str:
    host = {
        RegulatoryRegistryChannel.ARERA_ACTS: "www.arera.it",
        RegulatoryRegistryChannel.ARERA_TARIFFS: "www.arera.it",
        RegulatoryRegistryChannel.ADM_EXCISE: "www.adm.gov.it",
        RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: "www.gazzettaufficiale.it",
        RegulatoryRegistryChannel.NORMATTIVA_UPDATES: "www.normattiva.it",
    }[channel]
    return f"https://{host}/synthetic-registry-index"


def _act_record(channel: RegulatoryRegistryChannel) -> OfficialRegistryRecord:
    return OfficialRegistryRecord(
        channel=channel,
        act_id=ACT_ID,
        title="Synthetic regulatory act",
        published_at=AS_OF,
        url=f"{_index_url(channel).rsplit('/', 1)[0]}/acts/{ACT_ID}",
        document_id=f"{ACT_ID}.pdf",
    )


class _PageAdapter:
    def __init__(
        self,
        channel: RegulatoryRegistryChannel,
        *,
        include_act: bool = False,
        fetched_at: datetime = CHECKED_AT,
        search_period: DatePeriod = SEARCH_PERIOD,
    ) -> None:
        self.channel = channel
        self.search_period = search_period
        self.adapter_id = f"synthetic-{channel.value}"
        self.adapter_version = "1.0.0"
        records = (
            (_act_record(channel).model_copy(update={"published_at": search_period.start}),)
            if include_act
            else ()
        )
        self.page = RegistryIndexPage(
            channel=channel,
            search_period=search_period,
            query="synthetic exact date-window",
            source_url=_index_url(channel),
            fetched_at=fetched_at,
            page_number=1,
            total_pages=1,
            total_results=len(records),
            cursor_in=None,
            cursor_out="complete",
            index_sha256=hashlib.sha256(channel.value.encode()).hexdigest(),
            complete=True,
            records=records,
        )

    def fetch_page(
        self,
        search_period: DatePeriod,
        page_number: int,
        cursor: str | None,
    ) -> RegistryIndexPage:
        if search_period != self.search_period or page_number != 1 or cursor is not None:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        return self.page


def _discovery(
    *,
    act_channel: RegulatoryRegistryChannel | None = None,
    channels: tuple[RegulatoryRegistryChannel, ...] = DISCOVERY_CHANNELS,
    discovered_at: datetime = CHECKED_AT,
    as_of: date = AS_OF,
) -> RegulatoryDiscoveryReport:
    search_period = DatePeriod(start=as_of, end=as_of + timedelta(days=1))
    adapters = tuple(
        _PageAdapter(
            channel,
            include_act=channel == act_channel,
            fetched_at=discovered_at,
            search_period=search_period,
        )
        for channel in channels
    )
    return discover_regulatory_sources(adapters, search_period, discovered_at)


def _candidate(
    *,
    facts: tuple[RegulatoryFact, ...] | None = None,
    decision_ids: tuple[str, ...] = (),
) -> RegulatoryAnchorCandidate:
    return build_regulatory_anchor_candidate(
        current_anchor=load_domestic_projection_anchor(),
        validity=VALIDITY,
        as_of=AS_OF,
        created_at=CREATED_AT,
        facts=_complete_facts() if facts is None else facts,
        decision_ids=decision_ids,
    )


def _checks(
    candidate: RegulatoryAnchorCandidate,
    checked_at: datetime = CHECKED_AT,
    *,
    unavailable_source: str | None = None,
    changed_source: str | None = None,
) -> tuple[RegulatoryCandidateSourceCheck, ...]:
    result: list[RegulatoryCandidateSourceCheck] = []
    for source in candidate.anchor.sources:
        assert source.sha256 is not None
        observed: str | None = source.sha256
        if source.source_id == unavailable_source:
            observed = None
        elif source.source_id == changed_source:
            observed = "f" * 64
        result.append(
            RegulatoryCandidateSourceCheck(
                source_id=source.source_id,
                expected_sha256=source.sha256,
                observed_sha256=observed,
                checked_at=checked_at,
            )
        )
    return tuple(result)


def _verify(
    candidate: RegulatoryAnchorCandidate,
    discovery: RegulatoryDiscoveryReport | None = None,
    checks: tuple[RegulatoryCandidateSourceCheck, ...] | None = None,
    reviews: tuple[RegulatoryManualReview, ...] = (),
    review_source_checks: tuple[RegulatoryReviewSourceCheck, ...] = (),
    checked_at: datetime = CHECKED_AT,
    as_of: date = AS_OF,
) -> RegulatoryCandidateCoverageResult:
    return verify_regulatory_candidate_coverage(
        candidate=candidate,
        discovery=_discovery() if discovery is None else discovery,
        source_checks=_checks(candidate, checked_at) if checks is None else checks,
        as_of=as_of,
        checked_at=checked_at,
        reviews=reviews,
        review_source_checks=review_source_checks,
    )


def _review_checks(
    reviews: tuple[RegulatoryManualReview, ...], *, changed: bool = False
) -> tuple[RegulatoryReviewSourceCheck, ...]:
    return tuple(
        RegulatoryReviewSourceCheck(
            review_id=review.decision_id,
            expected_sha256=review.source_sha256,
            observed_sha256="f" * 64 if changed else review.source_sha256,
            checked_at=CHECKED_AT,
        )
        for review in reviews
    )


def _irrelevant_review() -> RegulatoryManualReview:
    return RegulatoryManualReview(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id=ACT_ID,
        source_url=f"https://www.arera.it/atti-e-provvedimenti/{ACT_ID}",
        source_sha256=ACT_SHA256,
        scope=VALIDITY,
        outcome=RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE,
        reviewer="operator-fixture",
        reviewed_at=CHECKED_AT,
        rationale="Synthetic fixture act is outside the tested domestic BT scope.",
        rule_id="fixture-scope-rule",
        rule_version="1.0.0",
    )


def test_complete_source_and_registry_evidence_verifies_candidate_coverage() -> None:
    candidate = _candidate()
    result = _verify(candidate)

    assert result.ready
    assert not result.reason_codes
    assert result.candidate_id == candidate.candidate_id
    assert len(result.source_checks) == len(candidate.anchor.sources)
    assert len(result.discovery_sha256) == 64


def test_temporarily_unavailable_and_changed_source_have_distinct_reasons() -> None:
    candidate = _candidate()
    first_source = candidate.anchor.sources[0].source_id
    unavailable = _verify(
        candidate,
        checks=_checks(candidate, unavailable_source=first_source),
    )
    changed = _verify(candidate, checks=_checks(candidate, changed_source=first_source))

    assert not unavailable.ready
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in unavailable.reason_codes
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in changed.reason_codes
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE not in changed.reason_codes


def test_missing_source_or_registry_evidence_fails_closed() -> None:
    candidate = _candidate()
    incomplete_checks = _checks(candidate)[:-1]
    missing_source = _verify(candidate, checks=incomplete_checks)
    missing_registry = _discovery(channels=DISCOVERY_CHANNELS[:-1])
    missing_discovery = _verify(candidate, discovery=missing_registry)

    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in missing_source.reason_codes
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in missing_discovery.reason_codes


def test_stale_as_of_discovery_and_source_checks_are_rejected() -> None:
    candidate = _candidate()
    previous_day = datetime(2026, 9, 28, 12, tzinfo=UTC)
    stale_checks = _checks(candidate, checked_at=previous_day)
    result = _verify(
        candidate,
        discovery=_discovery(discovered_at=previous_day),
        checks=stale_checks,
        checked_at=CHECKED_AT,
    )
    mismatched_date = _verify(candidate, as_of=date(2026, 10, 1))

    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in result.reason_codes
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in mismatched_date.reason_codes


def test_unrecognized_act_requires_review_artifact_in_candidate_identity() -> None:
    candidate = _candidate()
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    result = _verify(candidate, discovery=discovery)

    assert not result.ready
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in result.reason_codes


def test_unresolved_discovery_finding_blocks_current_anchor_coverage() -> None:
    anchor = load_domestic_projection_anchor()
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    source_checks = tuple(
        RegulatoryAnchorSourceCheck(
            source_id=source.source_id,
            expected_sha256=source.sha256,
            observed_sha256=source.sha256,
            checked_at=CHECKED_AT,
        )
        for source in anchor.sources
        if source.sha256 is not None
    )

    result = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=discovery,
        source_checks=source_checks,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
    )

    assert not result.ready
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in result.reason_codes


def test_non_numeric_confirmation_is_accepted_after_expiry_and_blocks_if_unapplied() -> None:
    anchor = load_domestic_projection_anchor()
    report = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_TARIFFS)
    report = report.model_copy(
        update={
            "findings": tuple(
                finding.model_copy(
                    update={
                        "disposition": DiscoveryActDisposition.SUPPORTED,
                        "rationale": "exact synthetic parser fixture",
                        "rule_id": "fixture-arera-confirmation",
                        "rule_version": "1.0.0",
                    }
                )
                for finding in report.findings
            )
        }
    )
    source_checks = tuple(
        RegulatoryAnchorSourceCheck(
            source_id=source.source_id,
            expected_sha256=source.sha256,
            observed_sha256=source.sha256,
            checked_at=CHECKED_AT,
        )
        for source in anchor.sources
        if source.sha256 is not None
    )
    assertion = RegulatoryEffectAssertion(
        assertion_id="fixture-confirmation:ASOS",
        component_code="ASOS",
        prior_effective_from=date(2026, 7, 1),
        validity=DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1)),
        segments=tuple(AreraCustomerSegment),
        quotas=tuple(BillingQuota),
        source_id="arera_343_fixture",
        source_url="https://www.arera.it/fileadmin/fixture/343.pdf",
        source_sha256=ACT_SHA256,
        act_id=ACT_ID,
        document="fixture-343.pdf",
        published_at=AS_OF,
        fetched_at=CHECKED_AT,
        parser_id="fixture-343-parser",
        parser_version="1.0.0",
        locator="page 6, article 1, paragraph 1.1",
        raw_value_token="sono confermati",
    )

    future_effect = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=report,
        source_checks=source_checks,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
        effect_assertions=(assertion,),
    )
    overlapping_effect = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=report,
        source_checks=source_checks,
        as_of=AS_OF,
        checked_at=CHECKED_AT,
        effect_assertions=(
            assertion.model_copy(
                update={"validity": DatePeriod(start=date(2026, 9, 15), end=date(2026, 12, 1))}
            ),
        ),
    )

    assert future_effect.ready
    assert RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY in overlapping_effect.reason_codes


def test_irrelevant_act_review_is_digest_bound_and_part_of_build_key() -> None:
    review = _irrelevant_review()
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )

    assert result.ready
    assert result.review_ids == (review.decision_id,)
    assert result.reviews == (review,)
    assert result.review_source_checks == _review_checks((review,))
    assert review.decision_id in candidate.decision_ids


def test_mapping_review_requires_candidate_facts_with_the_reviewed_digest() -> None:
    review = RegulatoryManualReview(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id=ACT_ID,
        source_url=f"https://www.arera.it/atti-e-provvedimenti/{ACT_ID}",
        source_sha256=ACT_SHA256,
        scope=VALIDITY,
        outcome=RegulatoryReviewOutcome.MAPPING_APPROVED,
        reviewer="operator-fixture",
        reviewed_at=CHECKED_AT,
        rationale="Synthetic approved exact mapping fixture.",
        parser_id="fixture-parser",
        parser_version="1.0.0",
        mapping_id="domestic-projection-anchor",
        mapping_version="1.0.0",
    )
    facts = list(_complete_facts())
    index = next(index for index, fact in enumerate(facts) if fact.source_id == "vat_dpr_633_art16")
    facts[index] = facts[index].model_copy(
        update={
            "act_id": ACT_ID,
            "source_sha256": ACT_SHA256,
            "source_url": f"https://www.arera.it/atti-e-provvedimenti/{ACT_ID}",
            "document": f"{ACT_ID}.pdf",
            "parser_id": "fixture-parser",
        }
    )
    candidate = _candidate(facts=tuple(facts), decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)

    result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )

    assert result.ready


def test_review_document_digest_must_match_the_reviewed_bytes() -> None:
    review = _irrelevant_review()
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)

    missing = _verify(candidate, discovery=discovery, reviews=(review,))
    changed = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=_review_checks((review,), changed=True),
    )

    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in missing.reason_codes
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in changed.reason_codes


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"source_url": "https://example.invalid/act"}, "official registry channel"),
        (
            {
                "outcome": RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE,
                "rule_id": None,
                "rule_version": None,
            },
            "versioned rule",
        ),
        ({"outcome": RegulatoryReviewOutcome.MAPPING_APPROVED}, "parser and mapping versions"),
        ({"reviewed_at": datetime(2026, 9, 30)}, "timezone-aware"),
    ),
)
def test_manual_review_requires_auditable_decision_metadata(
    changes: dict[str, Any], message: str
) -> None:
    payload = _irrelevant_review().model_dump(mode="python")
    payload.update(changes)

    with pytest.raises(ValidationError, match=message):
        RegulatoryManualReview.model_validate(payload)


def test_coverage_result_requires_reason_and_readiness_to_match() -> None:
    candidate = _candidate()
    result = _verify(candidate)
    payload = result.model_dump(mode="python")
    payload["ready"] = False

    with pytest.raises(ValidationError, match="readiness must match"):
        RegulatoryCandidateCoverageResult.model_validate(payload)


def test_duplicate_source_check_is_reported_as_invalid_evidence() -> None:
    candidate = _candidate()
    checks = _checks(candidate)
    duplicated = (checks[0], *checks)
    result = _verify(candidate, checks=duplicated)

    assert not result.ready
    assert RegulatoryRolloverReason.MAPPING_FAILURE in result.reason_codes


def test_duplicate_and_orphan_review_evidence_is_rejected() -> None:
    review = _irrelevant_review()
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    duplicate = _review_checks((review,))[0]
    duplicate_result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=(duplicate, duplicate),
    )
    orphan = RegulatoryReviewSourceCheck(
        review_id="e" * 64,
        expected_sha256=ACT_SHA256,
        observed_sha256=ACT_SHA256,
        checked_at=CHECKED_AT,
    )
    orphan_result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=(orphan,),
    )

    assert RegulatoryRolloverReason.MAPPING_FAILURE in duplicate_result.reason_codes
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in orphan_result.reason_codes


def test_review_source_temporarily_unavailable_and_stale_are_distinct() -> None:
    review = _irrelevant_review()
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    unavailable = RegulatoryReviewSourceCheck(
        review_id=review.decision_id,
        expected_sha256=review.source_sha256,
        observed_sha256=None,
        checked_at=CHECKED_AT,
    )
    stale = unavailable.model_copy(
        update={
            "observed_sha256": review.source_sha256,
            "checked_at": datetime(2026, 9, 28, 12, tzinfo=UTC),
        }
    )
    unavailable_result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=(unavailable,),
    )
    stale_result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=(stale,),
    )

    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in unavailable_result.reason_codes
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in stale_result.reason_codes


def test_rejected_review_and_changed_discovery_record_fail_closed() -> None:
    review = _irrelevant_review().model_copy(update={"outcome": RegulatoryReviewOutcome.REJECTED})
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    source_check = _review_checks((review,))[0]
    rejected = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=(source_check,),
    )
    changed_record = DiscoveryRecordChange(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id=ACT_ID,
        kind=DiscoveryChangeKind.CHANGED,
        previous_sha256="a" * 64,
        observed_sha256="b" * 64,
    )
    changed_discovery = discovery.model_copy(update={"changes": (changed_record,)})
    changed = _verify(candidate, discovery=changed_discovery)

    assert RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED in rejected.reason_codes
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in changed.reason_codes


@pytest.mark.parametrize(
    ("scope", "reviewed_at", "outcome", "expected_reason"),
    (
        (
            DatePeriod(start=AS_OF + timedelta(days=2), end=VALIDITY.end),
            CHECKED_AT,
            None,
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
        ),
        (
            DatePeriod(start=AS_OF, end=VALIDITY.end - timedelta(days=1)),
            CHECKED_AT,
            None,
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
        ),
        (
            VALIDITY,
            CHECKED_AT + timedelta(days=1),
            None,
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
        ),
        (
            VALIDITY,
            CHECKED_AT,
            RegulatoryReviewOutcome.REJECTED,
            RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
        ),
    ),
)
def test_review_scope_time_and_rejection_must_cover_candidate(
    scope: DatePeriod,
    reviewed_at: datetime,
    outcome: RegulatoryReviewOutcome | None,
    expected_reason: RegulatoryRolloverReason,
) -> None:
    review = _irrelevant_review()
    updates: dict[str, object] = {"scope": scope, "reviewed_at": reviewed_at}
    if outcome is not None:
        updates["outcome"] = outcome
    review = review.model_copy(update=updates)
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )

    assert expected_reason in result.reason_codes


def test_mapping_review_requires_matching_fact_and_mapping_version() -> None:
    review = RegulatoryManualReview(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id=ACT_ID,
        source_url=f"https://www.arera.it/atti-e-provvedimenti/{ACT_ID}",
        source_sha256=ACT_SHA256,
        scope=VALIDITY,
        outcome=RegulatoryReviewOutcome.MAPPING_APPROVED,
        reviewer="operator-fixture",
        reviewed_at=CHECKED_AT,
        rationale="Synthetic parser/mapping disagreement fixture.",
        parser_id="fixture-parser",
        parser_version="different-version",
        mapping_id="domestic-projection-anchor",
        mapping_version="different-version",
    )
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    result = _verify(
        candidate,
        discovery=discovery,
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )

    assert not result.ready
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in result.reason_codes


def test_new_change_does_not_require_a_second_review_but_changed_change_does() -> None:
    candidate = _candidate()
    discovery = _discovery()
    new_record = DiscoveryRecordChange(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id="R-new-another-fixture",
        kind=DiscoveryChangeKind.NEW,
        observed_sha256="b" * 64,
    )
    result = _verify(candidate, discovery=discovery.model_copy(update={"changes": (new_record,)}))

    assert result.ready


def test_review_artifact_and_result_reject_noncanonical_identity() -> None:
    review = _irrelevant_review()
    result = _verify(_candidate())
    payload = result.model_dump(mode="python")
    payload["reviews"] = [review]
    with pytest.raises(ValidationError, match="artifacts must match"):
        RegulatoryCandidateCoverageResult.model_validate(payload)

    payload = result.model_dump(mode="python")
    payload["source_checks"] = [*payload["source_checks"], payload["source_checks"][0]]
    with pytest.raises(ValidationError, match="unique source IDs"):
        RegulatoryCandidateCoverageResult.model_validate(payload)


def test_duplicate_review_for_the_same_act_is_a_mapping_failure() -> None:
    first = _irrelevant_review()
    second = first.model_copy(update={"rationale": "Different signed decision."})
    candidate = _candidate(decision_ids=(first.decision_id, second.decision_id))
    result = _verify(
        candidate,
        discovery=_discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS),
        reviews=(first, second),
        review_source_checks=_review_checks((first, second)),
    )

    assert RegulatoryRolloverReason.MAPPING_FAILURE in result.reason_codes


def test_review_must_be_part_of_candidate_and_match_discovered_channel() -> None:
    review = _irrelevant_review()
    missing_decision = _verify(
        _candidate(),
        discovery=_discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS),
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )
    wrong_channel = review.model_copy(
        update={
            "channel": RegulatoryRegistryChannel.ADM_EXCISE,
            "source_url": f"https://www.adm.gov.it/aliquote/{ACT_ID}",
        }
    )
    channel_mismatch = _verify(
        _candidate(decision_ids=(wrong_channel.decision_id,)),
        discovery=_discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS),
        reviews=(wrong_channel,),
        review_source_checks=_review_checks((wrong_channel,)),
    )

    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in missing_decision.reason_codes
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in channel_mismatch.reason_codes


def test_review_check_digest_mismatch_and_future_source_check_are_blocked() -> None:
    review = _irrelevant_review()
    candidate = _candidate(decision_ids=(review.decision_id,))
    mismatched_review_check = RegulatoryReviewSourceCheck(
        review_id=review.decision_id,
        expected_sha256="f" * 64,
        observed_sha256=review.source_sha256,
        checked_at=CHECKED_AT,
    )
    mismatched = _verify(
        candidate,
        discovery=_discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS),
        reviews=(review,),
        review_source_checks=(mismatched_review_check,),
    )
    future_source_checks = tuple(
        item.model_copy(update={"checked_at": CHECKED_AT + timedelta(days=1)})
        for item in _checks(candidate)
    )
    future = _verify(candidate, checks=future_source_checks)
    wrong_expected = tuple(
        item.model_copy(update={"expected_sha256": "f" * 64}) if index == 0 else item
        for index, item in enumerate(_checks(candidate))
    )
    expected_digest_mismatch = _verify(candidate, checks=wrong_expected)

    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in mismatched.reason_codes
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in future.reason_codes
    assert (
        RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
        in expected_digest_mismatch.reason_codes
    )


def test_naive_check_timestamps_and_duplicate_reasons_are_invalid() -> None:
    candidate = _candidate()
    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryCandidateSourceCheck(
            source_id="fixture",
            expected_sha256="a" * 64,
            checked_at=datetime(2026, 9, 30),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryReviewSourceCheck(
            review_id="a" * 64,
            expected_sha256="a" * 64,
            checked_at=datetime(2026, 9, 30),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryCandidateCoverageResult(
            candidate_id=candidate.candidate_id,
            candidate_build_key=candidate.build_key,
            as_of=AS_OF,
            checked_at=datetime(2026, 9, 30),
            discovery_sha256="a" * 64,
            source_checks=_checks(candidate),
            ready=True,
        )
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_regulatory_candidate_coverage(
            candidate=candidate,
            discovery=_discovery(),
            source_checks=_checks(candidate),
            as_of=AS_OF,
            checked_at=datetime(2026, 9, 30),
        )

    payload = _verify(candidate).model_dump(mode="python")
    payload["reason_codes"] = [RegulatoryRolloverReason.SOURCE_UNAVAILABLE] * 2
    payload["ready"] = False
    with pytest.raises(ValidationError, match="reason codes must be unique"):
        RegulatoryCandidateCoverageResult.model_validate(payload)


def test_coverage_result_requires_canonical_review_ids_and_known_source_checks() -> None:
    result = _verify(_candidate())
    payload = result.model_dump(mode="python")
    payload["review_ids"] = ("b" * 64, "a" * 64)
    with pytest.raises(ValidationError, match="unique and canonical"):
        RegulatoryCandidateCoverageResult.model_validate(payload)

    payload = result.model_dump(mode="python")
    payload["review_source_checks"] = [
        RegulatoryReviewSourceCheck(
            review_id="e" * 64,
            expected_sha256=ACT_SHA256,
            observed_sha256=ACT_SHA256,
            checked_at=CHECKED_AT,
        )
    ]
    with pytest.raises(ValidationError, match="known artifacts"):
        RegulatoryCandidateCoverageResult.model_validate(payload)


def test_incomplete_snapshot_and_non_review_finding_are_handled_safely() -> None:
    candidate = _candidate()
    discovery = _discovery()
    incomplete_snapshot = discovery.snapshots[0].model_copy(
        update={"complete": False, "next_cursor": None, "reason_code": None}
    )
    incomplete = discovery.model_copy(
        update={"snapshots": (incomplete_snapshot, *discovery.snapshots[1:])}
    )
    failed = _verify(candidate, discovery=incomplete)

    act_discovery = _discovery(act_channel=RegulatoryRegistryChannel.ARERA_ACTS)
    approved_finding = act_discovery.findings[0].model_copy(
        update={
            "disposition": DiscoveryActDisposition.SUPPORTED,
            "rule_id": "fixture-supported-rule",
            "rule_version": "1.0.0",
        }
    )
    approved = act_discovery.model_copy(update={"findings": (approved_finding,)})
    verified = _verify(_candidate(), discovery=approved)

    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in failed.reason_codes
    assert verified.ready


def test_rejected_review_of_changed_record_is_blocked() -> None:
    review = _irrelevant_review().model_copy(update={"outcome": RegulatoryReviewOutcome.REJECTED})
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery()
    changed_record = DiscoveryRecordChange(
        channel=review.channel,
        act_id=review.act_id,
        kind=DiscoveryChangeKind.CHANGED,
        previous_sha256="a" * 64,
        observed_sha256="b" * 64,
    )
    discovery_with_change = discovery.model_copy(update={"changes": (changed_record,)})
    result = _verify(
        candidate,
        discovery=discovery_with_change,
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )

    assert RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED in result.reason_codes


def test_changed_record_review_is_bound_to_the_observed_document_digest() -> None:
    review = _irrelevant_review()
    candidate = _candidate(decision_ids=(review.decision_id,))
    discovery = _discovery()
    changed_record = DiscoveryRecordChange(
        channel=review.channel,
        act_id=review.act_id,
        kind=DiscoveryChangeKind.CHANGED,
        previous_sha256="a" * 64,
        observed_sha256=review.source_sha256,
    )
    matched = _verify(
        candidate,
        discovery=discovery.model_copy(update={"changes": (changed_record,)}),
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )
    other_version = changed_record.model_copy(update={"observed_sha256": "b" * 64})
    mismatched = _verify(
        candidate,
        discovery=discovery.model_copy(update={"changes": (other_version,)}),
        reviews=(review,),
        review_source_checks=_review_checks((review,)),
    )

    assert matched.ready
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in mismatched.reason_codes
