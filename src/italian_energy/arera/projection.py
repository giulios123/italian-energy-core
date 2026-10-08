"""Verified regulatory anchor used only as an explicit future assumption."""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from importlib.resources import files
from typing import Self

from pydantic import Field, model_validator

from italian_energy.arera.composer import (
    AreraDomesticRuleSetComposer,
    DomesticFiscalPolicy,
)
from italian_energy.arera.models import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCustomerSegment,
    AreraRegulatoryBundle,
    AreraSourceLocator,
)
from italian_energy.domain.base import DomainModel
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import (
    BillingCategory,
    BillingQuota,
    RegulatoryRuleSet,
    VerificationStatus,
)
from italian_energy.domain.time import DatePeriod

_ARTIFACT = "arera-domestic-bt-projection-anchor-2026-q3.json"
_VERSIONED_ARTIFACTS = (
    _ARTIFACT,
    "arera-domestic-bt-projection-anchor-2026-q4.json",
)
ROLLOVER_ANCHOR_SCHEMA_VERSION = "014-rollover-anchor-v2"


class ProjectionAnchorSource(DomainModel):
    source_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    url: str = Field(min_length=1)
    retrieved_at: datetime
    published_at: date | None = None
    effective_period: DatePeriod | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    document: str = Field(min_length=1)


class ProjectionAnchorSourceReference(DomainModel):
    source_id: str = Field(min_length=1)
    sheet: str | None = None
    cell: str | None = None
    section: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_location(self) -> Self:
        if (self.sheet is None) != (self.cell is None):
            raise ValueError("projection source sheet and cell must be supplied together")
        return self


class ProjectionAnchorCharge(DomainModel):
    code: str = Field(min_length=1)
    segment: AreraCustomerSegment
    component_code: str = Field(min_length=1)
    category: BillingCategory
    quota: BillingQuota
    value: Decimal
    unit: RateUnit
    references: tuple[ProjectionAnchorSourceReference, ...]

    @model_validator(mode="after")
    def validate_charge(self) -> Self:
        if self.component_code not in {"network_total", "system_total"}:
            raise ValueError("projection anchor can compose only network/system totals")
        if self.category not in {BillingCategory.NETWORK, BillingCategory.SYSTEM_CHARGES}:
            raise ValueError("projection anchor charge category is incompatible")
        if not self.references:
            raise ValueError("projection anchor charge requires official source references")
        if self.value < 0:
            raise ValueError("projection anchor charge cannot be negative")
        return self


