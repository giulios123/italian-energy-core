from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import ValidationError

from italian_energy.arera.discovery import (
    DISCOVERY_CHANNELS,
    DiscoveryActDisposition,
    DiscoveryActFinding,
    DiscoveryChangeKind,
    DiscoveryFailure,
    DiscoveryRecordChange,
    DiscoverySnapshot,
    OfficialRegistryRecord,
    RegistryCursor,
    RegistryIndexPage,
    RegistryPageEvidence,
    RegulatoryDiscoveryReport,
    RegulatoryRegistryChannel,
    compare_overlapping_discoveries,
    discover_regulatory_sources,
    incremental_search_period,
    scan_regulatory_registry,
)
from italian_energy.arera.rollover_classification import classify_official_regulatory_record
from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.domain.time import DatePeriod
from italian_energy.integration.manifest import CORE_CONTRACT_VERSION, CoreSchemaId
from italian_energy.integration.serialization import dump_envelope, load_envelope

NOW = datetime(2026, 9, 30, 12, tzinfo=UTC)
PERIOD = DatePeriod(start=date(2026, 9, 23), end=date(2026, 10, 1))


class _FixtureAdapter:
    def __init__(
        self,
        channel: RegulatoryRegistryChannel,
        pages: tuple[RegistryIndexPage, ...],
        *,
        fail: bool = False,
        offline: bool = False,
        parse_error: bool = False,
    ) -> None:
        self.channel = channel
        self.adapter_id = f"synthetic-{channel.value}"
        self.adapter_version = "1.0.0"
        self.pages = pages
        self.fail = fail
        self.offline = offline
        self.parse_error = parse_error
        self.calls: list[tuple[int, str | None, DatePeriod]] = []

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        self.calls.append((page_number, cursor, search_period))
        if self.offline:
            raise TimeoutError("synthetic timeout")
        if self.parse_error:
            raise ValueError("unsupported synthetic index structure")
        if self.fail:
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_UNAVAILABLE)
        if page_number > len(self.pages):
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        return self.pages[page_number - 1]


def _index_url(channel: RegulatoryRegistryChannel) -> str:
    return {
        RegulatoryRegistryChannel.ARERA_ACTS: "https://www.arera.it/atti-e-provvedimenti/",
        RegulatoryRegistryChannel.ARERA_TARIFFS: (
            "https://www.arera.it/area-operatori/prezzi-e-tariffe/"
        ),
        RegulatoryRegistryChannel.ADM_EXCISE: (
            "https://www.adm.gov.it/portale/aliquote-accisa-nazionali"
        ),
        RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: (
            "https://www.gazzettaufficiale.it/archivioCompleto"
        ),
        RegulatoryRegistryChannel.NORMATTIVA_UPDATES: "https://www.normattiva.it/",
    }[channel]


def _fixture_pages() -> tuple[RegistryIndexPage, ...]:
    path = Path(__file__).parents[1] / "fixtures/regulatory_rollover/arera-acts-two-pages.json"
    fixture = json.loads(path.read_text(encoding="utf-8"))
    period = DatePeriod.model_validate(fixture["search_period"])
    return tuple(
        RegistryIndexPage.model_validate({"search_period": period, "query": "date-window", **item})
        for item in fixture["pages"]
    )


def _empty_adapter(channel: RegulatoryRegistryChannel) -> _FixtureAdapter:
    page = RegistryIndexPage(
        channel=channel,
        search_period=PERIOD,
        query="synthetic-empty-index",
        source_url=_index_url(channel),
        fetched_at=NOW,
        page_number=1,
        total_pages=1,
        total_results=0,
        cursor_in=None,
        cursor_out="empty-cutoff",
        index_sha256=sha256(channel.value.encode()).hexdigest(),
        records=(),
    )
    return _FixtureAdapter(channel, (page,))


def _record(
    channel: RegulatoryRegistryChannel = RegulatoryRegistryChannel.ARERA_ACTS,
    act_id: str = "fixture-act",
) -> OfficialRegistryRecord:
    host = {
        RegulatoryRegistryChannel.ARERA_ACTS: "www.arera.it",
        RegulatoryRegistryChannel.ARERA_TARIFFS: "www.arera.it",
        RegulatoryRegistryChannel.ADM_EXCISE: "www.adm.gov.it",
        RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: "www.gazzettaufficiale.it",
        RegulatoryRegistryChannel.NORMATTIVA_UPDATES: "www.normattiva.it",
    }[channel]
    return OfficialRegistryRecord(
        channel=channel,
        act_id=act_id,
        title="Synthetic act",
        published_at=date(2026, 9, 25),
        url=f"https://{host}/acts/{act_id}",
        document_id=f"{act_id}.pdf",
    )


def _single_page(
    channel: RegulatoryRegistryChannel = RegulatoryRegistryChannel.ARERA_ACTS,
    *,
    records: tuple[OfficialRegistryRecord, ...] | None = None,
    page_number: int = 1,
    total_pages: int = 1,
    total_results: int | None = None,
    cursor_in: str | None = None,
    cursor_out: str | None = "done",
    complete: bool = True,
) -> RegistryIndexPage:
    page_records = records if records is not None else (_record(channel),)
    result_count = len(page_records) if total_results is None else total_results
    return RegistryIndexPage(
        channel=channel,
        search_period=PERIOD,
        query="synthetic-query",
        source_url=_index_url(channel),
        fetched_at=NOW,
        page_number=page_number,
        total_pages=total_pages,
        total_results=result_count,
        cursor_in=cursor_in,
        cursor_out=cursor_out,
        index_sha256=sha256(f"{channel.value}:{page_number}".encode()).hexdigest(),
        complete=complete,
        records=page_records,
    )


def _complete_snapshot(channel: RegulatoryRegistryChannel) -> DiscoverySnapshot:
    return scan_regulatory_registry(
        _FixtureAdapter(channel, (_single_page(channel),)),
        PERIOD,
        NOW,
    )


