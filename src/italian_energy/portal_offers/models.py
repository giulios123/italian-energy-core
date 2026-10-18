"""Immutable source and application models for the Portale Offerte importer."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.comparison.engine import ComparisonContext, ComparisonResult
from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import RateUnit, UnitRate
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


PORTAL_CDISPD_PROJECTION_MAPPING_VERSION: Literal["portale-regole-4.2-cdispd-v1"] = (
    "portale-regole-4.2-cdispd-v1"
)
_PORTAL_BASE_URL = "https://www.ilportaleofferte.it"


def market_free_parameters_url(dataset_date: date) -> str:
    stamp = dataset_date.strftime("%Y%m%d")
    folder = f"{dataset_date.year}_{dataset_date.month}"
    return (
        f"{_PORTAL_BASE_URL}/portaleOfferte/resources/opendata/csv/parametriML/{folder}/"
        f"PO_Parametri_Mercato_Libero_E_{stamp}.csv"
    )


class PortalOfferType(StrEnum):
    FIXED = "fixed"
    INDEXED = "indexed"
    UNSUPPORTED = "unsupported"


class PortalComponentSemantic(StrEnum):
    ENERGY_PRICE = "energy_price"
    COMMERCIAL_CHARGE = "commercial_charge"
    DISPATCHING = "dispatching"
    CAPACITY_MARKET = "capacity_market"
    DISPATCHING_CAPACITY_AGGREGATE = "dispatching_capacity_aggregate"
    SELLER_DEFINED_DISPATCHING = "seller_defined_dispatching"
    REGULATED_FIXED_DISPATCHING = "regulated_fixed_dispatching"
    SAFEGUARD_REINTEGRATION = "safeguard_reintegration"
    GRADUAL_PROTECTION_REINTEGRATION = "gradual_protection_reintegration"
    UNSUPPORTED = "unsupported"


class PortalPricingTreatment(StrEnum):
    TARIFF_ADDITION = "tariff_addition"
    REGULATORY_REFERENCE = "regulatory_reference"
    UNSUPPORTED = "unsupported"


class PortalLossTreatment(StrEnum):
    INCLUDED = "included"
    EXCLUDED = "excluded"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


PORTAL_DISPATCHING_MAPPING_VERSION = "portale-dispacciamento-v1"
PORTAL_ECONOMIC_VALIDITY_VERSION: Literal["portale-regole-4.2-economic-validity-v2"] = (
    "portale-regole-4.2-economic-validity-v2"
)


class PortalOfferExclusionCode(StrEnum):
    UNSUPPORTED_COMMODITY = "unsupported_commodity"
    UNSUPPORTED_OFFER_TYPE = "unsupported_offer_type"
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
    UNSUPPORTED_COMMERCIAL_COMPONENT = "unsupported_commercial_component"
    MISSING_COMMERCIAL_COMPONENT = "missing_commercial_component"
    AMBIGUOUS_COMPONENT_COMPOSITION = "ambiguous_component_composition"
    ECONOMIC_TERMS_UNVERIFIED = "economic_terms_unverified"
    ECONOMIC_PERIOD_NOT_REPRESENTABLE = "economic_period_not_representable"


class PortalPriceValidityKind(StrEnum):
    DEFAULT = "default"
    DURATION = "duration"
    VALID_UNTIL = "valid_until"
    MONTH = "month"
    UNSUPPORTED = "unsupported"


class PortalEconomicTermsBasis(StrEnum):
    DECLARED_ECONOMIC_CONDITIONS = "declared_economic_conditions"
    EXPLICIT_COMPONENT_VALIDITY = "explicit_component_validity"
    PUBLISHED_DEFAULT_PRICES = "published_default_prices"
    UNKNOWN = "unknown"


class PortalEconomicDurationScope(StrEnum):
    SELLER_CONDITIONS = "seller_conditions"
    ENERGY_PRICE = "energy_price"


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


class PortalCdispDParameterSnapshot(DomainModel):
    """One official daily Portale Offerte CdispD parameter row."""

    dataset_date: date
    parameter_name: Literal["cdispd"] = "cdispd"
    rate: UnitRate
    description: str = Field(min_length=1)
    status: Literal[VerificationStatus.VERIFIED] = VerificationStatus.VERIFIED
    provenance: tuple[Provenance, ...]

    @model_validator(mode="after")
    def validate_parameter(self) -> PortalCdispDParameterSnapshot:
        if self.rate.unit != RateUnit.EUR_PER_KWH or self.rate.amount < 0:
            raise ValueError("official CdispD parameter must be a non-negative EUR/kWh rate")
        if len(self.provenance) != 1:
            raise ValueError("CdispD parameter requires exactly one source row")
        source = self.provenance[0]
        if (
            source.source != "portale_offerte"
            or source.source_identifier
            != f"PO_Parametri_Mercato_Libero_E_{self.dataset_date:%Y%m%d}.csv"
            or source.url != market_free_parameters_url(self.dataset_date)
            or source.sha256 is None
            or source.locator is None
            or source.locator.document != PortalSourceRole.MARKET_FREE_PARAMETERS.value
            or source.locator.section is None
            or not source.locator.section.startswith("row:")
            or source.effective_period is not None
        ):
            raise ValueError("CdispD provenance must identify the exact daily parameter row")
        return self


class PortalOffersSnapshot(DomainModel):
    dataset_date: date
    files: tuple[PortalFileSnapshot, ...]
    snapshot_id: str = Field(pattern=r"^portal-snapshot:[0-9a-f]{64}$")
    status: VerificationStatus
    parser_version: str = Field(min_length=1)
    cdispd_parameter: PortalCdispDParameterSnapshot | None = None

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
        if self.cdispd_parameter is not None:
            parameter_files = tuple(
                item for item in self.files if item.role == PortalSourceRole.MARKET_FREE_PARAMETERS
            )
            if len(parameter_files) != 1:
                raise ValueError("CdispD parameter requires one market-free parameter file")
            file = parameter_files[0]
            source = self.cdispd_parameter.provenance[0]
            if (
                self.status != VerificationStatus.VERIFIED
                or self.cdispd_parameter.status != VerificationStatus.VERIFIED
                or self.cdispd_parameter.dataset_date != self.dataset_date
                or file.status != VerificationStatus.VERIFIED
                or file.dataset_date != self.dataset_date
                or file.final_url != market_free_parameters_url(self.dataset_date)
                or file.sha256 != source.sha256
                or file.final_url != source.url
                or file.retrieved_at != source.retrieved_at
            ):
                raise ValueError("CdispD parameter must match the verified daily catalog source")
        return self


class PortalCdispDProjection(DomainModel):
    """A verified current parameter applied as an explicit future estimate."""

    parameter: PortalCdispDParameterSnapshot
    catalog_snapshot_id: str = Field(pattern=r"^portal-snapshot:[0-9a-f]{64}$")
    period: DatePeriod
    policy: Literal["portal_current_parameter_constant"] = "portal_current_parameter_constant"
    mapping_version: Literal["portale-regole-4.2-cdispd-v1"] = (
        PORTAL_CDISPD_PROJECTION_MAPPING_VERSION
    )
    future_values_verified: Literal[False] = False
    costs_are_estimates: Literal[True] = True

    @model_validator(mode="after")
    def validate_projection(self) -> PortalCdispDProjection:
        if self.period.start <= self.parameter.dataset_date:
            raise ValueError("CdispD projection period must follow the source observation date")
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
    residential: bool | None = None
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


class PortalComponentPriceValidity(DomainModel):
    """A structurally parsed component-price validity declaration."""

    kind: PortalPriceValidityKind
    duration_months: int | None = Field(default=None, ge=1)
    month: date | None = None
    raw_fields: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def validate_shape(self) -> PortalComponentPriceValidity:
        if self.kind == PortalPriceValidityKind.DURATION:
            if self.duration_months is None or self.month is not None:
                raise ValueError("duration validity requires only a positive month count")
        elif self.kind in {
            PortalPriceValidityKind.VALID_UNTIL,
            PortalPriceValidityKind.MONTH,
        }:
            if self.month is None or self.duration_months is not None or self.month.day != 1:
                raise ValueError("calendar validity requires the first day of its month")
        elif self.duration_months is not None or self.month is not None:
            raise ValueError("default and unsupported validity cannot carry parsed bounds")
        return self


class PortalEconomicTerms(DomainModel):
    """Coverage and duration evidence used for a projected annual estimate."""

    activation_date: date
    estimate_period: DatePeriod
    known_duration_months: int | None = Field(default=None, ge=1)
    duration_scope: PortalEconomicDurationScope | None = None
    extends_beyond_12_months: bool | None = None
    basis: PortalEconomicTermsBasis
    provenance: tuple[Provenance, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> PortalEconomicTerms:
        if self.estimate_period.start != self.activation_date:
            raise ValueError("economic estimate must start on its activation date")
        if self.known_duration_months is None and self.extends_beyond_12_months is True:
            raise ValueError("extension beyond twelve months requires a known duration")
        if self.known_duration_months is not None:
            expected = self.known_duration_months > 12
            if self.extends_beyond_12_months is not expected:
                raise ValueError("extension flag must match the proven duration")
            if self.duration_scope is None or not self.provenance:
                raise ValueError("proven duration requires a scope and source provenance")
        return self


class PortalEconomicComponent(DomainModel):
    code: str = Field(min_length=1)
    description: str = Field(min_length=1)
    amount: Decimal | None = None
    unit: str | None = Field(default=None, min_length=1)
    band: str | None = None
    macroarea: str | None = None
    index_code: str | None = None
    coefficient: Decimal | None = None
    discount: bool = False
    locator: ProvenanceLocator | None = None
    source_code: str | None = Field(default=None, min_length=1)
    semantic: PortalComponentSemantic | None = None
    pricing_treatment: PortalPricingTreatment = PortalPricingTreatment.TARIFF_ADDITION
    loss_treatment: PortalLossTreatment = PortalLossTreatment.NOT_APPLICABLE
    included_semantics: tuple[PortalComponentSemantic, ...] = ()
    period: DatePeriod | None = None
    price_validity: PortalComponentPriceValidity | None = None
    mapping_version: str | None = None
    source_provenance: tuple[Provenance, ...] = ()
    source_fields: tuple[tuple[str, str], ...] = ()

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
    economic_conditions_duration_raw: str | None = None
    economic_conditions_duration_provenance: tuple[Provenance, ...] = ()
    economic_validity_version: str | None = None
    unmodeled_commercial_terms: tuple[Provenance, ...] = ()
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
    economic_terms: PortalEconomicTerms | None = None


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
    cdispd_reference_snapshot_id: str | None = None
    cdispd_reference_snapshot_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    cdispd_reference_period: DatePeriod | None = None
    cdispd_customer_segment: AreraCustomerSegment | None = None
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
        if (self.cdispd_reference_snapshot_id is None) != (
            self.cdispd_reference_snapshot_digest is None
        ):
            raise ValueError("CdispD source snapshot id and digest must be supplied together")
        if self.cdispd_customer_segment is not None and self.cdispd_reference_period is None:
            raise ValueError("CdispD customer segment requires a reference applicability period")
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
