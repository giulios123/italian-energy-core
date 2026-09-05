"""Traceability metadata for external data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.time import DatePeriod


class Provenance(DomainModel):
    source: str = Field(min_length=1)
    source_identifier: str = Field(min_length=1)
    retrieved_at: datetime
    effective_period: DatePeriod | None = None
    dataset_version: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    url: str | None = None

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