def test_complete_paged_registry_scan_is_deterministic_and_advances_cursor() -> None:
    adapter = _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
    previous = RegistryCursor(
        channel=adapter.channel,
        covered_through=date(2026, 9, 24),
        next_token=None,
        snapshot_sha256="c" * 64,
    )

    first = scan_regulatory_registry(adapter, PERIOD, NOW, previous_cursor=previous)
    replay = scan_regulatory_registry(adapter, PERIOD, NOW, previous_cursor=previous)

    assert first.complete
    assert [item.act_id for item in first.records] == ["fixture-arera-001", "fixture-arera-002"]
    assert first.index_sha256 == replay.index_sha256
    assert first.next_cursor is not None
    assert first.next_cursor.covered_through == PERIOD.end
    assert first.next_cursor.next_token == "page-3"
    assert len(first.page_evidence) == 2
    assert first.page_evidence[0].source_url == "https://www.arera.it/atti-e-provvedimenti/"
    assert first.page_evidence[0].fetched_at < first.discovered_at
    assert adapter.calls[0] == (1, None, PERIOD)


def test_discovery_timestamp_cannot_precede_the_last_successful_page_fetch() -> None:
    page = _single_page()
    snapshot = scan_regulatory_registry(
        _FixtureAdapter(page.channel, (page,)),
        PERIOD,
        NOW - timedelta(minutes=1),
    )

    assert snapshot.complete
    assert snapshot.page_evidence[0].fetched_at == NOW
    assert snapshot.discovered_at == NOW


def test_scan_overlap_starts_before_last_cutoff_and_ends_after_as_of() -> None:
    period = incremental_search_period(
        as_of=date(2026, 9, 30),
        last_covered_through=date(2026, 9, 29),
        overlap_days=7,
    )

    assert period == DatePeriod(start=date(2026, 9, 22), end=date(2026, 10, 1))
    assert incremental_search_period(
        as_of=date(2026, 9, 30),
        last_covered_through=None,
        overlap_days=7,
        initial_search_start=date(2026, 9, 23),
    ) == DatePeriod(start=date(2026, 9, 23), end=date(2026, 10, 1))
    with pytest.raises(ValueError, match="initial discovery search start must be configured"):
        incremental_search_period(
            as_of=date(2026, 9, 30), last_covered_through=None, overlap_days=7
        )
    with pytest.raises(ValueError, match="overlap days cannot be negative"):
        incremental_search_period(
            as_of=date(2026, 9, 30), last_covered_through=PERIOD.end, overlap_days=-1
        )


def test_missing_page_produces_incomplete_snapshot_without_cursor_advance() -> None:
    pages = _fixture_pages()
    adapter = _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, pages[:1])
    result = scan_regulatory_registry(adapter, PERIOD, NOW)

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE
    assert result.next_cursor is None
    assert result.pages_received == 1


def test_incomplete_page_and_page_limit_do_not_advance_cursor() -> None:
    first, second = _fixture_pages()
    partial = first.model_copy(update={"complete": False})
    partial_result = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (partial, second)), PERIOD, NOW
    )
    limited_result = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (first, second)),
        PERIOD,
        NOW,
        max_pages=1,
    )

    assert partial_result.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE
    assert partial_result.next_cursor is None
    assert limited_result.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE
    assert limited_result.next_cursor is None


@pytest.mark.parametrize(
    "page_change",
    (
        {"page_number": 1},
        {"total_pages": 3},
        {"total_results": 3},
        {"query": "changed-filter"},
        {"cursor_in": "wrong-cursor"},
    ),
)
def test_unstable_pagination_metadata_invalidates_scan(page_change: dict[str, object]) -> None:
    first, second = _fixture_pages()
    changed = second.model_copy(update=page_change)
    result = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (first, changed)), PERIOD, NOW
    )

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
    assert result.next_cursor is None


def test_temporary_source_failure_is_distinct_from_regulatory_uncertainty() -> None:
    adapter = _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (), fail=True)
    result = scan_regulatory_registry(adapter, PERIOD, NOW)

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.SOURCE_UNAVAILABLE
    assert result.next_cursor is None


def test_transport_timeout_is_reported_as_temporary_unavailability() -> None:
    adapter = _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (), offline=True)

    result = scan_regulatory_registry(adapter, PERIOD, NOW)

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.SOURCE_UNAVAILABLE


def test_changed_duplicate_act_is_integrity_failure_not_a_new_guess() -> None:
    first, second = _fixture_pages()
    changed_record = first.records[0].model_copy(update={"title": "Changed title"})
    conflicting_page = second.model_copy(update={"records": (changed_record,)})
    adapter = _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (first, conflicting_page))

    result = scan_regulatory_registry(adapter, PERIOD, NOW)

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
    assert result.next_cursor is None


def test_record_outside_requested_published_date_window_invalidates_scan() -> None:
    first, second = _fixture_pages()
    out_of_window = first.records[0].model_copy(update={"published_at": date(2026, 9, 1)})
    page = first.model_copy(update={"records": (out_of_window,)})

    result = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (page, second)),
        PERIOD,
        NOW,
    )

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY


def test_incremental_overlap_reports_rectified_and_removed_prior_acts() -> None:
    previous = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages()), PERIOD, NOW
    )
    first_page, second_page = _fixture_pages()
    revised = second_page.records[0].model_copy(update={"title": "Synthetic correction"})
    current_pages = (
        first_page.model_copy(update={"index_sha256": "c" * 64}),
        second_page.model_copy(update={"records": (revised,), "index_sha256": "d" * 64}),
    )
    current = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, current_pages), PERIOD, NOW
    )

    changes = compare_overlapping_discoveries(previous, current)

    assert len(changes) == 1
    assert changes[0].kind == DiscoveryChangeKind.CHANGED
    assert changes[0].act_id == "fixture-arera-002"

    removed_pages = (
        first_page.model_copy(update={"total_results": 1, "index_sha256": "e" * 64}),
        second_page.model_copy(
            update={"total_results": 1, "records": (), "index_sha256": "f" * 64}
        ),
    )
    after_removal = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, removed_pages), PERIOD, NOW
    )
    removed = compare_overlapping_discoveries(previous, after_removal)

    assert len(removed) == 1
    assert removed[0].kind == DiscoveryChangeKind.REMOVED
    assert removed[0].act_id == "fixture-arera-002"


