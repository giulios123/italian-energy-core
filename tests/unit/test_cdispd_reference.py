from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError
from test_portal_offers import DATE, XML, _transport

from italian_energy.arera import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCustomerSegment,
    AreraImportResult,
    AreraRegulatoryBundle,
    AreraSourceLocator,
    RawAreraSnapshot,
)
from italian_energy.arera.cdispd_reference import (
    CdispDReferenceSnapshot,
    acquire_cdispd_reference_snapshot,
    cdispd_reference_snapshot_from_import,
)
from italian_energy.domain.consumption import ConsumptionBucket, ConsumptionProfile
from italian_energy.domain.costs import ComponentMeaning, PricingResult
from italian_energy.domain.money import (
    EnergyQuantity,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    UnitRate,
)
from italian_energy.domain.offer import Contract
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import BillingCategory, BillingQuota, VerificationStatus
from italian_energy.domain.supply import SupplyPoint
from italian_energy.domain.tariff import ChargeBasis, FixedTariff
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval
from italian_energy.integration.manifest import CORE_CAPABILITIES, CoreSchemaId
from italian_energy.integration.serialization import dump_envelope, load_envelope
from italian_energy.portal_offers import (
    PortalEligibilityProfile,
    PortalOffersImporter,
    PortalTerritory,
)
from italian_energy.portal_offers import models as portal_models
from italian_energy.portal_offers.models import PortalOfferRecord, PortalSnapshot
from italian_energy.portal_offers.normalizer import normalize_offers
from italian_energy.pricing import FixedPricingEngine, PricingRequest

RETRIEVED_AT = datetime(2026, 9, 8, 10, 0, tzinfo=UTC)
ARERA_URL = (
    "https://www.arera.it/fileadmin/area_operatori/prezzi_e_tariffe/"
    "Corrispettivi_libero_elettrico_domestico_2026.xlsx"
)


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, 1)


def _verified_import(month_count: int = 2) -> AreraImportResult:
    raw = b"independent synthetic ARERA source workbook"
    digest = sha256(raw).hexdigest()
    source = RawAreraSnapshot(
        content=raw,
        source_url=ARERA_URL,
        retrieved_at=RETRIEVED_AT,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        sha256=digest,
    )
    charges: list[AreraChargeValue] = []
    for month_offset in range(month_count):
        start = _add_months(date(2026, 1, 1), month_offset)
        period = DatePeriod(start=start, end=_add_months(start, 1))
        for segment, rate in (
            (AreraCustomerSegment.RESIDENT, Decimal("0.019902") + month_offset * Decimal("0.001")),
            (
                AreraCustomerSegment.NON_RESIDENT,
                Decimal("0.025000") + month_offset * Decimal("0.001"),
            ),
        ):
            provenance = Provenance(
                source="ARERA",
                source_identifier=ARERA_URL,
                retrieved_at=RETRIEVED_AT,
                effective_period=period,
                dataset_version="2026",
                sha256=digest,
                url=ARERA_URL,
                locator=ProvenanceLocator(
                    sheet=f"mese {start.month}",
                    cell="C11",
                ),
            )
            charges.append(
                AreraChargeValue(
                    code=f"arera:2026:{start.month:02d}:{segment.value}:CDISPD:consumption",
                    segment=segment,
                    component_code="CDISPD",
                    category=BillingCategory.SALES,
                    quota=BillingQuota.CONSUMPTION,
                    rate=UnitRate(amount=rate, unit=RateUnit.EUR_PER_KWH),
                    validity=period,
                    role=AreraChargeRole.ATOMIC,
                    source=AreraSourceLocator(
                        sheet=f"mese {start.month}",
                        cell="C11",
                        label="dispacciamento",
                    ),
                    status=VerificationStatus.VERIFIED,
                    provenance=(provenance,),
                )
            )
    bundle = AreraRegulatoryBundle(
        bundle_id=f"arera-bundle:{digest}",
        schema_version="005-domestic-electricity-2026-v1",
        dataset_version="2026",
        validity=DatePeriod(
            start=date(2026, 1, 1),
            end=_add_months(date(2026, 1, 1), month_count),
        ),
        charges=tuple(charges),
        status=VerificationStatus.VERIFIED,
        provenance=tuple(item for charge in charges for item in charge.provenance),
    )
    return AreraImportResult(snapshot=source, status=VerificationStatus.VERIFIED, bundle=bundle)


