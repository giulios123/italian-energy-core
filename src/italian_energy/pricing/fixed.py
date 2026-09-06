"""Deterministic evaluator for fixed electricity tariffs."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from italian_energy.domain.consumption import ConsumptionBucket
from italian_energy.domain.costs import CostBreakdown, CostComponent, PricingResult
from italian_energy.domain.money import Money, RateUnit, RoundingPolicy, UnitRate
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.tariff import ChargeBasis, ChargeRule, FixedTariff, Tariff
from italian_energy.domain.time import DatePeriod
from italian_energy.pricing.engine import PricingRequest

ROME = ZoneInfo("Europe/Rome")
SUPPORTED_BASES = frozenset(
    {ChargeBasis.PER_KWH, ChargeBasis.PER_DAY, ChargeBasis.PER_KW_DAY, ChargeBasis.FLAT}
)


class FixedPricingError(ValueError):
    """Raised when a fixed pricing request cannot be evaluated safely."""


class FixedPricingEngine:
    """Price a fixed tariff without external state or side effects."""

    def price(self, request: PricingRequest) -> PricingResult:
        contract = request.contract
        tariff = contract.tariff
        if not isinstance(tariff, FixedTariff):
            raise FixedPricingError("fixed pricing requires a fixed tariff")
        if request.market_data is not None:
            raise FixedPricingError("market data is not supported by fixed pricing")
        if request.regulatory_parameters:
            raise FixedPricingError("regulatory parameters are not supported by fixed pricing")
        self._validate_period(request.period, contract)
        self._validate_tariff(tariff)

        selected = self._select_buckets(request)
        components: list[CostComponent] = []
        assumptions: list[str] = list(contract.conditions) + list(tariff.conditions)

        components.extend(
            self._energy_components(
                request.period,
                tariff,
                selected,
                request.rounding_policy,
            )
        )
        for prefix, rules in (
            ("fixed", tariff.fixed_charges),
            ("additional", tariff.additional_charges),
            ("discount", tariff.discounts),
        ):
            for rule in rules:
                component = self._charge_component(
                    request,
                    contract,
                    tariff,
                    selected,
                    prefix,
                    rule,
                )
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
        )
        provenance = self._merge_provenance(
            contract.provenance,
            tariff.provenance,
            *(component.provenance for component in rounded_components),
        )
        return PricingResult(
            pricing_id=self._pricing_id(request),
            contract_id=contract.contract_id,
            period=request.period,
            breakdown=breakdown,
            assumptions=self._unique_strings(assumptions),
            provenance=provenance,
        )

    @staticmethod
    def _pricing_id(request: PricingRequest) -> str:
        payload = json.dumps(
            request.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return f"fixed:{hashlib.sha256(payload).hexdigest()}"

    @staticmethod
    def _validate_period(period: DatePeriod, contract: Contract) -> None:
        tariff = contract.tariff
        if period.start < contract.validity.start or period.end > contract.validity.end:
            raise FixedPricingError("requested period must be contained in contract validity")
        if period.start < tariff.validity.start or period.end > tariff.validity.end:
            raise FixedPricingError("requested period must be contained in tariff validity")

    @staticmethod
    def _validate_tariff(tariff: FixedTariff) -> None:
        for price in tariff.prices:
            if price.rate.unit != RateUnit.EUR_PER_KWH:
                raise FixedPricingError("fixed energy prices require EUR/kWh")
        for rule in (*tariff.fixed_charges, *tariff.additional_charges, *tariff.discounts):
            if rule.basis not in SUPPORTED_BASES:
                raise FixedPricingError(f"charge basis {rule.basis.value} is not supported")
            if rule.band is not None and rule.band != "ALL" and rule.basis != ChargeBasis.PER_KWH:
                raise FixedPricingError(
                    f"charge {rule.code} named bands are supported only for PER_KWH"
                )
            if rule.basis == ChargeBasis.PER_KWH:
                FixedPricingEngine._require_rate(rule, RateUnit.EUR_PER_KWH)
            elif rule.basis == ChargeBasis.PER_DAY:
                FixedPricingEngine._require_rate(rule, RateUnit.EUR_PER_DAY)
            elif rule.basis == ChargeBasis.PER_KW_DAY:
                FixedPricingEngine._require_rate(rule, RateUnit.EUR_PER_KW_DAY)
            elif rule.basis == ChargeBasis.FLAT and not isinstance(rule.value, Money):
                raise FixedPricingError(f"flat charge {rule.code} requires Money")

    @staticmethod
    def _require_rate(rule: ChargeRule, unit: RateUnit) -> UnitRate:
        if not isinstance(rule.value, UnitRate) or rule.value.unit != unit:
            raise FixedPricingError(f"charge {rule.code} requires {unit.value}")
        return rule.value

    @staticmethod
    def _period_bounds(period: DatePeriod) -> tuple[datetime, datetime]:
        return (
            datetime.combine(period.start, time.min, ROME),
            datetime.combine(period.end, time.min, ROME),
        )

    def _select_buckets(self, request: PricingRequest) -> tuple[ConsumptionBucket, ...]:
        start, end = self._period_bounds(request.period)
        selected: list[ConsumptionBucket] = []
        for bucket in request.consumption.buckets:
            local_start = bucket.interval.start.astimezone(ROME)
            local_end = bucket.interval.end.astimezone(ROME)
            if local_end <= start or local_start >= end:
                continue
            if local_start < start or local_end > end:
                raise FixedPricingError("consumption bucket crosses requested period boundary")
            selected.append(bucket)
        return tuple(selected)

    def _energy_components(
        self,
        period: DatePeriod,
        tariff: FixedTariff,
        buckets: tuple[ConsumptionBucket, ...],
        policy: RoundingPolicy,
    ) -> tuple[CostComponent, ...]:
        if not buckets:
            return ()
        profile_bands = {bucket.band for bucket in buckets}
        tariff_bands = {price.band for price in tariff.prices}
        if "ALL" not in tariff_bands and "ALL" in profile_bands:
            raise FixedPricingError("named bands cannot price an ALL consumption profile")
        if "ALL" not in tariff_bands:
            missing = profile_bands - tariff_bands
            if missing:
                raise FixedPricingError(f"consumption band {sorted(missing)[0]} has no fixed price")

        components: list[CostComponent] = []
        for price in tariff.prices:
            if price.band == "ALL":
                quantity = sum((bucket.energy.kwh for bucket in buckets), Decimal(0))
            else:
                quantity = sum(
                    (bucket.energy.kwh for bucket in buckets if bucket.band == price.band),
                    Decimal(0),
                )
            if quantity == 0:
                continue
            amount = Money(amount=quantity * price.rate.amount).round(policy)
            components.append(
                CostComponent(
                    code=f"energy:{price.band}",
                    description=f"Energy {price.band}",
                    amount=amount,
                    quantity=quantity,
                    unit_rate=price.rate,
                    period=period,
                    formula="quantity_kwh * rate_eur_per_kwh",
                    provenance=tariff.provenance,
                )
            )
        return tuple(components)

    def _charge_component(
        self,
        request: PricingRequest,
        contract: Contract,
        tariff: Tariff,
        buckets: tuple[ConsumptionBucket, ...],
        prefix: str,
        rule: ChargeRule,
    ) -> CostComponent | None:
        window, trigger = self._rule_window(request.period, contract, tariff, rule)
        if window is None:
            return None
        amount: Decimal
        quantity: Decimal | None
        unit_rate: UnitRate | None
        formula: str
        if rule.basis == ChargeBasis.PER_KWH:
            applicable = self._buckets_in_window(buckets, window, rule)
            if not applicable and not buckets:
                return None
            rate = self._require_rate(rule, RateUnit.EUR_PER_KWH)
            quantity = self._charge_quantity(applicable, rule.band, rule)
            amount = quantity * rate.amount
            unit_rate = rate
            formula = "quantity_kwh * rate_eur_per_kwh"
        elif rule.basis == ChargeBasis.PER_DAY:
            rate = self._require_rate(rule, RateUnit.EUR_PER_DAY)
            quantity = Decimal((window.end - window.start).days)
            amount = quantity * rate.amount
            unit_rate = rate
            formula = "days * rate_eur_per_day"
        elif rule.basis == ChargeBasis.PER_KW_DAY:
            rate = self._require_rate(rule, RateUnit.EUR_PER_KW_DAY)
            if contract.supply.contracted_power is None:
                raise FixedPricingError("PER_KW_DAY requires contracted power")
            quantity = contract.supply.contracted_power.kw * Decimal(
                (window.end - window.start).days
            )
            amount = quantity * rate.amount
            unit_rate = rate
            formula = "kw_days * rate_eur_per_kw_day"
        elif rule.basis == ChargeBasis.FLAT:
            if trigger is None or not (request.period.start <= trigger < request.period.end):
                return None
            if not isinstance(rule.value, Money):
                raise FixedPricingError(f"flat charge {rule.code} requires Money")
            quantity = None
            amount = rule.value.amount
            unit_rate = None
            formula = "flat_amount"
        else:
            raise FixedPricingError(f"charge basis {rule.basis.value} is not supported")

        provenance = self._merge_provenance(tariff.provenance, rule.provenance)
        return CostComponent(
            code=f"{prefix}:{rule.code}",
            description=rule.description,
            amount=Money(amount=amount).round(request.rounding_policy),
            quantity=quantity,
            unit_rate=unit_rate,
            period=window,
            formula=formula,
            provenance=provenance,
        )

    @staticmethod
    def _rule_window(
        request_period: DatePeriod,
        contract: Contract,
        tariff: Tariff,
        rule: ChargeRule,
    ) -> tuple[DatePeriod | None, date | None]:
        start = max(contract.validity.start, tariff.validity.start)
        end = min(contract.validity.end, tariff.validity.end)
        if rule.validity is not None:
            start = max(start, rule.validity.start)
            end = min(end, rule.validity.end)
        trigger = start
        overlap_start = max(start, request_period.start)
        overlap_end = min(end, request_period.end)
        if overlap_end <= overlap_start:
            return None, trigger
        return DatePeriod(start=overlap_start, end=overlap_end), trigger

    def _buckets_in_window(
        self,
        buckets: tuple[ConsumptionBucket, ...],
        window: DatePeriod,
        rule: ChargeRule,
    ) -> tuple[ConsumptionBucket, ...]:
        start, end = self._period_bounds(window)
        applicable: list[ConsumptionBucket] = []
        for bucket in buckets:
            local_start = bucket.interval.start.astimezone(ROME)
            local_end = bucket.interval.end.astimezone(ROME)
            if local_end <= start or local_start >= end:
                continue
            if local_start < start or local_end > end:
                raise FixedPricingError(
                    f"charge {rule.code} validity cuts through a consumption bucket"
                )
            applicable.append(bucket)
        return tuple(applicable)

    @staticmethod
    def _charge_quantity(
        buckets: tuple[ConsumptionBucket, ...], band: str | None, rule: ChargeRule
    ) -> Decimal:
        if band is not None and band != "ALL":
            if any(bucket.band == "ALL" for bucket in buckets):
                raise FixedPricingError(f"charge {rule.code} requires named consumption bands")
            return sum((bucket.energy.kwh for bucket in buckets if bucket.band == band), Decimal(0))
        return sum((bucket.energy.kwh for bucket in buckets), Decimal(0))

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
