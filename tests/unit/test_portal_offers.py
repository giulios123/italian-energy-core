from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import cast
from urllib.request import Request
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

from italian_energy.billing import load_coverage_matrix, load_ruleset
from italian_energy.comparison import ComparisonContext
from italian_energy.domain import (
    ConsumptionBucket,
    ConsumptionProfile,
    Contract,
    DatePeriod,
    EnergyQuantity,
    FixedTariff,
    Granularity,
    Power,
    RateUnit,
    RoundingMode,
    RoundingPolicy,
    SupplyClassification,
    SupplyPoint,
    TimeInterval,
    UnitRate,
    VoltageLevel,
)
from italian_energy.domain.formula import AddPrice
from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.tariff import BandPrice, ChargeBasis
from italian_energy.portal_offers import (
    PortalCatalog,
    PortalComparisonRequest,
    PortalComparisonService,
    PortalEligibilityProfile,
    PortalHttpResponse,
    PortalImportError,
    PortalOfferExclusionCode,
    PortalOffersImporter,
    PortalTerritory,
)
from italian_energy.portal_offers import importer as portal_importer
from italian_energy.portal_offers import models as portal_models
from italian_energy.portal_offers import normalizer as portal_normalizer
from italian_energy.portal_offers.normalizer import normalize_offers

DATE = date(2026, 1, 1)
XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListaOfferteMercatoLibero
 xmlns="http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01">
  <offerta>
    <IdentificativiOfferta>
      <PIVA_UTENTE>12345678901</PIVA_UTENTE>
      <COD_OFFERTA>XML1</COD_OFFERTA>
    </IdentificativiOfferta>
    <DettaglioOfferta>
      <TIPO_CLIENTE>01</TIPO_CLIENTE><TIPO_OFFERTA>01</TIPO_OFFERTA>
      <NOME_OFFERTA>XML fixed</NOME_OFFERTA>
      <ModalitaAttivazione><MODALITA>02</MODALITA></ModalitaAttivazione>
    </DettaglioOfferta>
    <ValiditaOfferta>
      <DATA_INIZIO>01/01/2026_00:00:00</DATA_INIZIO>
      <DATA_FINE>31/12/2026_23:59:59</DATA_FINE>
    </ValiditaOfferta>
    <MetodoPagamento><MODALITA_PAGAMENTO>01</MODALITA_PAGAMENTO></MetodoPagamento>
    <ComponenteImpresa>
      <NOME>Prezzo energia</NOME><DESCRIZIONE>energia</DESCRIZIONE><MACROAREA>04</MACROAREA>
      <IntervalloPrezzi>
        <FASCIA_COMPONENTE>01</FASCIA_COMPONENTE><PREZZO>0.20</PREZZO>
        <UNITA_MISURA>03</UNITA_MISURA>
      </IntervalloPrezzi>
    </ComponenteImpresa>
    <ComponenteImpresa>
      <NOME>Quota fissa</NOME><DESCRIZIONE>commerciale</DESCRIZIONE><MACROAREA>01</MACROAREA>
      <IntervalloPrezzi><PREZZO>120</PREZZO><UNITA_MISURA>01</UNITA_MISURA></IntervalloPrezzi>
    </ComponenteImpresa>
  </offerta>