def _dispatching_offer(
    source_code: str = "14",
) -> tuple[PortalSnapshot, PortalOfferRecord]:
    element = (
        b"<Dispacciamento><TIPO_DISPACCIAMENTO>"
        + source_code.encode()
        + b"</TIPO_DISPACCIAMENTO><VALORE_DISP>0.0088</VALORE_DISP>"
        + b"<NOME>Capacity Market</NOME></Dispacciamento>"
        if source_code == "99"
        else (
            b"<Dispacciamento><TIPO_DISPACCIAMENTO>14</TIPO_DISPACCIAMENTO>"
            b"<NOME>CdispD</NOME></Dispacciamento>"
        )
    )
    transport = _transport()
    transport.contents = {
        **transport.contents,
        "offerteML": (
            XML.replace(b"    <ComponenteImpresa>", element + b"    <ComponenteImpresa>", 1),
            "application/xml",
        ),
    }
    importer = PortalOffersImporter(transport=transport, clock=lambda: RETRIEVED_AT)
    snapshot = importer.fetch(DATE, include_indexes=False)
    record = next(
        item for item in importer.parse_offers(snapshot.offers) if item.source_offer_id == "XML1"
    )
    return snapshot, record


def _eligibility(residential: bool | None) -> PortalEligibilityProfile:
    return PortalEligibilityProfile(
        territory=PortalTerritory(
            region_code="06", province_code="015", municipality_code="015213"
        ),
        activation_method="02",
        payment_method="01",
        residential=residential,
    )


def _price_one_month(tariff: FixedTariff, residential: bool, period: DatePeriod) -> PricingResult:
    supply = SupplyPoint(
        supply_id="POD-test",
        market_zone="NORD",
        contracted_power=Power(kw=Decimal("3")),
        residential=residential,
    )
    contract = Contract(
        contract_id="offer-test",
        supply=supply,
        tariff=tariff,
        validity=tariff.validity,
    )
    rome = ZoneInfo("Europe/Rome")
    start = datetime(period.start.year, period.start.month, 1, tzinfo=rome)
    end_date = _add_months(period.start, 1)
    end = datetime(end_date.year, end_date.month, 1, tzinfo=rome)
    profile = ConsumptionProfile(
        profile_id="one-month-100kwh",
        buckets=(
            ConsumptionBucket(
                interval=TimeInterval(start=start, end=end),
                energy=EnergyQuantity(kwh=Decimal("100")),
                band="F1",
                granularity=Granularity.MONTH,
            ),
        ),
    )
    return FixedPricingEngine().price(
        PricingRequest(
            contract=contract,
            consumption=profile,
            period=period,
            rounding_policy=RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP),
        )
    )


def test_verified_arera_import_builds_immutable_versioned_envelope() -> None:
    reference = cdispd_reference_snapshot_from_import(_verified_import())

    envelope = reference.to_envelope()
    decoded = json.loads(envelope)
    restored = CdispDReferenceSnapshot.from_envelope(envelope)

    assert decoded["schema_id"] == CoreSchemaId.CDISPD_REFERENCE_SNAPSHOT.value
    assert "portal_cdispd_reference_pricing" in CORE_CAPABILITIES
    assert isinstance(load_envelope(dump_envelope(reference)), CdispDReferenceSnapshot)
    assert reference.source_snapshot_id == f"arera-snapshot:{reference.source_digest}"
    assert reference.source_bundle_id == f"arera-bundle:{reference.source_digest}"
    assert reference == restored
    with pytest.raises(ValidationError):
        reference.status = VerificationStatus.UNVERIFIED  # type: ignore[misc]


def test_cdispd_reference_rejects_unverified_and_digest_mismatched_bundle() -> None:
    unverified_import = _verified_import().model_copy(
        update={"status": VerificationStatus.UNVERIFIED}
    )
    with pytest.raises(ValueError, match="verified"):
        cdispd_reference_snapshot_from_import(unverified_import)

    result = _verified_import()
    assert result.bundle is not None
    mismatched_bundle = result.bundle.model_copy(update={"bundle_id": "arera-bundle:" + "0" * 64})
    with pytest.raises(ValueError, match="digest"):
        cdispd_reference_snapshot_from_import(
            result.model_copy(update={"bundle": mismatched_bundle})
        )


