"""Deterministic mapping from Portale Offerte records to canonical tariffs."""

from __future__ import annotations

import calendar
import hashlib
import json
from collections import Counter
from datetime import date

from italian_energy.arera.cdispd_reference import CdispDReferenceSnapshot
from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.domain.costs import ComponentMeaning, ComponentPricingTreatment
from italian_energy.domain.formula import (
    AddPrice,
    IndexReference,
    MultiplyPrice,
    PriceConstant,
    PriceExpression,
    ScalarConstant,
)
from italian_energy.domain.market import MarketData
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.offer import Offer
from italian_energy.domain.provenance import ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.tariff import (
    BandFormula,
    BandPrice,
    ChargeBasis,
    ChargeRule,
    FixedTariff,
    IndexedTariff,
)
from italian_energy.domain.time import DatePeriod, Granularity
from italian_energy.portal_offers.models import (
    NormalizedPortalOffer,
    PortalCatalog,
    PortalCdispDProjection,
    PortalComponentSemantic,
    PortalEligibilityProfile,
    PortalLossTreatment,
    PortalOfferExclusion,
    PortalOfferExclusionCode,
    PortalOfferRecord,
    PortalOffersImportResult,
    PortalOffersSnapshot,
    PortalOfferType,
    PortalPricingTreatment,
)
from italian_energy.portal_offers.parameters import projection_matches_snapshot

_INDEX_CODES = {"01": "PUN", "05": "PUN", "08": "PE", "12": "PUN", "PUN": "PUN", "PE": "PE"}
_BANDS = {"01": "F1", "02": "F2", "03": "F3", "07": "BF1", "08": "BF23", "91": "ALL"}
_UNIT_MAP = {
    "EUR/kWh": RateUnit.EUR_PER_KWH,
    "EUR/year": RateUnit.EUR_PER_YEAR,
    "EUR/kW/year": RateUnit.EUR_PER_KW_YEAR,
}

_COMPONENT_MEANING_MAP = {
    PortalComponentSemantic.ENERGY_PRICE: ComponentMeaning.ENERGY_PRICE,
    PortalComponentSemantic.COMMERCIAL_CHARGE: ComponentMeaning.COMMERCIAL_CHARGE,
    PortalComponentSemantic.DISPATCHING: ComponentMeaning.DISPATCHING,
    PortalComponentSemantic.CAPACITY_MARKET: ComponentMeaning.CAPACITY_MARKET,
    PortalComponentSemantic.DISPATCHING_CAPACITY_AGGREGATE: (
        ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
    ),
    PortalComponentSemantic.SELLER_DEFINED_DISPATCHING: (
        ComponentMeaning.SELLER_DEFINED_DISPATCHING
    ),
    PortalComponentSemantic.REGULATED_FIXED_DISPATCHING: (
        ComponentMeaning.REGULATED_FIXED_DISPATCHING
    ),
    PortalComponentSemantic.SAFEGUARD_REINTEGRATION: ComponentMeaning.SAFEGUARD_REINTEGRATION,
    PortalComponentSemantic.GRADUAL_PROTECTION_REINTEGRATION: (
        ComponentMeaning.GRADUAL_PROTECTION_REINTEGRATION
    ),
    PortalComponentSemantic.UNSUPPORTED: ComponentMeaning.UNSUPPORTED,
}
_COMPONENT_PRICING_TREATMENT_MAP = {
    PortalPricingTreatment.TARIFF_ADDITION: ComponentPricingTreatment.TARIFF_ADDITION,
    PortalPricingTreatment.REGULATORY_REFERENCE: ComponentPricingTreatment.REGULATORY_REFERENCE,
    PortalPricingTreatment.UNSUPPORTED: ComponentPricingTreatment.UNSUPPORTED,
}


def _component_meaning(
    semantic: PortalComponentSemantic | None,
) -> ComponentMeaning | None:
    return None if semantic is None else _COMPONENT_MEANING_MAP[semantic]


def _component_loss_inclusion(treatment: PortalLossTreatment) -> bool | None:
    if treatment == PortalLossTreatment.INCLUDED:
        return True
    if treatment == PortalLossTreatment.EXCLUDED:
        return False
    return None


