"""Consumption profile and time buckets."""

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import BandCode
from italian_energy.domain.money import EnergyQuantity
from italian_energy.domain.time import Granularity, TimeInterval


class ConsumptionBucket(DomainModel):
    interval: TimeInterval
    energy: EnergyQuantity
    band: BandCode = "ALL"
    granularity: Granularity


class ConsumptionProfile(DomainModel):
    profile_id: str = Field(min_length=1)
    buckets: tuple[ConsumptionBucket, ...] = ()

    @field_validator("buckets", mode="before")
    @classmethod
    def tuple_buckets(cls, value: object) -> tuple[ConsumptionBucket, ...]:
        return tuple(value) if value is not None else ()  # type: ignore[arg-type]

    @model_validator(mode="after")
    def validate_buckets(self) -> ConsumptionProfile:
        bands = {bucket.band for bucket in self.buckets}
        if "ALL" in bands and len(bands) > 1:
            raise ValueError("consumption profile cannot mix ALL and named bands")
        for band in bands:
            ordered = sorted(
                (bucket for bucket in self.buckets if bucket.band == band),
                key=lambda bucket: bucket.interval.start,
            )
            for previous, current in pairwise(ordered):
                if current.interval.start < previous.interval.end:
                    raise ValueError(f"consumption buckets overlap for band {band}")
        return self

    def total_energy(self) -> EnergyQuantity:
        total = sum((bucket.energy.kwh for bucket in self.buckets), Decimal(0))
        return EnergyQuantity(kwh=total)
