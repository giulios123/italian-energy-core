"""Deterministic domain core for Italian electricity offers."""

from italian_energy.billing import BillingError, BillingRequest, RegulatoryBillingEngine
from italian_energy.comparison import (
    ComparisonContext,
    ComparisonError,
    ComparisonRequest,
    ComparisonResult,
    DeterministicComparisonEngine,
)
from italian_energy.domain.money import (
    Currency,
    EnergyQuantity,
    Money,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.tariff import FixedTariff, IndexedTariff, Tariff
from italian_energy.integration import (
    CORE_CAPABILITIES,
    CORE_CONTRACT_VERSION,
    CORE_MANIFEST,
    CORE_SCHEMA_IDS,
    CurrentCatalogSnapshot,
    CurrentDomesticEnergyService,
    CurrentPortalComparisonRequest,
    CurrentPortalComparisonResult,
    CurrentRecommendationRequest,
    CurrentScenario,
    ProjectedMarketScenarioSet,
)
from italian_energy.portal_offers import (
    PortalComparisonRequest,
    PortalComparisonResult,
    PortalComparisonService,
    PortalOffersImporter,
    PortalRecommendationAdapter,
)
from italian_energy.pricing import FixedPricingEngine, FixedPricingError
from italian_energy.recommendation import (
    DeterministicRecommendationEngine,
    Recommendation,
    RecommendationError,
    RecommendationPreferences,
    RecommendationRequest,
)

__version__ = CORE_MANIFEST.package_version

__all__ = [
    "CORE_CAPABILITIES",
    "CORE_CONTRACT_VERSION",
    "CORE_MANIFEST",
    "CORE_SCHEMA_IDS",
    "BillingError",
    "BillingRequest",
    "ComparisonContext",
    "ComparisonError",
    "ComparisonRequest",
    "ComparisonResult",
    "Currency",
    "CurrentCatalogSnapshot",
    "CurrentDomesticEnergyService",
    "CurrentPortalComparisonRequest",
    "CurrentPortalComparisonResult",
    "CurrentRecommendationRequest",
    "CurrentScenario",
    "DeterministicComparisonEngine",
    "DeterministicRecommendationEngine",
    "EnergyQuantity",
    "FixedPricingEngine",
    "FixedPricingError",
    "FixedTariff",
    "IndexedTariff",
    "Money",
    "PortalComparisonRequest",
    "PortalComparisonResult",
    "PortalComparisonService",
    "PortalOffersImporter",
    "PortalRecommendationAdapter",
    "Power",
    "ProjectedMarketScenarioSet",
    "RateUnit",
    "Recommendation",
    "RecommendationError",
    "RecommendationPreferences",
    "RecommendationRequest",
    "RegulatoryBillingEngine",
    "RoundingMode",
    "RoundingPolicy",
    "Tariff",
    "UnitRate",
    "__version__",
]
