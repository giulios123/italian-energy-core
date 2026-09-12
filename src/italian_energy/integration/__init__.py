"""Stable typed and JSON integration contract for application consumers."""

from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.offer import Contract
from italian_energy.domain.supply import SupplyPoint
from italian_energy.portal_offers.models import PortalComparisonResult, VerifiedMarketData
from italian_energy.recommendation import Recommendation, RecommendationPreferences

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
    "HistoricalDomesticEnergyService",
    "HistoricalPortalComparisonRequest",
    "HistoricalRecommendationRequest",
    "IntegrationPayload",
    "PortalComparisonResult",
    "Recommendation",
    "RecommendationPreferences",
    "SupplyPoint",
    "VerifiedMarketData",
    "dump_envelope",
    "load_envelope",
    "supported_schema_ids",
]
