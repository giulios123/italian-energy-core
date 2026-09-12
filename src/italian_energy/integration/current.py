"""Current-advisor contracts for the Core--Platform boundary.

The current advisor deliberately keeps projection semantics explicit.  The values
produced here are scenarios derived from verified historical observations; they are
not market forecasts and must never be presented as such by a consumer.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self

from pydantic import Field, field_validator, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.common import strict_decimal
from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.costs import ExternalBillItem
from italian_energy.domain.market import MarketData, MarketDataPoint
from italian_energy.domain.money import Money
from italian_energy.domain.offer import Contract
from italian_energy.domain.regulatory import BillingMeasure, SupplyClassification, VoltageLevel
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval
from italian_energy.portal_offers.models import (
    PortalComparisonResult,
    PortalEligibilityProfile,
    PortalOfferRecord,
    PortalSnapshot,
    VerifiedMarketData,
)
from italian_energy.recommendation import RecommendationPreferences

from .errors import CoreContractError, CoreErrorCode


class CurrentScenario(StrEnum):
    """Names of the three deterministic index scenarios."""

    LOW_INDEX = "low_index"
    BASE = "base"
    HIGH_INDEX = "high_index"


class CurrentPortalComparisonRequest(DomainModel):
    """A complete domestic BT scenario for a forward twelve-month comparison."""

    current_contract: Contract
    consumption: ConsumptionProfile
    as_of: date
    classification: SupplyClassification
    eligibility: PortalEligibilityProfile
    continuation_assumption: bool = False
    stress_delta: Decimal = Decimal("0.20")
    supplemental_market_data: VerifiedMarketData | None = None
    measurements: tuple[BillingMeasure, ...] = ()
    external_items: tuple[ExternalBillItem, ...] = ()

    @field_validator("stress_delta", mode="before")
    @classmethod
    def validate_stress_delta(cls, value: object) -> Decimal:
        result = strict_decimal(value)
        if result < 0 or result >= 1:
            raise ValueError("stress_delta must be in [0, 1)")
        return result

    @model_validator(mode="after")
    def validate_scenario(self) -> Self:
        classification = self.classification
        supply = self.current_contract.supply
        if (
            classification.voltage_level != VoltageLevel.BT
            or classification.usage_code != "domestic"
            or classification.residential is None
            or supply.residential is None
            or supply.residential != classification.residential
            or supply.commodity.value != "electricity"
            or self.eligibility.voltage_level != VoltageLevel.BT
            or not self.eligibility.domestic
        ):
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "current integration scenario requires domestic electricity BT",
            )
        _validate_history(self.consumption, self.as_of)
        return self


class CurrentCatalogSnapshot(DomainModel):
    """Parsed, verified catalogue data retained for deterministic replays."""

    dataset_date: date
    snapshot: PortalSnapshot
    records: tuple[PortalOfferRecord, ...]
    market_data: MarketData | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> Self:
        if self.snapshot.offers.dataset_date != self.dataset_date:
            raise ValueError("catalogue snapshot date mismatch")
        if self.snapshot.offers.status.value != "verified":
            raise ValueError("current catalogue snapshot must be verified")
        if self.snapshot.indexes is not None and self.market_data is None:
            raise ValueError("index snapshot requires parsed market data")
        return self


class CurrentScenarioComparison(DomainModel):
    scenario: CurrentScenario
    comparison: PortalComparisonResult


class ProjectedMarketScenarioSet(DomainModel):
    """The three future market datasets used by a current comparison."""

    as_of: date
    period: DatePeriod
    low_index: MarketData
    base: MarketData
    high_index: MarketData

    @model_validator(mode="after")
    def validate_period(self) -> Self:
        for value in (self.low_index, self.base, self.high_index):
            if any(point.interval.start.date() < self.period.start for point in value.points):
                raise ValueError("projected market points must be inside the future period")
        return self


class CurrentPortalComparisonResult(DomainModel):
    """Three scenario comparisons sharing one catalogue and future horizon."""

    current_result_id: str = Field(pattern=r"^current-portal-comparison:[0-9a-f]{64}$")
    as_of: date
    period: DatePeriod
    catalog_dataset_date: date
    scenarios: tuple[CurrentScenarioComparison, ...]

    @model_validator(mode="after")
    def validate_scenarios(self) -> Self:
        expected = (CurrentScenario.LOW_INDEX, CurrentScenario.BASE, CurrentScenario.HIGH_INDEX)
        actual = tuple(item.scenario for item in self.scenarios)
        if actual != expected:
            raise ValueError("current result must contain low, base and high scenarios in order")
        return self

    @property
    def base(self) -> PortalComparisonResult:
        return self.scenarios[1].comparison


class CurrentRecommendationRequest(DomainModel):
    comparison: CurrentPortalComparisonResult
    preferences: RecommendationPreferences = Field(default_factory=RecommendationPreferences)
    minimum_savings: Money = Money(amount=Decimal("50.00"))
    minimum_percentage_savings: Decimal = Decimal("5")

    @field_validator("minimum_percentage_savings", mode="before")
    @classmethod
    def validate_minimum_percentage(cls, value: object) -> Decimal:
        result = strict_decimal(value)
        if result < 0:
            raise ValueError("minimum percentage savings must be non-negative")
        return result


def _first_of_month(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    return date(year, month_index + 1, 1)


def _month_start(value: datetime, target: date) -> datetime:
    return datetime(target.year, target.month, 1, tzinfo=value.tzinfo)


def _validate_history(profile: ConsumptionProfile, as_of: date) -> None:
    cutoff = _first_of_month(as_of)
    buckets = profile.buckets
    if not buckets:
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_SCENARIO,
            "current comparison requires twelve complete monthly consumption buckets",
        )
    if any(bucket.granularity != Granularity.MONTH for bucket in buckets):
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_SCENARIO,
            "current comparison requires monthly consumption buckets",
        )
    bands = {bucket.band for bucket in buckets}
    if any(band not in {"ALL", "F1", "F2", "F3"} for band in bands):
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_SCENARIO,
            "current comparison accepts only total or F1/F2/F3 monthly buckets",
        )
    months = {(bucket.interval.start.year, bucket.interval.start.month) for bucket in buckets}
    expected = {
        (_add_months(cutoff, -offset).year, _add_months(cutoff, -offset).month)
        for offset in range(1, 13)
    }
    if months != expected or any(bucket.interval.end.date() > cutoff for bucket in buckets):
        raise CoreContractError(
            CoreErrorCode.UNSUPPORTED_SCENARIO,
            "current comparison requires the twelve latest complete calendar months",
        )
    if "ALL" not in {bucket.band for bucket in buckets}:
        by_band: dict[str, set[tuple[int, int]]] = {}
        for bucket in buckets:
            by_band.setdefault(bucket.band, set()).add(
                (bucket.interval.start.year, bucket.interval.start.month)
            )
        if any(band_months != expected for band_months in by_band.values()):
            raise CoreContractError(
                CoreErrorCode.UNSUPPORTED_SCENARIO,
                "each consumption band must cover the same twelve complete months",
            )


def future_period(as_of: date) -> DatePeriod:
    """Return the next twelve complete calendar months."""

    start = _add_months(_first_of_month(as_of), 1)
    return DatePeriod(start=start, end=_add_months(start, 12))


def project_consumption(profile: ConsumptionProfile, as_of: date) -> ConsumptionProfile:
    """Shift twelve historical monthly buckets onto the future horizon."""

    cutoff = _first_of_month(as_of)
    ordered = sorted(profile.buckets, key=lambda item: item.interval.start)
    output: list[ConsumptionBucket] = []
    for bucket in ordered:
        offset = (
            bucket.interval.start.year * 12
            + bucket.interval.start.month
            - (cutoff.year * 12 + cutoff.month)
        )
        target = _add_months(future_period(as_of).start, offset + 12)
        start = _month_start(bucket.interval.start, target)
        end = _month_start(bucket.interval.start, _add_months(target, 1))
        output.append(bucket.model_copy(update={"interval": TimeInterval(start=start, end=end)}))
    return profile.model_copy(update={"buckets": tuple(output)})


def project_market_data(
    market_data: MarketData,
    as_of: date,
    scenario: CurrentScenario,
    stress_delta: Decimal,
) -> MarketData:
    """Shift the latest twelve complete monthly points and apply the scenario delta."""

    horizon = future_period(as_of)
    cutoff = _first_of_month(as_of)
    points: list[MarketDataPoint] = []
    for index in market_data.indexes:
        history = sorted(
            (
                point
                for point in market_data.points
                if point.index_code == index.code and point.interval.end.date() <= cutoff
            ),
            key=lambda point: point.interval.start,
        )[-12:]
        if len(history) != 12:
            raise CoreContractError(
                CoreErrorCode.COVERAGE_UNAVAILABLE,
                f"market index {index.code} lacks twelve complete historical months",
            )
        multiplier = {
            CurrentScenario.LOW_INDEX: Decimal(1) - stress_delta,
            CurrentScenario.BASE: Decimal(1),
            CurrentScenario.HIGH_INDEX: Decimal(1) + stress_delta,
        }[scenario]
        for offset, source in enumerate(history):
            target = _add_months(horizon.start, offset)
            start = datetime(target.year, target.month, 1, tzinfo=source.interval.start.tzinfo)
            end_date = _add_months(target, 1)
            end = datetime(end_date.year, end_date.month, 1, tzinfo=source.interval.end.tzinfo)
            points.append(
                source.model_copy(
                    update={
                        "interval": TimeInterval(start=start, end=end),
                        "value": source.value * multiplier,
                    }
                )
            )
    return MarketData(indexes=market_data.indexes, points=tuple(points))


__all__ = [
    "CurrentCatalogSnapshot",
    "CurrentPortalComparisonRequest",
    "CurrentPortalComparisonResult",
    "CurrentRecommendationRequest",
    "CurrentScenario",
    "CurrentScenarioComparison",
    "ProjectedMarketScenarioSet",
    "future_period",
    "project_consumption",
    "project_market_data",
]
