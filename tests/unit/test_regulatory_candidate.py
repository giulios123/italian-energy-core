from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from italian_energy.arera.composer import AreraDomesticRuleSetComposer
from italian_energy.arera.discovery import RegulatoryRegistryChannel
from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.arera.rollover_mapping import build_regulatory_anchor_candidate
from italian_energy.arera.rollover_models import (
    CandidateValidationResult,
    MappingDecision,
    RegulatoryAnchorCandidate,
    RegulatoryEffect,
    RegulatoryEffectAssertion,
    RegulatoryEffectKind,
    RegulatoryFact,
    RegulatoryFactFamily,
    RegulatoryRolloverReason,
    regulatory_candidate_artifact_digest,
)
from italian_energy.arera.rollover_parsers import (
    ARERA_DOMESTIC_WORKBOOK_KIND,
    ARERA_DOMESTIC_WORKBOOK_MIME,
    RegulatorySourceDocument,
    default_regulatory_parser_registry,
)
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.arera.rollover_validation import (
    CandidateBuildFailure,
    resolve_constant_fact_value,
    validate_candidate_interval,
)
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import dump_envelope, load_envelope

AS_OF = date(2026, 9, 30)
CREATED_AT = datetime(2026, 9, 30, 12, tzinfo=UTC)
VALIDITY = DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))
FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures/regulatory_rollover/domestic-2026-q4-synthetic.xlsx"
)


def _charge_facts() -> tuple[RegulatoryFact, ...]:
    body = FIXTURE_PATH.read_bytes()
    acquired = AcquiredOfficialBytes(
        url=(
            "https://www.arera.it/fileadmin/area_operatori/prezzi_e_tariffe/"
            "Corrispettivi_libero_elettrico_domestico_2026.xlsx"
        ),
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
        fetched_at=CREATED_AT,
    )
    source = RegulatorySourceDocument(
        acquired=acquired,
        source_id="arera-workbook-2026-q4-fixture",
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="R-fixture-2026-01",
        document_id="synthetic Q4 ARERA workbook",
        published_at=date(2026, 9, 25),
        content_type=ARERA_DOMESTIC_WORKBOOK_MIME,
        document_kind=ARERA_DOMESTIC_WORKBOOK_KIND,
        layout_version="005-domestic-electricity-2026-v1",
    )
    result = default_regulatory_parser_registry().parse(source)
    assert result.facts
    return result.facts


def _fiscal_fact(
    *, family: RegulatoryFactFamily, source_id: str, value: str, unit: RateUnit
) -> RegulatoryFact:
    is_excise = family == RegulatoryFactFamily.EXCISE_RATE
    url = (
        "https://www.adm.gov.it/portale/aliquote-accisa-nazionali"
        if is_excise
        else f"https://www.normattiva.it/fixture/{source_id}"
    )
    document = "synthetic ADM source fixture" if is_excise else "synthetic statutory fixture"
    return RegulatoryFact(
        fact_id=f"fixture:{source_id}:{family.value}",
        family=family,
        value=Decimal(value),
        unit=unit,
        validity=VALIDITY,
        source_id=source_id,
        source_url=url,
        source_sha256=hashlib.sha256(source_id.encode()).hexdigest(),
        act_id=f"fixture-act:{source_id}",
        document=document,
        published_at=date(2026, 9, 20),
        fetched_at=CREATED_AT,
        parser_id="synthetic-regulatory-fact-fixture",
        parser_version="1.0.0",
        locator="synthetic table row 1",
        raw_value_token=value,
        derivation="synthetic fixture token parsed as Decimal",
        status=VerificationStatus.VERIFIED,
    )


def _complete_facts() -> tuple[RegulatoryFact, ...]:
    return (
        *_charge_facts(),
        _fiscal_fact(
            family=RegulatoryFactFamily.EXCISE_RATE,
            source_id="adm_20260918",
            value="0.0230",
            unit=RateUnit.EUR_PER_KWH,
        ),
        _fiscal_fact(
            family=RegulatoryFactFamily.VAT_RATE,
            source_id="vat_dpr_633",
            value="10",
            unit=RateUnit.PERCENT,
        ),
        _fiscal_fact(
            family=RegulatoryFactFamily.VAT_RATE,
            source_id="vat_dpr_633_art16",
            value="10",
            unit=RateUnit.PERCENT,
        ),
    )


