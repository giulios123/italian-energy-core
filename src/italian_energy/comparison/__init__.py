"""Comparison Engine contract."""

from italian_energy.comparison.engine import (
    AlternativePricing,
    ComparisonContext,
    ComparisonEngine,
    ComparisonError,
    ComparisonRequest,
    ComparisonResult,
    DeterministicComparisonEngine,
    OfferExclusion,
    OfferExclusionCode,
)

__all__ = [
    "AlternativePricing",
    "ComparisonContext",
    "ComparisonEngine",
    "ComparisonError",
    "ComparisonRequest",
    "ComparisonResult",
    "DeterministicComparisonEngine",
    "OfferExclusion",
    "OfferExclusionCode",
]