</ListaOfferteMercatoLibero>"""
PLACET = (
    b"denominazione,codice_fiscale,p_iva,url_sito_venditore,telefono,nome_offerta,"
    b"cod_offerta,url_offerta,modalita_attivazione,modalita_pagamento,data_inizio,"
    b"data_fine,tipo_cliente,tipo_offerta,p_fix_f,p_fix_v,p_vol_f1,p_vol_f2,p_vol_f3,"
    b"p_vol_bf1,p_vol_bf23,p_vol_mono,alpha,regione,provincia,comune\n"
    b"Seller,,,,,PLACET fixed,PL1,,02,01,01/01/2026,31/12/2026,domestico,"
    b"prezzo fisso,120,,,0.20,0.20,0.20,,,,06,015,015213\n"
)
PARAMETERS = b"nome_parametro;valore;descrizione\nfoo;1;fixture\n"
INDICES = "AnnoMese;PUN (€/kWh);PE (€/kWh)\n202601;0,10;0,20\n".encode()


class FakeTransport:
    def __init__(self, contents: Mapping[str, tuple[bytes, str]]) -> None:
        self.contents = contents
        self.urls: list[str] = []

    def get(self, url: str, timeout_seconds: float) -> PortalHttpResponse:
        self.urls.append(url)
        for marker, (content, content_type) in self.contents.items():
            if marker in url:
                return PortalHttpResponse(
                    status=200, url=url, headers={"Content-Type": content_type}, content=content
                )
        raise AssertionError(url)


def _transport() -> FakeTransport:
    return FakeTransport(
        {
            "offerteML": (XML, "application/xml"),
            "parametriML": (PARAMETERS, "text/csv"),
            "offerte/": (PLACET, "text/csv"),
            "parametri/": (PARAMETERS, "text/csv"),
            "documents/": (INDICES, "text/csv"),
        }
    )


def _eligibility() -> PortalEligibilityProfile:
    return PortalEligibilityProfile(
        territory=PortalTerritory(
            region_code="06", province_code="015", municipality_code="015213"
        ),
        activation_method="02",
        payment_method="01",
    )


def test_fetch_snapshot_is_allowlisted_and_parses_both_catalogues() -> None:
    transport = _transport()
    snapshot = PortalOffersImporter(
        transport=transport, clock=lambda: datetime(2026, 2, 1, tzinfo=UTC)
    ).fetch(DATE)
    assert len(snapshot.offers.files) == 4
    assert snapshot.indexes is not None
    assert all("www.ilportaleofferte.it" in url for url in transport.urls)
    records = PortalOffersImporter.parse_offers(snapshot.offers)
    assert {record.source_offer_id for record in records} == {"XML1", "PL1"}
    assert all(record.tariff_validity.end == date(2027, 1, 1) for record in records)
    market = PortalOffersImporter.parse_market_data(snapshot.indexes)
    assert market is not None
    assert market.points[0].value == Decimal("0.10")


def test_parser_rejects_schema_and_transport_drift() -> None:
    transport = FakeTransport(
        {
            "offerteML": (b"<wrong/>", "application/xml"),
            "parametriML": (PARAMETERS, "text/csv"),
            "offerte/": (PLACET, "text/csv"),
            "parametri/": (PARAMETERS, "text/csv"),
        }
    )
    importer = PortalOffersImporter(transport=transport)
    snapshot = importer.fetch(DATE, include_indexes=False)
    with pytest.raises(PortalImportError, match=r"root|XML"):
        importer.parse_offers(snapshot.offers)


def test_normalizer_keeps_fixed_offer_and_excludes_non_domestic() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    records = PortalOffersImporter.parse_offers(snapshot.offers)
    result = normalize_offers(snapshot.offers, records, _eligibility(), DATE, date(2026, 2, 1))
    assert result.eligible_count == 2
    assert result.exclusions == ()
    assert result.eligible_offers[0].offer_id.startswith("portal:")
    assert result.eligible_offers[0].tariff.kind in {"fixed", "indexed"}


def test_offline_snapshot_is_audit_only_and_counts_every_record() -> None:
    live = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    offline = live.offers.model_copy(update={"status": "unverified"})
    records = PortalOffersImporter.parse_offers(offline)
    result = normalize_offers(offline, records, _eligibility(), DATE, date(2026, 2, 1))
    assert result.eligible_count == 0
    assert result.excluded_count == result.received_count == len(records)
    assert {item.code for item in result.exclusions} == {PortalOfferExclusionCode.NOT_VERIFIED}


def test_snapshot_manifest_is_immutable_and_content_digest_is_checked() -> None:
    file = (
        PortalOffersImporter(transport=_transport())
        .fetch(DATE, include_indexes=False)
        .offers.files[0]
    )
    assert file.sha256 == sha256(file.content or b"").hexdigest()
    with pytest.raises(ValidationError):
        file.content = b"changed"  # type: ignore[misc]


def test_service_runs_preflight_import_and_comparison() -> None:
    period = DatePeriod(start=DATE, end=date(2026, 2, 1))
    contract = Contract(
        contract_id="current",
        supply=SupplyPoint(
            supply_id="pod",
            market_zone="NORD",
            contracted_power=Power(kw=Decimal("3")),
            residential=True,
        ),
        tariff=FixedTariff(
            tariff_id="current-tariff",
            validity=DatePeriod(start=DATE, end=date(2027, 1, 1)),
            prices=(
                BandPrice(
                    band="ALL", rate=UnitRate(amount=Decimal("0.30"), unit=RateUnit.EUR_PER_KWH)
                ),
            ),
        ),
        validity=DatePeriod(start=DATE, end=date(2027, 1, 1)),
    )
    context = ComparisonContext(
        current_contract=contract,
        consumption=ConsumptionProfile(
            profile_id="profile",
            buckets=(
                ConsumptionBucket(
                    interval=TimeInterval(
                        start=datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/Rome")),
                        end=datetime(2026, 1, 1, 1, tzinfo=ZoneInfo("Europe/Rome")),
                    ),
                    energy=EnergyQuantity(kwh=Decimal("100")),
                    granularity=Granularity.HOUR,
                ),
            ),
        ),
        period=period,
        as_of=DATE,
        classification=SupplyClassification(
            contract_type_code="domestic_bt_resident",
            voltage_level=VoltageLevel.BT,
            usage_code="domestic",
            residential=True,
        ),
        rule_set=load_ruleset(segment="resident"),
        coverage_matrix=load_coverage_matrix(),
        rounding_policy=RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP),
        percentage_rounding_policy=RoundingPolicy(scale=2, mode=RoundingMode.HALF_UP),
    )
    request = PortalComparisonRequest(
        comparison=context,
        catalogs=frozenset({PortalCatalog.MARKET_FREE, PortalCatalog.PLACET}),
        eligibility=_eligibility(),
    )
    result = PortalComparisonService(
        importer=PortalOffersImporter(transport=_transport()),
        clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    ).compare(request)
    assert result.comparison_result.current_contract_id == "current"
    assert result.import_result.received_count == 2
    assert result.comparison_result.ranking
    indexed_transport = FakeTransport(
        {
            "offerteML": (XML, "application/xml"),
            "parametriML": (PARAMETERS, "text/csv"),
            "offerte/": (PLACET.replace(b"prezzo fisso", b"prezzo variabile"), "text/csv"),
            "parametri/": (PARAMETERS, "text/csv"),
            "documents/": (INDICES, "text/csv"),
        }
    )
    indexed_result = PortalComparisonService(
        importer=PortalOffersImporter(transport=indexed_transport),
        clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
    ).compare(request)
    assert indexed_result.import_result.eligible_count == 2
    assert indexed_result.comparison_result.ranking
    assert indexed_result.portal_result_id == indexed_result.portal_comparison_id


def test_normalizer_resolves_relative_duration_and_clamps_month_end() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    source = PortalOffersImporter.parse_offers(snapshot.offers)[0]
    record = source.model_copy(
        update={
            "subscription_period": DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
            "tariff_validity": DatePeriod(start=date(2026, 1, 1), end=date(2027, 1, 1)),
            "duration_months": 1,
        }
    )
    result = normalize_offers(
        snapshot.offers,
        (record,),
        _eligibility(),
        date(2026, 1, 31),
        date(2026, 3, 1),
    )
    assert result.eligible_count == 0
    assert result.exclusions[0].code == PortalOfferExclusionCode.PERIOD_NOT_COVERED


def test_normalizer_supports_multiple_indexes_and_reports_missing_inputs() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    source = PortalOffersImporter.parse_offers(snapshot.offers)[0]
    indexed = source.model_copy(
        update={
            "offer_type": portal_models.PortalOfferType.INDEXED,
            "index_code": "PUN",
            "index_codes": ("PUN", "PE"),
            "tariff_validity": DatePeriod(start=DATE, end=date(2027, 1, 1)),
        }
    )
    missing = normalize_offers(
        snapshot.offers, (indexed,), _eligibility(), DATE, date(2026, 2, 1), market_data=None
    )
    assert missing.exclusions[0].code == PortalOfferExclusionCode.INDEXED_INPUT_MISSING
    indexes_snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE).indexes
    assert indexes_snapshot is not None
    market = PortalOffersImporter.parse_market_data(indexes_snapshot)
    complete = normalize_offers(
        snapshot.offers,
        (indexed,),
        _eligibility(),
        DATE,
        date(2026, 2, 1),
        market_data=market,
    )
    assert complete.eligible_count == 1
    expression = complete.normalized[0].offer.tariff.formulas[0].expression  # type: ignore[union-attr]
    assert isinstance(expression, AddPrice)


@pytest.mark.parametrize(
    ("field", "value"),
    [("retrieved_at", datetime(2026, 1, 1)), ("content_type", "")],
)
def test_snapshot_models_reject_invalid_metadata(field: str, value: object) -> None:
    kwargs: dict[str, object] = {
        "role": portal_models.PortalSourceRole.PLACET_OFFERS,
        "original_url": "https://www.ilportaleofferte.it/x",
        "final_url": "https://www.ilportaleofferte.it/x",
        "retrieved_at": datetime(2026, 1, 1, tzinfo=UTC),
        "content_type": "text/csv",
        "size": 0,
        "sha256": sha256(b"").hexdigest(),
    }
    kwargs[field] = value
    with pytest.raises(ValidationError):
        portal_models.PortalFileSnapshot.model_validate(kwargs)


def test_snapshot_models_validate_roles_dates_and_result_counts() -> None:
    snapshot = (
        PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False).offers
    )
    with pytest.raises(ValidationError, match="four"):
        portal_models.PortalOffersSnapshot(
            dataset_date=DATE,
            files=snapshot.files[:1],
            snapshot_id=snapshot.snapshot_id,
            status=snapshot.status,
            parser_version=snapshot.parser_version,
        )
    with pytest.raises(ValidationError, match="counts"):
        portal_models.PortalOffersImportResult(
            snapshot=snapshot,
            status=snapshot.status,
            import_id="portal-import:" + "0" * 64,
            received_count=1,
            eligible_count=0,
            excluded_count=0,
        )

    file = snapshot.files[0]
    file_data = file.model_dump(mode="python")
    file_data["content"] = file.content
    with pytest.raises(ValidationError, match="digest"):
        portal_models.PortalFileSnapshot.model_validate({**file_data, "sha256": "1" * 64})
    with pytest.raises(ValidationError, match="size"):
        portal_models.PortalFileSnapshot.model_validate({**file_data, "size": file.size + 1})
    wrong_date = file.model_copy(update={"dataset_date": date(2025, 1, 1)})
    with pytest.raises(ValidationError, match="dates"):
        portal_models.PortalOffersSnapshot(
            dataset_date=DATE,
            files=tuple(wrong_date if item is file else item for item in snapshot.files),
            snapshot_id=snapshot.snapshot_id,
            status=snapshot.status,
            parser_version=snapshot.parser_version,
        )


def test_importer_rejects_bad_media_status_redirect_and_size() -> None:
    class BadTransport:
        def __init__(self, response: PortalHttpResponse) -> None:
            self.response = response

        def get(self, url: str, timeout_seconds: float) -> PortalHttpResponse:
            return self.response

    url = portal_importer._url_for(portal_models.PortalSourceRole.PLACET_OFFERS, DATE)
    for response in (
        PortalHttpResponse(status=500, url=url, headers={"Content-Type": "text/csv"}, content=b""),
        PortalHttpResponse(
            status=200,
            url="https://evil.example/x",
            headers={"Content-Type": "text/csv"},
            content=b"",
        ),
        PortalHttpResponse(
            status=200, url=url, headers={"Content-Type": "application/pdf"}, content=b""
        ),
    ):
        with pytest.raises(PortalImportError):
            PortalOffersImporter(transport=BadTransport(response)).fetch(
                DATE, include_indexes=False
            )

    huge = b"x" * (portal_importer.MAX_CSV_BYTES + 1)
    response = PortalHttpResponse(
        status=200, url=url, headers={"Content-Type": "text/csv"}, content=huge
    )
    with pytest.raises(PortalImportError, match="size"):
        PortalOffersImporter(transport=BadTransport(response))._fetch_file(
            portal_models.PortalSourceRole.PLACET_OFFERS, DATE, 60
        )


def test_importer_rejects_invalid_csv_dates_decimals_and_index_month() -> None:
    base = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False).offers
    placet_file = next(
        item for item in base.files if item.role == portal_models.PortalSourceRole.PLACET_OFFERS
    )
    bad_csv = PLACET.replace(b"01/01/2026", b"not-a-date")
    bad_file = placet_file.model_copy(
        update={"content": bad_csv, "size": len(bad_csv), "sha256": sha256(bad_csv).hexdigest()}
    )
    with pytest.raises(PortalImportError, match="date"):
        portal_importer._parse_placet_csv(bad_file)
    bad_decimal = PLACET.replace(b"0.20", b"NaN")
    bad_file = placet_file.model_copy(
        update={
            "content": bad_decimal,
            "size": len(bad_decimal),
            "sha256": sha256(bad_decimal).hexdigest(),
        }
    )
    with pytest.raises(PortalImportError, match="decimal"):
        portal_importer._parse_placet_csv(bad_file)
    index_file = PortalOffersImporter(transport=_transport()).fetch(DATE).indexes.file  # type: ignore[union-attr]
    invalid_index = INDICES.replace(b"202601", b"202613")
    bad_index = index_file.model_copy(
        update={
            "content": invalid_index,
            "size": len(invalid_index),
            "sha256": sha256(invalid_index).hexdigest(),
        }
    )
    with pytest.raises((PortalImportError, ValueError), match="month"):
        portal_importer._parse_historical_indices(bad_index)


def test_normalizer_excludes_duplicate_territory_activation_payment_and_dual() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    record = PortalOffersImporter.parse_offers(snapshot.offers)[0]
    records = (
        record,
        record,
        record.model_copy(update={"source_offer_id": "business", "customer_type": "business"}),
        record.model_copy(update={"source_offer_id": "region", "region_codes": ("99",)}),
        record.model_copy(update={"source_offer_id": "activation", "activation_methods": ("99",)}),
        record.model_copy(update={"source_offer_id": "payment", "payment_methods": ("99",)}),
        record.model_copy(
            update={"source_offer_id": "dual", "conditions": ("dual fuel required",)}
        ),
        record.model_copy(
            update={"source_offer_id": "mandatory", "conditions": ("mandatory service",)}
        ),
        record.model_copy(update={"source_offer_id": "provenance", "source_provenance": ()}),
    )
    result = normalize_offers(snapshot.offers, records, _eligibility(), DATE, date(2026, 2, 1))
    assert result.received_count == result.eligible_count + result.excluded_count
    codes = {item.code for item in result.exclusions}
    assert PortalOfferExclusionCode.DUPLICATE_OFFER_ID in codes
    assert PortalOfferExclusionCode.CLASSIFICATION_NOT_COVERED in codes
    assert PortalOfferExclusionCode.TERRITORY_NOT_COVERED in codes
    assert PortalOfferExclusionCode.ACTIVATION_NOT_COVERED in codes
    assert PortalOfferExclusionCode.PAYMENT_NOT_COVERED in codes
    assert PortalOfferExclusionCode.DUAL_FUEL_REQUIRED in codes
    assert PortalOfferExclusionCode.MANDATORY_SERVICE_REQUIRED in codes
    assert PortalOfferExclusionCode.MISSING_PROVENANCE in codes


def test_market_merge_accepts_equal_data_and_rejects_conflict() -> None:
    from italian_energy.portal_offers.service import merge_market_data

    assert merge_market_data(None, None) is None
    index = MarketIndex(
        code="PUN", name="PUN", unit=RateUnit.EUR_PER_KWH, granularity=Granularity.MONTH
    )
    interval = TimeInterval(
        start=datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/Rome")),
        end=datetime(2026, 2, 1, tzinfo=ZoneInfo("Europe/Rome")),
    )
    point = MarketDataPoint(index_code="PUN", interval=interval, value=Decimal("0.10"))
    official = MarketData(indexes=(index,), points=(point,))
    provenance = (
        Provenance(
            source="test",
            source_identifier="idx",
            retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
            dataset_version="1",
        ),
    )
    verified = portal_models.VerifiedMarketData(
        data=official,
        status=VerificationStatus.VERIFIED,
        provenance=provenance,
        sha256="0" * 64,
    )
    assert merge_market_data(official, verified) == official
    conflict = portal_models.VerifiedMarketData(
        data=MarketData(
            indexes=(index,), points=(point.model_copy(update={"value": Decimal("0.11")}),)
        ),
        status=VerificationStatus.VERIFIED,
        provenance=provenance,
        sha256="0" * 64,
    )
    with pytest.raises(PortalImportError, match="point"):
        merge_market_data(official, conflict)
    conflict_index = portal_models.VerifiedMarketData(
        data=MarketData(
            indexes=(index.model_copy(update={"name": "different"}),),
            points=(),
        ),
        status=VerificationStatus.VERIFIED,
        provenance=provenance,
        sha256="0" * 64,
    )
    with pytest.raises(PortalImportError, match="index definition"):
        merge_market_data(official, conflict_index)


def test_service_rejects_future_and_unverified_replays(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from italian_energy.portal_offers import service as portal_service

    future_request = SimpleNamespace(
        comparison=SimpleNamespace(period=DatePeriod(start=DATE, end=date(2026, 3, 1)), as_of=DATE)
    )
    future_service = PortalComparisonService(clock=lambda: datetime(2026, 2, 1, tzinfo=UTC))
    with pytest.raises(PortalImportError, match="concluded"):
        future_service.compare(cast(PortalComparisonRequest, future_request))

    verified_snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE)
    unverified_snapshot = verified_snapshot.model_copy(
        update={
            "offers": verified_snapshot.offers.model_copy(
                update={"status": VerificationStatus.UNVERIFIED}
            )
        }
    )

    class StubImporter:
        def fetch(self, dataset_date: date, *, include_indexes: bool = True) -> object:
            return unverified_snapshot

    class StubEngine:
        def preflight(self, context: object) -> None:
            return None

    concluded_request = SimpleNamespace(
        comparison=SimpleNamespace(period=DatePeriod(start=DATE, end=date(2026, 2, 1)), as_of=DATE)
    )
    with pytest.raises(PortalImportError, match="unverified"):
        PortalComparisonService(
            importer=StubImporter(),  # type: ignore[arg-type]
            engine=StubEngine(),  # type: ignore[arg-type]
            clock=lambda: datetime(2026, 2, 2, tzinfo=UTC),
        ).compare(concluded_request)  # type: ignore[arg-type]

    class StubService:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def compare(self, request: object) -> str:
            return "stub-result"

    monkeypatch.setattr(portal_service, "PortalComparisonService", StubService)
    assert portal_service.compare_portal_offers(cast(PortalComparisonRequest, object())) is not None


def test_normalizer_private_mappings_and_tariff_exclusions() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    record = PortalOffersImporter.parse_offers(snapshot.offers)[0]
    assert portal_normalizer._add_months_clamped(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert portal_normalizer._contains((), None)
    assert not portal_normalizer._contains(("01",), None)
    assert portal_normalizer._map_band(None, only_band="F1") == "F1"
    assert portal_normalizer._unit("unsupported") is None
    with pytest.raises(LookupError):
        portal_normalizer._record_index_codes(record.model_copy(update={"index_codes": ("BAD",)}))
    assert portal_normalizer._record_index_codes(
        record.model_copy(update={"index_codes": ("PUN", "01")})
    ) == ("PUN",)

    rules_record = record.model_copy(
        update={
            "components": (
                portal_models.PortalEconomicComponent(
                    code="energy",
                    description="energy",
                    amount=Decimal("0.10"),
                    unit="EUR/kWh",
                ),
                portal_models.PortalEconomicComponent(
                    code="annual", description="annual", amount=Decimal("12"), unit="EUR/year"
                ),
                portal_models.PortalEconomicComponent(
                    code="power",
                    description="power",
                    amount=Decimal("3"),
                    unit="EUR/kW/year",
                ),
                portal_models.PortalEconomicComponent(
                    code="discount",
                    description="discount",
                    amount=Decimal("1"),
                    unit="EUR/year",
                    discount=True,
                ),
                portal_models.PortalEconomicComponent(
                    code="ignored",
                    description="ignored",
                    amount=Decimal("1"),
                    unit="unsupported",
                ),
            )
        }
    )
    fixed_rules, additional_rules, discounts = portal_normalizer._charge_rules(rules_record)
    assert {rule.basis for rule in fixed_rules} == {
        ChargeBasis.PER_YEAR,
        ChargeBasis.PER_KW_YEAR,
    }
    assert additional_rules and discounts
    assert portal_normalizer._charge_rules(
        record.model_copy(
            update={
                "catalog": portal_models.PortalCatalog.PLACET,
                "components": (
                    portal_models.PortalEconomicComponent(
                        code="p_vol_f1",
                        description="volume",
                        amount=Decimal("1"),
                        unit="EUR/kWh",
                    ),
                ),
            }
        )
    ) == ((), (), ())

    outside = portal_models.PortalEconomicComponent(
        code="outside",
        description="outside",
        amount=Decimal("0.40"),
        unit="EUR/kWh",
        band="01",
        macroarea="01",
    )
    assert portal_normalizer._fixed_tariff(
        record.model_copy(update={"components": (record.components[0], outside)})
    ).prices
    mono = (
        portal_models.PortalEconomicComponent(
            code="f1",
            description="f1",
            amount=Decimal("0.20"),
            unit="EUR/kWh",
            band="01",
            macroarea="04",
        ),
        portal_models.PortalEconomicComponent(
            code="f2",
            description="f2",
            amount=Decimal("0.20"),
            unit="EUR/kWh",
            band="02",
            macroarea="04",
        ),
    )
    assert (
        portal_normalizer._fixed_tariff(record.model_copy(update={"components": mono}))
        .prices[0]
        .band
        == "ALL"
    )
    with pytest.raises(LookupError):
        portal_normalizer._indexed_tariff(
            record.model_copy(
                update={
                    "offer_type": portal_models.PortalOfferType.INDEXED,
                    "index_code": None,
                    "index_codes": (),
                }
            )
        )
    assert portal_normalizer._indexed_tariff(
        record.model_copy(
            update={
                "offer_type": portal_models.PortalOfferType.INDEXED,
                "index_code": "PUN",
                "index_codes": ("PUN",),
                "components": (
                    portal_models.PortalEconomicComponent(
                        code="external",
                        description="external",
                        amount=Decimal("0.01"),
                        unit="EUR/kWh",
                        index_code="PUN",
                        coefficient=Decimal("1.5"),
                        macroarea="01",
                    ),
                ),
            }
        )
    ).formulas
    with pytest.raises(LookupError):
        portal_normalizer._indexed_tariff(
            record.model_copy(
                update={
                    "offer_type": portal_models.PortalOfferType.INDEXED,
                    "index_code": "PUN",
                    "index_codes": ("PUN",),
                    "components": (
                        portal_models.PortalEconomicComponent(
                            code="bad-index",
                            description="bad-index",
                            amount=Decimal("0.01"),
                            unit="EUR/kWh",
                            index_code="BAD",
                        ),
                    ),
                }
            )
        )

    no_energy = record.model_copy(update={"source_offer_id": "no-energy", "components": ()})
    result = normalize_offers(snapshot.offers, (no_energy,), _eligibility(), DATE, date(2026, 2, 1))
    assert result.exclusions[0].code == PortalOfferExclusionCode.TARIFF_NOT_REPRESENTABLE
    conflicting = record.model_copy(
        update={
            "source_offer_id": "conflict",
            "components": (
                *record.components,
                portal_models.PortalEconomicComponent(
                    code="second",
                    description="second",
                    amount=Decimal("0.99"),
                    unit="EUR/kWh",
                    band="01",
                    macroarea="04",
                ),
            ),
        }
    )
    result = normalize_offers(
        snapshot.offers, (conflicting,), _eligibility(), DATE, date(2026, 2, 1)
    )
    assert result.exclusions[0].code == PortalOfferExclusionCode.TARIFF_NOT_REPRESENTABLE
    indexed_unknown = record.model_copy(
        update={
            "source_offer_id": "indexed-unknown",
            "offer_type": portal_models.PortalOfferType.INDEXED,
            "index_code": "BAD",
            "index_codes": ("BAD",),
        }
    )
    result = normalize_offers(
        snapshot.offers,
        (indexed_unknown,),
        _eligibility(),
        DATE,
        date(2026, 2, 1),
        market_data=MarketData(),
    )
    assert result.exclusions[0].code == PortalOfferExclusionCode.INDEXED_INPUT_MISSING


def test_normalizer_checks_all_applicability_boundaries_and_index_availability() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE)
    record = PortalOffersImporter.parse_offers(snapshot.offers)[0]
    variants = (
        record.model_copy(
            update={
                "source_offer_id": "old",
                "subscription_period": DatePeriod(start=date(2025, 1, 1), end=DATE),
            }
        ),
        record.model_copy(update={"source_offer_id": "province", "province_codes": ("999",)}),
        record.model_copy(
            update={"source_offer_id": "municipality", "municipality_codes": ("999999",)}
        ),
    )
    result = normalize_offers(snapshot.offers, variants, _eligibility(), DATE, date(2026, 2, 1))
    assert {item.code for item in result.exclusions} >= {
        PortalOfferExclusionCode.NOT_CURRENT,
        PortalOfferExclusionCode.TERRITORY_NOT_COVERED,
    }
    indexed = record.model_copy(
        update={
            "source_offer_id": "missing-index",
            "offer_type": portal_models.PortalOfferType.INDEXED,
            "index_code": "PUN",
            "index_codes": ("PUN", "PE"),
            "tariff_validity": DatePeriod(start=DATE, end=date(2027, 1, 1)),
        }
    )
    only_pun = MarketData(
        indexes=(
            MarketIndex(
                code="PUN",
                name="PUN",
                unit=RateUnit.EUR_PER_KWH,
                granularity=Granularity.MONTH,
            ),
        )
    )
    result = normalize_offers(
        snapshot.offers,
        (indexed,),
        _eligibility(),
        DATE,
        date(2026, 2, 1),
        market_data=only_pun,
    )
    assert result.exclusions[0].code == PortalOfferExclusionCode.INDEXED_INPUT_MISSING


def test_portal_ids_are_invariant_to_record_order() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)
    records = PortalOffersImporter.parse_offers(snapshot.offers)
    first = normalize_offers(snapshot.offers, records, _eligibility(), DATE, date(2026, 2, 1))
    second = normalize_offers(
        snapshot.offers, tuple(reversed(records)), _eligibility(), DATE, date(2026, 2, 1)
    )
    assert first.import_id == second.import_id
    assert first.exclusions == second.exclusions
    assert first.eligible_offers == second.eligible_offers


def test_importer_helpers_reject_invalid_inputs_and_parse_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert not portal_importer._is_allowlisted_url("http://www.ilportaleofferte.it/x")
    assert not portal_importer._is_allowlisted_url("https://evil.example/x")
    assert not portal_importer._is_allowlisted_url("https://www.ilportaleofferte.it/x?pod=1")
    assert portal_importer._header((("X-Test", "ok"),), "x-test") == "ok"
    assert portal_importer._header((), "x-test") is None
    assert portal_importer._parse_date("2026-01-01", field="x") == DATE
    assert portal_importer._parse_duration("-1") is None
    assert portal_importer._parse_duration("12") == 12
    with pytest.raises(PortalImportError):
        portal_importer._parse_duration("0")
    with pytest.raises(PortalImportError):
        portal_importer._parse_decimal("Infinity", field="x")
    with pytest.raises(PortalImportError):
        portal_importer._parse_decimal("not-a-number", field="x")
    with pytest.raises(PortalImportError, match="header"):
        portal_importer._csv_rows(b"")
    element = ET.fromstring(b"<root><x> value </x><x>two</x></root>")
    assert portal_importer._text(element, "x") == "value"
    assert portal_importer._all_text(element, "x") == ("value", "two")
    with pytest.raises(PortalImportError):
        portal_importer._content(
            portal_models.PortalFileSnapshot(
                role=portal_models.PortalSourceRole.PLACET_OFFERS,
                original_url="https://www.ilportaleofferte.it/x",
                final_url="https://www.ilportaleofferte.it/x",
                retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
                content_type="text/csv",
                size=0,
                sha256="0" * 64,
            )
        )

    with pytest.raises(ValueError):
        PortalOffersImporter(transport=_transport()).fetch(DATE, timeout_seconds=0)
    guard = portal_importer._RedirectGuard()
    with pytest.raises(PortalImportError, match="redirect"):
        guard.redirect_request(
            Request("https://www.ilportaleofferte.it/x"),
            None,
            302,
            "found",
            {},
            "https://evil.example/x",
        )
    monkeypatch.setattr(portal_importer, "MAX_TOTAL_BYTES", 1)
    with pytest.raises(PortalImportError, match="total size"):
        PortalOffersImporter(transport=_transport()).fetch(DATE, include_indexes=False)


def test_importer_rejects_parameter_and_source_shape_errors() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE)
    param = next(
        item
        for item in snapshot.offers.files
        if item.role == portal_models.PortalSourceRole.PLACET_PARAMETERS
    )
    empty = param.model_copy(update={"content": b"", "size": 0, "sha256": sha256(b"").hexdigest()})
    with pytest.raises(PortalImportError, match="header"):
        portal_importer._validate_parameter_csv(empty)
    wrong = param.model_copy(
        update={
            "content": b"unexpected\nvalue\n",
            "size": len(b"unexpected\nvalue\n"),
            "sha256": sha256(b"unexpected\nvalue\n").hexdigest(),
        }
    )
    with pytest.raises(PortalImportError, match="columns"):
        portal_importer._validate_parameter_csv(wrong)
    placet = next(
        item
        for item in snapshot.offers.files
        if item.role == portal_models.PortalSourceRole.PLACET_OFFERS
    )
    missing_code = PLACET.replace(b"PL1", b"")
    missing_code_file = placet.model_copy(
        update={
            "content": missing_code,
            "size": len(missing_code),
            "sha256": sha256(missing_code).hexdigest(),
        }
    )
    with pytest.raises(PortalImportError, match="offer code"):
        portal_importer._parse_placet_csv(missing_code_file)
    xml_file = next(
        item
        for item in snapshot.offers.files
        if item.role == portal_models.PortalSourceRole.MARKET_FREE_OFFERS
    )
    malformed = xml_file.model_copy(
        update={"content": b"<broken", "size": 7, "sha256": sha256(b"<broken").hexdigest()}
    )
    with pytest.raises(PortalImportError, match="XML"):
        portal_importer._parse_market_free_xml(malformed)
    malformed_offer = (
        b'<ListaOfferteMercatoLibero xmlns="http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01">'
        b"<offerta/></ListaOfferteMercatoLibero>"
    )
    malformed_offer_file = xml_file.model_copy(
        update={
            "content": malformed_offer,
            "size": len(malformed_offer),
            "sha256": sha256(malformed_offer).hexdigest(),
        }
    )
    with pytest.raises(PortalImportError, match=r"malformed|namespace"):
        portal_importer._parse_market_free_xml(malformed_offer_file)


def test_importer_handles_optional_xml_intervals_and_index_headers() -> None:
    snapshot = PortalOffersImporter(transport=_transport()).fetch(DATE)
    xml_file = next(
        item
        for item in snapshot.offers.files
        if item.role == portal_models.PortalSourceRole.MARKET_FREE_OFFERS
    )
    xml = b"""<ListaOfferteMercatoLibero xmlns="http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01"><offerta>
    <PIVA_UTENTE>1</PIVA_UTENTE><COD_OFFERTA>X</COD_OFFERTA>
    <DATA_INIZIO>01/01/2026</DATA_INIZIO><DATA_FINE>01/01/2027</DATA_FINE>
    <TIPO_OFFERTA>01</TIPO_OFFERTA><TIPO_CLIENTE>01</TIPO_CLIENTE>
    <ComponenteImpresa><NOME>X</NOME><IntervalloPrezzi><UNITA_MISURA>03</UNITA_MISURA></IntervalloPrezzi>
    <IntervalloPrezzi><PREZZO>1</PREZZO><UNITA_MISURA>99</UNITA_MISURA></IntervalloPrezzi></ComponenteImpresa>
    </offerta></ListaOfferteMercatoLibero>"""
    parsed = xml_file.model_copy(
        update={"content": xml, "size": len(xml), "sha256": sha256(xml).hexdigest()}
    )
    assert (
        PortalOffersImporter.parse_offers(
            snapshot.offers.model_copy(
                update={
                    "files": tuple(
                        parsed if item is xml_file else item for item in snapshot.offers.files
                    )
                }
            )
        )[0].components
        == ()
    )
    index_file = snapshot.indexes.file  # type: ignore[union-attr]
    empty = index_file.model_copy(
        update={"content": b"", "size": 0, "sha256": sha256(b"").hexdigest()}
    )
    with pytest.raises(PortalImportError, match="header"):
        portal_importer._parse_historical_indices(empty)
    bad_header = b"AnnoMese;Other\n202601;1\n"
    bad_header_file = index_file.model_copy(
        update={
            "content": bad_header,
            "size": len(bad_header),
            "sha256": sha256(bad_header).hexdigest(),
        }
    )
    with pytest.raises(PortalImportError, match="columns"):
        portal_importer._parse_historical_indices(bad_header_file)
    pun_only = b"AnnoMese;PUN (\xe2\x82\xac/kWh);PE (\xe2\x82\xac/kWh)\n202601;0,10;\n"
    pun_file = index_file.model_copy(
        update={"content": pun_only, "size": len(pun_only), "sha256": sha256(pun_only).hexdigest()}
    )
    assert len(portal_importer._parse_historical_indices(pun_file).indexes) == 2


def test_models_reject_scope_and_provenance_violations() -> None:
    snapshot = (
        PortalOffersImporter(transport=_transport(), clock=lambda: datetime(2026, 1, 1, tzinfo=UTC))
        .fetch(DATE, include_indexes=False)
        .offers
    )
    with pytest.raises(ValidationError):
        portal_models.PortalIndexSnapshot(
            file=snapshot.files[0],
            snapshot_id="portal-index-snapshot:" + "0" * 64,
            status=VerificationStatus.VERIFIED,
            parser_version="x",
        )
    with pytest.raises(ValidationError):
        PortalEligibilityProfile(territory=_eligibility().territory, domestic=False)
    with pytest.raises(ValidationError):
        PortalEligibilityProfile(territory=_eligibility().territory, voltage_level=VoltageLevel.MT)
    with pytest.raises(ValidationError):
        portal_models.VerifiedMarketData(
            data=MarketData(),
            status=VerificationStatus.UNVERIFIED,
            provenance=(),
            sha256="0" * 64,
        )
    with pytest.raises(ValidationError):
        portal_models.PortalEconomicComponent.model_validate(
            {"code": "x", "description": "x", "amount": "not-a-decimal", "unit": "EUR/kWh"}
        )