def _arera_343_assertions() -> tuple[RegulatoryEffectAssertion, ...]:
    return tuple(
        RegulatoryEffectAssertion(
            assertion_id=f"arera_343:{component_code.lower()}:2026-10-01",
            component_code=component_code,
            prior_effective_from=prior_effective_from,
            validity=VALIDITY,
            segments=(AreraCustomerSegment.RESIDENT, AreraCustomerSegment.NON_RESIDENT),
            quotas=(BillingQuota.CONSUMPTION, BillingQuota.FIXED, BillingQuota.POWER),
            source_id="arera_343",
            source_url="https://www.arera.it/fileadmin/allegati/docs/26/343-2026-R-com.pdf",
            source_sha256=hashlib.sha256(b"343 private fixture").hexdigest(),
            act_id="343/2026/R/com",
            document="343-2026-R-com.pdf",
            published_at=date(2026, 9, 29),
            fetched_at=CREATED_AT,
            parser_id="arera-343-q4-confirmation",
            parser_version="1.0.0",
            locator=f"page 6, article 1, paragraph {paragraph}",
            raw_value_token="sono confermati",
        )
        for component_code, prior_effective_from, paragraph in (
            ("ASOS", date(2026, 7, 1), "1.1"),
            ("ARIM", date(2026, 1, 1), "1.3"),
            ("UC3", date(2026, 1, 1), "1.4"),
            ("UC6", date(2026, 1, 1), "1.4"),
        )
    )


def _build(
    facts: tuple[RegulatoryFact, ...] | None = None,
    *,
    validity: DatePeriod = VALIDITY,
    as_of: date = AS_OF,
    created_at: datetime = CREATED_AT,
) -> RegulatoryAnchorCandidate:
    return build_regulatory_anchor_candidate(
        current_anchor=load_domestic_projection_anchor(),
        validity=validity,
        as_of=as_of,
        created_at=created_at,
        facts=_complete_facts() if facts is None else facts,
    )


def test_complete_q4_facts_build_unverified_candidate_with_full_provenance() -> None:
    candidate = _build()

    assert candidate.status.value == "candidate_ready"
    assert candidate.anchor.status == VerificationStatus.UNVERIFIED
    assert candidate.anchor.anchor_id == f"candidate:{candidate.build_key}"
    assert candidate.anchor.validity == VALIDITY
    assert len(candidate.anchor.charges) == 12
    assert candidate.validation_result.fact_count == 39
    assert candidate.validation_result.decision_count == 14
    assert candidate.anchor.vat_source_ids == ("vat_dpr_633", "vat_dpr_633_art16")
    assert candidate.anchor.excise_source_ids == ("adm_20260918",)
    assert all(source.sha256 for source in candidate.anchor.sources)
    fiscal_sources = tuple(
        source
        for source in candidate.anchor.sources
        if source.source_id != "arera-workbook-2026-q4-fixture"
    )
    assert all(source.published_at == date(2026, 9, 20) for source in fiscal_sources)
    references = tuple(
        reference for charge in candidate.anchor.charges for reference in charge.references
    )
    assert any(reference.sheet == "dicembre 2026" for reference in references)
    assert len(regulatory_candidate_artifact_digest(candidate)) == 64


def test_candidate_effect_chain_uses_v2_envelope_and_round_trips_canonically() -> None:
    candidate = _build()

    encoded = dump_envelope(candidate)
    envelope = json.loads(encoded)
    restored = load_envelope(encoded)

    assert envelope["schema_id"] == "italian-energy/regulatory-candidate/v2"
    assert isinstance(restored, RegulatoryAnchorCandidate)
    assert restored == candidate
    assert all(decision.effects for decision in restored.mapping_decisions)

    effect_envelope = json.loads(dump_envelope(candidate.facts[0].effect))
    assert effect_envelope["schema_id"] == "italian-energy/regulatory-effect/v1"
    assert load_envelope(dump_envelope(candidate.facts[0].effect)) == candidate.facts[0].effect


def test_quarter_wide_candidate_composes_as_one_verified_validity_period() -> None:
    candidate = _build()

    ruleset = AreraDomesticRuleSetComposer().compose(
        candidate.anchor.to_bundle(),
        AreraCustomerSegment.RESIDENT,
        candidate.anchor.fiscal_policy(),
    )

    assert ruleset.validity == VALIDITY
    assert all(rule.validity == VALIDITY for rule in ruleset.profiles[0].rules)


