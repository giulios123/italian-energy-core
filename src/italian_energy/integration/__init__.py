"""Stable typed and JSON integration contract for application consumers."""

from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.offer import Contract
from italian_energy.domain.supply import SupplyPoint
from italian_energy.portal_offers.models import PortalComparisonResult, VerifiedMarketData
from italian_energy.recommendation import Recommendation, RecommendationPreferences

from .current import (
    CurrentCatalogSnapshot,
    CurrentPortalComparisonRequest,
    CurrentPortalComparisonResult,
    CurrentRecommendationRequest,
    CurrentScenario,
    CurrentScenarioComparison,
    ProjectedMarketScenarioSet,
    future_period,
    project_consumption,
    project_market_data,
)
from .errors import CoreContractError, CoreErrorCode, CoreIntegrationError
from .manifest import (
    CORE_CAPABILITIES,
    CORE_CONTRACT_VERSION,
    CORE_DISTRIBUTION,
    CORE_IMPORT_PACKAGE,
    CORE_MANIFEST,
    CORE_SCHEMA_IDS,
    CoreCapability,
    CoreManifest,
    CoreSchemaId,
)
from .models import HistoricalPortalComparisonRequest, HistoricalRecommendationRequest
from .serialization import IntegrationPayload, dump_envelope, load_envelope, supported_schema_ids
from .service import (
    DEFAULT_PERCENTAGE_ROUNDING_POLICY,
    DEFAULT_ROUNDING_POLICY,
    CurrentDomesticEnergyService,
    HistoricalDomesticEnergyService,
)

__all__ = [
    "CORE_CAPABILITIES",
    "CORE_CONTRACT_VERSION",
    "CORE_DISTRIBUTION",
    "CORE_IMPORT_PACKAGE",
    "CORE_MANIFEST",
    "CORE_SCHEMA_IDS",
    "DEFAULT_PERCENTAGE_ROUNDING_POLICY",
    "DEFAULT_ROUNDING_POLICY",
    "ConsumptionProfile",
    "Contract",
    "CoreCapability",
    "CoreContractError",
    "CoreErrorCode",
    "CoreIntegrationError",
    "CoreManifest",
    "CoreSchemaId",
    "CurrentCatalogSnapshot",
    "CurrentDomesticEnergyService",
    "CurrentPortalComparisonRequest",
    "CurrentPortalComparisonResult",
    "CurrentRecommendationRequest",
    "CurrentScenario",
    "CurrentScenarioComparison",
    "HistoricalDomesticEnergyService",
    "HistoricalPortalComparisonRequest",
    "HistoricalRecommendationRequest",
    "IntegrationPayload",
    "PortalComparisonResult",
    "ProjectedMarketScenarioSet",
    "Recommendation",
    "RecommendationPreferences",
    "SupplyPoint",
    "VerifiedMarketData",
    "dump_envelope",
    "future_period",
    "load_envelope",
    "project_consumption",
    "project_market_data",
    "supported_schema_ids",
]