def _add_months_clamped(value: date, months: int) -> date:
    """Add calendar months while clamping to the target month's last day."""
    absolute = value.year * 12 + value.month - 1 + months
    year, month_index = divmod(absolute, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _effective_validity(record: PortalOfferRecord, activation: date) -> DatePeriod:
    """Resolve a relative offer duration from the simulated activation date."""
    start = max(record.tariff_validity.start, activation)
    end = record.tariff_validity.end
    if record.duration_months is not None:
        end = min(end, _add_months_clamped(activation, record.duration_months))
    return DatePeriod(start=start, end=end)


def _record_index_codes(record: PortalOfferRecord) -> tuple[str, ...]:
    values = list(record.index_codes or ((record.index_code,) if record.index_code else ()))
    values.extend(
        component.index_code for component in record.components if component.index_code is not None
    )
    result: list[str] = []
    for raw in values:
        mapped = _INDEX_CODES.get(raw.upper())
        if mapped is None:
            raise LookupError(f"indexed offer references an unsupported public index: {raw}")
        if mapped not in result:
            result.append(mapped)
    return tuple(result)


def _contains(values: tuple[str, ...], expected: str | None) -> bool:
    if not values:
        return True
    if expected is None:
        return False
    lowered = expected.lower()
    return any(
        value.lower() == lowered or "qualsiasi" in value.lower() or "any" in value.lower()
        for value in values
    )


def _source_offer_id(record: PortalOfferRecord) -> str:
    return f"portal:{record.catalog.value}:{record.source_offer_id}"


def _exclude(
    record: PortalOfferRecord,
    code: PortalOfferExclusionCode,
    detail: str,
    *,
    locator: ProvenanceLocator | None = None,
) -> PortalOfferExclusion:
    return PortalOfferExclusion(
        offer_id=_source_offer_id(record),
        code=code,
        detail=detail,
        locator=(
            locator
            if locator is not None
            else record.source_provenance[0].locator
            if record.source_provenance
            else None
        ),
    )


def _map_band(raw: str | None, *, only_band: str | None = None) -> str:
    if only_band is not None:
        return only_band
    return _BANDS.get(raw or "", "ALL")


def _unit(value: str | None) -> RateUnit | None:
    return _UNIT_MAP.get(value) if value is not None else None


def _commercial_component_exclusion(
    record: PortalOfferRecord,
    eligibility: PortalEligibilityProfile,
    cdispd_reference: CdispDReferenceSnapshot | None,
    cdispd_period: DatePeriod,
    cdispd_projection: PortalCdispDProjection | None = None,
    snapshot: PortalOffersSnapshot | None = None,
) -> PortalOfferExclusion | None:
    unsupported = next(
        (
            component
            for component in record.components
            if component.pricing_treatment == PortalPricingTreatment.UNSUPPORTED
        ),
        None,
    )
    if unsupported is not None:
        code = unsupported.source_code or "missing"
        return _exclude(
            record,
            PortalOfferExclusionCode.UNSUPPORTED_COMMERCIAL_COMPONENT,
            f"unsupported TIPO_DISPACCIAMENTO={code}; source fields are retained for audit",
            locator=unsupported.locator,
        )

    aggregates = tuple(
        component
        for component in record.components
        if component.semantic == PortalComponentSemantic.DISPATCHING_CAPACITY_AGGREGATE
    )
    for aggregate in aggregates:
        overlap = next(
            (
                component
                for component in record.components
                if component is not aggregate and component.semantic in aggregate.included_semantics
            ),
            None,
        )
        if overlap is not None:
            return _exclude(
                record,
                PortalOfferExclusionCode.AMBIGUOUS_COMPONENT_COMPOSITION,
                "aggregated CdispD overlaps a separate dispatching or capacity-market component; "
                "refusing possible double count",
                locator=aggregate.locator,
            )
    if len(aggregates) > 1:
        return _exclude(
            record,
            PortalOfferExclusionCode.AMBIGUOUS_COMPONENT_COMPOSITION,
            "multiple aggregated CdispD components are present; refusing possible double count",
            locator=aggregates[0].locator,
        )

    for missing in record.components:
        if missing.source_code is None or not (
            missing.pricing_treatment == PortalPricingTreatment.REGULATORY_REFERENCE
            or (
                missing.pricing_treatment == PortalPricingTreatment.TARIFF_ADDITION
                and (missing.amount is None or missing.unit is None)
            )
        ):
            continue
        code = missing.source_code or "unknown"
        if (
            code == "14"
            and missing.semantic == PortalComponentSemantic.DISPATCHING_CAPACITY_AGGREGATE
        ):
            if eligibility.residential is None:
                detail = "TIPO_DISPACCIAMENTO=14 requires an explicit resident/non-resident profile"
            elif cdispd_projection is not None:
                if snapshot is None or not projection_matches_snapshot(
                    cdispd_projection, snapshot, cdispd_period
                ):
                    detail = (
                        "daily CdispD projection does not match the verified catalog snapshot, "
                        "source date or projected period"
                    )
                else:
                    continue
            elif cdispd_reference is None:
                detail = (
                    "TIPO_DISPACCIAMENTO=14 requires a verified current CdispD parameter "
                    "for a projection or a monthly ARERA reference"
                )
            else:
                segment = (
                    AreraCustomerSegment.RESIDENT
                    if eligibility.residential
                    else AreraCustomerSegment.NON_RESIDENT
                )
                if not cdispd_reference.covers(segment, cdispd_period):
                    detail = (
                        "verified ARERA CdispD reference does not cover every requested month; "
                        "monthly values are never carried forward"
                    )
                else:
                    continue
            return _exclude(
                record,
                PortalOfferExclusionCode.MISSING_COMMERCIAL_COMPONENT,
                f"{detail}; no zero or split was inferred",
                locator=missing.locator,
            )
        return _exclude(
            record,
            PortalOfferExclusionCode.MISSING_COMMERCIAL_COMPONENT,
            f"TIPO_DISPACCIAMENTO={code} is a regulatory reference without a directly "
            "priced source value; no zero or split was inferred",
            locator=missing.locator,
        )
    return None


def _charge_rules(
    record: PortalOfferRecord,
    eligibility: PortalEligibilityProfile | None = None,
    cdispd_reference: CdispDReferenceSnapshot | None = None,
    cdispd_period: DatePeriod | None = None,
    cdispd_projection: PortalCdispDProjection | None = None,
    snapshot: PortalOffersSnapshot | None = None,
) -> tuple[tuple[ChargeRule, ...], tuple[ChargeRule, ...], tuple[ChargeRule, ...]]:
    fixed: list[ChargeRule] = []
    additional: list[ChargeRule] = []
    discounts: list[ChargeRule] = []
    for component in record.components:
        if component.source_code is not None and (
            component.pricing_treatment != PortalPricingTreatment.TARIFF_ADDITION
        ):
            continue
        if record.catalog == PortalCatalog.PLACET and (
            component.code.startswith("p_vol_") or component.code == "alpha"
        ):
            continue
        unit = _unit(component.unit)
        if unit is None or component.amount is None:
            continue
        if unit == RateUnit.EUR_PER_KWH and component.macroarea in {"04", "06"}:
            continue
        if unit == RateUnit.EUR_PER_KWH:
            basis = ChargeBasis.PER_KWH
        elif unit == RateUnit.EUR_PER_YEAR:
            basis = ChargeBasis.PER_YEAR
        elif unit == RateUnit.EUR_PER_KW_YEAR:
            basis = ChargeBasis.PER_KW_YEAR
        value = UnitRate(amount=component.amount, unit=unit)
        discount = component.discount
        if discount:
            discounts.append(
                ChargeRule(
                    code=component.code,
                    description=component.description,
                    basis=basis,
                    value=UnitRate(amount=-abs(component.amount), unit=unit),
                    band=_map_band(component.band) if basis == ChargeBasis.PER_KWH else None,
                    discount=True,
                    meaning=_component_meaning(component.semantic),
                    pricing_treatment=_COMPONENT_PRICING_TREATMENT_MAP[component.pricing_treatment],
                    losses_included=_component_loss_inclusion(component.loss_treatment),
                    included_semantics=tuple(
                        _COMPONENT_MEANING_MAP[semantic]
                        for semantic in component.included_semantics
                    ),
                    validity=component.period,
                    provenance=component.source_provenance or record.source_provenance,
                )
            )
        else:
            target = (
                fixed if basis in {ChargeBasis.PER_YEAR, ChargeBasis.PER_KW_YEAR} else additional
            )
            target.append(
                ChargeRule(
                    code=component.code,
                    description=component.description,
                    basis=basis,
                    value=value,
                    band=_map_band(component.band) if basis == ChargeBasis.PER_KWH else None,
                    meaning=_component_meaning(component.semantic),
                    pricing_treatment=_COMPONENT_PRICING_TREATMENT_MAP[component.pricing_treatment],
                    losses_included=_component_loss_inclusion(component.loss_treatment),
                    included_semantics=tuple(
                        _COMPONENT_MEANING_MAP[semantic]
                        for semantic in component.included_semantics
                    ),
                    validity=component.period,
                    provenance=component.source_provenance or record.source_provenance,
                )
            )
    cdispd_component = next(
        (
            component
            for component in record.components
            if component.source_code == "14"
            and component.semantic == PortalComponentSemantic.DISPATCHING_CAPACITY_AGGREGATE
        ),
        None,
    )
    if cdispd_component is not None:
        if eligibility is None or eligibility.residential is None or cdispd_period is None:
            raise ValueError("verified CdispD source and resident profile were not resolved")
        if cdispd_projection is not None:
            if snapshot is None or not projection_matches_snapshot(
                cdispd_projection, snapshot, cdispd_period
            ):
                raise ValueError("daily CdispD projection does not match its frozen catalog")
            additional.append(
                ChargeRule(
                    code=cdispd_component.code,
                    description="Dispacciamento e mercato capacità (CdispD)",
                    basis=ChargeBasis.PER_KWH,
                    value=cdispd_projection.parameter.rate,
                    meaning=ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE,
                    pricing_treatment=ComponentPricingTreatment.REGULATORY_REFERENCE,
                    losses_included=True,
                    included_semantics=(
                        ComponentMeaning.DISPATCHING,
                        ComponentMeaning.CAPACITY_MARKET,
                    ),
                    validity=cdispd_projection.period,
                    provenance=(
                        *cdispd_component.source_provenance,
                        *cdispd_projection.parameter.provenance,
                    ),
                )
            )
        else:
            if cdispd_reference is None:
                raise ValueError("verified CdispD reference and resident profile were not resolved")
            segment = (
                AreraCustomerSegment.RESIDENT
                if eligibility.residential
                else AreraCustomerSegment.NON_RESIDENT
            )
            for charge in cdispd_reference.charges_for_period(segment, cdispd_period):
                additional.append(
                    ChargeRule(
                        code=cdispd_component.code,
                        description="Dispacciamento e mercato capacità (CdispD)",
                        basis=ChargeBasis.PER_KWH,
                        value=charge.rate,
                        meaning=ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE,
                        pricing_treatment=ComponentPricingTreatment.REGULATORY_REFERENCE,
                        losses_included=True,
                        included_semantics=(
                            ComponentMeaning.DISPATCHING,
                            ComponentMeaning.CAPACITY_MARKET,
                        ),
                        validity=charge.validity,
                        provenance=(
                            *cdispd_component.source_provenance,
                            *charge.provenance,
                        ),
                    )
                )
    return tuple(fixed), tuple(additional), tuple(discounts)


def _fixed_tariff(
    record: PortalOfferRecord,
    eligibility: PortalEligibilityProfile | None = None,
    cdispd_reference: CdispDReferenceSnapshot | None = None,
    cdispd_period: DatePeriod | None = None,
    cdispd_projection: PortalCdispDProjection | None = None,
    snapshot: PortalOffersSnapshot | None = None,
) -> FixedTariff:
    prices: list[BandPrice] = []
    for component in record.components:
        if component.source_code is not None:
            continue
        unit = _unit(component.unit)
        if unit != RateUnit.EUR_PER_KWH or component.amount is None:
            continue
        if component.macroarea not in {None, "04", "06"}:
            continue
        prices.append(
            BandPrice(
                band=_map_band(component.band),
                rate=UnitRate(amount=component.amount, unit=RateUnit.EUR_PER_KWH),
            )
        )
    if not prices:
        raise ValueError("fixed offer has no EUR/kWh energy component")
    grouped: dict[str, UnitRate] = {}
    for price in prices:
        previous = grouped.get(price.band)
        if previous is not None and previous.amount != price.rate.amount:
            raise ValueError(f"fixed offer has conflicting price for band {price.band}")
        grouped[price.band] = price.rate
    # The XML repeats the same value for all three bands for a monoraria offer.
    if len(grouped) > 1 and len({rate.amount for rate in grouped.values()}) == 1:
        grouped = {"ALL": next(iter(grouped.values()))}
    fixed, additional, discounts = _charge_rules(
        record,
        eligibility,
        cdispd_reference,
        cdispd_period,
        cdispd_projection,
        snapshot,
    )
    return FixedTariff(
        tariff_id=f"{_source_offer_id(record)}:tariff",
        validity=record.tariff_validity,
        prices=tuple(BandPrice(band=band, rate=rate) for band, rate in sorted(grouped.items())),
        fixed_charges=fixed,
        additional_charges=additional,
        discounts=discounts,
        conditions=record.conditions,
        provenance=record.source_provenance,
    )


def _indexed_tariff(
    record: PortalOfferRecord,
    eligibility: PortalEligibilityProfile | None = None,
    cdispd_reference: CdispDReferenceSnapshot | None = None,
    cdispd_period: DatePeriod | None = None,
    cdispd_projection: PortalCdispDProjection | None = None,
    snapshot: PortalOffersSnapshot | None = None,
) -> IndexedTariff:
    index_codes = _record_index_codes(record)
    if not index_codes:
        raise LookupError("indexed offer references no public index")
    granularity = Granularity.MONTH
    structured_terms: list[PriceExpression] = []
    for component in record.components:
        if (
            component.source_code is not None
            or component.index_code is None
            or _unit(component.unit) != RateUnit.EUR_PER_KWH
        ):
            continue
        mapped = _INDEX_CODES.get(component.index_code.upper())
        if mapped is None:
            raise LookupError(
                f"indexed offer references an unsupported public index: {component.index_code}"
            )
        reference: PriceExpression = IndexReference(
            index_code=mapped, unit=RateUnit.EUR_PER_KWH, granularity=granularity
        )
        if component.coefficient is not None:
            reference = MultiplyPrice(
                price=reference,
                scalar=ScalarConstant(value=component.coefficient, name=component.code),
            )
        structured_terms.append(reference)
    terms = structured_terms or [
        IndexReference(index_code=index_code, unit=RateUnit.EUR_PER_KWH, granularity=granularity)
        for index_code in index_codes
    ]
    expression = terms[0]
    for term in terms[1:]:
        expression = AddPrice(left=expression, right=term)
    for component in record.components:
        if component.source_code is not None:
            continue
        unit = _unit(component.unit)
        if unit != RateUnit.EUR_PER_KWH or component.discount or component.amount is None:
            continue
        if record.catalog == PortalCatalog.PLACET and component.code.startswith("p_vol_"):
            continue
        if (
            component.index_code is None
            or component.code.lower() in {"alpha", "spread"}
            or component.macroarea in {"04", "06", None}
        ):
            expression = AddPrice(
                left=expression,
                right=PriceConstant(
                    rate=UnitRate(amount=component.amount, unit=RateUnit.EUR_PER_KWH)
                ),
            )
    fixed, additional, discounts = _charge_rules(
        record,
        eligibility,
        cdispd_reference,
        cdispd_period,
        cdispd_projection,
        snapshot,
    )
    return IndexedTariff(
        tariff_id=f"{_source_offer_id(record)}:tariff",
        validity=record.tariff_validity,
        granularity=granularity,
        formulas=(BandFormula(band="ALL", expression=expression),),
        fixed_charges=fixed,
        additional_charges=additional,
        discounts=discounts,
        conditions=record.conditions,
        provenance=record.source_provenance,
    )


def _record_applicability(
    record: PortalOfferRecord,
    eligibility: PortalEligibilityProfile,
    period_start: date,
    period_end: date,
) -> PortalOfferExclusion | None:
    if record.customer_type not in {"01", "domestico", "DOMESTICO", "domestic"}:
        return _exclude(
            record, PortalOfferExclusionCode.CLASSIFICATION_NOT_COVERED, "offer is not domestic"
        )
    if not (record.subscription_period.start <= period_start < record.subscription_period.end):
        return _exclude(
            record,
            PortalOfferExclusionCode.NOT_CURRENT,
            "subscription period does not contain as_of",
        )
    validity = _effective_validity(record, period_start)
    if period_start < validity.start or period_end > validity.end:
        return _exclude(
            record,
            PortalOfferExclusionCode.PERIOD_NOT_COVERED,
            "tariff validity does not cover the requested period",
        )
    territory = eligibility.territory
    if record.region_codes and territory.region_code not in record.region_codes:
        return _exclude(
            record, PortalOfferExclusionCode.TERRITORY_NOT_COVERED, "region is not covered"
        )
    if record.province_codes and territory.province_code not in record.province_codes:
        return _exclude(
            record, PortalOfferExclusionCode.TERRITORY_NOT_COVERED, "province is not covered"
        )
    if record.municipality_codes and territory.municipality_code not in record.municipality_codes:
        return _exclude(
            record, PortalOfferExclusionCode.TERRITORY_NOT_COVERED, "municipality is not covered"
        )
    if not _contains(record.activation_methods, eligibility.activation_method):
        return _exclude(
            record,
            PortalOfferExclusionCode.ACTIVATION_NOT_COVERED,
            "activation method is not covered",
        )
    if not _contains(record.payment_methods, eligibility.payment_method):
        return _exclude(
            record, PortalOfferExclusionCode.PAYMENT_NOT_COVERED, "payment method is not covered"
        )
    if any("dual" in condition.lower() for condition in record.conditions):
        return _exclude(
            record,
            PortalOfferExclusionCode.DUAL_FUEL_REQUIRED,
            "dual-fuel condition is not supported",
        )
    if any(
        any(
            token in condition.lower()
            for token in ("mandatory service", "servizio obbligatorio", "servizio richiesto")
        )
        for condition in record.conditions
    ):
        return _exclude(
            record,
            PortalOfferExclusionCode.MANDATORY_SERVICE_REQUIRED,
            "mandatory service condition is not supported",
        )
    return None


def normalize_offers(
    snapshot: PortalOffersSnapshot,
    records: tuple[PortalOfferRecord, ...],
    eligibility: PortalEligibilityProfile,
    period_start: date,
    period_end: date,
    *,
    market_data: MarketData | None = None,
    cdispd_reference: CdispDReferenceSnapshot | None = None,
    cdispd_reference_period: DatePeriod | None = None,
    cdispd_projection: PortalCdispDProjection | None = None,
) -> PortalOffersImportResult:
    """Normalize and filter every parsed source record exactly once."""
    ordered_records = tuple(
        sorted(
            records,
            key=lambda item: (
                item.catalog.value,
                item.source_offer_id,
                json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
            ),
        )
    )
    exclusions: list[PortalOfferExclusion] = []
    normalized: list[NormalizedPortalOffer] = []
    occurrence_count = Counter(_source_offer_id(record) for record in records)
    comparison_period = DatePeriod(start=period_start, end=period_end)
    reference_period = cdispd_reference_period or comparison_period
    for record in ordered_records:
        offer_id = _source_offer_id(record)
        if occurrence_count[offer_id] > 1:
            exclusions.append(
                _exclude(
                    record, PortalOfferExclusionCode.DUPLICATE_OFFER_ID, "duplicate source offer id"
                )
            )
            continue
        if snapshot.status != VerificationStatus.VERIFIED:
            exclusions.append(
                _exclude(record, PortalOfferExclusionCode.NOT_VERIFIED, "snapshot is not verified")
            )
            continue
        if not record.source_provenance:
            exclusions.append(
                _exclude(
                    record,
                    PortalOfferExclusionCode.MISSING_PROVENANCE,
                    "offer has no source provenance",
                )
            )
            continue
        if record.offer_type == PortalOfferType.UNSUPPORTED:
            exclusions.append(
                _exclude(
                    record,
                    PortalOfferExclusionCode.UNSUPPORTED_OFFER_TYPE,
                    "TIPO_OFFERTA=04 is temporarily excluded by policy",
                )
            )
            continue
        applicability = _record_applicability(record, eligibility, period_start, period_end)
        if applicability is not None:
            exclusions.append(applicability)
            continue
        commercial_component_issue = _commercial_component_exclusion(
            record,
            eligibility,
            cdispd_reference,
            reference_period,
            cdispd_projection,
            snapshot,
        )
        if commercial_component_issue is not None:
            exclusions.append(commercial_component_issue)
            continue
        try:
            tariff = (
                _fixed_tariff(
                    record,
                    eligibility,
                    cdispd_reference,
                    reference_period,
                    cdispd_projection,
                    snapshot,
                )
                if record.offer_type == PortalOfferType.FIXED
                else _indexed_tariff(
                    record,
                    eligibility,
                    cdispd_reference,
                    reference_period,
                    cdispd_projection,
                    snapshot,
                )
            )
            tariff = tariff.model_copy(
                update={"validity": _effective_validity(record, period_start)}
            )
        except LookupError as exc:
            exclusions.append(
                _exclude(record, PortalOfferExclusionCode.INDEXED_INPUT_MISSING, str(exc))
            )
            continue
        except (TypeError, ValueError) as exc:
            exclusions.append(
                _exclude(record, PortalOfferExclusionCode.TARIFF_NOT_REPRESENTABLE, str(exc))
            )
            continue
        if record.offer_type == PortalOfferType.INDEXED:
            if market_data is None:
                exclusions.append(
                    _exclude(
                        record,
                        PortalOfferExclusionCode.INDEXED_INPUT_MISSING,
                        "required market data is missing",
                    )
                )
                continue
            index_codes = _record_index_codes(record)
            available_indexes = {item.code for item in market_data.indexes}
            if any(index_code not in available_indexes for index_code in index_codes):
                exclusions.append(
                    _exclude(
                        record,
                        PortalOfferExclusionCode.INDEXED_INPUT_MISSING,
                        "required market index is missing",
                    )
                )
                continue
        offer = Offer(
            offer_id=offer_id,
            supplier_id=record.supplier_id,
            name=record.name,
            subscription_period=record.subscription_period,
            tariff=tariff,
            conditions=record.conditions,
            provenance=record.source_provenance,
        )
        normalized.append(
            NormalizedPortalOffer(
                offer=offer,
                source_record=record,
                assumptions=("portal annual estimate is evidence only",),
            )
        )
    normalized.sort(key=lambda item: item.offer.offer_id)
    exclusions.sort(key=lambda item: (item.offer_id, item.code.value, item.detail))
    eligible = tuple(item.offer for item in normalized)
    payload = {
        "snapshot": snapshot.snapshot_id,
        "parser": snapshot.parser_version,
        "records": [record.model_dump(mode="json") for record in ordered_records],
        "eligibility": eligibility.model_dump(mode="json"),
        "period_start": str(period_start),
        "period_end": str(period_end),
        "cdispd_reference_snapshot_id": (
            cdispd_reference.snapshot_id if cdispd_reference is not None else None
        ),
        "cdispd_reference_snapshot_digest": (
            cdispd_reference.digest if cdispd_reference is not None else None
        ),
        "cdispd_reference_period": reference_period.model_dump(mode="json"),
        "cdispd_customer_segment": (
            AreraCustomerSegment.RESIDENT.value
            if eligibility.residential is True
            else AreraCustomerSegment.NON_RESIDENT.value
            if eligibility.residential is False
            else None
        ),
        "cdispd_projection": (
            cdispd_projection.model_dump(mode="json") if cdispd_projection is not None else None
        ),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    import_id = f"portal-import:{digest}"
    return PortalOffersImportResult(
        snapshot=snapshot,
        status=snapshot.status,
        import_id=import_id,
        records=ordered_records,
        normalized=tuple(normalized),
        eligible_offers=eligible,
        exclusions=tuple(exclusions),
        received_count=len(records),
        eligible_count=len(eligible),
        excluded_count=len(exclusions),
        cdispd_reference_snapshot_id=(
            cdispd_reference.snapshot_id if cdispd_reference is not None else None
        ),
        cdispd_reference_snapshot_digest=(
            cdispd_reference.digest if cdispd_reference is not None else None
        ),
        cdispd_reference_period=reference_period,
        cdispd_customer_segment=(
            AreraCustomerSegment.RESIDENT
            if eligibility.residential is True
            else AreraCustomerSegment.NON_RESIDENT
            if eligibility.residential is False
            else None
        ),
    )