def test_same_semantic_inputs_keep_build_identity_across_creation_times() -> None:
    facts = _complete_facts()
    first = _build(facts)
    second = _build(facts, created_at=datetime(2026, 9, 30, 13, tzinfo=UTC))

    assert first.build_key == second.build_key
    assert first.candidate_id == second.candidate_id
    first_digest = regulatory_candidate_artifact_digest(first)
    second_digest = regulatory_candidate_artifact_digest(second)
    assert first_digest != second_digest


def test_missing_fiscal_fact_fails_closed_without_reusing_current_anchor() -> None:
    facts = tuple(
        fact for fact in _complete_facts() if fact.family != RegulatoryFactFamily.EXCISE_RATE
    )

    with pytest.raises(CandidateBuildFailure) as caught:
        _build(facts)

    assert caught.value.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE


def test_gap_in_monthly_facts_blocks_candidate() -> None:
    facts = tuple(
        fact
        for fact in _complete_facts()
        if fact.validity.start.month != 11 or fact.family != RegulatoryFactFamily.CHARGE
    )

    with pytest.raises(CandidateBuildFailure) as caught:
        _build(facts)

    assert caught.value.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE


def test_monthly_value_change_requires_a_shorter_anchor_interval() -> None:
    facts = list(_complete_facts())
    index = next(
        index
        for index, fact in enumerate(facts)
        if fact.family == RegulatoryFactFamily.CHARGE
        and fact.segment == AreraCustomerSegment.RESIDENT
        and fact.component_code == "network_total"
        and fact.quota == BillingQuota.CONSUMPTION
        and fact.validity.start.month == 11
    )
    facts[index] = facts[index].model_copy(update={"value": Decimal("0.015")})

    with pytest.raises(CandidateBuildFailure) as caught:
        _build(tuple(facts))

    assert caught.value.reason_code == RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY


def test_candidate_period_must_be_adjacent_to_current_and_prepared_in_advance() -> None:
    with pytest.raises(CandidateBuildFailure) as caught_gap:
        _build(validity=DatePeriod(start=date(2026, 10, 2), end=date(2027, 1, 1)))
    assert caught_gap.value.reason_code == RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL

    with pytest.raises(CandidateBuildFailure) as caught_late:
        _build(as_of=date(2026, 10, 2))
    assert caught_late.value.reason_code == RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL


def test_candidate_accepts_only_confirmations_linked_to_the_current_anchor() -> None:
    current = load_domestic_projection_anchor()
    facts = list(_complete_facts())
    fact_index = next(
        index
        for index, item in enumerate(facts)
        if item.family == RegulatoryFactFamily.CHARGE
        and item.segment == AreraCustomerSegment.RESIDENT
        and item.component_code == "network_total"
        and item.quota == BillingQuota.CONSUMPTION
        and item.validity.start == VALIDITY.start
    )
    source_fact = facts[fact_index]
    previous = next(
        item
        for item in current.charges
        if item.segment == source_fact.segment
        and item.component_code == source_fact.component_code
        and item.quota == source_fact.quota
    )
    effect = RegulatoryEffect(
        kind=RegulatoryEffectKind.CONFIRM_VALUE,
        provision="delibera fixture, dispositivo 2",
        previous_anchor_id=current.anchor_id,
        previous_value=previous.value,
        previous_fact_id=f"{current.anchor_id}:network_total",
    )
    facts[fact_index] = source_fact.model_copy(update={"value": previous.value, "effect": effect})

    candidate = build_regulatory_anchor_candidate(
        current_anchor=current,
        validity=VALIDITY,
        as_of=AS_OF,
        created_at=CREATED_AT,
        facts=tuple(facts),
    )
    decision = next(
        item
        for item in candidate.mapping_decisions
        if item.output_field == "charges.residenza_anagrafica.network_total.consumption"
    )
    assert any(item.kind == RegulatoryEffectKind.CONFIRM_VALUE for item in decision.effects)

    facts[fact_index] = source_fact.model_copy(
        update={
            "value": previous.value,
            "effect": effect.model_copy(update={"previous_value": previous.value + Decimal("1")}),
        }
    )
    with pytest.raises(CandidateBuildFailure) as mismatched:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=tuple(facts),
        )
    assert mismatched.value.reason_code == RegulatoryRolloverReason.MAPPING_FAILURE


