"""Recommendation models that cannot mutate economic results."""

from __future__ import annotations

from typing import Protocol

from pydantic import Field

from italian_energy.comparison.engine import ComparisonResult
from italian_energy.domain.base import DomainModel


class RecommendationPreferences(DomainModel):
    fixed_preference: bool | None = None
    volatility_tolerance: str | None = None
    minimum_contract_months: int | None = Field(default=None, ge=0)
    require_temporary_discounts: bool | None = None


class RecommendationRequest(DomainModel):
    comparison: ComparisonResult
    preferences: RecommendationPreferences = RecommendationPreferences()


class Recommendation(DomainModel):
    recommendation_id: str = Field(min_length=1)
    comparison_id: str = Field(min_length=1)
    selected_offer_id: str | None = None
    rationale: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


class RecommendationEngine(Protocol):
    def recommend(self, request: RecommendationRequest) -> Recommendation:
        """Interpret a comparison without changing its economic outputs."""
