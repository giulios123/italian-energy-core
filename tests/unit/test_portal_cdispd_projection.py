from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256

import pytest
from test_cdispd_reference import (
    _dispatching_offer,
    _eligibility,
    _price_one_month,
)

from italian_energy.domain.costs import ComponentMeaning
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.tariff import ChargeBasis, FixedTariff
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers.importer import PortalOffersImporter
from italian_energy.portal_offers.models import (
    PortalCdispDProjection,
    PortalFileSnapshot,
    PortalOffersSnapshot,
    PortalSourceRole,
    market_free_parameters_url,
)
from italian_energy.portal_offers.normalizer import normalize_offers
from italian_energy.portal_offers.parameters import (
    parse_market_free_cdispd_parameter,
    projection_matches_snapshot,
)

AS_OF = date(2026, 10, 18)
URL = market_free_parameters_url(AS_OF)
PARAMETERS = (
    b"nome_parametro,valore,descrizione\n"
    b"foo,0.2,other parameter\n"
    b"cdispd,0.016776,Corrispettivo somma del corrispettivo di Capacita e di quelli "
    b"applicati da Terna per il servizio di dispacciamento\n"
)


def _parameter_file(
    content: bytes = PARAMETERS,
    *,
    dataset_date: date = AS_OF,
) -> PortalFileSnapshot:
    url = market_free_parameters_url(dataset_date)
    return PortalFileSnapshot(
        role=PortalSourceRole.MARKET_FREE_PARAMETERS,
        original_url=url,
        final_url=url,
        retrieved_at=datetime.combine(dataset_date, datetime.min.time(), tzinfo=UTC),
        content_type="text/csv",
        size=len(content),
        sha256=sha256(content).hexdigest(),
        dataset_date=dataset_date,
        status=VerificationStatus.VERIFIED,
        content=content,
    )


def _snapshot_with_parameter(
    parameter_file: PortalFileSnapshot,
) -> PortalOffersSnapshot:
    importer = PortalOffersImporter(clock=lambda: datetime(2026, 10, 18, 9, 0, tzinfo=UTC))
    files = (
        PortalFileSnapshot(
            role=PortalSourceRole.MARKET_FREE_OFFERS,
            original_url="https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/offerteML/2026_10/PO_Offerte_E_MLIBERO_20261018.xml",
            final_url="https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/offerteML/2026_10/PO_Offerte_E_MLIBERO_20261018.xml",
            retrieved_at=parameter_file.retrieved_at,
            content_type="application/xml",
            size=0,
            sha256="0" * 64,
            dataset_date=AS_OF,
            status=VerificationStatus.VERIFIED,
        ),
        parameter_file,
        PortalFileSnapshot(
            role=PortalSourceRole.PLACET_OFFERS,
            original_url="https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/offerte/2026_10/PO_Offerte_E_20261018.csv",
            final_url="https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/offerte/2026_10/PO_Offerte_E_20261018.csv",
            retrieved_at=parameter_file.retrieved_at,
            content_type="text/csv",
            size=0,
            sha256="1" * 64,
            dataset_date=AS_OF,
            status=VerificationStatus.VERIFIED,
        ),
        PortalFileSnapshot(
            role=PortalSourceRole.PLACET_PARAMETERS,
            original_url="https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/parametri/2026_10/PO_Parametri_E_20261018.csv",
            final_url="https://www.ilportaleofferte.it/portaleOfferte/resources/opendata/csv/parametri/2026_10/PO_Parametri_E_20261018.csv",
            retrieved_at=parameter_file.retrieved_at,
            content_type="text/csv",
            size=0,
            sha256="2" * 64,
            dataset_date=AS_OF,
            status=VerificationStatus.VERIFIED,
        ),
    )
    cdispd_parameter = parse_market_free_cdispd_parameter(parameter_file)
    return PortalOffersSnapshot(
        dataset_date=AS_OF,
        files=files,
        snapshot_id=importer._snapshot_id(AS_OF, files),
        status=VerificationStatus.VERIFIED,
        parser_version="test",
        cdispd_parameter=cdispd_parameter,
    )


def test_current_parameter_parser_freezes_official_cdispd_row_and_provenance() -> None:
    file = _parameter_file()

    parameter = parse_market_free_cdispd_parameter(file)

    assert parameter is not None
    assert parameter.dataset_date == AS_OF
    assert parameter.parameter_name == "cdispd"
    assert parameter.rate == UnitRate(amount=Decimal("0.016776"), unit=RateUnit.EUR_PER_KWH)
    assert parameter.description.startswith("Corrispettivo somma")
    assert len(parameter.provenance) == 1
    source = parameter.provenance[0]
    assert source.source == "portale_offerte"
    assert source.url == URL
    assert source.sha256 == file.sha256
    assert source.effective_period is None
    assert source.locator == ProvenanceLocator(document="market_free_parameters", section="row:3")


