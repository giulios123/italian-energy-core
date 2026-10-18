"""Projection-time interpretation of Portale component price-validity fields."""

from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from itertools import pairwise

from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers.models import (
    PORTAL_ECONOMIC_VALIDITY_VERSION,
    PortalComponentPriceValidity,
    PortalEconomicComponent,
    PortalEconomicDurationScope,
    PortalEconomicTerms,
    PortalEconomicTermsBasis,
    PortalOfferExclusionCode,
    PortalOfferRecord,
    PortalPriceValidityKind,
)

type _Interval = tuple[date, date] | None


class EconomicValidityError(ValueError):
    def __init__(
        self,
        code: PortalOfferExclusionCode,
        detail: str,
        *,
        locator: ProvenanceLocator | None = None,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.locator = locator


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _month_after(value: date) -> date:
    return date(value.year + (value.month == 12), 1 if value.month == 12 else value.month + 1, 1)


def _resolved_interval(validity: PortalComponentPriceValidity, activation_date: date) -> _Interval:
    if validity.kind == PortalPriceValidityKind.DEFAULT:
        return None
    if validity.kind == PortalPriceValidityKind.DURATION:
        assert validity.duration_months is not None
        return activation_date, _add_months(activation_date, validity.duration_months)
    if validity.kind == PortalPriceValidityKind.VALID_UNTIL:
        assert validity.month is not None
        return activation_date, _month_after(validity.month)
    if validity.kind == PortalPriceValidityKind.MONTH:
        assert validity.month is not None
        return validity.month, _month_after(validity.month)
    raise EconomicValidityError(
        PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE,
        "component has an explicit malformed or unsupported PeriodoValidita",
    )


def _group_key(component: PortalEconomicComponent) -> tuple[object, ...]:
    return (
        component.code,
        component.unit,
        component.band,
        component.macroarea,
        component.index_code,
        component.coefficient,
        component.semantic,
        component.discount,
        component.pricing_treatment,
    )


def _signature(component: PortalEconomicComponent) -> tuple[object, ...]:
    return (
        component.amount,
        component.unit,
        component.index_code,
        component.coefficient,
        component.discount,
    )


def _coverage_intersection(interval: _Interval, period: DatePeriod) -> tuple[date, date] | None:
    if interval is None:
        return period.start, period.end
    start = max(interval[0], period.start)
    end = min(interval[1], period.end)
    return (start, end) if start < end else None


def _normalise_component_groups(
    record: PortalOfferRecord, activation_date: date, economic_period: DatePeriod
) -> tuple[PortalEconomicComponent, ...]:
    groups: dict[tuple[object, ...], list[tuple[PortalEconomicComponent, _Interval]]] = defaultdict(
        list
    )
    unchanged: list[PortalEconomicComponent] = []
    for component in record.components:
        if component.source_code is not None:
            # Dispatching references and direct additions follow their own source or
            # CdispD period; the offer subscription window is not their tariff period.
            unchanged.append(component.model_copy(update={"period": None}))
            continue
        if component.price_validity is None:
            raise EconomicValidityError(
                PortalOfferExclusionCode.ECONOMIC_TERMS_UNVERIFIED,
                "component price validity is absent from this parser snapshot; "
                "refresh the catalogue",
            )
        interval = _resolved_interval(component.price_validity, activation_date)
        groups[_group_key(component)].append((component, interval))

    projected: list[PortalEconomicComponent] = list(unchanged)
    for group in groups.values():
        boundaries = {economic_period.start, economic_period.end}
        for _, interval in group:
            overlap = _coverage_intersection(interval, economic_period)
            if overlap is not None:
                boundaries.update(overlap)
        ordered = sorted(boundaries)
        chosen_segments: list[tuple[date, date, PortalEconomicComponent | None]] = []
        for start, end in pairwise(ordered):
            explicit = [
                component
                for component, interval in group
                if interval is not None and interval[0] <= start and interval[1] >= end
            ]
            defaults = [component for component, interval in group if interval is None]
            selected = explicit or defaults
            if not selected:
                if group[0][0].discount:
                    chosen_segments.append((start, end, None))
                    continue
                raise EconomicValidityError(
                    PortalOfferExclusionCode.PERIOD_NOT_COVERED,
                    f"component {group[0][0].code} has no price for part of the economic period",
                )
            signatures = {_signature(component) for component in selected}
            if len(signatures) != 1:
                raise EconomicValidityError(
                    PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE,
                    f"component {selected[0].code} has overlapping prices with different values",
                )
            chosen_segments.append((start, end, selected[0]))

        valued = [component for _, _, component in chosen_segments if component is not None]
        signatures = {_signature(component) for component in valued}
        if len(signatures) > 1:
            raise EconomicValidityError(
                PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE,
                f"component {valued[0].code} changes price inside the requested period",
            )
        if not valued:
            continue
        missing_segments = [segment for segment in chosen_segments if segment[2] is None]
        if missing_segments:
            if not group[0][0].discount:
                raise EconomicValidityError(
                    PortalOfferExclusionCode.PERIOD_NOT_COVERED,
                    f"component {group[0][0].code} has uncovered time in the economic period",
                )
            active = [segment for segment in chosen_segments if segment[2] is not None]
            if not active or any(
                previous[1] != current[0] for previous, current in pairwise(active)
            ):
                raise EconomicValidityError(
                    PortalOfferExclusionCode.ECONOMIC_PERIOD_NOT_REPRESENTABLE,
                    "a temporary discount has multiple disjoint active windows",
                )
            start = active[0][0]
            end = active[-1][1]
            source = active[0][2]
            assert source is not None
            projected.append(source.model_copy(update={"period": DatePeriod(start=start, end=end)}))
            continue
        source = valued[0]
        projected.append(source.model_copy(update={"period": None}))
    return tuple(projected)


def _duration_for_validity(
    validity: PortalComponentPriceValidity, activation_date: date
) -> int | None:
    if validity.kind == PortalPriceValidityKind.DURATION:
        return validity.duration_months
    interval = _resolved_interval(validity, activation_date)
    if interval is None or interval[0] > activation_date or interval[1] <= activation_date:
        return None
    months = (interval[1].year - activation_date.year) * 12 + (
        interval[1].month - activation_date.month
    )
    if interval[1].day < activation_date.day:
        months -= 1
    return months if months > 0 else None


def _source_provenance(
    record: PortalOfferRecord, component: PortalEconomicComponent | None = None
) -> tuple[Provenance, ...]:
    if component is not None and component.source_provenance:
        return component.source_provenance
    return record.source_provenance


def _component_duration_evidence(
    record: PortalOfferRecord, activation_date: date
) -> tuple[int | None, PortalEconomicDurationScope | None, tuple[Provenance, ...]]:
    priced = tuple(
        component
        for component in record.components
        if component.source_code is None and component.amount is not None
    )
    if not priced:
        return None, None, ()
    grouped: dict[tuple[object, ...], list[PortalEconomicComponent]] = defaultdict(list)
    for component in priced:
        grouped[_group_key(component)].append(component)
    durations: list[int] = []
    provenanced: list[Provenance] = []
    all_groups_explicit = True
    all_energy_explicit = True
    energy_durations: list[int] = []
    energy_group_count = 0
    for group in grouped.values():
        is_energy = any(
            (item.semantic is not None and item.semantic.value == "energy_price")
            or item.macroarea in {"04", "06"}
            for item in group
        )
        if is_energy:
            energy_group_count += 1
        validities = tuple(item.price_validity for item in group if item.price_validity is not None)
        explicit = tuple(
            validity
            for validity in validities
            if validity.kind != PortalPriceValidityKind.DEFAULT
            and validity.kind != PortalPriceValidityKind.UNSUPPORTED
        )
        group_durations = tuple(
            duration
            for validity in explicit
            if (duration := _duration_for_validity(validity, activation_date)) is not None
        )
        if not group_durations:
            all_groups_explicit = False
            if is_energy:
                all_energy_explicit = False
            continue
        shortest = min(group_durations)
        durations.append(shortest)
        if is_energy:
            energy_durations.append(shortest)
        for item in group:
            if item.price_validity in explicit:
                provenanced.extend(_source_provenance(record, item))
    if all_groups_explicit and durations:
        return min(durations), PortalEconomicDurationScope.SELLER_CONDITIONS, tuple(provenanced)
    if all_energy_explicit and energy_group_count and energy_durations:
        return min(energy_durations), PortalEconomicDurationScope.ENERGY_PRICE, tuple(provenanced)
    return None, None, ()


def _dedupe_provenance(values: tuple[Provenance, ...]) -> tuple[Provenance, ...]:
    by_key = {}
    for value in values:
        key = repr(value.model_dump(mode="json"))
        by_key[key] = value
    return tuple(by_key[key] for key in sorted(by_key))


def project_economic_validity(
    record: PortalOfferRecord,
    activation_date: date,
    economic_period: DatePeriod,
) -> tuple[PortalOfferRecord, PortalEconomicTerms]:
    """Apply official component validity over a projected period, without DATA_FINE clipping."""
    if record.economic_validity_version != PORTAL_ECONOMIC_VALIDITY_VERSION:
        raise EconomicValidityError(
            PortalOfferExclusionCode.ECONOMIC_TERMS_UNVERIFIED,
            "source snapshot predates structured economic validity; refresh the catalogue",
        )
    if activation_date != economic_period.start:
        raise ValueError("activation date must equal the economic period start")
    if not record.source_provenance:
        raise EconomicValidityError(
            PortalOfferExclusionCode.MISSING_PROVENANCE,
            "economic validity has no source provenance",
        )
    if record.unmodeled_commercial_terms:
        source = record.unmodeled_commercial_terms[0]
        raise EconomicValidityError(
            PortalOfferExclusionCode.UNSUPPORTED_COMMERCIAL_COMPONENT,
            "structured Sconto terms are preserved but not modeled; no discount or duration "
            "was inferred",
            locator=source.locator,
        )
    if record.duration_months is not None:
        declared_end = _add_months(activation_date, record.duration_months)
        if declared_end < economic_period.end:
            raise EconomicValidityError(
                PortalOfferExclusionCode.PERIOD_NOT_COVERED,
                "declared economic-conditions duration does not cover the requested period",
            )
    for component in record.components:
        if component.source_code is None and component.price_validity is None:
            raise EconomicValidityError(
                PortalOfferExclusionCode.ECONOMIC_TERMS_UNVERIFIED,
                "component price validity is absent from this parser snapshot; "
                "refresh the catalogue",
            )

    components = _normalise_component_groups(record, activation_date, economic_period)
    top_provenance = record.economic_conditions_duration_provenance
    known_duration: int | None
    scope: PortalEconomicDurationScope | None
    if record.duration_months is not None:
        if not top_provenance:
            raise EconomicValidityError(
                PortalOfferExclusionCode.ECONOMIC_TERMS_UNVERIFIED,
                "declared economic-conditions duration has no field-level provenance",
            )
        known_duration = record.duration_months
        scope = PortalEconomicDurationScope.SELLER_CONDITIONS
        basis = PortalEconomicTermsBasis.DECLARED_ECONOMIC_CONDITIONS
        evidence = top_provenance
    else:
        known_duration, scope, component_provenance = _component_duration_evidence(
            record, activation_date
        )
        if known_duration is not None and scope is not None:
            basis = PortalEconomicTermsBasis.EXPLICIT_COMPONENT_VALIDITY
            evidence = component_provenance
        else:
            has_default_energy_price = any(
                item.source_code is None
                and item.amount is not None
                and item.price_validity is not None
                and item.price_validity.kind == PortalPriceValidityKind.DEFAULT
                and (
                    (item.semantic is not None and item.semantic.value == "energy_price")
                    or item.macroarea in {"04", "06"}
                )
                for item in record.components
            )
            basis = (
                PortalEconomicTermsBasis.PUBLISHED_DEFAULT_PRICES
                if has_default_energy_price
                else PortalEconomicTermsBasis.UNKNOWN
            )
            evidence = top_provenance or record.source_provenance

    terms = PortalEconomicTerms(
        activation_date=activation_date,
        estimate_period=economic_period,
        known_duration_months=known_duration,
        duration_scope=scope,
        extends_beyond_12_months=(known_duration > 12) if known_duration is not None else None,
        basis=basis,
        provenance=_dedupe_provenance(tuple(evidence)),
    )
    projected_record = record.model_copy(
        update={"components": components, "tariff_validity": economic_period}
    )
    return projected_record, terms
