"""Deterministic evaluator for indexed electricity tariffs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from italian_energy.domain.consumption import ConsumptionBucket
from italian_energy.domain.costs import CostBreakdown, CostComponent, PricingResult
from italian_energy.domain.formula import (
    AddPrice,
    ClampPrice,
    IndexReference,
    MultiplyPrice,
    PriceConstant,
    PriceExpression,
)
from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.money import Money, RateUnit, RoundingPolicy, UnitRate
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.tariff import ChargeBasis, ChargeRule, IndexedTariff
from italian_energy.domain.time import DatePeriod, Granularity
from italian_energy.pricing.engine import PricingRequest
from italian_energy.pricing.fixed import FixedPricingEngine, FixedPricingError


class IndexedPricingError(ValueError):
    """Raised when indexed pricing cannot be evaluated safely."""


_GRANULARITY_RANK: Mapping[Granularity, int] = {
    Granularity.QUARTER_HOUR: 0,
    Granularity.HOUR: 1,
    Granularity.DAY: 2,
    Granularity.MONTH: 3,
}
_SUPPORTED_GRANULARITIES = frozenset(_GRANULARITY_RANK)
_SUPPORTED_BASES = frozenset(
    {ChargeBasis.PER_KWH, ChargeBasis.PER_DAY, ChargeBasis.PER_KW_DAY, ChargeBasis.FLAT}
)


class IndexedPricingEngine:
    """Price an indexed tariff without external state or side effects."""

    def price(self, request: PricingRequest) -> PricingResult:
        contract = request.contract
        tariff = contract.tariff
        if not isinstance(tariff, IndexedTariff):
            raise IndexedPricingError("indexed pricing requires an indexed tariff")
        if request.market_data is None:
            raise IndexedPricingError("indexed pricing requires market data")
        if request.regulatory_parameters:
            raise IndexedPricingError("regulatory parameters are not supported by indexed pricing")
        self._validate_period(request.period, contract)
        self._validate_tariff(tariff, request.market_data)
        try:
            selected = FixedPricingEngine()._select_buckets(request)
        except FixedPricingError as exc:
            raise IndexedPricingError(str(exc)) from exc

        components: list[CostComponent] = []
        assumptions: list[str] = list(contract.conditions) + list(tariff.conditions)
        warnings: list[str] = []
        used_provenance: list[tuple[Provenance, ...]] = []
        energy_components, energy_warnings, energy_provenance = self._energy_components(
            request.period, tariff, selected, request.market_data, request.rounding_policy
        )
        components.extend(energy_components)
        warnings.extend(energy_warnings)
        used_provenance.extend(energy_provenance)

        helper = FixedPricingEngine()
        for prefix, rules in (
            ("fixed", tariff.fixed_charges),
            ("additional", tariff.additional_charges),
            ("discount", tariff.discounts),
        ):
            for rule in rules:
                try:
                    component = helper._charge_component(
                        request, contract, tariff, selected, prefix, rule
                    )
                except FixedPricingError as exc:
                    raise IndexedPricingError(str(exc)) from exc
                if component is not None:
                    components.append(component)
                    assumptions.extend(rule.conditions)

        rounded_components = tuple(components)
        total = sum(
            (component.amount for component in rounded_components),
            Money(amount=Decimal(0)),
        )
        breakdown = CostBreakdown(
            components=rounded_components,
            total=total,
            assumptions=self._unique_strings(assumptions),
            warnings=self._unique_strings(warnings),
        )
        provenance = self._merge_provenance(
            contract.provenance,
            tariff.provenance,
            *used_provenance,
            *(component.provenance for component in rounded_components),
        )
        return PricingResult(
            pricing_id=self._pricing_id(request),
            contract_id=contract.contract_id,
            period=request.period,
            breakdown=breakdown,
            assumptions=self._unique_strings(assumptions),
            warnings=self._unique_strings(warnings),
            provenance=provenance,
        )

    @staticmethod
    def _pricing_id(request: PricingRequest) -> str:
        return FixedPricingEngine._pricing_id(request).replace("fixed:", "indexed:", 1)

    @staticmethod
    def _validate_period(period: DatePeriod, contract: Contract) -> None:
        tariff = contract.tariff
        if period.start < contract.validity.start or period.end > contract.validity.end:
            raise IndexedPricingError("requested period must be contained in contract validity")
        if period.start < tariff.validity.start or period.end > tariff.validity.end:
            raise IndexedPricingError("requested period must be contained in tariff validity")

    @classmethod
    def _validate_tariff(cls, tariff: IndexedTariff, market_data: MarketData) -> None:
        if tariff.granularity not in _SUPPORTED_GRANULARITIES:
            raise IndexedPricingError(f"granularity {tariff.granularity.value} is not supported")
        index_map = {index.code: index for index in market_data.indexes}
        for formula in tariff.formulas:
            references = cls._index_references(formula.expression)
            if not references:
                raise IndexedPricingError(f"formula {formula.band} requires an index reference")
            for reference in references:
                index = index_map.get(reference.index_code)
                if index is None:
                    raise IndexedPricingError(f"market index {reference.index_code} is missing")
                if reference.unit != index.unit:
                    raise IndexedPricingError(
                        f"market index {reference.index_code} unit does not match reference"
                    )
                if reference.granularity != tariff.granularity:
                    raise IndexedPricingError(
                        f"index {reference.index_code} granularity does not match tariff"
                    )
                if index.granularity != tariff.granularity:
                    raise IndexedPricingError(
                        f"market index {reference.index_code} granularity does not match tariff"
                    )
        cls._validate_charge_rules(tariff)

    @staticmethod
    def _validate_charge_rules(tariff: IndexedTariff) -> None:
        for rule in (*tariff.fixed_charges, *tariff.additional_charges, *tariff.discounts):
            if rule.basis not in _SUPPORTED_BASES:
                raise IndexedPricingError(f"charge basis {rule.basis.value} is not supported")
            if rule.band is not None and rule.band != "ALL" and rule.basis != ChargeBasis.PER_KWH:
                raise IndexedPricingError(
                    f"charge {rule.code} named bands are supported only for PER_KWH"
                )
            if rule.basis == ChargeBasis.PER_KWH:
                IndexedPricingEngine._require_rate(rule, RateUnit.EUR_PER_KWH)
            elif rule.basis == ChargeBasis.PER_DAY:
                IndexedPricingEngine._require_rate(rule, RateUnit.EUR_PER_DAY)
            elif rule.basis == ChargeBasis.PER_KW_DAY:
                IndexedPricingEngine._require_rate(rule, RateUnit.EUR_PER_KW_DAY)
            elif rule.basis == ChargeBasis.FLAT and not isinstance(rule.value, Money):
                raise IndexedPricingError(f"flat charge {rule.code} requires Money")

    @staticmethod
    def _require_rate(rule: ChargeRule, unit: RateUnit) -> UnitRate:
        if not isinstance(rule.value, UnitRate) or rule.value.unit != unit:
            raise IndexedPricingError(f"charge {rule.code} requires {unit.value}")
        return rule.value

    @classmethod
    def _energy_components(
        cls,
        period: DatePeriod,
        tariff: IndexedTariff,
        buckets: tuple[ConsumptionBucket, ...],
        market_data: MarketData,
        policy: RoundingPolicy,
    ) -> tuple[
        tuple[CostComponent, ...],
        tuple[str, ...],
        tuple[tuple[Provenance, ...], ...],
    ]:
        profile_bands = {bucket.band for bucket in buckets}
        tariff_bands = {formula.band for formula in tariff.formulas}
        if "ALL" not in tariff_bands and "ALL" in profile_bands:
            raise IndexedPricingError("named bands cannot price an ALL consumption profile")
        if "ALL" not in tariff_bands:
            missing = profile_bands - tariff_bands
            if missing:
                raise IndexedPricingError(
                    f"consumption band {sorted(missing)[0]} has no indexed formula"
                )

        components: list[CostComponent] = []
        warnings: list[str] = []
        provenance: list[tuple[Provenance, ...]] = []
        indexes = {index.code: index for index in market_data.indexes}
        for formula in tariff.formulas:
            applicable = (
                buckets
                if formula.band == "ALL"
                else tuple(bucket for bucket in buckets if bucket.band == formula.band)
            )
            quantity = sum((bucket.energy.kwh for bucket in applicable), Decimal(0))
            if quantity == 0:
                continue
            raw_amount = Decimal(0)
            used_points: list[MarketDataPoint] = []
            references = cls._index_references(formula.expression)
            for bucket in applicable:
                if bucket.energy.kwh == 0:
                    continue
                values: dict[str, UnitRate] = {}
                for reference in references:
                    index = indexes[reference.index_code]
                    point = cls._point_for_bucket(bucket, index, market_data.points)
                    values[reference.index_code] = UnitRate(
                        amount=point.value,
                        unit=reference.unit,
                    )
                    if point not in used_points:
                        used_points.append(point)
                rate = cls._evaluate(formula.expression, values)
                if rate.unit == RateUnit.EUR_PER_MWH:
                    rate = UnitRate(amount=rate.amount / Decimal(1000), unit=RateUnit.EUR_PER_KWH)
                if rate.unit != RateUnit.EUR_PER_KWH:
                    raise IndexedPricingError(
                        f"formula {formula.band} must result in EUR/kWh or EUR/MWh"
                    )
                raw_amount += bucket.energy.kwh * rate.amount
            weighted_rate = UnitRate(amount=raw_amount / quantity, unit=RateUnit.EUR_PER_KWH)
            component_provenance = cls._merge_provenance(
                tariff.provenance,
                *(indexes[reference.index_code].provenance for reference in references),
                *(point.provenance for point in used_points),
            )
            components.append(
                CostComponent(
                    code=f"energy:{formula.band}",
                    description=f"Energy {formula.band}",
                    amount=Money(amount=raw_amount).round(policy),
                    quantity=quantity,
                    unit_rate=weighted_rate,
                    period=period,
                    formula="sum(quantity_kwh_i * evaluated_rate_eur_per_kwh_i)",
                    provenance=component_provenance,
                )
            )
            provenance.append(component_provenance)
            for reference in references:
                index = indexes[reference.index_code]
                if not index.provenance:
                    warnings.append(f"market index {index.code} has no provenance")
                if any(
                    not point.provenance for point in used_points if point.index_code == index.code
                ):
                    warnings.append(f"market data points for index {index.code} have no provenance")
        return tuple(components), cls._unique_strings(warnings), tuple(provenance)

    @classmethod
    def _point_for_bucket(
        cls,
        bucket: ConsumptionBucket,
        index: MarketIndex,
        points: tuple[MarketDataPoint, ...],
    ) -> MarketDataPoint:
        bucket_rank = _GRANULARITY_RANK.get(bucket.granularity)
        index_rank = _GRANULARITY_RANK.get(index.granularity)
        if bucket_rank is None or index_rank is None or bucket_rank > index_rank:
            raise IndexedPricingError(
                f"consumption granularity {bucket.granularity.value} is too aggregated for index "
                f"{index.code}"
            )
        candidates = tuple(
            point
            for point in points
            if point.index_code == index.code
            and point.interval.start <= bucket.interval.start
            and point.interval.end >= bucket.interval.end
        )
        if len(candidates) != 1:
            reason = "missing" if not candidates else "ambiguous"
            raise IndexedPricingError(
                f"market index {index.code} coverage is {reason} for "
                f"{bucket.interval.start.isoformat()}..{bucket.interval.end.isoformat()}"
            )
        cls._validate_point(candidates[0], index)
        return candidates[0]

    @staticmethod
    def _validate_point(point: MarketDataPoint, index: MarketIndex) -> None:
        try:
            timezone = ZoneInfo(index.timezone)
        except ZoneInfoNotFoundError as exc:
            raise IndexedPricingError(f"unknown index timezone {index.timezone}") from exc
        local_start = point.interval.start.astimezone(timezone)
        local_end = point.interval.end.astimezone(timezone)
        duration = point.interval.end.astimezone(ZoneInfo("UTC")) - point.interval.start.astimezone(
            ZoneInfo("UTC")
        )
        granularity = index.granularity
        if granularity == Granularity.QUARTER_HOUR:
            if local_start.minute % 15 or local_start.second or local_start.microsecond:
                raise IndexedPricingError(
                    f"market point for {index.code} is not on a quarter-hour boundary"
                )
            if duration != timedelta(minutes=15):
                raise IndexedPricingError(f"market point for {index.code} is not 15 minutes long")
        elif granularity == Granularity.HOUR:
            if local_start.minute or local_start.second or local_start.microsecond:
                raise IndexedPricingError(
                    f"market point for {index.code} is not on an hour boundary"
                )
            if duration != timedelta(hours=1):
                raise IndexedPricingError(f"market point for {index.code} is not one hour long")
        elif granularity == Granularity.DAY:
            if local_start.time() != datetime.min.time() or local_end.time() != datetime.min.time():
                raise IndexedPricingError(f"market point for {index.code} is not a civil day")
            expected_end = local_start.date().fromordinal(local_start.date().toordinal() + 1)
            if local_end.date() != expected_end:
                raise IndexedPricingError(f"market point for {index.code} is not one civil day")
        elif granularity == Granularity.MONTH:
            if local_start.day != 1 or local_start.time() != datetime.min.time():
                raise IndexedPricingError(f"market point for {index.code} is not a month boundary")
            if local_start.month == 12:
                next_month = local_start.replace(year=local_start.year + 1, month=1)
            else:
                next_month = local_start.replace(month=local_start.month + 1)
            if local_end != next_month:
                raise IndexedPricingError(f"market point for {index.code} is not one civil month")

    @staticmethod
    def _index_references(expression: PriceExpression) -> tuple[IndexReference, ...]:
        found: list[IndexReference] = []

        def visit(node: PriceExpression) -> None:
            if isinstance(node, IndexReference):
                if node not in found:
                    found.append(node)
            elif isinstance(node, AddPrice):
                visit(node.left)
                visit(node.right)
            elif isinstance(node, MultiplyPrice):
                visit(node.price)
            elif isinstance(node, ClampPrice):
                visit(node.operand)

        visit(expression)
        return tuple(found)

    @staticmethod
    def _evaluate(expression: PriceExpression, values: Mapping[str, UnitRate]) -> UnitRate:
        if isinstance(expression, IndexReference):
            try:
                return values[expression.index_code]
            except KeyError as exc:
                raise IndexedPricingError(
                    f"missing value for index {expression.index_code}"
                ) from exc
        if isinstance(expression, PriceConstant):
            return expression.rate
        if isinstance(expression, AddPrice):
            left = IndexedPricingEngine._evaluate(expression.left, values)
            right = IndexedPricingEngine._evaluate(expression.right, values)
            if left.unit != right.unit:
                raise IndexedPricingError("price addition requires equal units")
            return UnitRate(amount=left.amount + right.amount, unit=left.unit)
        if isinstance(expression, MultiplyPrice):
            price = IndexedPricingEngine._evaluate(expression.price, values)
            scalar = expression.scalar.value
            return UnitRate(amount=price.amount * scalar, unit=price.unit)
        if isinstance(expression, ClampPrice):
            result = IndexedPricingEngine._evaluate(expression.operand, values)
            amount = result.amount
            if expression.floor is not None:
                amount = max(amount, expression.floor.amount)
            if expression.cap is not None:
                amount = min(amount, expression.cap.amount)
            return UnitRate(amount=amount, unit=result.unit)
        raise IndexedPricingError(f"unsupported price expression {type(expression)!r}")

    @staticmethod
    def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            if value not in result:
                result.append(value)
        return tuple(result)

    @staticmethod
    def _merge_provenance(*groups: Iterable[Provenance]) -> tuple[Provenance, ...]:
        result: list[Provenance] = []
        for group in groups:
            for item in group:
                if item not in result:
                    result.append(item)
        return tuple(result)
