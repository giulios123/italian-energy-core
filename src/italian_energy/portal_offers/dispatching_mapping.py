"""Versioned interpretation of Portale XML ``Dispacciamento`` entries.

The mapping preserves source declarations and distinguishes a direct seller
charge from a source code whose amount must come from a separate rule or
parameter. Missing amounts remain missing; callers must not turn them into 0.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from italian_energy.domain.provenance import Provenance
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers.models import (
    PORTAL_DISPATCHING_MAPPING_VERSION,
    PortalComponentSemantic,
    PortalEconomicComponent,
    PortalLossTreatment,
    PortalPricingTreatment,
)


@dataclass(frozen=True, slots=True)
class DispatchingMapping:
    semantic: PortalComponentSemantic
    pricing_treatment: PortalPricingTreatment
    unit: str | None
    loss_treatment: PortalLossTreatment
    included_semantics: tuple[PortalComponentSemantic, ...] = ()


# The XML codes are kept as source codes. Codes without a source-supplied value
# identify an economic rule but do not by themselves provide a rate.
_BASE_MAPPINGS: dict[str, DispatchingMapping] = {
    "01": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "02": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "03": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "04": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "05": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "06": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "07": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "08": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "09": DispatchingMapping(
        PortalComponentSemantic.CAPACITY_MARKET,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "10": DispatchingMapping(
        PortalComponentSemantic.CAPACITY_MARKET,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "11": DispatchingMapping(
        PortalComponentSemantic.SAFEGUARD_REINTEGRATION,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "12": DispatchingMapping(
        PortalComponentSemantic.GRADUAL_PROTECTION_REINTEGRATION,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
    "13": DispatchingMapping(
        PortalComponentSemantic.REGULATED_FIXED_DISPATCHING,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/year",
        PortalLossTreatment.NOT_APPLICABLE,
    ),
    "14": DispatchingMapping(
        PortalComponentSemantic.DISPATCHING_CAPACITY_AGGREGATE,
        PortalPricingTreatment.REGULATORY_REFERENCE,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
        (
            PortalComponentSemantic.DISPATCHING,
            PortalComponentSemantic.CAPACITY_MARKET,
        ),
    ),
    "99": DispatchingMapping(
        PortalComponentSemantic.SELLER_DEFINED_DISPATCHING,
        PortalPricingTreatment.TARIFF_ADDITION,
        "EUR/kWh",
        PortalLossTreatment.INCLUDED,
    ),
}

_CAPACITY_MARKET_NAMES = frozenset(
    {
        "capacity market",
        "corrispettivo capacity market",
        "corrispettivo capacita di mercato",
        "corrispettivo capacita mercato",
        "corr capacita di mercato",
        "corr cap di mercato",
    }
)


def _normalized_label(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    without_marks = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", without_marks).split())


def _mapping_for(source_code: str | None, name: str) -> DispatchingMapping:
    if source_code is None:
        return DispatchingMapping(
            PortalComponentSemantic.UNSUPPORTED,
            PortalPricingTreatment.UNSUPPORTED,
            None,
            PortalLossTreatment.UNKNOWN,
        )
    mapping = _BASE_MAPPINGS.get(source_code)
    if mapping is None:
        return DispatchingMapping(
            PortalComponentSemantic.UNSUPPORTED,
            PortalPricingTreatment.UNSUPPORTED,
            None,
            PortalLossTreatment.UNKNOWN,
        )
    if source_code == "99" and _normalized_label(name) in _CAPACITY_MARKET_NAMES:
        return DispatchingMapping(
            PortalComponentSemantic.CAPACITY_MARKET,
            mapping.pricing_treatment,
            mapping.unit,
            mapping.loss_treatment,
        )
    return mapping


def make_dispatching_component(
    *,
    source_code: str | None,
    name: str,
    description: str,
    amount: Decimal | None,
    period: DatePeriod,
    source_fields: tuple[tuple[str, str], ...],
    source_provenance: tuple[Provenance, ...],
) -> PortalEconomicComponent:
    """Create a structured component while preserving source values."""
    mapping = _mapping_for(source_code, name)
    code = f"dispatching:{source_code or 'unknown'}"
    return PortalEconomicComponent(
        code=code,
        description=description or name or code,
        amount=amount,
        unit=mapping.unit,
        source_code=source_code,
        semantic=mapping.semantic,
        pricing_treatment=mapping.pricing_treatment,
        loss_treatment=mapping.loss_treatment,
        included_semantics=mapping.included_semantics,
        period=period,
        mapping_version=PORTAL_DISPATCHING_MAPPING_VERSION,
        source_provenance=source_provenance,
        source_fields=source_fields,
        locator=source_provenance[0].locator if source_provenance else None,
    )