def test_overlap_comparison_requires_a_complete_shared_window() -> None:
    previous = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages()), PERIOD, NOW
    )
    other_period = DatePeriod(start=date(2026, 10, 1), end=date(2026, 10, 8))
    page = RegistryIndexPage(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        search_period=other_period,
        query="later-period",
        source_url=_index_url(RegulatoryRegistryChannel.ARERA_ACTS),
        fetched_at=NOW,
        page_number=1,
        total_pages=1,
        total_results=0,
        cursor_in=None,
        cursor_out="later-cutoff",
        index_sha256="1" * 64,
        records=(),
    )
    current = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (page,)), other_period, NOW
    )

    with pytest.raises(ValueError, match="overlapping search period"):
        compare_overlapping_discoveries(previous, current)


def test_discovery_report_requires_all_channels_and_unknown_acts_need_review() -> None:
    adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )
    report = discover_regulatory_sources(
        adapters,
        PERIOD,
        NOW,
        known_act_ids=((RegulatoryRegistryChannel.ARERA_ACTS, "fixture-arera-001"),),
    )

    assert report.scans_complete
    assert len(report.cursor_updates) == len(DISCOVERY_CHANNELS)
    assert len(report.findings) == 1
    assert report.findings[0].act_id == "fixture-arera-002"
    assert report.findings[0].disposition == DiscoveryActDisposition.REVIEW_REQUIRED


def test_versioned_classifier_can_resolve_supported_index_records() -> None:
    adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )

    def classify(record: OfficialRegistryRecord) -> DiscoveryActFinding:
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.SUPPORTED,
            rationale="synthetic explicit policy",
            rule_id="synthetic-rule",
            rule_version="1.0.0",
        )

    report = discover_regulatory_sources(adapters, PERIOD, NOW, classifier=classify)

    assert report.scans_complete
    assert not report.review_required
    assert len(report.findings) == 2


def test_default_classifier_supports_exact_q4_act_and_scopes_dl148_exactly() -> None:
    arera_tariff_act = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="343/2026/R/com",
        title="Delibera 343/2026/R/com",
        published_at=date(2026, 9, 29),
        effective_from=date(2026, 10, 1),
        url="https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26",
        document_id="343/2026/R/com",
    )
    gazzetta_act = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26A04702",
        title="Decreto legislativo 4 settembre 2026, n. 148",
        published_at=date(2026, 9, 4),
        registry_date=date(2026, 9, 4),
        url=(
            "https://www.gazzettaufficiale.it/atto/serie_generale/"
            "caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=2026-09-04&"
            "atto.codiceRedazionale=26A04702&elenco30giorni=false"
        ),
        document_id="26A04702",
    )

    arera_finding = classify_official_regulatory_record(arera_tariff_act)
    arera_index_duplicate = classify_official_regulatory_record(
        arera_tariff_act.model_copy(
            update={
                "channel": RegulatoryRegistryChannel.ARERA_ACTS,
                "effective_from": None,
            }
        )
    )
    gazzetta_finding = classify_official_regulatory_record(gazzetta_act)

    assert arera_finding.disposition == DiscoveryActDisposition.SUPPORTED
    assert arera_finding.rule_id == "arera-343-q4-confirmation"
    assert arera_finding.rule_version == "1.0.0"
    assert arera_index_duplicate.disposition == (
        DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    )
    assert arera_index_duplicate.rule_id == "arera-343-general-index-duplicate"
    assert arera_index_duplicate.rule_version == "1.0.0"
    assert gazzetta_finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert gazzetta_finding.rule_id == "gazzetta-dl148-domestic-electricity-rates-out-of-scope"
    assert gazzetta_finding.rule_version == "1.0.0"
    assert "household electricity" in gazzetta_finding.rationale.lower()


def test_default_official_classifier_marks_exact_diesel_decree_out_of_q4_scope() -> None:
    excise_decree = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26A04766",
        title="Decreto 4 settembre 2026 - Rideterminazione temporanea delle aliquote di accisa",
        published_at=date(2026, 9, 4),
        registry_date=date(2026, 9, 4),
        url=(
            "https://www.gazzettaufficiale.it/atto/serie_generale/"
            "caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=2026-09-04&"
            "atto.codiceRedazionale=26A04766&elenco30giorni=false"
        ),
        document_id="26A04766",
    )

    finding = classify_official_regulatory_record(excise_decree)

    assert finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert finding.rule_id == "gazzetta-diesel-excise-out-of-scope"
    assert finding.rule_version == "1.0.0"
    assert "electricity" in finding.rationale.lower()


def test_default_official_classifier_uses_exact_gazzetta_section_metadata() -> None:
    communication = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26A09999",
        title="Synthetic official notice",
        published_at=date(2026, 9, 29),
        registry_date=date(2026, 9, 29),
        url=(
            "https://www.gazzettaufficiale.it/atto/serie_generale/"
            "caricaDettaglioAtto/originario?atto.codiceRedazionale=26A09999"
        ),
        document_id="26A09999",
        registry_section="ESTRATTI, SUNTI E COMUNICATI",
    )

    finding = classify_official_regulatory_record(communication)
    normative_lookalike = classify_official_regulatory_record(
        communication.model_copy(update={"registry_section": "LEGGI ED ALTRI ATTI NORMATIVI"})
    )
    unknown_section = classify_official_regulatory_record(
        communication.model_copy(update={"registry_section": "ESTRATTI E COMUNICATI"})
    )

    assert finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert finding.rule_id == "gazzetta-extracts-summaries-communications-out-of-scope"
    assert finding.rule_version == "1.0.0"
    for unresolved in (normative_lookalike, unknown_section):
        assert unresolved.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
        assert unresolved.rule_id is None
        assert unresolved.rule_version is None


