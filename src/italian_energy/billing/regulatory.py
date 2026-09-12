"""Deterministic ruleset-driven billing and bill reconciliation."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime, time
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

from italian_energy.billing.engine import BillingRequest
from italian_energy.domain.consumption import ConsumptionBucket
from italian_energy.domain.costs import (
    Bill,
    BillingResult,
    BillReconciliation,
    ComponentDifference,
    CostBreakdown,
    CostComponent,
    ExternalBillItem,
    ObservedBill,
    ObservedBillComponent,
    PricingResult,
    ReconciliationStatus,
)
from italian_energy.domain.money import Money, RateUnit, RoundingPolicy, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import (
    AddQuantity,
    BillingBasis,
    BillingCategory,
    BillingMeasureUnit,
    BillingQuota,
    ClampQuantity,
    LinearRegulatoryRule,
    MaxQuantity,
    MeasureReference,
    MinQuantity,
    MultiplyQuantity,
    PercentageRegulatoryRule,
    ProrationPolicy,
    QuantityConstant,
    QuantityExpression,
    RegulatoryParameter,
    RegulatoryProfile,
    RegulatoryRuleSet,
    SubtractQuantity,
    SupplyClassification,
    ThresholdRegulatoryRule,
    VerificationStatus,
)
from italian_energy.domain.time import DatePeriod


class BillingError(ValueError):
    """Raised when a bill cannot be reconstructed safely."""


TOLERANCE = Money(amount=Decimal("0.01"))
ROME = ZoneInfo("Europe/Rome")


def select_regulatory_profile(
    ruleset: RegulatoryRuleSet,
    classification: SupplyClassification,
    request: BillingRequest,
) -> RegulatoryProfile:
    """Select the unique ruleset profile for a classified supply context."""

    power = request.contract.supply.contracted_power
    candidates: list[RegulatoryProfile] = []
    for profile in ruleset.profiles:
        if (
            profile.contract_type_code is not None
            and profile.contract_type_code != classification.contract_type_code
        ):
            continue
        if (
            profile.voltage_level is not None
            and profile.voltage_level != classification.voltage_level
        ):
            continue
        if profile.usage_code is not None and profile.usage_code != classification.usage_code:
            continue
        if profile.residential is not None and profile.residential != classification.residential:
            continue
        if (
            profile.tax_profile_code is not None
            and profile.tax_profile_code != classification.tax_profile_code
        ):
            continue
        if not set(profile.required_eligibility_codes).issubset(classification.eligibility_codes):
            continue
        if profile.min_contracted_power_kw is not None:
            if power is None:
                continue
            if profile.min_contracted_power_inclusive:
                if power.kw < profile.min_contracted_power_kw:
                    continue
            elif power.kw <= profile.min_contracted_power_kw:
                continue
        if profile.max_contracted_power_kw is not None:
            if power is None:
                continue
            if profile.max_contracted_power_inclusive:
                if power.kw > profile.max_contracted_power_kw:
                    continue
            elif power.kw >= profile.max_contracted_power_kw:
                continue
        candidates.append(profile)
    if len(candidates) != 1:
        raise BillingError(
            "regulatory profile selection is " + ("missing" if not candidates else "ambiguous")
        )
    return candidates[0]


class RegulatoryBillingEngine:
    """Build a bill from a pricing result and verified regulatory rules."""

    def bill(self, request: BillingRequest) -> Bill:
        return self.evaluate(request).bill

    def evaluate(self, request: BillingRequest) -> BillingResult:
        pricing = self._validate_request(request)
        ruleset = request.rule_set
        classification = request.classification
        policy = request.rounding_policy
        assert ruleset is not None
        assert classification is not None
        assert policy is not None

        profile = self._select_profile(ruleset, classification, request)
        self._validate_ruleset_inputs(request, ruleset, profile)
        selected_buckets = self._selected_buckets(request)
        components = [
            self._commercial_component(component) for component in pricing.breakdown.components
        ]
        assumptions = list(pricing.assumptions) + list(request.contract.conditions)
        warnings = list(pricing.warnings)
        provenance_groups: list[Iterable[Provenance]] = [
            pricing.provenance,
            request.contract.provenance,
        ]

        produced = {self._component_key(component) for component in components}
        if len(produced) != len(components):
            raise BillingError("pricing result contains duplicate billing component keys")
        linear_and_threshold = tuple(
            rule
            for rule in profile.rules
            if isinstance(rule, (LinearRegulatoryRule, ThresholdRegulatoryRule))
        )
        for rule in linear_and_threshold:
            window = self._rule_window(request.period, rule.validity)
            if window is None:
                continue
            if isinstance(rule, LinearRegulatoryRule):
                component = self._linear_component(
                    request,
                    rule,
                    window,
                    selected_buckets,
                    policy,
                    ruleset.parameters,
                )
            elif isinstance(rule, ThresholdRegulatoryRule):
                component = self._threshold_component(
                    request,
                    rule,
                    window,
                    policy,
                    ruleset.parameters,
                )
            key = self._component_key(component)
            if key in produced:
                raise BillingError(f"duplicate billing component key {key}")
            produced.add(key)
            components.append(component)
            assumptions.extend(rule.conditions)
            provenance_groups.append(component.provenance)

        pending_percentages = [
            rule for rule in profile.rules if isinstance(rule, PercentageRegulatoryRule)
        ]
        while pending_percentages:
            progressed = False
            for percentage_rule in tuple(pending_percentages):
                window = self._rule_window(request.period, percentage_rule.validity)
                if window is None:
                    pending_percentages.remove(percentage_rule)
                    progressed = True
                    continue
                if not self._percentage_ready(percentage_rule, window, components):
                    continue
                component = self._percentage_component(
                    percentage_rule, window, components, policy, ruleset.parameters
                )
                key = self._component_key(component)
                if key in produced:
                    raise BillingError(f"duplicate billing component key {key}")
                produced.add(key)
                components.append(component)
                assumptions.extend(percentage_rule.conditions)
                provenance_groups.append(component.provenance)
                pending_percentages.remove(percentage_rule)
                progressed = True
            if not progressed:
                percentage_rule = pending_percentages[0]
                percentage_window = self._rule_window(request.period, percentage_rule.validity)
                if percentage_window is None:  # pragma: no cover - removed above
                    raise BillingError(f"percentage rule {percentage_rule.code} has no window")
                missing = self._percentage_missing_reference(
                    percentage_rule, percentage_window, components
                )
                raise BillingError(
                    f"percentage rule {percentage_rule.code} base {missing} is missing or cyclic"
                )

        for item in request.external_items:
            self._validate_external_item(item, request.period)
            component = self._external_component(item)
            key = self._component_key(component)
            if key in produced:
                raise BillingError(f"duplicate billing component key {key}")
            produced.add(key)
            components.append(component)
            provenance_groups.append(item.provenance)

        total = sum((component.amount for component in components), Money(amount=Decimal(0)))
        breakdown = CostBreakdown(
            components=tuple(components),
            total=total,
            assumptions=self._unique_strings(assumptions),
            warnings=self._unique_strings(warnings),
        )
        provenance = self._merge_provenance(*provenance_groups, ruleset.provenance)
        bill = Bill(
            bill_id=self._bill_id(request),
            contract_id=request.contract.contract_id,
            period=request.period,
            breakdown=breakdown,
            declared_total=total,
            provenance=provenance,
        )
        reconciliation = self._reconcile(request.observed_bill, bill)
        result = BillingResult(
            billing_id=self._billing_id(request),
            bill=bill,
            reconciliation=reconciliation,
            assumptions=breakdown.assumptions,
            warnings=breakdown.warnings,
            provenance=provenance,
        )
        return result

    @staticmethod
    def _validate_request(request: BillingRequest) -> PricingResult:
        if request.pricing_result is None:
            raise BillingError("billing requires a pricing result")
        if request.rule_set is None:
            raise BillingError("billing requires a regulatory rule set")
        if request.classification is None:
            raise BillingError("billing requires a supply classification")
        if request.rounding_policy is None:
            raise BillingError("billing requires a rounding policy")
        pricing = request.pricing_result
        if pricing.contract_id != request.contract.contract_id:
            raise BillingError("pricing result contract does not match billing contract")
        if pricing.period != request.period:
            raise BillingError("pricing result period does not match billing period")
        return pricing

    @staticmethod
    def _select_profile(
        ruleset: RegulatoryRuleSet,
        classification: SupplyClassification,
        request: BillingRequest,
    ) -> RegulatoryProfile:
        return select_regulatory_profile(ruleset, classification, request)

    @staticmethod
    def _validate_ruleset_inputs(
        request: BillingRequest,
        ruleset: RegulatoryRuleSet,
        profile: RegulatoryProfile,
    ) -> None:
        if ruleset.status != VerificationStatus.VERIFIED:
            raise BillingError("regulatory rule set is not verified")
        if not ruleset.provenance:
            raise BillingError("regulatory rule set provenance is missing")
        if (
            request.period.start < ruleset.validity.start
            or request.period.end > ruleset.validity.end
        ):
            raise BillingError("billing period is outside regulatory rule set validity")
        parameters = {parameter.code: parameter for parameter in ruleset.parameters}
        for rule in profile.rules:
            if rule.status != VerificationStatus.VERIFIED:
                raise BillingError(f"regulatory rule {rule.code} is not verified")
            if not rule.provenance:
                raise BillingError(f"regulatory rule {rule.code} provenance is missing")
            for code in rule.parameter_codes:
                parameter = parameters.get(code)
                if parameter is None:
                    raise BillingError(f"regulatory parameter {code} is missing")
                if parameter.status != VerificationStatus.VERIFIED:
                    raise BillingError(f"regulatory parameter {code} is not verified")
                if not parameter.provenance:
                    raise BillingError(f"regulatory parameter {code} provenance is missing")
                if (
                    request.period.start < parameter.validity.start
                    or request.period.end > parameter.validity.end
                ):
                    raise BillingError(f"regulatory parameter {code} does not cover billing period")

    def _selected_buckets(self, request: BillingRequest) -> tuple[ConsumptionBucket, ...]:
        start = datetime.combine(request.period.start, time.min, ROME)
        end = datetime.combine(request.period.end, time.min, ROME)
        selected: list[ConsumptionBucket] = []
        for bucket in request.consumption.buckets:
            local_start = bucket.interval.start.astimezone(ROME)
            local_end = bucket.interval.end.astimezone(ROME)
            if local_end <= start or local_start >= end:
                continue
            if local_start < start or local_end > end:
                raise BillingError("consumption bucket crosses requested billing period boundary")
            selected.append(bucket)
        return tuple(selected)

    @staticmethod
    def _rule_window(request_period: DatePeriod, validity: DatePeriod) -> DatePeriod | None:
        start = max(request_period.start, validity.start)
        end = min(request_period.end, validity.end)
        if end <= start:
            return None
        return DatePeriod(start=start, end=end)

    @staticmethod
    def _commercial_component(component: CostComponent) -> CostComponent:
        key = component.reconciliation_key or component.code
        quota = component.quota
        if quota is None:
            quota = (
                BillingQuota.CONSUMPTION if component.quantity is not None else BillingQuota.FIXED
            )
        return component.model_copy(
            update={
                "category": BillingCategory.SALES,
                "quota": quota,
                "reconciliation_key": key,
            }
        )

    def _linear_component(
        self,
        request: BillingRequest,
        rule: LinearRegulatoryRule,
        window: DatePeriod,
        buckets: tuple[ConsumptionBucket, ...],
        policy: RoundingPolicy,
        parameters: tuple[RegulatoryParameter, ...],
    ) -> CostComponent:
        value = rule.value
        if rule.basis == BillingBasis.FLAT:
            if not isinstance(value, Money):
                raise BillingError(f"rule {rule.code} flat basis requires Money")
            quantity = None
            raw_amount = value.amount
            unit_rate = None
            formula = "flat_amount"
        else:
            if not isinstance(value, UnitRate):
                raise BillingError(f"rule {rule.code} requires a unit rate")
            quantity, expected_unit, formula = self._linear_quantity(request, rule, window, buckets)
            if value.unit != expected_unit:
                raise BillingError(
                    f"rule {rule.code} requires {expected_unit.value}, got {value.unit.value}"
                )
            if rule.proration == ProrationPolicy.MONTHLY_TWELFTHS_PARTIAL_365 and rule.basis in (
                BillingBasis.PER_YEAR,
                BillingBasis.PER_KW_YEAR,
            ):
                raw_amount = self._arera_annual_amount(request, value, window, rule.basis)
            else:
                raw_amount = quantity * value.amount
            unit_rate = value
        self._validate_sign(rule.code, raw_amount, rule.credit)
        provenance = self._rule_provenance(rule, parameters)
        return CostComponent(
            code=f"regulatory:{rule.code}",
            description=rule.description,
            amount=Money(amount=raw_amount).round(policy),
            quantity=quantity,
            unit_rate=unit_rate,
            period=window,
            formula=formula,
            provenance=provenance,
            category=rule.category,
            quota=rule.quota,
            reconciliation_key=rule.code,
        )

    def _linear_quantity(
        self,
        request: BillingRequest,
        rule: LinearRegulatoryRule,
        window: DatePeriod,
        buckets: tuple[ConsumptionBucket, ...],
    ) -> tuple[Decimal, RateUnit, str]:
        basis = rule.basis
        if basis == BillingBasis.PER_KWH:
            quantity = (
                self._measure_quantity(request, rule.measure_code, BillingMeasureUnit.KWH, window)
                if rule.measure_code is not None
                else self._consumption_quantity(buckets, window)
            )
            return quantity, RateUnit.EUR_PER_KWH, "quantity_kwh * rate_eur_per_kwh"
        if basis == BillingBasis.PER_KVARH:
            quantity = self._measure_quantity(
                request, rule.measure_code, BillingMeasureUnit.KVARH, window
            )
            return quantity, RateUnit.EUR_PER_KVARH, "quantity_kvarh * rate_eur_per_kvarh"
        if basis == BillingBasis.PER_DAY:
            quantity = self._time_quantity(window, rule.proration)
            return quantity, RateUnit.EUR_PER_DAY, "days * rate_eur_per_day"
        if basis == BillingBasis.PER_MONTH:
            quantity = self._time_quantity(window, rule.proration)
            return quantity, RateUnit.EUR_PER_MONTH, "months * rate_eur_per_month"
        if basis == BillingBasis.PER_YEAR:
            quantity = self._time_quantity(window, rule.proration)
            return quantity, RateUnit.EUR_PER_YEAR, "years * rate_eur_per_year"
        if basis in (BillingBasis.PER_KW_DAY, BillingBasis.PER_KW_MONTH, BillingBasis.PER_KW_YEAR):
            if request.contract.supply.contracted_power is None:
                raise BillingError(f"rule {rule.code} requires contracted power")
            time_quantity = self._time_quantity(window, rule.proration)
            quantity = request.contract.supply.contracted_power.kw * time_quantity
            expected = {
                BillingBasis.PER_KW_DAY: RateUnit.EUR_PER_KW_DAY,
                BillingBasis.PER_KW_MONTH: RateUnit.EUR_PER_KW_MONTH,
                BillingBasis.PER_KW_YEAR: RateUnit.EUR_PER_KW_YEAR,
            }[basis]
            formula = {
                BillingBasis.PER_KW_DAY: "kw_days * rate_eur_per_kw_day",
                BillingBasis.PER_KW_MONTH: "kw_months * rate_eur_per_kw_month",
                BillingBasis.PER_KW_YEAR: "kw_years * rate_eur_per_kw_year",
            }[basis]
            return quantity, expected, formula
        if basis == BillingBasis.PERCENTAGE:
            raise BillingError(f"rule {rule.code} percentage basis requires percentage rule")
        raise BillingError(f"billing basis {basis.value} is not supported")

    @staticmethod
    def _arera_annual_amount(
        request: BillingRequest,
        value: UnitRate,
        window: DatePeriod,
        basis: BillingBasis,
    ) -> Decimal:
        """Apply TIT annual charges using twelfths for whole months and 365 days otherwise."""

        multiplier = Decimal(1)
        if basis == BillingBasis.PER_KW_YEAR:
            power = request.contract.supply.contracted_power
            if power is None:
                raise BillingError("rule requires contracted power")
            multiplier = power.kw
        cursor = window.start
        total = Decimal(0)
        while cursor < window.end:
            month_start = cursor.replace(day=1)
            month_end = RegulatoryBillingEngine._next_month(month_start)
            segment_end = min(window.end, month_end)
            full_month = cursor == month_start and segment_end == month_end
            if full_month:
                monthly_rate = (value.amount / Decimal(12)).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_UP
                )
                total += monthly_rate * multiplier
            else:
                total += (
                    value.amount * Decimal((segment_end - cursor).days) / Decimal(365) * multiplier
                )
            cursor = segment_end
        return total

    @staticmethod
    def _consumption_quantity(
        buckets: tuple[ConsumptionBucket, ...], window: DatePeriod
    ) -> Decimal:
        start = datetime.combine(window.start, time.min, ROME)
        end = datetime.combine(window.end, time.min, ROME)
        selected = []
        for bucket in buckets:
            local_start = bucket.interval.start.astimezone(ROME)
            local_end = bucket.interval.end.astimezone(ROME)
            if local_end <= start or local_start >= end:
                continue
            if local_start < start or local_end > end:
                raise BillingError("consumption bucket crosses regulatory rule boundary")
            selected.append(bucket)
        return sum((bucket.energy.kwh for bucket in selected), Decimal(0))

    def _threshold_component(
        self,
        request: BillingRequest,
        rule: ThresholdRegulatoryRule,
        window: DatePeriod,
        policy: RoundingPolicy,
        parameters: tuple[RegulatoryParameter, ...],
    ) -> CostComponent:
        quantity = self._evaluate_quantity(request, rule.quantity, window)
        if quantity < 0:
            raise BillingError(f"threshold rule {rule.code} produced a negative quantity")
        quantity_unit = self._quantity_unit(rule.quantity)
        if rule.rate.unit not in {
            RateUnit.EUR_PER_KWH,
            RateUnit.EUR_PER_KVARH,
            RateUnit.EUR_PER_DAY,
            RateUnit.EUR_PER_MONTH,
            RateUnit.EUR_PER_YEAR,
            RateUnit.EUR_PER_KW_DAY,
            RateUnit.EUR_PER_KW_MONTH,
            RateUnit.EUR_PER_KW_YEAR,
        }:
            raise BillingError(f"threshold rule {rule.code} has unsupported rate unit")
        expected_unit = {
            RateUnit.EUR_PER_KWH: BillingMeasureUnit.KWH,
            RateUnit.EUR_PER_KVARH: BillingMeasureUnit.KVARH,
            RateUnit.EUR_PER_KW_DAY: BillingMeasureUnit.KW,
            RateUnit.EUR_PER_KW_MONTH: BillingMeasureUnit.KW,
            RateUnit.EUR_PER_KW_YEAR: BillingMeasureUnit.KW,
        }.get(rule.rate.unit)
        if expected_unit is not None and quantity_unit not in (None, expected_unit):
            raise BillingError(f"threshold rule {rule.code} quantity unit does not match rate unit")
        raw_amount = quantity * rule.rate.amount
        self._validate_sign(rule.code, raw_amount, rule.credit)
        return CostComponent(
            code=f"regulatory:{rule.code}",
            description=rule.description,
            amount=Money(amount=raw_amount).round(policy),
            quantity=quantity,
            unit_rate=rule.rate,
            period=window,
            formula="threshold_quantity * rate",
            provenance=self._rule_provenance(rule, parameters),
            category=rule.category,
            quota=rule.quota,
            reconciliation_key=rule.code,
        )

    @staticmethod
    def _percentage_ready(
        rule: PercentageRegulatoryRule,
        window: DatePeriod,
        components: list[CostComponent],
    ) -> bool:
        scoped = [
            component
            for component in components
            if window.start <= component.period.start and component.period.end <= window.end
        ]
        by_key = {component.reconciliation_key or component.code: component for component in scoped}
        by_code = {component.code: component for component in scoped}
        if any(code not in by_key and code not in by_code for code in rule.base_codes):
            return False
        return all(
            any(component.category == category for component in scoped)
            for category in rule.base_categories
        )

    @staticmethod
    def _percentage_missing_reference(
        rule: PercentageRegulatoryRule,
        window: DatePeriod,
        components: list[CostComponent],
    ) -> str:
        scoped = [
            component
            for component in components
            if window.start <= component.period.start and component.period.end <= window.end
        ]
        by_key = {component.reconciliation_key or component.code: component for component in scoped}
        by_code = {component.code: component for component in scoped}
        for code in rule.base_codes:
            if code not in by_key and code not in by_code:
                return code
        for category in rule.base_categories:
            if not any(component.category == category for component in scoped):
                return category.value
        return "dependency"

    @staticmethod
    def _percentage_component(
        rule: PercentageRegulatoryRule,
        window: DatePeriod,
        components: list[CostComponent],
        policy: RoundingPolicy,
        parameters: tuple[RegulatoryParameter, ...],
    ) -> CostComponent:
        if rule.rate.unit != RateUnit.PERCENT:
            raise BillingError(f"percentage rule {rule.code} requires percent rate")
        scoped = [
            component
            for component in components
            if window.start <= component.period.start and component.period.end <= window.end
        ]
        by_key = {component.reconciliation_key or component.code: component for component in scoped}
        by_code = {component.code: component for component in scoped}
        missing = [code for code in rule.base_codes if code not in by_key and code not in by_code]
        if missing:
            raise BillingError(f"percentage rule {rule.code} base {missing[0]} is missing")
        category_components: list[CostComponent] = []
        for category in rule.base_categories:
            matches = [component for component in scoped if component.category == category]
            if not matches:
                raise BillingError(
                    f"percentage rule {rule.code} category {category.value} is missing"
                )
            category_components.extend(matches)
        base_components = [by_key.get(code) or by_code[code] for code in rule.base_codes]
        base_components.extend(category_components)
        base = sum(
            (component.amount.amount for component in base_components),
            Decimal(0),
        )
        raw_amount = base * rule.rate.amount / Decimal(100)
        RegulatoryBillingEngine._validate_sign(rule.code, raw_amount, rule.credit)
        return CostComponent(
            code=f"regulatory:{rule.code}",
            description=rule.description,
            amount=Money(amount=raw_amount).round(policy),
            quantity=base,
            unit_rate=rule.rate,
            period=window,
            formula="taxable_base * rate_percent / 100",
            provenance=RegulatoryBillingEngine._rule_provenance(rule, parameters),
            category=rule.category,
            quota=rule.quota,
            reconciliation_key=rule.code,
        )

    def _evaluate_quantity(
        self,
        request: BillingRequest,
        expression: QuantityExpression,
        window: DatePeriod,
    ) -> Decimal:
        if isinstance(expression, MeasureReference):
            return self._measure_quantity(request, expression.code, expression.unit, window)
        if isinstance(expression, QuantityConstant):
            return expression.value
        if isinstance(expression, AddQuantity):
            return self._evaluate_quantity(
                request, expression.left, window
            ) + self._evaluate_quantity(request, expression.right, window)
        if isinstance(expression, SubtractQuantity):
            return self._evaluate_quantity(
                request, expression.left, window
            ) - self._evaluate_quantity(request, expression.right, window)
        if isinstance(expression, MultiplyQuantity):
            return self._evaluate_quantity(request, expression.quantity, window) * expression.scalar
        if isinstance(expression, MinQuantity):
            return min(
                self._evaluate_quantity(request, expression.left, window),
                self._evaluate_quantity(request, expression.right, window),
            )
        if isinstance(expression, MaxQuantity):
            return max(
                self._evaluate_quantity(request, expression.left, window),
                self._evaluate_quantity(request, expression.right, window),
            )
        if isinstance(expression, ClampQuantity):
            value = self._evaluate_quantity(request, expression.operand, window)
            if expression.floor is not None:
                value = max(value, expression.floor)
            if expression.cap is not None:
                value = min(value, expression.cap)
            return value
        raise BillingError(f"unsupported quantity expression {type(expression)!r}")

    @staticmethod
    def _quantity_unit(expression: QuantityExpression) -> BillingMeasureUnit | None:
        if isinstance(expression, MeasureReference):
            return expression.unit
        if isinstance(expression, QuantityConstant):
            return None
        if isinstance(expression, MultiplyQuantity):
            return RegulatoryBillingEngine._quantity_unit(expression.quantity)
        if isinstance(expression, ClampQuantity):
            return RegulatoryBillingEngine._quantity_unit(expression.operand)
        if isinstance(expression, (AddQuantity, SubtractQuantity, MinQuantity, MaxQuantity)):
            left = RegulatoryBillingEngine._quantity_unit(expression.left)
            right = RegulatoryBillingEngine._quantity_unit(expression.right)
            if left is not None and right is not None and left != right:
                raise BillingError("quantity expression combines incompatible units")
            return left or right
        raise BillingError(f"unsupported quantity expression {type(expression)!r}")

    def _measure_quantity(
        self,
        request: BillingRequest,
        code: str | None,
        expected_unit: BillingMeasureUnit,
        window: DatePeriod,
    ) -> Decimal:
        if code is None:
            raise BillingError(f"a {expected_unit.value} measure code is required")
        candidates = tuple(measure for measure in request.measurements if measure.code == code)
        if not candidates:
            if code == "consumption_kwh" and expected_unit == BillingMeasureUnit.KWH:
                buckets = self._selected_buckets(request)
                return self._consumption_quantity(buckets, window)
            if code == "contracted_power_kw" and expected_unit == BillingMeasureUnit.KW:
                power = request.contract.supply.contracted_power
                if power is None:
                    raise BillingError("contracted power is missing")
                return power.kw
            raise BillingError(f"billing measure {code} is missing")
        if len(candidates) != 1:
            raise BillingError(f"billing measure {code} is ambiguous")
        measure = candidates[0]
        if measure.unit != expected_unit:
            raise BillingError(f"billing measure {code} unit does not match rule")
        if measure.status != VerificationStatus.VERIFIED:
            raise BillingError(f"billing measure {code} is not verified")
        if not measure.provenance:
            raise BillingError(f"billing measure {code} provenance is missing")
        if window.start < measure.period.start or window.end > measure.period.end:
            raise BillingError(f"billing measure {code} does not cover rule period")
        return measure.value

    @staticmethod
    def _time_quantity(window: DatePeriod, policy: ProrationPolicy | None) -> Decimal:
        if policy is None:
            raise BillingError("temporal billing rule requires proration policy")
        if policy == ProrationPolicy.FULL_PERIOD:
            return Decimal(1)
        if policy == ProrationPolicy.ACTUAL_DAYS:
            return Decimal((window.end - window.start).days)
        if policy == ProrationPolicy.CALENDAR_MONTH_FRACTION:
            cursor = window.start
            result = Decimal(0)
            while cursor < window.end:
                month_start = cursor.replace(day=1)
                month_end = RegulatoryBillingEngine._next_month(month_start)
                segment_end = min(window.end, month_end)
                denominator = Decimal((month_end - month_start).days)
                result += Decimal((segment_end - cursor).days) / denominator
                cursor = segment_end
            return result
        if policy == ProrationPolicy.CALENDAR_YEAR_FRACTION:
            cursor = window.start
            result = Decimal(0)
            while cursor < window.end:
                year_start = cursor.replace(month=1, day=1)
                year_end = year_start.replace(year=year_start.year + 1)
                segment_end = min(window.end, year_end)
                denominator = Decimal((year_end - year_start).days)
                result += Decimal((segment_end - cursor).days) / denominator
                cursor = segment_end
            return result
        if policy == ProrationPolicy.MONTHLY_TWELFTHS_PARTIAL_365:
            cursor = window.start
            result = Decimal(0)
            while cursor < window.end:
                month_start = cursor.replace(day=1)
                month_end = RegulatoryBillingEngine._next_month(month_start)
                segment_end = min(window.end, month_end)
                if cursor == month_start and segment_end == month_end:
                    result += Decimal(1) / Decimal(12)
                else:
                    result += Decimal((segment_end - cursor).days) / Decimal(365)
                cursor = segment_end
            return result
        policy_name = getattr(policy, "value", repr(policy))
        raise BillingError(f"unsupported proration policy {policy_name}")

    @staticmethod
    def _next_month(value: date) -> date:
        if value.month == 12:
            return value.replace(year=value.year + 1, month=1)
        return value.replace(month=value.month + 1)

    @staticmethod
    def _rule_provenance(
        rule: LinearRegulatoryRule | ThresholdRegulatoryRule | PercentageRegulatoryRule,
        parameters: tuple[RegulatoryParameter, ...],
    ) -> tuple[Provenance, ...]:
        result: list[Provenance] = list(rule.provenance)
        by_code = {parameter.code: parameter for parameter in parameters}
        for code in rule.parameter_codes:
            for item in by_code[code].provenance:
                if item not in result:
                    result.append(item)
        return tuple(result)

    @staticmethod
    def _validate_sign(code: str, amount: Decimal, credit: bool) -> None:
        if credit and amount > 0:
            raise BillingError(f"credit rule {code} produced a positive amount")
        if not credit and amount < 0:
            raise BillingError(f"charge rule {code} produced a negative amount")

    @staticmethod
    def _external_component(item: ExternalBillItem) -> CostComponent:
        return CostComponent(
            code=f"external:{item.code}",
            description=item.description,
            amount=item.amount,
            period=item.period,
            formula="external_amount",
            provenance=item.provenance,
            category=item.category,
            quota=item.quota,
            reconciliation_key=item.reconciliation_key,
        )

    @staticmethod
    def _validate_external_item(item: ExternalBillItem, period: DatePeriod) -> None:
        if item.status != VerificationStatus.VERIFIED:
            raise BillingError(f"external bill item {item.code} is not verified")
        if not item.provenance:
            raise BillingError(f"external bill item {item.code} provenance is missing")
        if item.period.start < period.start or item.period.end > period.end:
            raise BillingError(f"external bill item {item.code} is outside billing period")

    @staticmethod
    def _component_key(component: CostComponent) -> str:
        return component.reconciliation_key or component.code

    @staticmethod
    def _reconcile(
        observed: Bill | ObservedBill | None,
        computed: Bill,
    ) -> BillReconciliation | None:
        if observed is None:
            return None
        if observed.contract_id != computed.contract_id or observed.period != computed.period:
            raise BillingError("observed bill contract or period does not match computed bill")
        if isinstance(observed, Bill):
            observed_components = tuple(
                ObservedBillComponent(
                    reconciliation_key=component.reconciliation_key or component.code,
                    code=component.code,
                    description=component.description,
                    category=component.category or BillingCategory.OTHER,
                    quota=component.quota or BillingQuota.FIXED,
                    amount=component.amount,
                    period=component.period,
                )
                for component in observed.breakdown.components
            )
            observed_total = observed.declared_total or observed.breakdown.total
        else:
            observed_components = observed.components
            observed_total = observed.declared_total or sum(
                (component.amount for component in observed_components), Money(amount=Decimal(0))
            )
        observed_keys = [component.reconciliation_key for component in observed_components]
        if len(observed_keys) != len(set(observed_keys)):
            raise BillingError("observed bill contains duplicate reconciliation keys")
        for component in observed_components:
            if (
                component.period.start < computed.period.start
                or component.period.end > computed.period.end
            ):
                raise BillingError(
                    f"observed component {component.reconciliation_key} is outside computed period"
                )
        computed_by_key = {
            RegulatoryBillingEngine._component_key(c): c for c in computed.breakdown.components
        }
        observed_by_key = {
            component.reconciliation_key: component for component in observed_components
        }
        keys = list(computed_by_key)
        keys.extend(key for key in observed_by_key if key not in computed_by_key)
        differences: list[ComponentDifference] = []
        unmatched_computed: list[str] = []
        unmatched_observed: list[str] = []
        passed = True
        for key in keys:
            computed_component = computed_by_key.get(key)
            observed_component = observed_by_key.get(key)
            if computed_component is None:
                assert observed_component is not None
                unmatched_observed.append(key)
                differences.append(
                    ComponentDifference(
                        reconciliation_key=key,
                        observed_amount=observed_component.amount,
                        within_tolerance=False,
                    )
                )
                passed = False
                continue
            if observed_component is None:
                unmatched_computed.append(key)
                differences.append(
                    ComponentDifference(
                        reconciliation_key=key,
                        computed_amount=computed_component.amount,
                        within_tolerance=False,
                    )
                )
                passed = False
                continue
            difference = Money(
                amount=computed_component.amount.amount - observed_component.amount.amount
            )
            within = abs(difference.amount) <= TOLERANCE.amount
            differences.append(
                ComponentDifference(
                    reconciliation_key=key,
                    computed_amount=computed_component.amount,
                    observed_amount=observed_component.amount,
                    difference=difference,
                    within_tolerance=within,
                )
            )
            passed = passed and within
        total_difference = Money(amount=computed.breakdown.total.amount - observed_total.amount)
        total_within = abs(total_difference.amount) <= TOLERANCE.amount
        passed = passed and total_within and not unmatched_computed and not unmatched_observed
        return BillReconciliation(
            status=ReconciliationStatus.PASSED if passed else ReconciliationStatus.FAILED,
            tolerance=TOLERANCE,
            components=tuple(differences),
            total_difference=total_difference,
            unmatched_computed=tuple(unmatched_computed),
            unmatched_observed=tuple(unmatched_observed),
        )

    @staticmethod
    def _bill_id(request: BillingRequest) -> str:
        payload = request.model_dump(mode="json", exclude={"observed_bill"})
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return f"bill:{sha256(encoded).hexdigest()}"

    @staticmethod
    def _billing_id(request: BillingRequest) -> str:
        payload = request.model_dump(mode="json")
        encoded = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
        return f"billing:{sha256(encoded).hexdigest()}"

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
