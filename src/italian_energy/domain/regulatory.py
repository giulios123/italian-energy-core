"""Versioned regulatory parameters without embedding unverified values."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import Field, field_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import DatePeriod


class VerificationStatus(StrEnum):
    UNVERIFIED = "unverified"
    REVIEW_REQUIRED = "review_required"
    VERIFIED = "verified"


class RegulatoryParameter(DomainModel):
    code: str = Field(min_length=1)
    value: Decimal
    unit: str = Field(min_length=1)
    validity: DatePeriod
    status: VerificationStatus = VerificationStatus.UNVERIFIED
    provenance: tuple[Provenance, ...] = ()

    @field_validator("value", mode="before")
    @classmethod
    def validate_value(cls, value: Any) -> Decimal:
        return strict_decimal(value)