def test_default_classifier_links_exact_tua_update_to_diesel_only_conversion_law() -> None:
    gazzetta_act = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26G00184",
        title="Legge 25 settembre 2026, n. 166",
        published_at=date(2026, 9, 25),
        registry_date=date(2026, 9, 25),
        url=(
            "https://www.gazzettaufficiale.it/atto/serie_generale/"
            "caricaDettaglioAtto/originario?atto.dataPubblicazioneGazzetta=2026-09-25&"
            "atto.codiceRedazionale=26G00184&elenco30giorni=false"
        ),
        document_id="26G00184",
    )
    tua_update = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
        act_id="095G0523",
        title="Testo unico delle disposizioni legislative concernenti le accise",
        published_at=date(1995, 11, 29),
        registry_date=date(2026, 9, 25),
        url=(
            "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/ricerca/aggiornati"
        ),
        document_id="095G0523",
        latest_amending_act_ids=("26G00184",),
    )

    gazzetta_finding = classify_official_regulatory_record(gazzetta_act)
    normattiva_finding = classify_official_regulatory_record(tua_update)

    assert gazzetta_finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert gazzetta_finding.rule_id == "gazzetta-law-166-diesel-only-out-of-scope"
    assert gazzetta_finding.rule_version == "1.0.0"
    assert normattiva_finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert normattiva_finding.rule_id == "normattiva-tua-updated-by-law-166-diesel-only"
    assert normattiva_finding.rule_version == "1.0.0"

    changed_link = tua_update.model_copy(update={"latest_amending_act_ids": ("26G00185",)})
    assert (
        classify_official_regulatory_record(changed_link).disposition
        == DiscoveryActDisposition.REVIEW_REQUIRED
    )


def test_default_official_classifier_scopes_arera_338_to_anchor_fields() -> None:
    act = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id="338/2026/R/eel",
        title="Deliberazione 338/2026/R/eel",
        published_at=date(2026, 9, 29),
        url="https://www.arera.it/atti-e-provvedimenti/dettaglio/26/338-26",
        document_id="338/2026/R/eel",
    )

    finding = classify_official_regulatory_record(act)

    assert finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert finding.rule_id == "arera-338-sale-terms-out-of-projection-anchor"
    assert finding.rule_version == "1.0.0"
    assert "network/system" in finding.rationale.lower()


@pytest.mark.parametrize(
    ("published_at", "document_id", "filename", "timestamp"),
    (
        (
            date(2026, 9, 26),
            "520d8bc6-cd18-ab4b-ea07-63b5a1ad1b85",
            "Aliquote+nazionali++aggiornamento+al+26+settembre+2026.pdf",
            "1791278639804",
        ),
        (
            date(2026, 10, 6),
            "843f942b-f77d-a718-b5f5-63559bd5fdb7",
            "Aliquote+nazionali++aggiornamento+al+6+ottobre+2026.pdf",
            "1791278679997",
        ),
    ),
)
def test_default_official_classifier_supports_exact_adm_q4_rate_sheets(
    published_at: date, document_id: str, filename: str, timestamp: str
) -> None:
    record = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ADM_EXCISE,
        act_id=f"adm-excise:{published_at.isoformat()}:{document_id}",
        title="ADM aliquote nazionali PDF",
        published_at=published_at,
        registry_date=published_at,
        url=(
            "https://www.adm.gov.it/portale/documents/20182/43975520/"
            f"{filename}/{document_id}?t={timestamp}"
        ),
        document_id=document_id,
    )

    finding = classify_official_regulatory_record(record)

    assert finding.disposition == DiscoveryActDisposition.SUPPORTED
    assert finding.rule_id == "adm-domestic-excise-q4-2026"
    assert finding.rule_version == "1.0.0"


@pytest.mark.parametrize(
    ("published_at", "document_id", "filename", "timestamp"),
    (
        (
            date(2025, 1, 1),
            "74c6d6b2-51ea-4e06-3d76-9c506ef0dfd0",
            "Aliquote+nazionali+aggiornamento+al+1+gennaio+2025.pdf",
            "1737560216015",
        ),
        (
            date(2026, 6, 7),
            "acef980d-4a2e-5feb-d59a-8ff962da87d5",
            "Aliquote+nazionali+aggiornamento+07+giugno+2026.pdf",
            "1783331967929",
        ),
    ),
)
def test_default_official_classifier_excludes_exact_historical_adm_rate_sheets(
    published_at: date, document_id: str, filename: str, timestamp: str
) -> None:
    record = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ADM_EXCISE,
        act_id=f"adm-excise:{published_at.isoformat()}:{document_id}",
        title="ADM historic aliquote nazionali PDF",
        published_at=published_at,
        registry_date=published_at,
        url=(
            "https://www.adm.gov.it/portale/documents/20182/43975520/"
            f"{filename}/{document_id}?t={timestamp}"
        ),
        document_id=document_id,
    )

    finding = classify_official_regulatory_record(record)

    assert finding.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert finding.rule_id == "adm-excise-historical-snapshots-superseded-q4-2026"
    assert finding.rule_version == "1.0.0"


def test_default_official_classifier_does_not_match_known_act_by_id_alone() -> None:
    lookalike = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="343/2026/R/com",
        title="Synthetic replacement document",
        published_at=date(2026, 9, 30),
        effective_from=date(2026, 10, 1),
        url="https://www.arera.it/other/343-26",
        document_id="343/2026/R/com",
    )
    excise_lookalike = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26A04766",
        title="Synthetic unrelated act",
        published_at=date(2026, 9, 5),
        registry_date=date(2026, 9, 5),
        url=(
            "https://www.gazzettaufficiale.it/atto/serie_generale/"
            "caricaDettaglioAtto/originario?atto.codiceRedazionale=26A04766&"
            "atto.dataPubblicazioneGazzetta=2026-09-05"
        ),
        document_id="26A04766",
    )
    dl148_lookalike = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        act_id="26A04702",
        title="Synthetic unrelated act",
        published_at=date(2026, 9, 5),
        registry_date=date(2026, 9, 5),
        url=(
            "https://www.gazzettaufficiale.it/atto/serie_generale/"
            "caricaDettaglioAtto/originario?atto.codiceRedazionale=26A04702&"
            "atto.dataPubblicazioneGazzetta=2026-09-04"
        ),
        document_id="26A04702",
    )
    unknown = _record()

    for record in (lookalike, excise_lookalike, dl148_lookalike, unknown):
        finding = classify_official_regulatory_record(record)
        assert finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
        assert finding.rule_id is None
        assert finding.rule_version is None