def test_cdispd_reference_factory_rejects_unverified_and_untrusted_sources() -> None:
    result = _verified_import()
    assert result.bundle is not None

    unverified_bundle = result.bundle.model_copy(update={"status": VerificationStatus.UNVERIFIED})
    with pytest.raises(ValueError, match="verified ARERA bundle"):
        cdispd_reference_snapshot_from_import(
            result.model_copy(update={"bundle": unverified_bundle})
        )

    changed_url = result.snapshot.model_copy(update={"source_url": "https://example.invalid/file"})
    with pytest.raises(ValueError, match="official ARERA"):
        cdispd_reference_snapshot_from_import(result.model_copy(update={"snapshot": changed_url}))

    without_cdispd = result.bundle.model_copy(
        update={
            "charges": tuple(
                charge.model_copy(update={"component_code": "not-CdispD"})
                for charge in result.bundle.charges
            )
        }
    )
    with pytest.raises(ValueError, match="no atomic CDISPD"):
        cdispd_reference_snapshot_from_import(result.model_copy(update={"bundle": without_cdispd}))

    first_charge = result.bundle.charges[0]
    bad_provenance = first_charge.provenance[0].model_copy(
        update={"url": "https://example.invalid/file"}
    )
    bad_charge = first_charge.model_copy(update={"provenance": (bad_provenance,)})
    bad_bundle = result.bundle.model_copy(
        update={"charges": (bad_charge, *result.bundle.charges[1:])}
    )
    with pytest.raises(ValueError, match="provenance does not match"):
        cdispd_reference_snapshot_from_import(result.model_copy(update={"bundle": bad_bundle}))


def test_cdispd_snapshot_acquisition_uses_fresh_importer_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import italian_energy.arera.importer as importer_module

    result = _verified_import()

    class StubImporter:
        def fetch_and_import(self) -> AreraImportResult:
            return result

    monkeypatch.setattr(importer_module, "AreraDomesticElectricityImporter", StubImporter)

    snapshot = acquire_cdispd_reference_snapshot()

    assert snapshot == cdispd_reference_snapshot_from_import(result)


def test_cdispd_envelope_rejects_wrong_payload_type_and_tampered_snapshot_id() -> None:
    reference = cdispd_reference_snapshot_from_import(_verified_import())
    wrong_type = SupplyPoint(
        supply_id="POD-envelope-test",
        market_zone="NORD",
        contracted_power=Power(kw=Decimal("3")),
        residential=True,
    )
    with pytest.raises(ValueError, match="does not contain a CdispD"):
        CdispDReferenceSnapshot.from_envelope(dump_envelope(wrong_type))

    payload = reference.model_dump(mode="python")
    payload["snapshot_id"] = "cdispd-reference-snapshot:" + "0" * 64
    with pytest.raises(ValidationError, match="id does not match"):
        CdispDReferenceSnapshot.model_validate(payload)


def test_cdispd_reference_rejects_missing_profile_month_pair() -> None:
    result = _verified_import()
    assert result.bundle is not None
    incomplete = result.bundle.model_copy(
        update={
            "charges": tuple(
                charge
                for charge in result.bundle.charges
                if charge.segment == AreraCustomerSegment.RESIDENT
            )
        }
    )
    with pytest.raises(ValueError, match="both customer segments"):
        cdispd_reference_snapshot_from_import(result.model_copy(update={"bundle": incomplete}))


def test_cdispd_reference_rejects_unexpected_cdispd_semantics() -> None:
    result = _verified_import()
    assert result.bundle is not None
    unexpected = result.bundle.charges[0].model_copy(
        update={
            "code": "arera:2026:01:unexpected-CDISPD-row",
            "category": BillingCategory.NETWORK,
        }
    )
    bundle = result.bundle.model_copy(update={"charges": (*result.bundle.charges, unexpected)})

    with pytest.raises(ValueError, match="unsupported CDISPD row"):
        cdispd_reference_snapshot_from_import(result.model_copy(update={"bundle": bundle}))


def test_cdispd_reference_months_are_half_open_and_never_carry_forward() -> None:
    reference = cdispd_reference_snapshot_from_import(_verified_import(month_count=1))

    january = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
    through_january = DatePeriod(start=date(2026, 1, 31), end=date(2026, 2, 1))
    crossing_into_february = DatePeriod(start=date(2026, 1, 31), end=date(2026, 2, 2))

    assert reference.covers(AreraCustomerSegment.RESIDENT, january)
    assert reference.covers(AreraCustomerSegment.RESIDENT, through_january)
    assert len(reference.charges_for_period(AreraCustomerSegment.RESIDENT, through_january)) == 1
    assert not reference.covers(AreraCustomerSegment.RESIDENT, crossing_into_february)
    with pytest.raises(ValueError, match="every month"):
        reference.charges_for_period(AreraCustomerSegment.RESIDENT, crossing_into_february)


