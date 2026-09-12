"""Immutable models returned by the ARERA source importer."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Any

from pydantic import ConfigDict, Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.money import UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import BillingCategory, BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod


class AreraCustomerSegment(StrEnum):
    """Customer segment named by the source workbook."""

    RESIDENT = "residenza_anagrafica"
    NON_RESIDENT = "diversa_da_residenza_anagrafica"


class AreraChargeRole(StrEnum):
    """Whether a value is a source component or a published total."""

    ATOMIC = "atomic"
    TOTAL = "total"


class AreraDiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class AreraHeader(DomainModel):
    """HTTP header preserved with a raw snapshot."""

    name: str = Field(min_length=1)
    value: str


class AreraSourceLocator(DomainModel):
    """Human-auditable location of a value in the source workbook."""

    sheet: str = Field(min_length=1)
    cell: str = Field(min_length=2, pattern=r"^[A-Za-z]{1,3}[1-9][0-9]*$")
    label: str = Field(min_length=1)
    number_format: str | None = None


class AreraDiagnostic(DomainModel):
    """Deterministic parser diagnostic."""

    severity: AreraDiagnosticSeverity
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    sheet: str | None = None
    cell: str | None = None


class RawAreraSnapshot(DomainModel):
    """The exact immutable bytes and acquisition metadata of a source file."""

    content: bytes = Field(repr=False)
    source_url: str | None = None
    retrieved_at: datetime
    content_type: str = Field(min_length=1)
    headers: tuple[AreraHeader, ...] = ()
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=True,
        ser_json_bytes="base64",
    )

    @field_validator("content", mode="before")
    @classmethod
    def validate_content(cls, value: Any) -> bytes:
        if not isinstance(value, bytes):
            raise TypeError("raw snapshot content must be bytes")
        return value

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_digest(self) -> RawAreraSnapshot:
        expected = sha256(self.content).hexdigest()
        if self.sha256 != expected:
            raise ValueError("raw snapshot sha256 does not match content")
        return self

    @property
    def snapshot_id(self) -> str:
        return f"arera-snapshot:{self.sha256}"


class AreraChargeValue(DomainModel):
    """One source-faithful rate, retaining its applicability and location."""

    code: str = Field(min_length=1)
    segment: AreraCustomerSegment
    component_code: str = Field(min_length=1)
    category: BillingCategory
    quota: BillingQuota
    rate: UnitRate
    validity: DatePeriod
    role: AreraChargeRole
    source: AreraSourceLocator
    status: VerificationStatus
    provenance: tuple[Provenance, ...] = ()

    @field_validator("rate", mode="before")
    @classmethod
    def validate_rate(cls, value: Any) -> UnitRate:
        if isinstance(value, UnitRate):
            return value
        if not isinstance(value, dict):
            raise TypeError("ARERA rate must be a UnitRate or mapping")
        return UnitRate.model_validate(value)


class AreraRegulatoryBundle(DomainModel):
    """Normalised ARERA values, deliberately distinct from a billing ruleset."""

    bundle_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    validity: DatePeriod
    charges: tuple[AreraChargeValue, ...]
    status: VerificationStatus
    provenance: tuple[Provenance, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_charges(self) -> AreraRegulatoryBundle:
        if not self.charges:
            raise ValueError("ARERA bundle requires charges")
        codes = [charge.code for charge in self.charges]
        if len(codes) != len(set(codes)):
            raise ValueError("ARERA charge codes must be unique")
        for charge in self.charges:
            if charge.status != self.status:
                raise ValueError("ARERA charge status must match bundle status")
            if (
                charge.validity.start < self.validity.start
                or charge.validity.end > self.validity.end
            ):
                raise ValueError("ARERA charge validity must be inside bundle validity")
        return self

    @property
    def is_billing_ruleset(self) -> bool:
        """Make the non-executable nature explicit to API consumers."""

        return False


class AreraImportResult(DomainModel):
    """Raw snapshot plus a verified, unverified, or review-required outcome."""

    snapshot: RawAreraSnapshot
    status: VerificationStatus
    bundle: AreraRegulatoryBundle | None = None
    diagnostics: tuple[AreraDiagnostic, ...] = ()

    @model_validator(mode="after")
    def validate_bundle_status(self) -> AreraImportResult:
        if self.bundle is not None and self.bundle.status != self.status:
            raise ValueError("ARERA result and bundle status must match")
        if self.status == VerificationStatus.REVIEW_REQUIRED and self.bundle is not None:
            raise ValueError("review-required result cannot contain a bundle")
        return self


def make_provenance(snapshot: RawAreraSnapshot, period: DatePeriod) -> Provenance:
    """Create the source provenance shared by all values in one snapshot."""

    return Provenance(
        source="ARERA",
        source_identifier="Corrispettivi_libero_elettrico_domestico_2026.xlsx",
        retrieved_at=snapshot.retrieved_at,
        effective_period=period,
        dataset_version="2026",
        sha256=snapshot.sha256,
        url=snapshot.source_url,
    )