@pytest.mark.parametrize(
    ("kind", "fact_value"),
    [
        (RegulatoryEffectKind.CONFIRM_VALUE, None),
        (RegulatoryEffectKind.AMEND_VALUE, "previous"),
        (RegulatoryEffectKind.TERMINATE_VALUE, None),
    ],
)
def test_candidate_rejects_inconsistent_confirmation_amendment_and_termination(
    kind: RegulatoryEffectKind, fact_value: str | None
) -> None:
    current = load_domestic_projection_anchor()
    facts = list(_complete_facts())
    fact_index = next(
        index
        for index, item in enumerate(facts)
        if item.family == RegulatoryFactFamily.CHARGE
        and item.segment == AreraCustomerSegment.RESIDENT
        and item.component_code == "network_total"
        and item.quota == BillingQuota.CONSUMPTION
        and item.validity.start == VALIDITY.start
    )
    source_fact = facts[fact_index]
    previous = next(
        item
        for item in current.charges
        if item.segment == source_fact.segment
        and item.component_code == source_fact.component_code
        and item.quota == source_fact.quota
    )
    effect = RegulatoryEffect(
        kind=kind,
        provision="delibera fixture, dispositivo 3",
        previous_anchor_id=current.anchor_id,
        previous_value=previous.value,
        previous_fact_id=f"{current.anchor_id}:network_total",
    )
    value = previous.value if fact_value == "previous" else previous.value + Decimal("1")
    for index, fact in enumerate(facts):
        if (
            fact.family == RegulatoryFactFamily.CHARGE
            and fact.segment == source_fact.segment
            and fact.component_code == source_fact.component_code
            and fact.quota == source_fact.quota
        ):
            facts[index] = fact.model_copy(update={"value": value, "effect": effect})

    with pytest.raises(CandidateBuildFailure) as caught:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=tuple(facts),
        )

    assert caught.value.reason_code == RegulatoryRolloverReason.MAPPING_FAILURE


def test_q4_candidate_materializes_explicit_343_confirmations_from_current_anchor() -> None:
    current = load_domestic_projection_anchor()
    fiscal_facts = tuple(
        fact for fact in _complete_facts() if fact.family != RegulatoryFactFamily.CHARGE
    )

    candidate = build_regulatory_anchor_candidate(
        current_anchor=current,
        validity=VALIDITY,
        as_of=AS_OF,
        created_at=CREATED_AT,
        facts=fiscal_facts,
        effect_assertions=_arera_343_assertions(),
    )

    current_values = {
        (charge.segment, charge.component_code, charge.quota): charge.value
        for charge in current.charges
    }
    candidate_values = {
        (charge.segment, charge.component_code, charge.quota): charge.value
        for charge in candidate.anchor.charges
    }
    assert candidate_values == current_values
    assert len(candidate.anchor.charges) == len(current.charges)
    assert "arera_343" in {source.source_id for source in candidate.anchor.sources}
    confirmation_facts = tuple(
        fact for fact in candidate.facts if fact.effect.kind == RegulatoryEffectKind.CONFIRM_VALUE
    )
    assert len(confirmation_facts) == len(current.charges)
    assert all(fact.effect.previous_anchor_id == current.anchor_id for fact in confirmation_facts)
    assert all(fact.effect.previous_value == fact.value for fact in confirmation_facts)
    assert all("343/2026/R/com" in fact.effect.provision for fact in confirmation_facts)


def test_q4_candidate_rejects_incomplete_343_confirmation_or_nonannual_network_source() -> None:
    current = load_domestic_projection_anchor()
    fiscal_facts = tuple(
        fact for fact in _complete_facts() if fact.family != RegulatoryFactFamily.CHARGE
    )
    assertions = _arera_343_assertions()

    with pytest.raises(CandidateBuildFailure) as missing_component_confirmation:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=tuple(item for item in assertions if item.component_code != "UC6"),
        )
    assert missing_component_confirmation.value.reason_code == (
        RegulatoryRolloverReason.MAPPING_FAILURE
    )

    short_annual_source = current.sources[0].model_copy(
        update={"effective_period": DatePeriod(start=date(2026, 1, 1), end=date(2026, 10, 1))}
    )
    shortened_current = current.model_copy(
        update={
            "sources": tuple(
                short_annual_source if item.source_id == "arera_575" else item
                for item in current.sources
            )
        }
    )
    with pytest.raises(CandidateBuildFailure) as stale_network_source:
        build_regulatory_anchor_candidate(
            current_anchor=shortened_current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=assertions,
        )
    assert stale_network_source.value.reason_code == (RegulatoryRolloverReason.INCOMPLETE_COVERAGE)

    mismatched_effective_date = tuple(
        item.model_copy(update={"prior_effective_from": date(2026, 1, 1)})
        if item.component_code == "ASOS"
        else item
        for item in assertions
    )
    with pytest.raises(CandidateBuildFailure) as wrong_prior_period:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=mismatched_effective_date,
        )
    assert wrong_prior_period.value.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE


def test_q4_candidate_rejects_duplicate_or_future_343_assertions() -> None:
    current = load_domestic_projection_anchor()
    fiscal_facts = tuple(
        fact for fact in _complete_facts() if fact.family != RegulatoryFactFamily.CHARGE
    )
    assertions = _arera_343_assertions()

    with pytest.raises(CandidateBuildFailure) as duplicate:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=(*assertions, assertions[0]),
        )
    assert duplicate.value.reason_code == RegulatoryRolloverReason.DETERMINISM_VIOLATION

    future_assertions = (
        assertions[0].model_copy(update={"fetched_at": datetime(2026, 9, 30, 13, tzinfo=UTC)}),
        *assertions[1:],
    )
    with pytest.raises(CandidateBuildFailure) as future:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=future_assertions,
        )
    assert future.value.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY


def test_q4_candidate_ignores_out_of_period_assertions_and_rejects_ambiguous_scope() -> None:
    current = load_domestic_projection_anchor()
    fiscal_facts = tuple(
        fact for fact in _complete_facts() if fact.family != RegulatoryFactFamily.CHARGE
    )
    assertions = _arera_343_assertions()
    prior_period_assertion = assertions[0].model_copy(
        update={
            "assertion_id": "arera_343:asos:prior-period",
            "validity": DatePeriod(start=date(2026, 7, 1), end=date(2026, 10, 1)),
        }
    )

    candidate = build_regulatory_anchor_candidate(
        current_anchor=current,
        validity=VALIDITY,
        as_of=AS_OF,
        created_at=CREATED_AT,
        facts=fiscal_facts,
        effect_assertions=(*assertions, prior_period_assertion),
    )
    assert candidate.anchor.validity == VALIDITY

    restricted_scope = (
        assertions[0].model_copy(update={"segments": (AreraCustomerSegment.RESIDENT,)}),
        *assertions[1:],
    )
    with pytest.raises(CandidateBuildFailure) as scope_mismatch:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=restricted_scope,
        )
    assert scope_mismatch.value.reason_code == RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY

    conflicting_asos = assertions[0].model_copy(
        update={
            "assertion_id": "arera_343:asos:conflicting",
            "locator": "page 6, article 1, paragraph 1.2",
        }
    )
    with pytest.raises(CandidateBuildFailure) as duplicate_component:
        build_regulatory_anchor_candidate(
            current_anchor=current,
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=fiscal_facts,
            effect_assertions=(*assertions, conflicting_asos),
        )
    assert duplicate_component.value.reason_code == RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY


@pytest.mark.parametrize(
    ("changes", "reason"),
    (
        (
            {"created_at": datetime(2026, 9, 30, 12)},
            RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
        ),
        ({"mapping_version": " "}, RegulatoryRolloverReason.MAPPING_FAILURE),
        ({"decision_ids": ("review-a", "review-a")}, RegulatoryRolloverReason.MAPPING_FAILURE),
    ),
)
def test_candidate_builder_rejects_invalid_creation_and_mapping_metadata(
    changes: dict[str, object], reason: RegulatoryRolloverReason
) -> None:
    inputs: dict[str, object] = {
        "current_anchor": load_domestic_projection_anchor(),
        "validity": VALIDITY,
        "as_of": AS_OF,
        "created_at": CREATED_AT,
        "facts": _complete_facts(),
    }
    inputs.update(changes)

    with pytest.raises(CandidateBuildFailure) as caught:
        build_regulatory_anchor_candidate(**inputs)  # type: ignore[arg-type]

    assert caught.value.reason_code == reason


def test_duplicate_fact_id_with_different_payload_is_a_determinism_violation() -> None:
    facts = _complete_facts()
    duplicate = facts[0].model_copy(update={"value": facts[0].value + Decimal("1")})

    with pytest.raises(CandidateBuildFailure) as caught:
        _build((*facts, duplicate))

    assert caught.value.reason_code == RegulatoryRolloverReason.DETERMINISM_VIOLATION