@pytest.mark.parametrize(
    ("residential", "expected_rate", "expected_amount"),
    [
        (True, Decimal("0.019902"), Decimal("1.99")),
        (False, Decimal("0.025000"), Decimal("2.50")),
    ],
)
def test_code_14_prices_once_from_profile_specific_monthly_reference(
    residential: bool,
    expected_rate: Decimal,
    expected_amount: Decimal,
) -> None:
    offers, record = _dispatching_offer()
    reference = cdispd_reference_snapshot_from_import(_verified_import(month_count=1))
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))

    normalized = normalize_offers(
        offers.offers,
        (record,),
        _eligibility(residential),
        period.start,
        period.end,
        cdispd_reference=reference,
    )

    assert normalized.eligible_count == 1
    tariff = normalized.normalized[0].offer.tariff
    assert isinstance(tariff, FixedTariff)
    cdispd_rules = tuple(
        rule
        for rule in tariff.additional_charges
        if rule.meaning == ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
    )
    assert len(cdispd_rules) == 1
    assert cdispd_rules[0].basis == ChargeBasis.PER_KWH
    assert cdispd_rules[0].value.amount == expected_rate
    assert cdispd_rules[0].validity == period
    assert cdispd_rules[0].losses_included is True
    assert cdispd_rules[0].included_semantics == (
        ComponentMeaning.DISPATCHING,
        ComponentMeaning.CAPACITY_MARKET,
    )

    priced = _price_one_month(tariff, residential, period)
    cdispd_costs = tuple(
        item
        for item in priced.breakdown.components
        if item.meaning == ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
    )
    assert len(cdispd_costs) == 1
    assert cdispd_costs[0].quantity == Decimal("100")
    assert cdispd_costs[0].unit_rate == UnitRate(amount=expected_rate, unit=RateUnit.EUR_PER_KWH)
    assert cdispd_costs[0].amount.amount == expected_amount
    assert cdispd_costs[0].period == period
    assert cdispd_costs[0].losses_included is True
    assert any(
        item.source == "ARERA" and item.sha256 == reference.source_digest
        for item in cdispd_costs[0].provenance
    )


def test_code_14_fails_closed_when_profile_is_unknown_or_month_is_not_covered() -> None:
    offers, record = _dispatching_offer()
    reference = cdispd_reference_snapshot_from_import(_verified_import(month_count=1))
    january = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))
    unknown_profile = normalize_offers(
        offers.offers,
        (record,),
        _eligibility(None),
        january.start,
        january.end,
        cdispd_reference=reference,
    )
    uncovered = normalize_offers(
        offers.offers,
        (record,),
        _eligibility(True),
        date(2026, 2, 1),
        date(2026, 3, 1),
        cdispd_reference=reference,
    )

    assert unknown_profile.eligible_count == 0
    assert (
        unknown_profile.exclusions[0].code
        == portal_models.PortalOfferExclusionCode.MISSING_COMMERCIAL_COMPONENT
    )
    assert "resident/non-resident" in unknown_profile.exclusions[0].detail
    assert uncovered.eligible_count == 0
    assert (
        uncovered.exclusions[0].code
        == portal_models.PortalOfferExclusionCode.MISSING_COMMERCIAL_COMPONENT
    )
    assert "month" in uncovered.exclusions[0].detail


def test_code_99_remains_a_direct_seller_addition_when_reference_is_supplied() -> None:
    offers, record = _dispatching_offer("99")
    reference = cdispd_reference_snapshot_from_import(_verified_import(month_count=1))
    period = DatePeriod(start=date(2026, 1, 1), end=date(2026, 2, 1))

    normalized = normalize_offers(
        offers.offers,
        (record,),
        _eligibility(True),
        period.start,
        period.end,
        cdispd_reference=reference,
    )

    assert normalized.eligible_count == 1
    tariff = normalized.normalized[0].offer.tariff
    seller_charge = next(
        rule for rule in tariff.additional_charges if rule.code == "dispatching:99"
    )
    assert seller_charge.value.amount == Decimal("0.0088")
    assert seller_charge.meaning == ComponentMeaning.CAPACITY_MARKET
    assert seller_charge.losses_included is True
    assert all(rule.code != "dispatching:14" for rule in tariff.additional_charges)