@pytest.mark.parametrize(
    "content",
    [
        b"nome_parametro,valore,descrizione\nfoo,0.2,other\n",
        b"nome_parametro,valore,descrizione\ncdispd,0.01,first\ncdispd,0.02,second\n",
        b"nome_parametro,valore,descrizione\ncdispd,NaN,description\n",
        b"nome_parametro,valore,descrizione\ncdispd,-0.01,description\n",
        b"nome_parametro,valore,descrizione\ncdispd,not-a-rate,description\n",
        b"nome_parametro,valore,descrizione\ncdispd,0.01,\n",
        b"wrong,header,fields\ncdispd,0.01,description\n",
        b"nome_parametro,valore,descrizione\ncdispd,0.01,description,unexpected-column\n",
        b"\xff\xfe malformed encoding",
    ],
)
def test_bad_or_missing_current_parameter_is_unavailable_without_fallback(
    content: bytes,
) -> None:
    assert parse_market_free_cdispd_parameter(_parameter_file(content)) is None


def test_parameter_parser_rejects_wrong_source_role_date_and_url() -> None:
    file = _parameter_file()

    wrong_role = file.model_copy(update={"role": PortalSourceRole.PLACET_PARAMETERS})
    wrong_date = file.model_copy(update={"dataset_date": date(2026, 10, 17)})
    wrong_url = file.model_copy(update={"final_url": URL.replace("20261018", "20261017")})

    assert parse_market_free_cdispd_parameter(wrong_role) is None
    assert parse_market_free_cdispd_parameter(wrong_date) is None
    assert parse_market_free_cdispd_parameter(wrong_url) is None


@pytest.mark.parametrize(
    "invalid_update",
    [
        {"rate": {"amount": "0.016776", "unit": "EUR/MWh"}},
        {"rate": {"amount": "-0.016776", "unit": "EUR/kWh"}},
        {"provenance": ()},
    ],
)
def test_hydrated_parameter_rejects_wrong_units_negative_rates_and_missing_provenance(
    invalid_update: dict[str, object],
) -> None:
    parameter = parse_market_free_cdispd_parameter(_parameter_file())
    assert parameter is not None
    serialized = parameter.model_dump(mode="python")
    serialized.update(invalid_update)

    with pytest.raises(ValueError):
        type(parameter).model_validate(serialized)


def test_current_parameter_cannot_be_applied_as_an_observed_historical_rate() -> None:
    parameter = parse_market_free_cdispd_parameter(_parameter_file())
    assert parameter is not None

    with pytest.raises(ValueError, match="must follow the source observation date"):
        PortalCdispDProjection(
            parameter=parameter,
            catalog_snapshot_id="portal-snapshot:" + "1" * 64,
            period=DatePeriod(start=AS_OF, end=AS_OF + timedelta(days=1)),
        )


def test_cdispd_parameter_survives_snapshot_hydration_without_raw_source_bytes() -> None:
    snapshot = _snapshot_with_parameter(_parameter_file())

    hydrated = PortalOffersSnapshot.model_validate(snapshot.model_dump(mode="python"))

    assert hydrated.cdispd_parameter == snapshot.cdispd_parameter
    assert hydrated.cdispd_parameter is not None
    assert hydrated.files[1].content is None
    assert hydrated.files[1].sha256 == snapshot.files[1].sha256


def test_projection_binds_parameter_source_to_catalog_period_and_explicit_assumption() -> None:
    snapshot = _snapshot_with_parameter(_parameter_file())
    parameter = snapshot.cdispd_parameter
    assert parameter is not None
    horizon = DatePeriod(start=date(2026, 11, 1), end=date(2027, 11, 1))
    projection = PortalCdispDProjection(
        parameter=parameter,
        catalog_snapshot_id=snapshot.snapshot_id,
        period=horizon,
    )

    assert projection.policy == "portal_current_parameter_constant"
    assert projection.future_values_verified is False
    assert projection.costs_are_estimates is True
    assert projection_matches_snapshot(projection, snapshot, horizon)
    assert not projection_matches_snapshot(
        projection, snapshot, DatePeriod(start=date(2026, 12, 1), end=date(2027, 12, 1))
    )
    assert not projection_matches_snapshot(
        projection.model_copy(update={"catalog_snapshot_id": "portal-snapshot:" + "f" * 64}),
        snapshot,
        horizon,
    )


def test_snapshot_parser_keeps_catalog_when_cdispd_row_is_missing() -> None:
    snapshot = _snapshot_with_parameter(
        _parameter_file(b"nome_parametro,valore,descrizione\nfoo,0.2,other\n")
    )

    assert snapshot.status == VerificationStatus.VERIFIED
    assert snapshot.cdispd_parameter is None