def test_discovery_uses_builtin_classifier_only_when_no_override_is_supplied() -> None:
    act = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="343/2026/R/com",
        title="Delibera 343/2026/R/com",
        published_at=date(2026, 9, 29),
        effective_from=date(2026, 10, 1),
        url="https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26",
        document_id="343/2026/R/com",
    )
    tariff_page = _single_page(
        RegulatoryRegistryChannel.ARERA_TARIFFS,
        records=(act,),
    )
    adapters = tuple(
        _FixtureAdapter(channel, (tariff_page,))
        if channel == RegulatoryRegistryChannel.ARERA_TARIFFS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )

    default_report = discover_regulatory_sources(adapters, PERIOD, NOW)
    override_report = discover_regulatory_sources(
        adapters,
        PERIOD,
        NOW,
        classifier=lambda record: DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
            rationale="test-specific unresolved applicability",
        ),
    )

    default_finding = default_report.findings[0]
    override_finding = override_report.findings[0]
    assert default_finding.rule_id == "arera-343-q4-confirmation"
    assert default_finding.disposition == DiscoveryActDisposition.SUPPORTED
    assert override_finding.rule_id is None
    assert override_finding.rationale == "test-specific unresolved applicability"


def test_prior_complete_snapshot_prevents_false_new_act_finding() -> None:
    adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )

    def classify_irrelevant(record: OfficialRegistryRecord) -> DiscoveryActFinding:
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale="synthetic exact metadata exclusion",
            rule_id="synthetic-irrelevant",
            rule_version="1.0.0",
        )

    first = discover_regulatory_sources(adapters, PERIOD, NOW, classifier=classify_irrelevant)
    second = discover_regulatory_sources(
        adapters,
        PERIOD,
        NOW,
        previous_snapshots=first.snapshots,
        classifier=classify_irrelevant,
    )

    assert first.scans_complete and second.scans_complete
    assert first.findings == second.findings == ()
    first_arera = next(
        item for item in first.snapshots if item.channel == RegulatoryRegistryChannel.ARERA_ACTS
    )
    second_arera = next(
        item for item in second.snapshots if item.channel == RegulatoryRegistryChannel.ARERA_ACTS
    )
    assert len(first_arera.findings) == len(second_arera.findings) == 2
    assert all(
        item.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
        for item in second_arera.findings
    )
    assert second.changes == ()


def test_unresolved_finding_is_carried_after_act_leaves_overlap_window() -> None:
    first_adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )
    first = discover_regulatory_sources(first_adapters, PERIOD, NOW)
    assert len(first.findings) == 2

    later_period = DatePeriod(start=date(2026, 10, 1), end=date(2026, 10, 9))
    later_adapters: list[_FixtureAdapter] = []
    for channel in DISCOVERY_CHANNELS:
        page = RegistryIndexPage(
            channel=channel,
            search_period=later_period,
            query="synthetic-next-window",
            source_url=_index_url(channel),
            fetched_at=NOW + timedelta(days=8),
            page_number=1,
            total_pages=1,
            total_results=0,
            cursor_in=None,
            cursor_out=later_period.end.isoformat(),
            index_sha256=sha256(f"later:{channel.value}".encode()).hexdigest(),
            records=(),
        )
        later_adapters.append(_FixtureAdapter(channel, (page,)))

    later = discover_regulatory_sources(
        tuple(later_adapters),
        later_period,
        NOW + timedelta(days=8),
        previous_snapshots=first.snapshots,
    )

    assert later.scans_complete
    assert {(item.channel, item.act_id) for item in later.findings} == {
        (item.channel, item.act_id) for item in first.findings
    }
    assert all(item.source_record is not None for item in later.findings)
    assert all(
        item.disposition == DiscoveryActDisposition.REVIEW_REQUIRED for item in later.findings
    )


def test_aged_out_findings_use_embedded_record_and_drop_versioned_irrelevance() -> None:
    first_adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )
    first = discover_regulatory_sources(
        first_adapters,
        PERIOD,
        NOW,
        known_act_ids=((RegulatoryRegistryChannel.ARERA_ACTS, "fixture-arera-001"),),
    )
    arera_snapshot = next(
        item for item in first.snapshots if item.channel == RegulatoryRegistryChannel.ARERA_ACTS
    )
    assert {item.act_id: item.disposition for item in arera_snapshot.findings} == {
        "fixture-arera-001": DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
        "fixture-arera-002": DiscoveryActDisposition.REVIEW_REQUIRED,
    }

    later_period = DatePeriod(start=date(2026, 10, 1), end=date(2026, 10, 9))
    later_adapters: list[_FixtureAdapter] = []
    for channel in DISCOVERY_CHANNELS:
        page = RegistryIndexPage(
            channel=channel,
            search_period=later_period,
            query="empty-later-window",
            source_url=_index_url(channel),
            fetched_at=NOW + timedelta(days=8),
            page_number=1,
            total_pages=1,
            total_results=0,
            cursor_in=None,
            cursor_out=later_period.end.isoformat(),
            index_sha256=sha256(f"empty:{channel.value}".encode()).hexdigest(),
            records=(),
        )
        later_adapters.append(_FixtureAdapter(channel, (page,)))
    historical_snapshots = tuple(
        item.model_copy(update={"records": ()}) if item.channel == arera_snapshot.channel else item
        for item in first.snapshots
    )

    later = discover_regulatory_sources(
        tuple(later_adapters),
        later_period,
        NOW + timedelta(days=8),
        previous_snapshots=historical_snapshots,
    )

    assert {(item.channel, item.act_id) for item in later.findings} == {
        (RegulatoryRegistryChannel.ARERA_ACTS, "fixture-arera-002")
    }
    assert later.findings[0].source_record == arera_snapshot.findings[1].source_record


