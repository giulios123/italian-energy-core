"""Versioned runtime coverage for verified billing rulesets."""

from __future__ import annotations

from collections.abc import Iterable
from enum import StrEnum
from itertools import pairwise

from pydantic import Field, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.regulatory import SupplyClassification
from italian_energy.domain.time import DatePeriod


class BillingCoverageError(ValueError):
    """Raised when a requested billing profile or period is not covered."""


class CoverageLevel(StrEnum):
    UNSUPPORTED = "unsupported"
    SOURCE_NORMALIZED = "source_normalized"
    RULESET_VERIFIED = "ruleset_verified"
    GOLDEN_RECONCILED = "golden_reconciled"

    @property
    def rank(self) -> int:
        return {
            CoverageLevel.UNSUPPORTED: 0,
            CoverageLevel.SOURCE_NORMALIZED: 1,
            CoverageLevel.RULESET_VERIFIED: 2,
            CoverageLevel.GOLDEN_RECONCILED: 3,
        }[self]


class BillingCoverageEntry(DomainModel):
    """One non-overlapping evidence interval for one ruleset/profile."""

    profile_code: str = Field(min_length=1)
    classification: SupplyClassification
    period: DatePeriod
    ruleset_id: str | None = None
    level: CoverageLevel
    source_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> BillingCoverageEntry:
        if len(self.source_ids) != len(set(self.source_ids)):
            raise ValueError("coverage source ids must be unique")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("coverage evidence ids must be unique")
        if self.level.rank >= CoverageLevel.RULESET_VERIFIED.rank and self.ruleset_id is None:
            raise ValueError("verified coverage requires a ruleset id")
        if self.level == CoverageLevel.GOLDEN_RECONCILED and not self.evidence_ids:
            raise ValueError("golden coverage requires evidence ids")
        return self


class BillingCoverageDecision(DomainModel):
    """Resolved coverage across one or more adjacent matrix entries."""

    profile_code: str = Field(min_length=1)
    ruleset_id: str = Field(min_length=1)
    period: DatePeriod
    level: CoverageLevel
    entries: tuple[BillingCoverageEntry, ...]
    source_ids: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()


class BillingCoverageMatrix(DomainModel):
    """Immutable, public and extensible billing evidence matrix."""

    matrix_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    entries: tuple[BillingCoverageEntry, ...]

    @model_validator(mode="after")
    def validate_entries(self) -> BillingCoverageMatrix:
        seen: list[tuple[str, SupplyClassification, str | None, DatePeriod]] = []
        for entry in self.entries:
            key = (entry.profile_code, entry.classification, entry.ruleset_id, entry.period)
            if key in seen:
                raise ValueError("duplicate billing coverage entry")
            seen.append(key)
        grouped: dict[tuple[str, SupplyClassification, str | None], list[BillingCoverageEntry]] = {}
        for entry in self.entries:
            grouped.setdefault(
                (entry.profile_code, entry.classification, entry.ruleset_id), []
            ).append(entry)
        for group in grouped.values():
            ordered = sorted(group, key=lambda item: item.period.start)
            for previous, current in pairwise(ordered):
                if current.period.start < previous.period.end:
                    raise ValueError("billing coverage entries overlap")
        return self

    def resolve(
        self,
        classification: SupplyClassification,
        ruleset_id: str,
        period: DatePeriod,
        minimum_level: CoverageLevel = CoverageLevel.RULESET_VERIFIED,
    ) -> BillingCoverageDecision:
        """Resolve contiguous coverage, failing closed on gaps or weak evidence."""

        candidates = sorted(
            (
                entry
                for entry in self.entries
                if entry.classification == classification
                and entry.ruleset_id == ruleset_id
                and entry.period.end > period.start
                and entry.period.start < period.end
            ),
            key=lambda entry: entry.period.start,
        )
        cursor = period.start
        selected: list[BillingCoverageEntry] = []
        for entry in candidates:
            if entry.period.end <= cursor:
                continue
            if entry.period.start > cursor:
                raise BillingCoverageError("billing coverage has a gap")
            selected.append(entry)
            cursor = min(entry.period.end, period.end)
            if cursor == period.end:
                break
        if not selected or cursor != period.end:
            raise BillingCoverageError("billing period is not covered")
        level = min((entry.level for entry in selected), key=lambda item: item.rank)
        if level.rank < minimum_level.rank:
            raise BillingCoverageError(
                f"billing coverage level {level.value} is below {minimum_level.value}"
            )
        profile_codes = {entry.profile_code for entry in selected}
        if len(profile_codes) != 1:
            raise BillingCoverageError("billing coverage profiles are ambiguous")
        return BillingCoverageDecision(
            profile_code=selected[0].profile_code,
            ruleset_id=ruleset_id,
            period=period,
            level=level,
            entries=tuple(selected),
            source_ids=_unique(selected, "source_ids"),
            evidence_ids=_unique(selected, "evidence_ids"),
        )


def _unique(entries: Iterable[BillingCoverageEntry], attribute: str) -> tuple[str, ...]:
    result: list[str] = []
    for entry in entries:
        for value in getattr(entry, attribute):
            if value not in result:
                result.append(value)
    return tuple(result)
