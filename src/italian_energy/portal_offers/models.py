"""Immutable source and application models for the Portale Offerte importer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from pydantic import Field, field_validator, model_validator

from italian_energy.comparison.engine import ComparisonContext, ComparisonResult
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.market import MarketData
from italian_energy.domain.offer import Offer
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus, VoltageLevel
from italian_energy.domain.time import DatePeriod


class PortalCatalog(StrEnum):
    MARKET_FREE = "market_free"
    PLACET = "placet"


class PortalSourceRole(StrEnum):
    MARKET_FREE_OFFERS = "market_free_offers"
    MARKET_FREE_PARAMETERS = "market_free_parameters"
    PLACET_OFFERS = "placet_offers"
    PLACET_PARAMETERS = "placet_parameters"
    HISTORICAL_INDICES = "historical_indices"


class PortalAcquisitionPolicy(StrEnum):
    ON_DEMAND_EXACT = "on_demand_exact"


class PortalOfferType(StrEnum):
    FIXED = "fixed"
    INDEXED = "indexed"


class PortalOfferExclusionCode(StrEnum):
    UNSUPPORTED_COMMODITY = "unsupported_commodity"
    NOT_CURRENT = "not_current"
    PERIOD_NOT_COVERED = "period_not_covered"
    TERRITORY_NOT_COVERED = "territory_not_covered"
    CLASSIFICATION_NOT_COVERED = "classification_not_covered"
    ACTIVATION_NOT_COVERED = "activation_not_covered"
    PAYMENT_NOT_COVERED = "payment_not_covered"
    DUPLICATE_OFFER_ID = "duplicate_offer_id"
    MISSING_PROVENANCE = "missing_provenance"
    SOURCE_MALFORMED = "source_malformed"
    TARIFF_NOT_REPRESENTABLE = "tariff_not_representable"
    INDEXED_INPUT_MISSING = "indexed_input_missing"
    NOT_VERIFIED = "not_verified"
    DUAL_FUEL_REQUIRED = "dual_fuel_required"
    MANDATORY_SERVICE_REQUIRED = "mandatory_service_required"


class PortalFileSnapshot(DomainModel):
    role: PortalSourceRole
    catalog: PortalCatalog | None = None
    original_url: str = Field(min_length=1)
    final_url: str = Field(min_length=1)
    retrieved_at: datetime
    content_type: str = Field(min_length=1)
    size: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_date: date | None = None
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    content: bytes | None = Field(default=None, exclude=True, repr=False)

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_content_digest(self) -> PortalFileSnapshot:
        if self.content is not None:
            if self.size != len(self.content):
                raise ValueError("snapshot size does not match content")
            if self.sha256 != sha256(self.content).hexdigest():
                raise ValueError("snapshot digest does not match content")
        return self


class PortalOffersSnapshot(DomainModel):
    dataset_date: date
    files: tuple[PortalFileSnapshot, ...]
    snapshot_id: str = Field(pattern=r"^portal-snapshot:[0-9a-f]{64}$")
    status: VerificationStatus
    parser_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog_files(self) -> PortalOffersSnapshot:
        required = {
            PortalSourceRole.MARKET_FREE_OFFERS,
            PortalSourceRole.MARKET_FREE_PARAMETERS,
            PortalSourceRole.PLACET_OFFERS,
            PortalSourceRole.PLACET_PARAMETERS,
        }
        roles = {item.role for item in self.files}
        if roles != required or len(self.files) != len(required):
            raise ValueError("offers snapshot must contain all four electricity catalog files")
        if any(item.dataset_date not in (None, self.dataset_date) for item in self.files):
            raise ValueError("catalog file dataset dates must match snapshot date")
        if self.status == VerificationStatus.VERIFIED and any(
            item.status != VerificationStatus.VERIFIED for item in self.files
        ):
            raise ValueError("verified offers snapshot requires verified catalog files")
        return self


class PortalIndexSnapshot(DomainModel):
    file: PortalFileSnapshot
    snapshot_id: str = Field(pattern=r"^portal-index-snapshot:[0-9a-f]{64}$")
    status: VerificationStatus
    parser_version: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_role(self) -> PortalIndexSnapshot:
        if self.file.role != PortalSourceRole.HISTORICAL_INDICES:
            raise ValueError("index snapshot requires the historical indices role")
        if (
            self.status == VerificationStatus.VERIFIED
            and self.file.status != VerificationStatus.VERIFIED
        ):
            raise ValueError("verified index snapshot requires a verified file")
        return self


class PortalSnapshot(DomainModel):
    offers: PortalOffersSnapshot
    indexes: PortalIndexSnapshot | None = None


class PortalComparisonRequest(DomainModel):
    comparison: ComparisonContext
    catalogs: frozenset[PortalCatalog]
    eligibility: PortalEligibilityProfile
    acquisition_policy: PortalAcquisitionPolicy = PortalAcquisitionPolicy.ON_DEMAND_EXACT
    supplemental_market_data: VerifiedMarketData | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> PortalComparisonRequest:
        if self.catalogs != frozenset({PortalCatalog.MARKET_FREE, PortalCatalog.PLACET}):
            raise ValueError("Spec 008 requires both market_free and placet catalogues")
        if self.comparison.market_data is not None:
            raise ValueError("PortalComparisonRequest uses supplemental_market_data explicitly")
        if self.comparison.as_of != self.comparison.period.start:
            raise ValueError("Portal replay requires as_of equal to period.start")
        return self


class PortalTerritory(DomainModel):
    """Structured scenario territory; never sent as HTTP user data."""

    region_code: str = Field(pattern=r"^[0-9]{2}$")
    province_code: str = Field(pattern=r"^[0-9]{3}$")
    municipality_code: str = Field(pattern=r"^[0-9]{6}$")


class PortalEligibilityProfile(DomainModel):
    territory: PortalTerritory
    voltage_level: VoltageLevel = VoltageLevel.BT
    domestic: bool = True
    activation_method: str | None = Field(default=None, min_length=1)
    payment_method: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_scope(self) -> PortalEligibilityProfile:
        if not self.domestic:
            raise ValueError("Spec 008 only supports domestic offers")
        if self.voltage_level != VoltageLevel.BT:
            raise ValueError("Spec 008 only supports BT offers")
        return self


class VerifiedMarketData(DomainModel):
    data: MarketData
    status: VerificationStatus
    provenance: tuple[Provenance, ...]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_verified(self) -> VerifiedMarketData:
        if self.status != VerificationStatus.VERIFIED:
            raise ValueError("supplemental market data must be verified")
        if not self.provenance:
            raise ValueError("supplemental market data requires provenance")
        return self


class PortalEconomicComponent(DomainModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: Decimal
    unit: str = Field(min_length=1)
    band: str | None = None
    macroarea: str | None = None
    index_code: str | None = None
    coefficient: Decimal | None = None
    discount: bool = False
    locator: ProvenanceLocator | None = None

    @field_validator("amount", "coefficient", mode="before")
    @classmethod
    def validate_decimal(cls, value: object) -> Decimal | None:
        return None if value is None else strict_decimal(value)


class PortalOfferRecord(DomainModel):
    catalog: PortalCatalog
    source_offer_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    offer_type: PortalOfferType
    subscription_period: DatePeriod
    tariff_validity: DatePeriod
    duration_months: int | None = Field(default=None, ge=1)
    customer_type: str = Field(min_length=1)
    activation_methods: tuple[str, ...] = ()
    payment_methods: tuple[str, ...] = ()
    region_codes: tuple[str, ...] = ()
    province_codes: tuple[str, ...] = ()
    municipality_codes: tuple[str, ...] = ()
    index_code: str | None = None
    index_codes: tuple[str, ...] = ()
    index_granularity: str | None = None
    components: tuple[PortalEconomicComponent, ...] = ()
    conditions: tuple[str, ...] = ()
    annual_estimate: Decimal | None = None
    source_provenance: tuple[Provenance, ...] = ()
    raw_fields: tuple[tuple[str, str], ...] = ()

    @field_validator("annual_estimate", mode="before")
    @classmethod
    def validate_annual_estimate(cls, value: object) -> Decimal | None:
        return None if value is None else strict_decimal(value)


class NormalizedPortalOffer(DomainModel):
    offer: Offer
    source_record: PortalOfferRecord
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class PortalOfferExclusion(DomainModel):
    offer_id: str = Field(min_length=1)
    code: PortalOfferExclusionCode
    detail: str = Field(min_length=1)
    locator: ProvenanceLocator | None = None


class PortalOffersImportResult(DomainModel):
    snapshot: PortalOffersSnapshot
    index_snapshot: PortalIndexSnapshot | None = None
    status: VerificationStatus
    import_id: str = Field(pattern=r"^portal-import:[0-9a-f]{64}$")
    records: tuple[PortalOfferRecord, ...] = ()
    normalized: tuple[NormalizedPortalOffer, ...] = ()
    eligible_offers: tuple[Offer, ...] = ()
    exclusions: tuple[PortalOfferExclusion, ...] = ()
    diagnostics: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    received_count: int = Field(ge=0)
    eligible_count: int = Field(ge=0)
    excluded_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> PortalOffersImportResult:
        if self.received_count != self.eligible_count + self.excluded_count:
            raise ValueError("portal import counts must account for every record")
        if self.eligible_count != len(self.eligible_offers):
            raise ValueError("eligible count does not match eligible offers")
        if self.excluded_count != len(self.exclusions):
            raise ValueError("excluded count does not match exclusions")
        return self


class PortalComparisonResult(DomainModel):
    portal_result_id: str = Field(pattern=r"^portal-comparison:[0-9a-f]{64}$")
    import_result: PortalOffersImportResult
    comparison_result: ComparisonResult

    @property
    def portal_comparison_id(self) -> str:
        """Backward-compatible name for early local callers."""
        return self.portal_result_id


PortalComparisonRequest.model_rebuild()