def test_current_anchor_must_be_verified_before_successor_build() -> None:
    current = load_domestic_projection_anchor().model_copy(
        update={"status": VerificationStatus.UNVERIFIED}
    )

    with pytest.raises(CandidateBuildFailure) as caught:
        validate_candidate_interval(current, VALIDITY, AS_OF)

    assert caught.value.reason_code == RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED


def test_fact_resolution_rejects_unverified_wrong_unit_and_late_snapshot_facts() -> None:
    base = next(fact for fact in _charge_facts() if fact.validity.start.month == 10)
    with pytest.raises(CandidateBuildFailure) as unverified:
        resolve_constant_fact_value(
            (base.model_copy(update={"status": VerificationStatus.UNVERIFIED}),),
            base.validity,
            base.unit,
            AS_OF,
        )
    assert unverified.value.reason_code == RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED

    with pytest.raises(CandidateBuildFailure) as wrong_unit:
        resolve_constant_fact_value((base,), base.validity, RateUnit.PERCENT, AS_OF)
    assert wrong_unit.value.reason_code == RegulatoryRolloverReason.MAPPING_FAILURE

    with pytest.raises(CandidateBuildFailure) as late:
        resolve_constant_fact_value((base,), base.validity, base.unit, date(2026, 9, 25))
    assert late.value.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY


def test_fact_resolution_rejects_conflicts_and_period_gaps() -> None:
    base = next(fact for fact in _charge_facts() if fact.validity.start.month == 10)
    conflict = base.model_copy(
        update={"fact_id": f"{base.fact_id}:conflict", "value": base.value + Decimal("1")}
    )
    with pytest.raises(CandidateBuildFailure) as conflicting:
        resolve_constant_fact_value((base, conflict), base.validity, base.unit, AS_OF)
    assert conflicting.value.reason_code == RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY

    with pytest.raises(CandidateBuildFailure) as uncovered:
        resolve_constant_fact_value((base,), VALIDITY, base.unit, AS_OF)
    assert uncovered.value.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE


def test_candidate_rejects_missing_vat_source_pair_and_unversioned_mapping() -> None:
    facts = tuple(fact for fact in _complete_facts() if fact.source_id != "vat_dpr_633_art16")
    with pytest.raises(CandidateBuildFailure) as missing_vat:
        _build(facts)
    assert missing_vat.value.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE

    with pytest.raises(CandidateBuildFailure) as missing_mapping_version:
        build_regulatory_anchor_candidate(
            current_anchor=load_domestic_projection_anchor(),
            validity=VALIDITY,
            as_of=AS_OF,
            created_at=CREATED_AT,
            facts=_complete_facts(),
            mapping_version=" ",
        )
    assert missing_mapping_version.value.reason_code == RegulatoryRolloverReason.MAPPING_FAILURE


def test_candidate_rejects_source_identifier_with_changed_provenance() -> None:
    facts = list(_complete_facts())
    index = next(
        index
        for index, fact in enumerate(facts)
        if fact.source_id == "arera-workbook-2026-q4-fixture"
    )
    facts[index] = facts[index].model_copy(
        update={"source_url": "https://www.arera.it/different-document"}
    )

    with pytest.raises(CandidateBuildFailure) as caught:
        _build(tuple(facts))

    assert caught.value.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY


def test_candidate_rejects_timestamp_before_selected_source_fetch() -> None:
    with pytest.raises(CandidateBuildFailure) as caught:
        _build(created_at=datetime(2026, 9, 30, 11, 59, tzinfo=UTC))

    assert caught.value.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY


def test_candidate_model_enforces_anchor_state_ids_and_canonical_facts() -> None:
    candidate = _build()
    payload = candidate.model_dump(mode="python")

    published_anchor = candidate.anchor.model_dump(mode="python")
    published_anchor["status"] = VerificationStatus.VERIFIED
    with pytest.raises(ValidationError, match="cannot claim verified coverage"):
        RegulatoryAnchorCandidate.model_validate({**payload, "anchor": published_anchor})

    with pytest.raises(ValidationError, match="candidate anchor ID"):
        anchor_payload = candidate.anchor.model_dump(mode="python")
        anchor_payload["anchor_id"] = "wrong"
        RegulatoryAnchorCandidate.model_validate({**payload, "anchor": anchor_payload})

    with pytest.raises(ValidationError, match="candidate ID"):
        RegulatoryAnchorCandidate.model_validate({**payload, "candidate_id": "wrong"})

    with pytest.raises(ValidationError, match="unique identifiers"):
        RegulatoryAnchorCandidate.model_validate({**payload, "facts": ()})

    with pytest.raises(ValidationError, match="canonical ordering"):
        RegulatoryAnchorCandidate.model_validate(
            {**payload, "facts": tuple(reversed(candidate.facts))}
        )


