from datetime import UTC, date, datetime
from decimal import Decimal

from test_portal_offers import XML, _transport
from test_projected_contract import AS_OF
from test_projected_service import _coverage, _history, _indexed_request

from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.domain.costs import ComponentMeaning, ComponentPricingTreatment
from italian_energy.domain.money import Money, RateUnit, UnitRate
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import ProjectedDomesticEnergyService
from italian_energy.integration.current import future_period
from italian_energy.integration.service import CurrentDomesticEnergyService
from italian_energy.portal_offers.importer import PortalOffersImporter
from italian_energy.portal_offers.models import PortalEconomicComponent


def test_imported_capacity_market_addition_reaches_annual_bill_once() -> None:
    dispatching = b"""
    <Dispacciamento>
      <TIPO_DISPACCIAMENTO>99</TIPO_DISPACCIAMENTO>
      <VALORE_DISP>0.0088</VALORE_DISP>
      <NOME>Capacity Market</NOME>
      <DESCRIZIONE>Quota commerciale Capacity Market</DESCRIZIONE>
    </Dispacciamento>
    """
    xml = XML.replace(
        b"    <ComponenteImpresa>", dispatching + b"    <ComponenteImpresa>", 1
    ).replace(b"31/12/2026_23:59:59", b"30/09/2027_23:59:59")
    transport = _transport()
    transport.contents = {**transport.contents, "offerteML": (xml, "application/xml")}

    def clock() -> datetime:
        return datetime(2026, 9, 27, 12, tzinfo=UTC)

    importer = PortalOffersImporter(transport=transport, clock=clock)
    catalog = CurrentDomesticEnergyService(importer=importer, clock=clock).acquire_catalog(AS_OF)

    source_record = next(item for item in catalog.records if item.source_offer_id == "XML1")
    imported_charge = next(item for item in source_record.components if item.source_code == "99")
    assert imported_charge.amount == Decimal("0.0088")
    assert imported_charge.source_provenance[0].locator is not None
    assert imported_charge.source_provenance[0].locator.section == "offer:XML1/Dispacciamento:1"

    horizon = future_period(AS_OF)
    tariff_validity = DatePeriod(start=date(2026, 9, 1), end=horizon.end)
    subscription = tariff_validity
    energy = PortalEconomicComponent(
        code="test_energy",
        description="synthetic test energy price",
        amount=Decimal("0.12"),
        unit="EUR/kWh",
        band="ALL",
        macroarea="04",
    )
    records = tuple(
        record.model_copy(
            update={
                "subscription_period": subscription,
                "tariff_validity": tariff_validity,
                "duration_months": 13,
                "components": (
                    energy,
                    *((imported_charge,) if record.source_offer_id == "XML1" else ()),
                ),
            }
        )
        for record in catalog.records
    )
    catalog = catalog.model_copy(update={"records": records})

    anchor = load_domestic_projection_anchor()
    result = ProjectedDomesticEnergyService(clock=clock).compare(
        _indexed_request("300"),
        catalog,
        _history(AS_OF),
        anchor,
        _coverage(anchor, AS_OF),
    )
    base = result.scenarios[1].comparison.comparison_result
    matching_offers = tuple(
        item for item in base.alternatives if item.offer_id == "portal:market_free:XML1"
    )
    assert matching_offers, tuple(
        (item.offer_id, item.code, item.detail) for item in base.excluded_offers
    )
    offer = matching_offers[0]
    assert offer.billing is not None
    bill = offer.billing.bill
    lines = tuple(
        item
        for item in bill.breakdown.components
        if item.meaning == ComponentMeaning.CAPACITY_MARKET
    )

    assert len(lines) == 1
    line = lines[0]
    assert line.pricing_treatment == ComponentPricingTreatment.TARIFF_ADDITION
    assert line.losses_included is True
    assert line.included_semantics == ()
    assert line.quantity == Decimal("3600")
    assert line.unit_rate == UnitRate(amount=Decimal("0.0088"), unit=RateUnit.EUR_PER_KWH)
    assert line.amount == Money(amount=Decimal("31.68"))
    assert line.period == result.period == horizon
    assert line.applied_periods == (horizon,)
    assert any(
        provenance.locator is not None
        and provenance.locator.section == "offer:XML1/Dispacciamento:1"
        for provenance in line.provenance
    )
