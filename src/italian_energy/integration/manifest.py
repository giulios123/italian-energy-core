"""Runtime manifest for the Core-Platform integration contract."""

from __future__ import annotations

from enum import StrEnum
from importlib.metadata import PackageNotFoundError, version

from pydantic import Field

from italian_energy.domain.base import DomainModel

CORE_CONTRACT_VERSION = "1"
CORE_DISTRIBUTION = "italian-energy"
CORE_IMPORT_PACKAGE = "italian_energy"


class CoreCapability(StrEnum):
    """Capabilities guaranteed by this integration contract."""

    CAPABILITY_MANIFEST = "capability_manifest"
    CANONICAL_MODELS = "canonical_models"
    CANONICAL_SERIALIZATION = "canonical_serialization"
    FIXED_PRICING = "fixed_pricing"
    INDEXED_PRICING = "indexed_pricing"
    REGULATORY_BILLING = "regulatory_billing"
    BILLING_COVERAGE = "billing_coverage"
    COMPARISON = "comparison"
    PORTAL_OFFERS_IMPORT = "portal_offers_import"
    HISTORICAL_PORTAL_COMPARISON = "historical_portal_comparison"
    CURRENT_PORTAL_COMPARISON = "current_portal_comparison"
    DETERMINISTIC_RECOMMENDATION = "deterministic_recommendation"


class CoreSchemaId(StrEnum):
    """Versioned aggregate payload identifiers."""

    SUPPLY_POINT = "italian-energy/supply-point/v1"
    CONTRACT = "italian-energy/contract/v1"
    CONSUMPTION_PROFILE = "italian-energy/consumption-profile/v1"
    VERIFIED_MARKET_DATA = "italian-energy/verified-market-data/v1"
    HISTORICAL_PORTAL_COMPARISON_REQUEST = "italian-energy/historical-portal-comparison-request/v1"
    PORTAL_COMPARISON_RESULT = "italian-energy/portal-comparison-result/v1"
    RECOMMENDATION_PREFERENCES = "italian-energy/recommendation-preferences/v1"
    HISTORICAL_RECOMMENDATION_REQUEST = "italian-energy/historical-recommendation-request/v1"
    RECOMMENDATION = "italian-energy/recommendation/v1"
    CURRENT_CATALOG_SNAPSHOT = "italian-energy/current-catalog-snapshot/v1"
    PROJECTED_MARKET_SCENARIO_SET = "italian-energy/projected-market-scenario-set/v1"
    CURRENT_PORTAL_COMPARISON_REQUEST = "italian-energy/current-portal-comparison-request/v1"
    CURRENT_PORTAL_COMPARISON_RESULT = "italian-energy/current-portal-comparison-result/v1"
    CURRENT_RECOMMENDATION_REQUEST = "italian-energy/current-recommendation-request/v1"


class CoreManifest(DomainModel):
    """Immutable metadata discoverable without invoking economic operations."""

    contract_version: str = Field(min_length=1)
    distribution: str = Field(min_length=1)
    import_package: str = Field(min_length=1)
    package_version: str = Field(min_length=1)
    capabilities: tuple[CoreCapability, ...]
    schema_ids: tuple[CoreSchemaId, ...]


def _package_version() -> str:
    try:
        return version(CORE_DISTRIBUTION)
    except PackageNotFoundError:
        return "0+unknown"


_CAPABILITIES = tuple(sorted(CoreCapability, key=lambda item: item.value))
_SCHEMA_IDS = tuple(sorted(CoreSchemaId, key=lambda item: item.value))

CORE_MANIFEST = CoreManifest(
    contract_version=CORE_CONTRACT_VERSION,
    distribution=CORE_DISTRIBUTION,
    import_package=CORE_IMPORT_PACKAGE,
    package_version=_package_version(),
    capabilities=_CAPABILITIES,
    schema_ids=_SCHEMA_IDS,
)
CORE_CAPABILITIES = tuple(item.value for item in CORE_MANIFEST.capabilities)
CORE_SCHEMA_IDS = tuple(item.value for item in CORE_MANIFEST.schema_ids)
