"""Verified, immutable ARERA reference snapshot for aggregate Portal CdispD."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from hashlib import sha256
from typing import TYPE_CHECKING, Protocol, Self
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.money import RateUnit
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import BillingCategory, BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod

from .importer import ARERA_DOMESTIC_2026_URL
from .models import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCustomerSegment,
    AreraImportResult,
)

if TYPE_CHECKING:
    pass


class AreraImportSource(Protocol):
    def fetch_and_import(self) -> AreraImportResult:
        """Acquire and verify one official ARERA workbook snapshot."""


def _add_months(value: date, count: int) -> date:
    absolute = value.year * 12 + value.month - 1 + count
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)


def _month_periods(period: DatePeriod) -> tuple[DatePeriod, ...]:
    """Return every complete calendar month touched by a half-open period."""
    first = date(period.start.year, period.start.month, 1)
    exclusive_end = period.end
    if exclusive_end.day != 1:
        exclusive_end = _add_months(date(exclusive_end.year, exclusive_end.month, 1), 1)
    result: list[DatePeriod] = []
    current = first
    while current < exclusive_end:
        following = _add_months(current, 1)
        result.append(DatePeriod(start=current, end=following))
        current = following
    return tuple(result)


def _canonical_snapshot_id(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return f"cdispd-reference-snapshot:{sha256(encoded).hexdigest()}"


class CdispDReferenceSnapshot(DomainModel):
    """Canonical verified rows with explicit source and monthly applicability."""

    snapshot_id: str = Field(pattern=r"^cdispd-reference-snapshot:[0-9a-f]{64}$")
    source_snapshot_id: str = Field(pattern=r"^arera-snapshot:[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_bundle_id: str = Field(pattern=r"^arera-bundle:[0-9a-f]{64}$")
    bundle_schema_version: str = Field(min_length=1)
    dataset_version: str = Field(min_length=1)
    validity: DatePeriod
    status: VerificationStatus
    charges: tuple[AreraChargeValue, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.status != VerificationStatus.VERIFIED:
            raise ValueError("CdispD reference snapshot must be verified")
        if self.source_snapshot_id != f"arera-snapshot:{self.source_digest}":
            raise ValueError("CdispD source snapshot digest does not match")
        if self.source_bundle_id != f"arera-bundle:{self.source_digest}":
            raise ValueError("CdispD source bundle digest does not match")
        if self.bundle_schema_version != "005-domestic-electricity-2026-v1":
            raise ValueError("unsupported ARERA CdispD bundle schema version")
        if self.dataset_version != "2026":
            raise ValueError("unsupported ARERA CdispD dataset version")
        if self.validity.start.day != 1 or self.validity.end.day != 1:
            raise ValueError("CdispD bundle validity must use complete calendar months")
        expected_months = _month_periods(self.validity)
        if not expected_months:
            raise ValueError("CdispD bundle validity cannot be empty")
        seen_codes: set[str] = set()
        counts: Counter[tuple[AreraCustomerSegment, date]] = Counter()
        for charge in self.charges:
            if charge.code in seen_codes:
                raise ValueError("CdispD source charge codes must be unique")
            seen_codes.add(charge.code)
            if (
                charge.component_code != "CDISPD"
                or charge.category != BillingCategory.SALES
                or charge.quota != BillingQuota.CONSUMPTION
                or charge.role != AreraChargeRole.ATOMIC
            ):
                raise ValueError("CdispD snapshot may contain only atomic sales consumption rows")
            if charge.status != VerificationStatus.VERIFIED:
                raise ValueError("CdispD source charge must be verified")
            if charge.rate.unit != RateUnit.EUR_PER_KWH or charge.rate.amount <= 0:
                raise ValueError("CdispD source rate must be a positive EUR/kWh charge")
            if charge.validity not in expected_months:
                raise ValueError("CdispD charge must cover one complete month in bundle validity")
            if not charge.provenance:
                raise ValueError("CdispD charge requires source provenance")
            locator = ProvenanceLocator(sheet=charge.source.sheet, cell=charge.source.cell)
            for item in charge.provenance:
                parsed_url = urlsplit(item.url or "")
                if (
                    item.source != "ARERA"
                    or item.sha256 != self.source_digest
                    or item.effective_period != charge.validity
                    or item.url != ARERA_DOMESTIC_2026_URL
                    or parsed_url.scheme != "https"
                    or parsed_url.hostname != "www.arera.it"
                    or item.locator != locator
                ):
                    raise ValueError("CdispD provenance must identify the verified ARERA row")
            counts[(charge.segment, charge.validity.start)] += 1
        expected = {
            (segment, month.start) for segment in AreraCustomerSegment for month in expected_months
        }
        if set(counts) != expected or any(count != 1 for count in counts.values()):
            raise ValueError("CdispD snapshot requires both customer segments for every month")
        payload = self.model_dump(mode="json")
        payload.pop("snapshot_id")
        if self.snapshot_id != _canonical_snapshot_id(payload):
            raise ValueError("CdispD reference snapshot id does not match its contents")
        return self

    @property
    def digest(self) -> str:
        """Return the canonical digest of this normalized reference snapshot."""
        return self.snapshot_id.partition(":")[2]

    def covers(self, segment: AreraCustomerSegment, period: DatePeriod) -> bool:
        """Whether every month touched by a period has one verified segment row."""
        months = _month_periods(period)
        return bool(months) and all(
            self.validity.start <= month.start
            and month.end <= self.validity.end
            and sum(
                charge.segment == segment and charge.validity == month for charge in self.charges
            )
            == 1
            for month in months
        )

    def charges_for_period(
        self, segment: AreraCustomerSegment, period: DatePeriod
    ) -> tuple[AreraChargeValue, ...]:
        """Return exact monthly rows, raising instead of carrying rates forward."""
        if not self.covers(segment, period):
            raise ValueError("CdispD reference does not cover every month in the requested period")
        months = set(_month_periods(period))
        return tuple(
            charge
            for charge in self.charges
            if charge.segment == segment and charge.validity in months
        )

    def to_envelope(self) -> bytes:
        """Serialize using Core's canonical registered integration envelope."""
        from italian_energy.integration.serialization import dump_envelope

        return dump_envelope(self)

    @classmethod
    def from_envelope(cls, data: bytes | str) -> CdispDReferenceSnapshot:
        """Deserialize a registered Core integration envelope as this typed model."""
        from italian_energy.integration.serialization import load_envelope

        result = load_envelope(data)
        if not isinstance(result, cls):
            raise ValueError("integration envelope does not contain a CdispD reference snapshot")
        return result