def test_metadata_change_without_overlap_is_recorded_once_and_requires_review() -> None:
    first_adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )
    first = discover_regulatory_sources(first_adapters, PERIOD, NOW)
    previous_record = next(
        item for item in first.findings if item.act_id == "fixture-arera-002"
    ).source_record
    assert previous_record is not None

    later_period = DatePeriod(start=date(2026, 10, 1), end=date(2026, 10, 9))
    changed_record = previous_record.model_copy(
        update={"title": "Corrected official index title", "published_at": date(2026, 10, 2)}
    )
    later_adapters: list[_FixtureAdapter] = []
    for channel in DISCOVERY_CHANNELS:
        records = (changed_record,) if channel == RegulatoryRegistryChannel.ARERA_ACTS else ()
        page = RegistryIndexPage(
            channel=channel,
            search_period=later_period,
            query="changed-act-in-later-window",
            source_url=_index_url(channel),
            fetched_at=NOW + timedelta(days=8),
            page_number=1,
            total_pages=1,
            total_results=len(records),
            cursor_in=None,
            cursor_out=later_period.end.isoformat(),
            index_sha256=sha256(f"changed:{channel.value}".encode()).hexdigest(),
            records=records,
        )
        later_adapters.append(_FixtureAdapter(channel, (page,)))

    later = discover_regulatory_sources(
        tuple(later_adapters),
        later_period,
        NOW + timedelta(days=8),
        previous_snapshots=first.snapshots,
    )

    assert len(later.changes) == 1
    assert later.changes[0].kind == DiscoveryChangeKind.CHANGED
    assert later.changes[0].act_id == changed_record.act_id
    finding = next(item for item in later.findings if item.act_id == changed_record.act_id)
    assert finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
    assert finding.source_record == changed_record


def test_classification_envelopes_are_versioned_and_v1_snapshot_remains_readable() -> None:
    adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )
    report = discover_regulatory_sources(adapters, PERIOD, NOW)
    encoded_report = dump_envelope(report)
    assert json.loads(encoded_report)["schema_id"] == CoreSchemaId.REGULATORY_DISCOVERY_REPORT_V2
    assert load_envelope(encoded_report) == report

    snapshot = next(
        item for item in report.snapshots if item.channel == RegulatoryRegistryChannel.ARERA_ACTS
    )
    encoded_snapshot = dump_envelope(snapshot)
    assert (
        json.loads(encoded_snapshot)["schema_id"] == CoreSchemaId.REGULATORY_DISCOVERY_SNAPSHOT_V2
    )
    assert load_envelope(encoded_snapshot) == snapshot

    legacy_payload = snapshot.model_dump(mode="json")
    legacy_payload.pop("classification_complete")
    legacy_payload.pop("findings")
    legacy_envelope = json.dumps(
        {
            "contract_version": CORE_CONTRACT_VERSION,
            "schema_id": CoreSchemaId.REGULATORY_DISCOVERY_SNAPSHOT.value,
            "payload": legacy_payload,
        }
    )
    legacy_snapshot = load_envelope(legacy_envelope)
    assert isinstance(legacy_snapshot, DiscoverySnapshot)
    assert not legacy_snapshot.classification_complete
    assert legacy_snapshot.findings == ()


def test_missing_channel_blocks_discovery_and_does_not_advance_its_cursor() -> None:
    adapters = tuple(_empty_adapter(channel) for channel in DISCOVERY_CHANNELS[:-1])
    report = discover_regulatory_sources(adapters, PERIOD, NOW)

    assert not report.scans_complete
    assert len(report.cursor_updates) == len(DISCOVERY_CHANNELS) - 1
    missing = next(item for item in report.snapshots if not item.complete)
    assert missing.reason_code == RegulatoryRolloverReason.INCOMPLETE_COVERAGE
    assert missing.next_cursor is None


def test_duplicate_adapters_cursors_and_classifier_mismatch_are_rejected() -> None:
    adapter = _empty_adapter(RegulatoryRegistryChannel.ARERA_ACTS)
    with pytest.raises(ValueError, match="adapter channels must be unique"):
        discover_regulatory_sources((adapter, adapter), PERIOD, NOW)
    cursor = RegistryCursor(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        covered_through=PERIOD.end,
        next_token=None,
        snapshot_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="cursors must be unique"):
        discover_regulatory_sources(
            (
                adapter,
                *tuple(
                    _empty_adapter(channel)
                    for channel in DISCOVERY_CHANNELS
                    if channel != RegulatoryRegistryChannel.ARERA_ACTS
                ),
            ),
            PERIOD,
            NOW,
            previous_cursors=(cursor, cursor),
        )

    def wrong_classifier(record: OfficialRegistryRecord) -> DiscoveryActFinding:
        return DiscoveryActFinding(
            channel=record.channel,
            act_id="different-act",
            disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
            rationale="synthetic mismatch",
        )

    adapters = tuple(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, _fixture_pages())
        if channel == RegulatoryRegistryChannel.ARERA_ACTS
        else _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
    )
    with pytest.raises(ValueError, match="must identify its input record"):
        discover_regulatory_sources(adapters, PERIOD, NOW, classifier=wrong_classifier)


def test_record_and_page_contract_reject_non_official_url_or_bad_digest() -> None:
    for url in ("http://www.arera.it/act", "https://example.com/act"):
        with pytest.raises(ValidationError, match="official HTTPS host"):
            OfficialRegistryRecord(
                channel=RegulatoryRegistryChannel.ARERA_ACTS,
                act_id="x",
                title="Synthetic",
                published_at=date(2026, 9, 20),
                url=url,
                document_id="x.pdf",
            )
    with pytest.raises(ValidationError):
        RegistryIndexPage(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            search_period=PERIOD,
            query="fixture",
            source_url=_index_url(RegulatoryRegistryChannel.ARERA_ACTS),
            fetched_at=NOW,
            page_number=1,
            total_pages=1,
            total_results=0,
            index_sha256="bad",
            records=(),
        )
    with pytest.raises(ValidationError, match="official HTTPS host"):
        RegistryIndexPage(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            search_period=PERIOD,
            query="fixture",
            source_url="https://example.com/index",
            fetched_at=NOW,
            page_number=1,
            total_pages=1,
            total_results=0,
            index_sha256="a" * 64,
            records=(),
        )
    with pytest.raises(ValidationError, match="timezone-aware"):
        RegistryPageEvidence(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            page_number=1,
            source_url=_index_url(RegulatoryRegistryChannel.ARERA_ACTS),
            fetched_at=datetime(2026, 9, 30),
            index_sha256="a" * 64,
        )


