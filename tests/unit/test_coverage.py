from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from italian_energy.billing import (
    BillingCoverageEntry,
    BillingCoverageError,
    BillingCoverageMatrix,
    CoverageLevel,
)
from italian_energy.domain.regulatory import SupplyClassification, VoltageLevel
from italian_energy.domain.time import DatePeriod

CLASSIFICATION = SupplyClassification(
    contract_type_code="domestic_bt_non_resident",
    voltage_level=VoltageLevel.BT,
    usage_code="domestic",
    residential=False,
)


def period(start: int, end: int) -> DatePeriod:
    return DatePeriod(start=date(2026, start, 1), end=date(2026, end, 1))


def entry(
    start: int,
    end: int,
    level: CoverageLevel,
    *,
    evidence: tuple[str, ...] = (),
) -> BillingCoverageEntry:
    return BillingCoverageEntry(
        profile_code=CLASSIFICATION.contract_type_code,
        classification=CLASSIFICATION,
        period=period(start, end),
        ruleset_id="ruleset-006",
        level=level,
        source_ids=(f"source-{start}",),
        evidence_ids=evidence,
    )


def test_resolve_accepts_contiguous_entries_and_returns_minimum_level() -> None:
    matrix = BillingCoverageMatrix(
        matrix_id="matrix-006",
        schema_version="006-v1",
        entries=(
            entry(1, 3, CoverageLevel.GOLDEN_RECONCILED, evidence=("golden-jan",)),
            entry(3, 5, CoverageLevel.RULESET_VERIFIED),
        ),
    )

    decision = matrix.resolve(CLASSIFICATION, "ruleset-006", period(1, 5))

    assert decision.level == CoverageLevel.RULESET_VERIFIED
    assert decision.source_ids == ("source-1", "source-3")
    assert decision.evidence_ids == ("golden-jan",)


def test_resolve_accepts_period_inside_one_entry() -> None:
    matrix = BillingCoverageMatrix(
        matrix_id="matrix-006",
        schema_version="006-v1",
        entries=(entry(1, 5, CoverageLevel.RULESET_VERIFIED),),
    )

    decision = matrix.resolve(CLASSIFICATION, "ruleset-006", period(2, 4))

    assert decision.period == period(2, 4)


def test_resolve_rejects_gap_or_weak_level() -> None:
    matrix = BillingCoverageMatrix(
        matrix_id="matrix-006",
        schema_version="006-v1",
        entries=(
            entry(1, 2, CoverageLevel.RULESET_VERIFIED),
            entry(3, 5, CoverageLevel.RULESET_VERIFIED),
        ),
    )

    with pytest.raises(BillingCoverageError, match="gap"):
        matrix.resolve(CLASSIFICATION, "ruleset-006", period(1, 5))

    weak = BillingCoverageMatrix(
        matrix_id="matrix-006-weak",
        schema_version="006-v1",
        entries=(entry(1, 5, CoverageLevel.SOURCE_NORMALIZED),),
    )
    with pytest.raises(BillingCoverageError, match="below"):
        weak.resolve(CLASSIFICATION, "ruleset-006", period(1, 5))


def test_matrix_rejects_overlap_and_invalid_golden_evidence() -> None:
    with pytest.raises(ValidationError, match="overlap"):
        BillingCoverageMatrix(
            matrix_id="matrix-006-overlap",
            schema_version="006-v1",
            entries=(
                entry(1, 3, CoverageLevel.RULESET_VERIFIED),
                entry(2, 4, CoverageLevel.RULESET_VERIFIED),
            ),
        )

    with pytest.raises(ValidationError, match="golden coverage"):
        BillingCoverageEntry(
            profile_code=CLASSIFICATION.contract_type_code,
            classification=CLASSIFICATION,
            period=period(1, 2),
            ruleset_id="ruleset-006",
            level=CoverageLevel.GOLDEN_RECONCILED,
        )

    with pytest.raises(ValidationError, match="source ids"):
        BillingCoverageEntry(
            profile_code=CLASSIFICATION.contract_type_code,
            classification=CLASSIFICATION,
            period=period(1, 2),
            level=CoverageLevel.SOURCE_NORMALIZED,
            source_ids=("same", "same"),
        )
    with pytest.raises(ValidationError, match="evidence ids"):
        BillingCoverageEntry(
            profile_code=CLASSIFICATION.contract_type_code,
            classification=CLASSIFICATION,
            period=period(1, 2),
            level=CoverageLevel.SOURCE_NORMALIZED,
            evidence_ids=("same", "same"),
        )


def test_verified_entry_requires_ruleset_id() -> None:
    with pytest.raises(ValidationError, match="ruleset id"):
        BillingCoverageEntry(
            profile_code=CLASSIFICATION.contract_type_code,
            classification=CLASSIFICATION,
            period=period(1, 2),
            level=CoverageLevel.RULESET_VERIFIED,
        )