class DomesticProjectionAnchor(DomainModel):
    """Source-backed snapshot with an explicit, half-open applicability period."""

    schema_version: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    as_of: date
    validity: DatePeriod
    sources: tuple[ProjectionAnchorSource, ...]
    charges: tuple[ProjectionAnchorCharge, ...]
    excise_rate: Decimal
    excise_source_ids: tuple[str, ...]
    vat_rate_percent: Decimal
    vat_source_ids: tuple[str, ...]
    status: VerificationStatus = VerificationStatus.VERIFIED

    @model_validator(mode="after")
    def validate_anchor(self) -> Self:
        if self.schema_version == ROLLOVER_ANCHOR_SCHEMA_VERSION:
            if self.as_of >= self.validity.end:
                raise ValueError("projection anchor snapshot must precede validity end")
            for source in self.sources:
                if source.sha256 is None:
                    raise ValueError(f"rollover anchor source {source.source_id} requires a digest")
                if source.published_at is None:
                    raise ValueError(
                        f"rollover anchor source {source.source_id} requires published_at"
                    )
                if source.published_at > self.as_of:
                    raise ValueError(
                        f"projection source {source.source_id} was published after snapshot"
                    )
                if source.retrieved_at.tzinfo is None or source.retrieved_at.utcoffset() is None:
                    raise ValueError(
                        f"rollover anchor source {source.source_id} retrieved_at must be aware"
                    )
        else:
            # Keep the legacy v1 validity contract byte-for-byte and semantically stable.
            if not (self.validity.start <= self.as_of < self.validity.end):
                raise ValueError("projection anchor date is outside its verified validity")
            next_month = date(
                self.as_of.year + (self.as_of.month == 12), self.as_of.month % 12 + 1, 1
            )
            if self.validity.start != self.as_of.replace(day=1) or self.validity.end != next_month:
                raise ValueError(
                    "projection anchor validity cannot extend beyond its calendar month"
                )
        source_ids = {source.source_id for source in self.sources}
        if len(source_ids) != len(self.sources):
            raise ValueError("projection anchor source identifiers must be unique")
        used_source_ids = (
            {reference.source_id for charge in self.charges for reference in charge.references}
            | set(self.excise_source_ids)
            | set(self.vat_source_ids)
        )
        if not used_source_ids.issubset(source_ids):
            raise ValueError("projection anchor references a missing source")
        if not {"vat_dpr_633", "vat_dpr_633_art16"}.issubset(self.vat_source_ids):
            raise ValueError("projection anchor requires both VAT table and rate sources")
        digest_required = {
            "arera_575",
            "arera_588",
            "arera_227",
            "adm_20260918",
            "tua_2025",
            "tua_decree_2026",
            "vat_dpr_633",
            "vat_dpr_633_art16",
        }
        for source in self.sources:
            if source.source_id in digest_required and source.sha256 is None:
                raise ValueError(f"projection anchor source {source.source_id} requires a digest")
        if not self.charges:
            raise ValueError("projection anchor has no regulated charges")
        if self.excise_rate <= 0 or self.vat_rate_percent <= 0:
            raise ValueError("projection anchor fiscal rates must be positive")
        for segment in AreraCustomerSegment:
            segment_charges = [charge for charge in self.charges if charge.segment == segment]
            if not any(
                charge.component_code == "network_total" for charge in segment_charges
            ) or not any(charge.component_code == "system_total" for charge in segment_charges):
                raise ValueError(f"projection anchor is incomplete for {segment.value}")
        return self

    def source_provenance(
        self, references: tuple[ProjectionAnchorSourceReference, ...]
    ) -> tuple[Provenance, ...]:
        by_id = {source.source_id: source for source in self.sources}
        result: list[Provenance] = []
        for reference in references:
            source = by_id[reference.source_id]
            locator = ProvenanceLocator(
                document=source.document,
                sheet=reference.sheet,
                cell=reference.cell,
                section=reference.section,
            )
            result.append(
                Provenance(
                    source=source.source,
                    source_identifier=source.source_identifier,
                    retrieved_at=source.retrieved_at,
                    effective_period=source.effective_period,
                    dataset_version=self.schema_version,
                    sha256=source.sha256,
                    url=source.url,
                    locator=locator,
                )
            )
        return tuple(result)

    def to_bundle(self) -> AreraRegulatoryBundle:
        charges = tuple(
            AreraChargeValue(
                code=charge.code,
                segment=charge.segment,
                component_code=charge.component_code,
                category=charge.category,
                quota=charge.quota,
                rate=UnitRate(amount=charge.value, unit=charge.unit),
                validity=self.validity,
                role=AreraChargeRole.TOTAL,
                source=AreraSourceLocator(
                    sheet=charge.references[0].sheet or "source publication",
                    cell=charge.references[0].cell or "A1",
                    label=charge.references[0].section,
                ),
                status=VerificationStatus.VERIFIED,
                provenance=self.source_provenance(charge.references),
            )
            for charge in self.charges
        )
        bundle_sources = tuple(
            reference
            for source in self.sources
            for reference in (
                ProjectionAnchorSourceReference(
                    source_id=source.source_id,
                    section=source.document,
                ),
            )
        )
        return AreraRegulatoryBundle(
            bundle_id=self.anchor_id,
            schema_version=self.schema_version,
            dataset_version=self.schema_version,
            validity=self.validity,
            charges=charges,
            status=VerificationStatus.VERIFIED,
            provenance=self.source_provenance(bundle_sources),
        )

    def fiscal_policy(self) -> DomesticFiscalPolicy:
        excise_refs = tuple(
            ProjectionAnchorSourceReference(source_id=source_id, section="TUA electricity excise")
            for source_id in self.excise_source_ids
        )
        vat_sections = {
            "vat_dpr_633": "DPR 633/1972 Tabella A parte III n. 103",
            "vat_dpr_633_art16": "DPR 633/1972 art. 16: aliquota ridotta del 10% per la parte III",
        }
        vat_refs = tuple(
            ProjectionAnchorSourceReference(
                source_id=source_id,
                section=vat_sections.get(source_id, "DPR 633/1972 VAT source"),
            )
            for source_id in self.vat_source_ids
        )
        return DomesticFiscalPolicy(
            schema_version=self.schema_version,
            excise_rate=UnitRate(amount=self.excise_rate, unit=RateUnit.EUR_PER_KWH),
            excise_provenance=self.source_provenance(excise_refs),
            vat_rate=UnitRate(amount=self.vat_rate_percent, unit=RateUnit.PERCENT),
            vat_provenance=self.source_provenance(vat_refs),
            validity=self.validity,
        )


def _load_projection_anchor_artifact(artifact: str) -> DomesticProjectionAnchor:
    resource = files("italian_energy").joinpath("data", "billing", artifact)
    try:
        with resource.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return DomesticProjectionAnchor.model_validate(payload)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ValueError(f"cannot load packaged domestic projection anchor {artifact}") from exc


def load_domestic_projection_anchor(as_of: date | None = None) -> DomesticProjectionAnchor:
    """Load an immutable anchor, selecting the half-open validity window when dated.

    The no-argument form retains the historical Q3 lookup for compatibility.
    New comparison callers should pass ``as_of`` so a successor is selected
    from its validity interval instead of the date of its snapshot.
    """

    if as_of is None:
        return _load_projection_anchor_artifact(_ARTIFACT)
    anchors = tuple(_load_projection_anchor_artifact(item) for item in _VERSIONED_ARTIFACTS)
    active = tuple(
        anchor for anchor in anchors if anchor.validity.start <= as_of < anchor.validity.end
    )
    if len(active) != 1:
        raise ValueError(f"no unique packaged domestic projection anchor is valid on {as_of}")
    return active[0]


def load_domestic_projection_ruleset(
    *, residential: bool, as_of: date | None = None
) -> RegulatoryRuleSet:
    """Compose resident or non-resident rules from an anchor valid at ``as_of``."""
    anchor = load_domestic_projection_anchor(as_of)
    segment = AreraCustomerSegment.RESIDENT if residential else AreraCustomerSegment.NON_RESIDENT
    return AreraDomesticRuleSetComposer().compose(
        anchor.to_bundle(),
        segment,
        anchor.fiscal_policy(),
    )


__all__ = [
    "DomesticProjectionAnchor",
    "ProjectionAnchorCharge",
    "ProjectionAnchorSource",
    "ProjectionAnchorSourceReference",
    "load_domestic_projection_anchor",
    "load_domestic_projection_ruleset",
]