@pytest.mark.parametrize("act_ids", (("26G00184", "26G00184"), ("",)))
def test_registry_record_rejects_duplicate_or_empty_amending_act_ids(
    act_ids: tuple[str, ...],
) -> None:
    with pytest.raises(ValidationError, match="latest amending act IDs"):
        OfficialRegistryRecord(
            **{
                **_record(RegulatoryRegistryChannel.NORMATTIVA_UPDATES).model_dump(),
                "latest_amending_act_ids": act_ids,
            }
        )


def test_discovery_scan_maps_adapter_parse_error_to_typed_failure() -> None:
    result = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (), parse_error=True), PERIOD, NOW
    )

    assert not result.complete
    assert result.reason_code == RegulatoryRolloverReason.PARSER_FAILURE


def test_registry_page_rejects_inconsistent_counts_channels_duplicates_and_cursor() -> None:
    record = _record()
    cases = (
        ({"page_number": 2, "total_pages": 1}, "exceeds the declared page count"),
        ({"total_results": 0, "records": (record,)}, "more records than the declared total"),
        (
            {"records": (_record(RegulatoryRegistryChannel.ADM_EXCISE),)},
            "another channel",
        ),
        ({"records": (record, record), "total_results": 2}, "act IDs must be unique"),
        (
            {"page_number": 1, "total_pages": 2, "cursor_out": None},
            "requires a progressing cursor",
        ),
        (
            {"page_number": 1, "total_pages": 2, "cursor_in": "next", "cursor_out": "next"},
            "requires a progressing cursor",
        ),
    )
    for change, message in cases:
        with pytest.raises(ValidationError, match=message):
            RegistryIndexPage.model_validate(
                {
                    **_single_page().model_dump(mode="python"),
                    **change,
                }
            )


def test_finding_and_change_models_require_complete_decision_evidence() -> None:
    with pytest.raises(ValidationError, match="must be supplied together"):
        DiscoveryActFinding(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            act_id="x",
            disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
            rationale="needs review",
            rule_id="review-rule",
        )
    with pytest.raises(ValidationError, match="versioned rule"):
        DiscoveryActFinding(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            act_id="x",
            disposition=DiscoveryActDisposition.SUPPORTED,
            rationale="supported",
        )
    with pytest.raises(ValidationError, match="source record must match"):
        DiscoveryActFinding(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            act_id="expected-act",
            disposition=DiscoveryActDisposition.SUPPORTED,
            rationale="supported",
            rule_id="fixture-rule",
            rule_version="1.0.0",
            source_record=_record(act_id="different-act"),
        )
    with pytest.raises(ValidationError):
        DiscoveryRecordChange(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            act_id="x",
            kind=DiscoveryChangeKind.NEW,
            previous_sha256="a" * 64,
        )
    with pytest.raises(ValidationError):
        DiscoveryRecordChange(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            act_id="x",
            kind=DiscoveryChangeKind.REMOVED,
            observed_sha256="b" * 64,
        )
    with pytest.raises(ValidationError):
        DiscoveryRecordChange(
            channel=RegulatoryRegistryChannel.ARERA_ACTS,
            act_id="x",
            kind=DiscoveryChangeKind.CHANGED,
            previous_sha256="a" * 64,
        )


def test_snapshot_validator_checks_time_records_and_cursor_binding() -> None:
    snapshot = _complete_snapshot(RegulatoryRegistryChannel.ARERA_ACTS)
    payload = snapshot.model_dump(mode="python")
    matching_finding = DiscoveryActFinding(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id=snapshot.records[0].act_id,
        disposition=DiscoveryActDisposition.SUPPORTED,
        rationale="synthetic complete classification",
        rule_id="fixture-rule",
        rule_version="1.0.0",
        source_record=snapshot.records[0],
    )
    invalid_variants = (
        ({"discovered_at": datetime(2026, 9, 30)}, "timezone-aware"),
        ({"records": (_record(RegulatoryRegistryChannel.ADM_EXCISE),)}, "another channel"),
        ({"records": (snapshot.records[0], snapshot.records[0])}, "act IDs must be unique"),
        ({"pages_received": 0}, "provenance for every received page"),
        ({"index_sha256": "e" * 64}, "index digest must match its page evidence"),
        (
            {
                "findings": (matching_finding, matching_finding),
            },
            "findings must identify unique acts",
        ),
        (
            {
                "findings": (
                    DiscoveryActFinding(
                        channel=RegulatoryRegistryChannel.ADM_EXCISE,
                        act_id="another-act",
                        disposition=DiscoveryActDisposition.SUPPORTED,
                        rationale="synthetic channel mismatch",
                        rule_id="fixture-rule",
                        rule_version="1.0.0",
                        source_record=_record(RegulatoryRegistryChannel.ADM_EXCISE, "another-act"),
                    ),
                ),
            },
            "findings must match its channel",
        ),
        ({"classification_complete": True}, "complete classification requires"),
        (
            {
                "complete": False,
                "next_cursor": None,
                "reason_code": RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
                "classification_complete": True,
                "findings": (matching_finding,),
            },
            "complete classification requires",
        ),
        ({"next_cursor": None}, "complete scan requires"),
        (
            {
                "next_cursor": RegistryCursor(
                    channel=RegulatoryRegistryChannel.ADM_EXCISE,
                    covered_through=PERIOD.end,
                    next_token="done",
                    snapshot_sha256=snapshot.index_sha256,
                )
            },
            "cursor channel must match",
        ),
        (
            {
                "page_evidence": (
                    RegistryPageEvidence(
                        channel=RegulatoryRegistryChannel.ARERA_ACTS,
                        page_number=1,
                        source_url=_index_url(RegulatoryRegistryChannel.ARERA_ACTS),
                        fetched_at=NOW + timedelta(seconds=1),
                        index_sha256=snapshot.page_evidence[0].index_sha256,
                    ),
                )
            },
            "cannot precede a page fetch",
        ),
        ({"page_evidence": ()}, "provenance for every received page"),
        (
            {
                "next_cursor": RegistryCursor(
                    channel=RegulatoryRegistryChannel.ARERA_ACTS,
                    covered_through=date(2026, 9, 30),
                    next_token="done",
                    snapshot_sha256=snapshot.index_sha256,
                )
            },
            "cutoff must match",
        ),
        (
            {
                "next_cursor": RegistryCursor(
                    channel=RegulatoryRegistryChannel.ARERA_ACTS,
                    covered_through=PERIOD.end,
                    next_token="done",
                    snapshot_sha256="e" * 64,
                )
            },
            "digest must match",
        ),
        ({"complete": False}, "cannot advance cursor"),
    )
    for change, message in invalid_variants:
        with pytest.raises(ValidationError, match=message):
            DiscoverySnapshot.model_validate({**payload, **change})


