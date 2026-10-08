"""Deterministic validation primitives for a regulatory anchor candidate."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from itertools import pairwise
from zoneinfo import ZoneInfo

from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.arera.rollover_models import RegulatoryFact, RegulatoryRolloverReason
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod

_CIVIL_TIMEZONE = ZoneInfo("Europe/Rome")


@dataclass(frozen=True, slots=True)
class FactValueResolution:
    """One Decimal value proven constant across a requested half-open period."""

    value: Decimal
    unit: RateUnit
    facts: tuple[RegulatoryFact, ...]


class CandidateBuildFailure(ValueError):
    """Stable failure reason for validation or mapping that blocks a candidate."""

    def __init__(self, reason_code: RegulatoryRolloverReason, detail: str) -> None:
        self.reason_code = reason_code
        self.detail = detail
        super().__init__(f"{reason_code.value}: {detail}")


def validate_candidate_interval(
    current_anchor: DomesticProjectionAnchor,
    validity: DatePeriod,
    as_of: date,
    *,
    allow_late_recovery: bool = False,
) -> None:
    """Require adjacency; late recovery needs complete discovery proof."""

    if current_anchor.status != VerificationStatus.VERIFIED:
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
            "current anchor must be verified before a successor can be built",
        )
    if validity.start >= validity.end or validity.start != current_anchor.validity.end:
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
            "candidate validity must be non-empty and start exactly at current valid_until",
        )
    if as_of > validity.start and not allow_late_recovery:
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
            "late candidate construction requires complete discovery recovery proof",
        )


def resolve_constant_fact_value(
    facts: tuple[RegulatoryFact, ...],
    validity: DatePeriod,
    expected_unit: RateUnit,
    as_of: date,
) -> FactValueResolution:
    """Prove complete, unambiguous coverage and one value/unit for the period."""

    relevant = tuple(
        fact
        for fact in facts
        if fact.validity.start < validity.end and validity.start < fact.validity.end
    )
    if not relevant:
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
            "no normalized regulatory facts cover the candidate period",
        )
    for fact in relevant:
        if fact.status != VerificationStatus.VERIFIED:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED,
                f"fact {fact.fact_id} is not verified",
            )
        if fact.unit != expected_unit:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.MAPPING_FAILURE,
                f"fact {fact.fact_id} uses {fact.unit.value}, expected {expected_unit.value}",
            )
        if fact.published_at > as_of or fact.fetched_at.astimezone(_CIVIL_TIMEZONE).date() > as_of:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
                f"fact {fact.fact_id} was not available at the candidate snapshot date",
            )

    boundaries = {validity.start, validity.end}
    for fact in relevant:
        boundaries.add(max(validity.start, fact.validity.start))
        boundaries.add(min(validity.end, fact.validity.end))
    ordered = sorted(boundaries)
    values: set[tuple[Decimal, RateUnit]] = set()
    for segment_start, segment_end in pairwise(ordered):
        if segment_start >= segment_end:
            continue
        covering = tuple(
            fact
            for fact in relevant
            if fact.validity.start <= segment_start and fact.validity.end >= segment_end
        )
        if not covering:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
                f"no regulatory fact covers {segment_start.isoformat()}/{segment_end.isoformat()}",
            )
        segment_values = {(fact.value, fact.unit) for fact in covering}
        if len(segment_values) != 1:
            raise CandidateBuildFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                f"conflicting facts apply on {segment_start.isoformat()}/{segment_end.isoformat()}",
            )
        values.update(segment_values)

    if len(values) != 1:
        raise CandidateBuildFailure(
            RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
            "candidate validity crosses a regulatory value change",
        )
    value, unit = next(iter(values))
    return FactValueResolution(
        value=value,
        unit=unit,
        facts=tuple(sorted(relevant, key=lambda item: item.fact_id)),
    )


__all__ = [
    "CandidateBuildFailure",
    "FactValueResolution",
    "resolve_constant_fact_value",
    "validate_candidate_interval",
]