@pytest.mark.parametrize(
    "content",
    [b"nome_parametro,valore,descrizione\n", b"unexpected,columns\n"],
)
def test_malformed_market_free_parameter_file_does_not_abort_offer_catalog(
    content: bytes,
) -> None:
    base, _ = _dispatching_offer()
    files = tuple(
        item.model_copy(
            update={
                "content": content,
                "size": len(content),
                "sha256": sha256(content).hexdigest(),
            }
        )
        if item.role == PortalSourceRole.MARKET_FREE_PARAMETERS
        else item
        for item in base.offers.files
    )
    importer = PortalOffersImporter()
    snapshot = PortalOffersSnapshot(
        dataset_date=base.offers.dataset_date,
        files=files,
        snapshot_id=importer._snapshot_id(base.offers.dataset_date, files),
        status=VerificationStatus.VERIFIED,
        parser_version="independent-test",
        cdispd_parameter=None,
    )

    records = PortalOffersImporter.parse_offers(snapshot)

    assert len(records) == 2


@pytest.mark.parametrize("residential", [True, False])
def test_current_cdispd_projection_prices_once_for_both_domestic_profiles(
    residential: bool,
) -> None:
    base, record = _dispatching_offer()
    parameter_file = _parameter_file(dataset_date=base.offers.dataset_date)
    files = tuple(
        parameter_file if item.role == PortalSourceRole.MARKET_FREE_PARAMETERS else item
        for item in base.offers.files
    )
    parameter = parse_market_free_cdispd_parameter(parameter_file)
    assert parameter is not None
    importer = PortalOffersImporter()
    snapshot = PortalOffersSnapshot(
        dataset_date=base.offers.dataset_date,
        files=files,
        snapshot_id=importer._snapshot_id(base.offers.dataset_date, files),
        status=VerificationStatus.VERIFIED,
        parser_version="independent-test",
        cdispd_parameter=parameter,
    )
    period = DatePeriod(start=date(2026, 2, 1), end=date(2026, 3, 1))
    projection = PortalCdispDProjection(
        parameter=parameter,
        catalog_snapshot_id=snapshot.snapshot_id,
        period=period,
    )

    normalized = normalize_offers(
        snapshot,
        (record,),
        _eligibility(residential),
        period.start,
        period.start + timedelta(days=1),
        cdispd_reference_period=period,
        cdispd_projection=projection,
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
    cdispd = cdispd_rules[0]
    assert cdispd.basis == ChargeBasis.PER_KWH
    assert cdispd.value == UnitRate(amount=Decimal("0.016776"), unit=RateUnit.EUR_PER_KWH)
    assert cdispd.validity == period
    assert cdispd.losses_included is True
    assert cdispd.included_semantics == (
        ComponentMeaning.DISPATCHING,
        ComponentMeaning.CAPACITY_MARKET,
    )
    assert any(item.sha256 == parameter.provenance[0].sha256 for item in cdispd.provenance)

    priced = _price_one_month(tariff, residential, period)
    cdispd_costs = tuple(
        item
        for item in priced.breakdown.components
        if item.meaning == ComponentMeaning.DISPATCHING_CAPACITY_AGGREGATE
    )
    assert len(cdispd_costs) == 1
    assert cdispd_costs[0].quantity == Decimal("100")
    assert cdispd_costs[0].amount.amount == Decimal("1.68")
    assert cdispd_costs[0].period == period


def test_projection_is_required_and_must_match_the_comparison_period() -> None:
    base, record = _dispatching_offer()
    parameter_file = _parameter_file(dataset_date=base.offers.dataset_date)
    files = tuple(
        parameter_file if item.role == PortalSourceRole.MARKET_FREE_PARAMETERS else item
        for item in base.offers.files
    )
    parameter = parse_market_free_cdispd_parameter(parameter_file)
    assert parameter is not None
    importer = PortalOffersImporter()
    snapshot = PortalOffersSnapshot(
        dataset_date=base.offers.dataset_date,
        files=files,
        snapshot_id=importer._snapshot_id(base.offers.dataset_date, files),
        status=VerificationStatus.VERIFIED,
        parser_version="independent-test",
        cdispd_parameter=parameter,
    )
    period = DatePeriod(start=date(2026, 2, 1), end=date(2026, 3, 1))
    other_period = DatePeriod(start=date(2026, 3, 1), end=date(2026, 4, 1))
    projection = PortalCdispDProjection(
        parameter=parameter,
        catalog_snapshot_id=snapshot.snapshot_id,
        period=other_period,
    )

    no_assumption = normalize_offers(
        snapshot,
        (record,),
        _eligibility(True),
        period.start,
        period.start + timedelta(days=1),
    )
    mismatched_period = normalize_offers(
        snapshot,
        (record,),
        _eligibility(True),
        period.start,
        period.start + timedelta(days=1),
        cdispd_reference_period=period,
        cdispd_projection=projection,
    )

    assert no_assumption.eligible_count == 0
    assert mismatched_period.eligible_count == 0
    assert "projection" in mismatched_period.exclusions[0].detail
