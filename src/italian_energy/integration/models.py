"""Typed requests for the stable Core-Platform integration surface."""

from __future__ import annotations

from pydantic import Field, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.costs import ExternalBillItem
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import (
    BillingMeasure,
    SupplyClassification,
    VoltageLevel,
)
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers.models import (
    PortalComparisonResult,
    PortalEligibilityProfile,
    VerifiedMarketData,
)
from italian_energy.recommendation import RecommendationPreferences

from .errors import CoreContractError, CoreErrorCode


class HistoricalPortalComparisonRequest(DomainModel):
    """Domestic-BT historical scenario accepted by the integration façade."""

    current_contract: Contract
    consumption: ConsumptionProfile
    period: DatePeriod
    classification: SupplyClassification
    eligibility: PortalEligibilityProfile
    supplemental_market_data: VerifiedMarketData | None = None
    measurements: tuple[BillingMeasure, ...] = ()
    external_items: tuple[ExternalBillItem, ...] = ()

    @model_validator(mode="after")
    def validate_scenario(self) -> HistoricalPortalComparisonRequest:
        if self.classification.voltage_level != VoltageLevel.BT:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "integration scenario requires BT voltage",
            )
        if self.classification.usage_code != "domestic":
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "integration scenario requires domestic usage",
            )
        if self.classification.residential is None:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "integration scenario requires explicit residential classification",
            )
        if self.current_contract.supply.residential is None:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "integration scenario requires explicit supply residential value",
            )
        if self.current_contract.supply.residential != self.classification.residential:
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "contract and classification residential values must match",
            )
        if self.current_contract.supply.commodity.value != "electricity":
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "integration scenario requires electricity",
            )
        return self


class HistoricalRecommendationRequest(DomainModel):
    """Recommendation request over one already-calculated historical comparison."""

    comparison: PortalComparisonResult
    preferences: RecommendationPreferences = Field(default_factory=RecommendationPreferences)
