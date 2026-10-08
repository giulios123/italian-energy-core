"""Versioned mapping from normalized regulatory facts to anchor candidates."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.arera.projection import (
    ROLLOVER_ANCHOR_SCHEMA_VERSION,
    DomesticProjectionAnchor,
    ProjectionAnchorCharge,
    ProjectionAnchorSource,
    ProjectionAnchorSourceReference,
)
from italian_energy.arera.rollover_models import (
    CandidateValidationResult,
    MappingDecision,
    RegulatoryAnchorCandidate,
    RegulatoryCandidateStatus,
    RegulatoryEffect,
    RegulatoryEffectAssertion,
    RegulatoryEffectKind,
    RegulatoryFact,
    RegulatoryFactFamily,
    RegulatoryRolloverReason,
    regulatory_build_key,
)
from italian_energy.arera.rollover_validation import (
    CandidateBuildFailure,
    FactValueResolution,
    resolve_constant_fact_value,
    validate_candidate_interval,
)
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import BillingCategory, BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod

MAPPING_ID = "domestic-projection-anchor"
MAPPING_VERSION = "1.0.0"
_CIVIL_TIMEZONE = ZoneInfo("Europe/Rome")
_CHARGE_UNITS = {
    BillingQuota.CONSUMPTION: RateUnit.EUR_PER_KWH,
    BillingQuota.FIXED: RateUnit.EUR_PER_YEAR,
    BillingQuota.POWER: RateUnit.EUR_PER_KW_YEAR,
}


def _fact_group(
    facts: tuple[RegulatoryFact, ...],
    *,
    family: RegulatoryFactFamily,
    segment: AreraCustomerSegment | None = None,
    component_code: str | None = None,
    quota: BillingQuota | None = None,
) -> tuple[RegulatoryFact, ...]:
    return tuple(
        fact
        for fact in facts
        if fact.family == family
        and fact.segment == segment
        and fact.component_code == component_code
        and fact.quota == quota
    )


def _unique_fact_ids(facts: tuple[RegulatoryFact, ...]) -> tuple[RegulatoryFact, ...]:
    by_id: dict[str, RegulatoryFact] = {}
    for fact in facts:
        previous = by_id.get(fact.fact_id)
        if previous is not None and previous != fact:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.DETERMINISM_VIOLATION,
                f"fact ID {fact.fact_id} identifies different normalized facts",
            )
        by_id[fact.fact_id] = fact
    return tuple(sorted(by_id.values(), key=lambda item: item.fact_id))


def _mapping_decision(
    *,
    output_field: str,
    resolution: FactValueResolution,
    validity: DatePeriod,
    mapping_version: str,
) -> MappingDecision:
    facts = resolution.facts
    fact_ids = tuple(sorted(fact.fact_id for fact in facts))
    source_ids = tuple(sorted({fact.source_id for fact in facts}))
    payload = {
        "mapping_id": MAPPING_ID,
        "mapping_version": mapping_version,
        "output_field": output_field,
        "fact_ids": fact_ids,
        "source_ids": source_ids,
        "value": str(resolution.value),
        "unit": resolution.unit.value,
        "validity": validity.model_dump(mode="json"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return MappingDecision(
        decision_id=hashlib.sha256(encoded).hexdigest(),
        mapping_id=MAPPING_ID,
        mapping_version=mapping_version,
        output_field=output_field,
        fact_ids=fact_ids,
        source_ids=source_ids,
        value=resolution.value,
        unit=resolution.unit,
        validity=validity,
        derivation=(
            "all fact intervals partition the half-open candidate period without gaps; "
            "all covering Decimal values and units agree"
        ),
        effects=tuple(fact.effect for fact in facts),
    )


def _previous_anchor_value(current: DomesticProjectionAnchor, output_field: str) -> Decimal | None:
    if output_field == "excise_rate":
        return current.excise_rate
    if output_field == "vat_rate_percent":
        return current.vat_rate_percent
    prefix = "charges."
    if output_field.startswith(prefix):
        _, segment, component_code, quota = output_field.split(".")
        return next(
            (
                charge.value
                for charge in current.charges
                if charge.segment.value == segment
                and charge.component_code == component_code
                and charge.quota.value == quota
            ),
            None,
        )
    return None


def _validate_effect_chain(
    resolution: FactValueResolution,
    current: DomesticProjectionAnchor,
    output_field: str,
) -> None:
    previous_value = _previous_anchor_value(current, output_field)
    for fact in resolution.facts:
        effect = fact.effect
        if effect.kind == RegulatoryEffectKind.SET_VALUE:
            continue
        if (
            effect.previous_anchor_id != current.anchor_id
            or effect.previous_value != previous_value
            or previous_value is None
        ):
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"{output_field}: regulatory effect does not link to the current anchor value",
            )
        if effect.kind == RegulatoryEffectKind.CONFIRM_VALUE and fact.value != previous_value:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"{output_field}: confirmation value differs from the linked prior value",
            )
        if effect.kind == RegulatoryEffectKind.AMEND_VALUE and fact.value == previous_value:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"{output_field}: unchanged value must be represented as a confirmation",
            )
        if effect.kind == RegulatoryEffectKind.TERMINATE_VALUE and fact.value != 0:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"{output_field}: terminated value must normalize to Decimal zero",
            )


def _source_label(url: str) -> str:
    host = urlsplit(url).hostname or "official source"
    if host.endswith("arera.it"):
        return "ARERA"
    if host.endswith("adm.gov.it"):
        return "ADM"
    if host.endswith("gazzettaufficiale.it"):
        return "Gazzetta Ufficiale"
    if host.endswith("normattiva.it"):
        return "Normattiva"
    return host


def _merge_fact_periods(facts: tuple[RegulatoryFact, ...]) -> DatePeriod | None:
    periods = sorted((fact.validity for fact in facts), key=lambda item: item.start)
    if not periods:
        return None
    start = periods[0].start
    end = periods[0].end
    for period in periods[1:]:
        if period.start > end:
            return None
        end = max(end, period.end)
    return DatePeriod(start=start, end=end)


def _anchor_sources(facts: tuple[RegulatoryFact, ...]) -> tuple[ProjectionAnchorSource, ...]:
    by_source: dict[str, list[RegulatoryFact]] = defaultdict(list)
    for fact in facts:
        by_source[fact.source_id].append(fact)
    sources: list[ProjectionAnchorSource] = []
    for source_id, group_list in sorted(by_source.items()):
        group = tuple(group_list)
        identity = {
            (
                fact.source_url,
                fact.source_sha256,
                fact.act_id,
                fact.document,
                fact.published_at,
                fact.fetched_at,
            )
            for fact in group
        }
        if len(identity) != 1:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
                f"source identifier {source_id} has inconsistent provenance",
            )
        url, digest, act_id, document, published_at, fetched_at = next(iter(identity))
        sources.append(
            ProjectionAnchorSource(
                source_id=source_id,
                source=_source_label(url),
                source_identifier=act_id,
                url=url,
                retrieved_at=fetched_at,
                published_at=published_at,
                effective_period=_merge_fact_periods(group),
                sha256=digest,
                document=document,
            )
        )
    return tuple(sources)


def _source_reference(fact: RegulatoryFact) -> ProjectionAnchorSourceReference:
    if "!" in fact.locator:
        sheet, cell = fact.locator.split("!", 1)
        return ProjectionAnchorSourceReference(
            source_id=fact.source_id,
            sheet=sheet,
            cell=cell,
            section=fact.locator,
        )
    return ProjectionAnchorSourceReference(source_id=fact.source_id, section=fact.locator)


def _charge_from_resolution(
    *,
    segment: AreraCustomerSegment,
    component_code: str,
    quota: BillingQuota,
    resolution: FactValueResolution,
) -> ProjectionAnchorCharge:
    category = (
        BillingCategory.NETWORK
        if component_code == "network_total"
        else BillingCategory.SYSTEM_CHARGES
    )
    references = tuple(
        _source_reference(fact)
        for fact in sorted(resolution.facts, key=lambda item: (item.source_id, item.locator))
    )
    return ProjectionAnchorCharge(
        code=(
            f"rollover:{segment.value}:{component_code}:{quota.value}:"
            f"{resolution.facts[0].validity.start.isoformat()}"
        ),
        segment=segment,
        component_code=component_code,
        category=category,
        quota=quota,
        value=resolution.value,
        unit=resolution.unit,
        references=references,
    )


def _resolution_or_failure(
    facts: tuple[RegulatoryFact, ...],
    validity: DatePeriod,
    expected_unit: RateUnit,
    as_of: date,
    output_field: str,
) -> FactValueResolution:
    try:
        return resolve_constant_fact_value(facts, validity, expected_unit, as_of)
    except CandidateBuildFailure as exc:
        raise CandidateBuildFailure(exc.reason_code, f"{output_field}: {exc.detail}") from exc


def _materialize_confirmation_facts(
    *,
    current_anchor: DomesticProjectionAnchor,
    validity: DatePeriod,
    as_of: date,
    created_at: datetime,
    facts: tuple[RegulatoryFact, ...],
    effect_assertions: tuple[RegulatoryEffectAssertion, ...],
) -> tuple[RegulatoryFact, ...]:
    """Bind non-numeric confirmations to prior values without guessing rates."""

    if not effect_assertions:
        return facts
    if len({item.assertion_id for item in effect_assertions}) != len(effect_assertions):
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.DETERMINISM_VIOLATION,
            "regulatory effect assertions contain duplicate IDs",
        )
    by_component: dict[str, RegulatoryEffectAssertion] = {}
    for assertion in effect_assertions:
        if assertion.validity.start > validity.start or assertion.validity.end < validity.end:
            continue
        if (
            assertion.published_at > as_of
            or assertion.fetched_at.astimezone(_CIVIL_TIMEZONE).date() > as_of
            or assertion.fetched_at > created_at
        ):
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
                f"confirmation {assertion.assertion_id} was not available at candidate snapshot",
            )
        prior_source_id = "arera_227" if assertion.component_code == "ASOS" else "arera_588"
        prior_source = next(
            (source for source in current_anchor.sources if source.source_id == prior_source_id),
            None,
        )
        if (
            prior_source is None
            or prior_source.effective_period is None
            or prior_source.effective_period.start != assertion.prior_effective_from
        ):
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
                f"{assertion.component_code} confirmation does not match its prior source period",
            )
        previous = by_component.get(assertion.component_code)
        if previous is not None and previous != assertion:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                f"multiple confirmations apply to {assertion.component_code}",
            )
        by_component[assertion.component_code] = assertion

    annual_network_source = next(
        (source for source in current_anchor.sources if source.source_id == "arera_575"), None
    )
    carry_facts: list[RegulatoryFact] = []
    for charge in current_anchor.charges:
        if charge.component_code == "system_total":
            required_components = ("ASOS", "ARIM")
        elif charge.component_code == "network_total":
            required_components = ("UC3", "UC6")
            if (
                annual_network_source is None
                or annual_network_source.effective_period is None
                or annual_network_source.effective_period.start > validity.start
                or annual_network_source.effective_period.end < validity.end
                or "arera_575" not in {reference.source_id for reference in charge.references}
            ):
                raise CandidateBuildFailure(
                    RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
                    "network confirmation requires arera_575 to remain valid "
                    "through the candidate period",
                )
        else:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"unsupported current-anchor component {charge.component_code}",
            )

        supporting = tuple(by_component.get(code) for code in required_components)
        if any(item is None for item in supporting):
            missing = tuple(
                code
                for code, item in zip(required_components, supporting, strict=True)
                if item is None
            )
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"{charge.component_code} carry-forward lacks confirmation for "
                f"{', '.join(missing)}",
            )
        confirmations = tuple(item for item in supporting if item is not None)
        if any(
            charge.segment not in item.segments or charge.quota not in item.quotas
            for item in confirmations
        ):
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                "confirmation does not cover the current charge's segment and quota",
            )
        representative = confirmations[0]
        provision = "; ".join(f"{item.act_id} {item.locator}" for item in confirmations)
        if charge.component_code == "network_total":
            provision += "; annual transmission source arera_575 remains valid"
        output_field = (
            f"charges.{charge.segment.value}.{charge.component_code}.{charge.quota.value}"
        )
        fact_id = f"{representative.source_id}:confirm:{current_anchor.anchor_id}:{output_field}"
        carry_facts.append(
            RegulatoryFact(
                fact_id=fact_id,
                family=RegulatoryFactFamily.CHARGE,
                component_code=charge.component_code,
                segment=charge.segment,
                quota=charge.quota,
                value=charge.value,
                unit=charge.unit,
                validity=validity,
                source_id=representative.source_id,
                source_url=representative.source_url,
                source_sha256=representative.source_sha256,
                act_id=representative.act_id,
                document=representative.document,
                published_at=representative.published_at,
                fetched_at=representative.fetched_at,
                parser_id=representative.parser_id,
                parser_version=representative.parser_version,
                locator="; ".join(item.locator for item in confirmations),
                raw_value_token="; ".join(item.raw_value_token for item in confirmations),
                derivation=(
                    f"Decimal {charge.value} is explicitly carried from current anchor "
                    f"{current_anchor.anchor_id} field {output_field}; no number is extracted "
                    "from the confirmation document"
                ),
                effect=RegulatoryEffect(
                    kind=RegulatoryEffectKind.CONFIRM_VALUE,
                    provision=provision,
                    previous_anchor_id=current_anchor.anchor_id,
                    previous_value=charge.value,
                    previous_fact_id=f"{current_anchor.anchor_id}:{output_field}",
                ),
            )
        )
    return (*facts, *carry_facts)


def build_regulatory_anchor_candidate(
    *,
    current_anchor: DomesticProjectionAnchor,
    validity: DatePeriod,
    as_of: date,
    created_at: datetime,
    facts: tuple[RegulatoryFact, ...],
    mapping_version: str = MAPPING_VERSION,
    decision_ids: tuple[str, ...] = (),
    allow_late_recovery: bool = False,
    effect_assertions: tuple[RegulatoryEffectAssertion, ...] = (),
) -> RegulatoryAnchorCandidate:
    """Build an immutable candidate only from complete, uniform verified facts."""

    validate_candidate_interval(
        current_anchor,
        validity,
        as_of,
        allow_late_recovery=allow_late_recovery,
    )
    if created_at.tzinfo is None or created_at.utcoffset() is None:
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
            "candidate creation timestamp must be timezone-aware",
        )
    if not mapping_version.strip():
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.MAPPING_FAILURE,
            "mapping version cannot be empty",
        )
    if len(set(decision_ids)) != len(decision_ids) or any(
        not item.strip() for item in decision_ids
    ):
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.MAPPING_FAILURE,
            "review decision IDs must be non-empty and unique",
        )
    input_fact_ids = [fact.fact_id for fact in facts]
    if len(set(input_fact_ids)) != len(input_fact_ids):
        facts = _unique_fact_ids(facts)
    facts = _materialize_confirmation_facts(
        current_anchor=current_anchor,
        validity=validity,
        as_of=as_of,
        created_at=created_at,
        facts=facts,
        effect_assertions=effect_assertions,
    )

    decisions: list[MappingDecision] = []
    selected_facts: list[RegulatoryFact] = []
    charges: list[ProjectionAnchorCharge] = []

    charge_keys = {
        (item.segment, item.component_code, item.quota) for item in current_anchor.charges
    }
    charge_keys.update(
        (item.segment, item.component_code, item.quota)
        for item in facts
        if item.family == RegulatoryFactFamily.CHARGE
        and item.segment is not None
        and item.component_code is not None
        and item.quota is not None
    )
    for segment, component_code, quota in sorted(
        charge_keys,
        key=lambda item: (item[0].value, item[1], item[2].value),
    ):
        expected_unit = _CHARGE_UNITS.get(quota)
        if expected_unit is None:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"unsupported charge quota {quota.value}",
            )
        group = _fact_group(
            facts,
            family=RegulatoryFactFamily.CHARGE,
            segment=segment,
            component_code=component_code,
            quota=quota,
        )
        output_field = f"charges.{segment.value}.{component_code}.{quota.value}"
        resolution = _resolution_or_failure(group, validity, expected_unit, as_of, output_field)
        _validate_effect_chain(resolution, current_anchor, output_field)
        decisions.append(
            _mapping_decision(
                output_field=output_field,
                resolution=resolution,
                validity=validity,
                mapping_version=mapping_version,
            )
        )
        selected_facts.extend(resolution.facts)
        charges.append(
            _charge_from_resolution(
                segment=segment,
                component_code=component_code,
                quota=quota,
                resolution=resolution,
            )
        )

    excise_group = _fact_group(facts, family=RegulatoryFactFamily.EXCISE_RATE)
    excise_resolution = _resolution_or_failure(
        excise_group,
        validity,
        RateUnit.EUR_PER_KWH,
        as_of,
        "excise_rate",
    )
    _validate_effect_chain(excise_resolution, current_anchor, "excise_rate")
    decisions.append(
        _mapping_decision(
            output_field="excise_rate",
            resolution=excise_resolution,
            validity=validity,
            mapping_version=mapping_version,
        )
    )
    selected_facts.extend(excise_resolution.facts)

    vat_group = _fact_group(facts, family=RegulatoryFactFamily.VAT_RATE)
    vat_resolution = _resolution_or_failure(
        vat_group,
        validity,
        RateUnit.PERCENT,
        as_of,
        "vat_rate_percent",
    )
    vat_source_ids = tuple(sorted({fact.source_id for fact in vat_resolution.facts}))
    _validate_effect_chain(vat_resolution, current_anchor, "vat_rate_percent")
    if not {"vat_dpr_633", "vat_dpr_633_art16"}.issubset(vat_source_ids):
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
            "VAT mapping requires both statutory table and rate-source facts",
        )
    decisions.append(
        _mapping_decision(
            output_field="vat_rate_percent",
            resolution=vat_resolution,
            validity=validity,
            mapping_version=mapping_version,
        )
    )
    selected_facts.extend(vat_resolution.facts)

    selected = _unique_fact_ids(tuple(selected_facts))
    if any(fact.fetched_at > created_at for fact in selected):
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
            "candidate creation timestamp precedes one or more selected source fetches",
        )
    source_digests = tuple(sorted({fact.source_sha256 for fact in selected}))
    parser_versions = tuple(
        sorted({f"{fact.parser_id}@{fact.parser_version}" for fact in selected})
    )
    decision_tuple = tuple(sorted(decisions, key=lambda item: item.output_field))
    all_decision_ids = tuple(
        sorted({*decision_ids, *(item.decision_id for item in decision_tuple)})
    )
    build_key = regulatory_build_key(
        validity=validity,
        source_digests=source_digests,
        facts=selected,
        parser_versions=parser_versions,
        mapping_versions=(mapping_version,),
        decision_ids=all_decision_ids,
    )
    source_by_id = {source.source_id: source for source in _anchor_sources(selected)}
    excise_source_ids = tuple(sorted({fact.source_id for fact in excise_resolution.facts}))
    final_vat_source_ids = tuple(sorted({fact.source_id for fact in vat_resolution.facts}))
    anchor = DomesticProjectionAnchor(
        schema_version=ROLLOVER_ANCHOR_SCHEMA_VERSION,
        anchor_id=f"candidate:{build_key}",
        as_of=as_of,
        validity=validity,
        sources=tuple(source_by_id[key] for key in sorted(source_by_id)),
        charges=tuple(
            sorted(
                charges,
                key=lambda item: (item.segment.value, item.component_code, item.quota.value),
            )
        ),
        excise_rate=excise_resolution.value,
        excise_source_ids=excise_source_ids,
        vat_rate_percent=vat_resolution.value,
        vat_source_ids=final_vat_source_ids,
        status=VerificationStatus.UNVERIFIED,
    )
    validation_result = CandidateValidationResult(
        passed=True,
        validated_at=created_at,
        fact_count=len(selected),
        decision_count=len(decision_tuple),
        validity=validity,
    )
    return RegulatoryAnchorCandidate(
        candidate_id=f"regulatory-anchor-candidate:{build_key}",
        build_key=build_key,
        created_at=created_at,
        status=RegulatoryCandidateStatus.CANDIDATE_READY,
        anchor=anchor,
        facts=selected,
        mapping_decisions=decision_tuple,
        decision_ids=tuple(sorted(decision_ids)),
        validation_result=validation_result,
    )


__all__ = [
    "MAPPING_ID",
    "MAPPING_VERSION",
    "build_regulatory_anchor_candidate",
]