def cdispd_reference_snapshot_from_import(
    result: AreraImportResult,
) -> CdispDReferenceSnapshot:
    """Project only trusted, complete CDISPD rows from one official ARERA import."""
    if result.status != VerificationStatus.VERIFIED or result.bundle is None:
        raise ValueError("CdispD reference requires a verified ARERA import and bundle")
    bundle = result.bundle
    if bundle.status != VerificationStatus.VERIFIED:
        raise ValueError("CdispD reference requires a verified ARERA bundle")
    if bundle.bundle_id != f"arera-bundle:{result.snapshot.sha256}":
        raise ValueError("ARERA bundle and raw snapshot digest do not match")
    if result.snapshot.source_url != ARERA_DOMESTIC_2026_URL:
        raise ValueError("CdispD reference requires the official ARERA 2026 workbook URL")
    cdispd_rows = tuple(charge for charge in bundle.charges if charge.component_code == "CDISPD")
    if any(
        charge.category != BillingCategory.SALES
        or charge.quota != BillingQuota.CONSUMPTION
        or charge.role != AreraChargeRole.ATOMIC
        for charge in cdispd_rows
    ):
        raise ValueError("ARERA bundle contains an unsupported CDISPD row")
    selected = cdispd_rows
    if not selected:
        raise ValueError("verified ARERA bundle contains no atomic CDISPD consumption rows")
    normalized: list[AreraChargeValue] = []
    for charge in selected:
        locator = ProvenanceLocator(sheet=charge.source.sheet, cell=charge.source.cell)
        provenance: list[Provenance] = []
        for item in charge.provenance:
            if (
                item.source != "ARERA"
                or item.sha256 != result.snapshot.sha256
                or item.effective_period != charge.validity
                or item.url != ARERA_DOMESTIC_2026_URL
            ):
                raise ValueError("ARERA CDISPD row provenance does not match the raw snapshot")
            provenance.append(item.model_copy(update={"locator": locator}))
        normalized.append(
            charge.model_copy(
                update={
                    "status": VerificationStatus.VERIFIED,
                    "provenance": tuple(provenance),
                }
            )
        )
    seed: dict[str, object] = {
        "source_snapshot_id": result.snapshot.snapshot_id,
        "source_digest": result.snapshot.sha256,
        "source_bundle_id": bundle.bundle_id,
        "bundle_schema_version": bundle.schema_version,
        "dataset_version": bundle.dataset_version,
        "validity": bundle.validity.model_dump(mode="json"),
        "status": VerificationStatus.VERIFIED.value,
        "charges": [
            item.model_dump(mode="json")
            for item in sorted(
                normalized,
                key=lambda row: (row.validity.start, row.segment.value, row.code),
            )
        ],
    }
    return CdispDReferenceSnapshot(
        snapshot_id=_canonical_snapshot_id(seed),
        source_snapshot_id=result.snapshot.snapshot_id,
        source_digest=result.snapshot.sha256,
        source_bundle_id=bundle.bundle_id,
        bundle_schema_version=bundle.schema_version,
        dataset_version=bundle.dataset_version,
        validity=bundle.validity,
        status=VerificationStatus.VERIFIED,
        charges=tuple(
            sorted(normalized, key=lambda row: (row.validity.start, row.segment.value, row.code))
        ),
    )


def acquire_cdispd_reference_snapshot(
    importer: AreraImportSource | None = None,
) -> CdispDReferenceSnapshot:
    """Acquire one fresh official workbook; never fall back to a cached snapshot."""
    if importer is None:
        from .importer import AreraDomesticElectricityImporter

        importer = AreraDomesticElectricityImporter()
    return cdispd_reference_snapshot_from_import(importer.fetch_and_import())