def test_discovery_report_rejects_missing_channel_bad_date_and_dangling_findings() -> None:
    snapshots = tuple(_complete_snapshot(channel) for channel in DISCOVERY_CHANNELS)
    with pytest.raises(ValidationError, match="every required channel"):
        RegulatoryDiscoveryReport(
            as_of=PERIOD.end - timedelta(days=1), snapshots=snapshots[:-1], findings=()
        )
    with pytest.raises(ValidationError, match="report date"):
        RegulatoryDiscoveryReport(as_of=date(2026, 9, 29), snapshots=snapshots, findings=())
    with pytest.raises(ValidationError, match="snapshot record"):
        RegulatoryDiscoveryReport(
            as_of=PERIOD.end - timedelta(days=1),
            snapshots=snapshots,
            findings=(
                DiscoveryActFinding(
                    channel=RegulatoryRegistryChannel.ARERA_ACTS,
                    act_id="missing",
                    disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
                    rationale="missing record",
                ),
            ),
        )
    with pytest.raises(ValidationError, match="unique channels"):
        RegulatoryDiscoveryReport(
            as_of=PERIOD.end - timedelta(days=1),
            snapshots=(*snapshots[:-1], snapshots[0]),
            findings=(),
        )
    change = DiscoveryRecordChange(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id="new-act",
        kind=DiscoveryChangeKind.NEW,
        observed_sha256="a" * 64,
    )
    with pytest.raises(ValidationError, match="changes must be unique"):
        RegulatoryDiscoveryReport(
            as_of=PERIOD.end - timedelta(days=1),
            snapshots=snapshots,
            findings=(),
            changes=(change, change),
        )
    with pytest.raises(ValidationError, match="findings must be unique"):
        RegulatoryDiscoveryReport(
            as_of=PERIOD.end - timedelta(days=1),
            snapshots=snapshots,
            findings=(
                DiscoveryActFinding(
                    channel=RegulatoryRegistryChannel.ARERA_ACTS,
                    act_id=snapshots[0].records[0].act_id,
                    disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
                    rationale="same act",
                ),
            )
            * 2,
        )


def test_scan_rejects_bad_clock_page_limit_cursor_and_adapter_schema() -> None:
    adapter = _FixtureAdapter(
        RegulatoryRegistryChannel.ARERA_ACTS,
        (_single_page(),),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        scan_regulatory_registry(adapter, PERIOD, datetime(2026, 9, 30))
    with pytest.raises(ValueError, match="page limit must be positive"):
        scan_regulatory_registry(adapter, PERIOD, NOW, max_pages=0)
    wrong_cursor = RegistryCursor(
        channel=RegulatoryRegistryChannel.ADM_EXCISE,
        covered_through=PERIOD.end,
        next_token="x",
        snapshot_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="does not match its adapter"):
        scan_regulatory_registry(adapter, PERIOD, NOW, previous_cursor=wrong_cursor)
    result = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (), parse_error=True), PERIOD, NOW
    )
    assert result.reason_code == RegulatoryRolloverReason.PARSER_FAILURE


def test_comparison_reports_new_act_and_changed_report_requires_review() -> None:
    prior_page = _single_page(records=(_record(act_id="old-act"),))
    prior = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (prior_page,)), PERIOD, NOW
    )
    current_page = _single_page(
        records=(_record(act_id="old-act"), _record(act_id="new-act")),
        total_results=2,
    )
    current = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (current_page,)), PERIOD, NOW
    )
    new_changes = compare_overlapping_discoveries(prior, current)
    assert [(item.act_id, item.kind) for item in new_changes] == [
        ("new-act", DiscoveryChangeKind.NEW)
    ]

    changed_page = _single_page(
        records=(_record(act_id="old-act").model_copy(update={"title": "Rectified"}),),
    )
    changed = scan_regulatory_registry(
        _FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (changed_page,)), PERIOD, NOW
    )
    other_channels = tuple(
        _empty_adapter(channel)
        for channel in DISCOVERY_CHANNELS
        if channel != RegulatoryRegistryChannel.ARERA_ACTS
    )
    report = discover_regulatory_sources(
        (_FixtureAdapter(RegulatoryRegistryChannel.ARERA_ACTS, (changed_page,)), *other_channels),
        PERIOD,
        NOW,
        previous_snapshots=(prior,),
    )

    assert changed.complete
    assert report.integrity_changed
    assert report.review_required
    assert report.findings[0].act_id == "old-act"


def test_discovery_snapshot_model_requires_complete_cursor_consistency() -> None:
    snapshot = _complete_snapshot(RegulatoryRegistryChannel.ARERA_ACTS)
    payload = snapshot.model_dump(mode="python")
    payload["next_cursor"] = None
    with pytest.raises(ValidationError, match="complete scan requires its next cursor"):
        DiscoverySnapshot.model_validate(payload)


def test_report_model_rejects_duplicate_channel_snapshots() -> None:
    snapshot = scan_regulatory_registry(
        _empty_adapter(RegulatoryRegistryChannel.ARERA_ACTS), PERIOD, NOW
    )
    with pytest.raises(ValidationError, match="unique channels"):
        RegulatoryDiscoveryReport(
            as_of=PERIOD.end - timedelta(days=1),
            snapshots=(snapshot, snapshot),
            findings=(),
        )