def test_candidate_model_checks_mapping_fact_source_and_count_invariants() -> None:
    candidate = _build()
    payload = candidate.model_dump(mode="python")

    facts = list(payload["facts"])
    facts[0] = {**facts[0], "status": VerificationStatus.UNVERIFIED}
    with pytest.raises(ValidationError, match="only verified normalized facts"):
        RegulatoryAnchorCandidate.model_validate({**payload, "facts": tuple(facts)})

    decisions = list(payload["mapping_decisions"])
    decisions[0] = {**decisions[0], "fact_ids": ("missing-fact",)}
    with pytest.raises(ValidationError, match="must reference candidate facts"):
        RegulatoryAnchorCandidate.model_validate({**payload, "mapping_decisions": tuple(decisions)})

    decisions = list(payload["mapping_decisions"])
    decisions[0] = {**decisions[0], "source_ids": ("wrong-source",)}
    with pytest.raises(ValidationError, match="sources and validity"):
        RegulatoryAnchorCandidate.model_validate({**payload, "mapping_decisions": tuple(decisions)})

    validation = dict(payload["validation_result"])
    validation["fact_count"] = 1
    with pytest.raises(ValidationError, match="fact count"):
        RegulatoryAnchorCandidate.model_validate({**payload, "validation_result": validation})

    validation = dict(payload["validation_result"])
    validation["decision_count"] = 1
    with pytest.raises(ValidationError, match="decision count"):
        RegulatoryAnchorCandidate.model_validate({**payload, "validation_result": validation})


def test_candidate_model_checks_decision_order_uniqueness_and_timestamp() -> None:
    candidate = _build()
    payload = candidate.model_dump(mode="python")
    decisions = list(payload["mapping_decisions"])

    with pytest.raises(ValidationError, match="outputs must be unique"):
        RegulatoryAnchorCandidate.model_validate(
            {**payload, "mapping_decisions": tuple([decisions[0], decisions[0], *decisions[2:]])}
        )

    with pytest.raises(ValidationError, match="canonical ordering"):
        RegulatoryAnchorCandidate.model_validate(
            {**payload, "mapping_decisions": tuple(reversed(decisions))}
        )

    validation = dict(payload["validation_result"])
    validation["validated_at"] = datetime(2026, 9, 30, 13, tzinfo=UTC)
    with pytest.raises(ValidationError, match="before its validation"):
        RegulatoryAnchorCandidate.model_validate({**payload, "validation_result": validation})


def test_mapping_decision_and_candidate_validation_result_fail_closed() -> None:
    with pytest.raises(ValidationError, match="unique fact IDs"):
        MappingDecision(
            decision_id="d",
            mapping_id="m",
            mapping_version="1",
            output_field="f",
            fact_ids=("x", "x"),
            source_ids=("s",),
            value=Decimal("1"),
            unit=RateUnit.EUR_PER_KWH,
            validity=VALIDITY,
            derivation="fixture",
        )

    with pytest.raises(ValidationError, match="unique source IDs"):
        MappingDecision(
            decision_id="d",
            mapping_id="m",
            mapping_version="1",
            output_field="f",
            fact_ids=("x",),
            source_ids=("s", "s"),
            value=Decimal("1"),
            unit=RateUnit.EUR_PER_KWH,
            validity=VALIDITY,
            derivation="fixture",
        )

    with pytest.raises(ValidationError, match="cannot be negative"):
        MappingDecision(
            decision_id="d",
            mapping_id="m",
            mapping_version="1",
            output_field="f",
            fact_ids=("x",),
            source_ids=("s",),
            value=Decimal("-1"),
            unit=RateUnit.EUR_PER_KWH,
            validity=VALIDITY,
            derivation="fixture",
        )

    with pytest.raises(ValidationError, match="belongs in a typed build failure"):
        CandidateValidationResult(
            passed=False,
            validated_at=CREATED_AT,
            fact_count=1,
            decision_count=1,
            validity=VALIDITY,
        )
