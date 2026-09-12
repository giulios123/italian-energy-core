"""Traceability metadata for external data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.time import DatePeriod


class ProvenanceLocator(DomainModel):
    """Optional fine-grained location inside a source document."""

    document: str | None = None
    sheet: str | None = None
    cell: str | None = None
    section: str | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> ProvenanceLocator:
        if not any((self.document, self.sheet, self.cell, self.section)):
            raise ValueError("provenance locator requires at least one location field")
        return self


class Provenance(DomainModel):
    source: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    retrieved_at: datetime
    effective_period: DatePeriod | None = None
    dataset_version: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    url: str | None = None
    locator: ProvenanceLocator | None = None

    @field_validator("retrieved_at")
    @classmethod
    def validate_retrieved_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @field_validator("dataset_version", "url", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise ValueError("optional provenance text must be a non-empty string")
        return value
