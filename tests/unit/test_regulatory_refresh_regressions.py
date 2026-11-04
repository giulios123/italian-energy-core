from datetime import UTC, date, datetime

import pytest

from italian_energy.arera.discovery import (
    DiscoveryActDisposition,
    DiscoveryChangeKind,
    DiscoverySnapshot,
    OfficialRegistryRecord,
    RegistryIndexPage,
    RegulatoryRegistryChannel,
    compare_overlapping_discoveries,
    scan_regulatory_registry,
)
from italian_energy.arera.rollover_classification import classify_official_regulatory_record
from italian_energy.domain.time import DatePeriod

NOW = datetime(2026, 11, 4, 12, tzinfo=UTC)
PERIOD = DatePeriod(start=date(2026, 10, 1), end=date(2026, 11, 5))


class _Adapter:
    adapter_id = "regulatory-date-regression"
    adapter_version = "1.0.0"

    def __init__(self, page: RegistryIndexPage) -> None:
        self.page = page
        self.channel = page.channel

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        assert search_period == self.page.search_period
        assert page_number == 1
        assert cursor is None
        return self.page


def _tariff(**updates: object) -> OfficialRegistryRecord:
    record = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="343/2026/R/com",
        title="delibera 343/2026/R/com",
        published_at=date(2026, 9, 29),
        registry_date=date(2026, 9, 29),
        effective_from=date(2026, 10, 1),
        url="https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26",
        document_id="343/2026/R/com",
    )
    return record.model_copy(update=updates)


def _scan(
    records: tuple[OfficialRegistryRecord, ...], period: DatePeriod = PERIOD
) -> DiscoverySnapshot:
    channel = records[0].channel if records else RegulatoryRegistryChannel.ARERA_TARIFFS
    page = RegistryIndexPage(
        channel=channel,
        search_period=period,
        query="date-regression",
        source_url="https://www.arera.it/area-operatori/prezzi-e-tariffe/",
        fetched_at=NOW,
        page_number=1,
        total_pages=1,
        total_results=len(records),
        index_sha256="a" * 64,
        cursor_out=period.end.isoformat(),
        records=records,
    )
    return scan_regulatory_registry(_Adapter(page), period, NOW)


def test_tariff_published_before_quarter_is_retained_by_effective_date() -> None:
    result = _scan((_tariff(),))
    assert result.complete
    assert result.next_cursor is not None
    assert len(result.records) == 1
    assert result.records[0].published_at == date(2026, 9, 29)
    assert result.records[0].registry_date == date(2026, 9, 29)
    assert result.records[0].effective_from == date(2026, 10, 1)


@pytest.mark.parametrize("effective", [None, date(2026, 9, 30), date(2026, 11, 5)])
def test_tariff_without_any_in_period_date_keeps_gate_closed(
    effective: date | None,
) -> None:
    result = _scan((_tariff(effective_from=effective),))
    assert not result.complete
    assert result.reason_code is not None
    assert result.next_cursor is None


def test_general_acts_still_use_publication_even_when_effective_date_is_in_period() -> None:
    result = _scan((_tariff(channel=RegulatoryRegistryChannel.ARERA_ACTS),))
    assert not result.complete
    assert result.next_cursor is None


def test_tariff_announced_in_period_can_be_staged_before_its_effective_date() -> None:
    result = _scan((_tariff(effective_from=date(2027, 1, 1), registry_date=date(2026, 10, 2)),))
    assert result.complete
    assert len(result.records) == 1
    assert result.records[0].effective_from == date(2027, 1, 1)


def test_tariff_records_are_sorted_by_effective_date() -> None:
    earlier = _tariff()
    later = _tariff(
        act_id="400/2026/R/com",
        document_id="400/2026/R/com",
        published_at=date(2026, 9, 28),
        registry_date=date(2026, 9, 28),
        effective_from=date(2026, 11, 1),
    )
    result = _scan((later, earlier))
    assert result.complete
    assert [record.act_id for record in result.records] == [earlier.act_id, later.act_id]


def test_tariff_removed_in_effective_date_overlap_is_detected() -> None:
    previous = _scan((_tariff(),), DatePeriod(start=date(2026, 9, 1), end=date(2026, 11, 1)))
    current = _scan(())
    changes = compare_overlapping_discoveries(previous, current)
    assert len(changes) == 1
    assert changes[0].act_id == "343/2026/R/com"
    assert changes[0].kind == DiscoveryChangeKind.REMOVED


def _october_decree() -> OfficialRegistryRecord:
    return OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26A05715",
        document_id="26A05715",
        title="Rideterminazione temporanea dell'aliquota d'accisa",
        published_at=date(2026, 10, 27),
        registry_date=date(2026, 10, 27),
        url="https://www.gazzettaufficiale.it/atto/serie_generale/"
        "caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=2026-10-27&"
        "atto.codiceRedazionale=26A05715&elenco30giorni=false",
    )


def _october_tua() -> OfficialRegistryRecord:
    return OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
        act_id="095G0523",
        document_id="095G0523",
        title="Testo unico accise",
        published_at=date(1995, 11, 29),
        registry_date=date(2026, 10, 27),
        latest_amending_act_ids=("26A05715",),
        url="https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/ricerca/aggiornati",
    )


@pytest.mark.parametrize("record", [_october_decree(), _october_tua()])
def test_exact_october_diesel_records_are_outside_household_electricity_scope(
    record: OfficialRegistryRecord,
) -> None:
    finding = classify_official_regulatory_record(record)
    assert finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert finding.rule_id is not None
    assert finding.rule_version == "1.0.0"
    assert "household" in finding.rationale


@pytest.mark.parametrize("record", [_october_decree(), _october_tua()])
@pytest.mark.parametrize(
    "updates",
    [
        {"act_id": "unknown"},
        {"document_id": "unknown"},
        {"registry_date": date(2026, 10, 28)},
        {"published_at": date(2026, 10, 28)},
        {"url": "https://www.normattiva.it/unknown"},
    ],
)
def test_similar_october_records_keep_review_required(
    record: OfficialRegistryRecord,
    updates: dict[str, object],
) -> None:
    finding = classify_official_regulatory_record(record.model_copy(update=updates))
    assert finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED


@pytest.mark.parametrize("amending", [("26A05716",), ("26A05715", "26A05716"), ()])
def test_tua_different_or_additional_amendments_remain_blocking(amending: tuple[str, ...]) -> None:
    finding = classify_official_regulatory_record(
        _october_tua().model_copy(update={"latest_amending_act_ids": amending})
    )
    assert finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED


@pytest.mark.parametrize("suffix", ["&malformed", "&extra=value", "#changed"])
def test_october_decree_url_variations_remain_unclassified(suffix: str) -> None:
    record = _october_decree()
    finding = classify_official_regulatory_record(
        record.model_copy(update={"url": record.url + suffix})
    )
    assert finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED


@pytest.mark.parametrize("record", [_october_decree(), _october_tua()])
def test_october_records_with_an_unexpected_effective_date_remain_unclassified(
    record: OfficialRegistryRecord,
) -> None:
    finding = classify_official_regulatory_record(
        record.model_copy(update={"effective_from": date(2026, 10, 28)})
    )
    assert finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
