"""Stable typed and JSON integration contract for application consumers."""

from italian_energy.arera.rollover_coverage import (
    RegulatoryAnchorCoverageEvidence,
    RegulatoryCandidateCoverageResult,
    RegulatoryManualReview,
)
from italian_energy.arera.rollover_models import RegulatoryEffect, RegulatoryRolloverReason
from italian_energy.arera.rollover_repository import regulatory_candidate_semantic_digest
from italian_energy.domain.consumption import ConsumptionProfile
from italian_energy.domain.offer import Contract
from italian_energy.domain.supply import SupplyPoint
from italian_energy.portal_offers.models import PortalComparisonResult, VerifiedMarketData
from italian_energy.recommendation import Recommendation, RecommendationPreferences

from .current import (
    CurrentCatalogSnapshot,
    CurrentPortalComparisonRequest,
    CurrentPortalComparisonResult,
    CurrentPreflightResult,
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
from .projected import (
    GmeDefinitionCheck,
    ProjectedComparisonAssumptions,
    ProjectedDomesticComparisonRequest,
    ProjectedDomesticComparisonResult,
    ProjectedDomesticPreflightResult,
    ProjectedDomesticRecommendationRequest,
    ProjectedDomesticRecommendationResult,
    ProjectedScenarioComparison,
    ProjectedSourceBundle,
    ProjectedSourcePreflightResult,
    ProjectedVerifiedInputs,
    RegulatoryActFinding,
    RegulatoryAnchorRefreshResult,
    RegulatoryCoverageEvidence,
    RegulatoryRegistryReview,
    RegulatorySourceDigestCheck,
    projection_anchor_digest,
)
from .projected_service import ProjectedDomesticEnergyService
from .regulatory_rollover_service import (
    RegulatoryRolloverAction,
    RegulatoryRolloverReport,
    RegulatoryRolloverService,
    RegulatoryRolloverSourcePort,
    RegulatorySourcePreflightResult,
    create_official_regulatory_service,
)
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
    "CurrentPreflightResult",
    "CurrentRecommendationRequest",
    "CurrentScenario",
    "CurrentScenarioComparison",
    "GmeDefinitionCheck",
    "HistoricalDomesticEnergyService",
    "HistoricalPortalComparisonRequest",
    "HistoricalRecommendationRequest",
    "IntegrationPayload",
    "PortalComparisonResult",
    "ProjectedComparisonAssumptions",
    "ProjectedDomesticComparisonRequest",
    "ProjectedDomesticComparisonResult",
    "ProjectedDomesticEnergyService",
    "ProjectedDomesticPreflightResult",
    "ProjectedDomesticRecommendationRequest",
    "ProjectedDomesticRecommendationResult",
    "ProjectedMarketScenarioSet",
    "ProjectedScenarioComparison",
    "ProjectedSourceBundle",
    "ProjectedSourcePreflightResult",
    "ProjectedVerifiedInputs",
    "Recommendation",
    "RecommendationPreferences",
    "RegulatoryActFinding",
    "RegulatoryAnchorCoverageEvidence",
    "RegulatoryAnchorRefreshResult",
    "RegulatoryCandidateCoverageResult",
    "RegulatoryCoverageEvidence",
    "RegulatoryEffect",
    "RegulatoryManualReview",
    "RegulatoryRegistryReview",
    "RegulatoryRolloverAction",
    "RegulatoryRolloverReason",
    "RegulatoryRolloverReport",
    "RegulatoryRolloverService",
    "RegulatoryRolloverSourcePort",
    "RegulatorySourceDigestCheck",
    "RegulatorySourcePreflightResult",
    "SupplyPoint",
    "VerifiedMarketData",
    "create_official_regulatory_service",
    "dump_envelope",
    "future_period",
    "load_envelope",
    "project_consumption",
    "project_market_data",
    "projection_anchor_digest",
    "regulatory_candidate_semantic_digest",
    "supported_schema_ids",
]
