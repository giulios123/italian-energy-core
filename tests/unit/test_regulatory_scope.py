from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256

from italian_energy.arera.discovery import (
    DISCOVERY_CHANNELS,
    DiscoveryActDisposition,
    DiscoveryActFinding,
    DiscoveryChangeKind,
    DiscoveryRecordChange,
    DiscoverySnapshot,
    OfficialRegistryRecord,
    RegistryIndexPage,
    RegulatoryDiscoveryReport,
    RegulatoryRegistryChannel,
    scan_regulatory_registry,
)
from italian_energy.arera.rollover_scope import scope_domestic_projection_discovery
from italian_energy.domain.time import DatePeriod

NOW = datetime(2026, 10, 8, 12, tzinfo=UTC)
AS_OF = date(2026, 10, 8)
PERIOD = DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 9))


class _Adapter:
    def __init__(self, channel: RegulatoryRegistryChannel, page: RegistryIndexPage) -> None:
        self.channel = channel
        self.adapter_id = f"fixture-{channel.value}"
        self.adapter_version = "1.0.0"
        self._page = page

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        assert search_period == PERIOD
        assert page_number == 1
        assert cursor is None
        return self._page


def _record(
    channel: RegulatoryRegistryChannel,
    act_id: str,
    *,
    document_id: str | None = None,
    amending_ids: tuple[str, ...] = (),
) -> OfficialRegistryRecord:
    hosts = {
        RegulatoryRegistryChannel.ARERA_ACTS: "www.arera.it",
        RegulatoryRegistryChannel.ARERA_TARIFFS: "www.arera.it",
        RegulatoryRegistryChannel.ADM_EXCISE: "www.adm.gov.it",
        RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: "www.gazzettaufficiale.it",
        RegulatoryRegistryChannel.NORMATTIVA_UPDATES: "api.normattiva.it",
    }
    return OfficialRegistryRecord(
        channel=channel,
        act_id=act_id,
        title="Fixture record",
        published_at=date(2026, 9, 25),
        registry_date=date(2026, 9, 25),
        url=f"https://{hosts[channel]}/official/{act_id}",
        document_id=document_id or act_id,
        latest_amending_act_ids=amending_ids,
    )


def _report(
    *, incomplete_channel: RegulatoryRegistryChannel | None = None
) -> RegulatoryDiscoveryReport:
    arera_acts = (
        _record(RegulatoryRegistryChannel.ARERA_ACTS, "343/2026/R/com"),
        _record(RegulatoryRegistryChannel.ARERA_ACTS, "338/2026/R/eel"),
    )
    arera_tariffs = (_record(RegulatoryRegistryChannel.ARERA_TARIFFS, "343/2026/R/com"),)
    normattiva = (
        _record(
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
            "095G0523",
            document_id="095G0523",
            amending_ids=("26G00184",),
        ),
        _record(
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
            "22G00154",
            document_id="22G00154",
            amending_ids=("26G00190",),
        ),
    )
    gazzetta = (
        _record(RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00184"),
        _record(RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00190"),
    )
    adm = (_record(RegulatoryRegistryChannel.ADM_EXCISE, "adm-new-sheet"),)
    records_by_channel = {
        RegulatoryRegistryChannel.ARERA_ACTS: arera_acts,
        RegulatoryRegistryChannel.ARERA_TARIFFS: arera_tariffs,
        RegulatoryRegistryChannel.ADM_EXCISE: adm,
        RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: gazzetta,
        RegulatoryRegistryChannel.NORMATTIVA_UPDATES: normattiva,
    }
    snapshots: list[DiscoverySnapshot] = []
    findings: list[DiscoveryActFinding] = []
    for channel in DISCOVERY_CHANNELS:
        records = records_by_channel[channel]
        page = RegistryIndexPage(
            channel=channel,
            search_period=PERIOD,
            query="fixture",
            source_url=f"https://{records[0].url.split('/')[2]}/index",
            fetched_at=NOW,
            page_number=1,
            total_pages=1,
            total_results=len(records),
            cursor_in=None,
            cursor_out="cutoff",
            index_sha256=sha256(channel.value.encode()).hexdigest(),
            complete=channel != incomplete_channel,
            records=records,
        )
        snapshot = scan_regulatory_registry(_Adapter(channel, page), PERIOD, NOW)
        snapshots.append(snapshot)
        findings.extend(
            DiscoveryActFinding(
                channel=channel,
                act_id=record.act_id,
                disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
                rationale="fixture is awaiting the source-scope policy",
                source_record=record,
            )
            for record in records
        )
    return RegulatoryDiscoveryReport(
        as_of=AS_OF,
        snapshots=tuple(snapshots),
        findings=tuple(findings),
    )


def _finding(
    report: RegulatoryDiscoveryReport,
    channel: RegulatoryRegistryChannel,
    act_id: str,
) -> DiscoveryActFinding:
    return next(
        item for item in report.findings if item.channel == channel and item.act_id == act_id
    )


def test_scope_links_only_complete_primary_source_relationships() -> None:
    scoped = scope_domestic_projection_discovery(_report())

    assert scoped.scans_complete
    assert (
        _finding(scoped, RegulatoryRegistryChannel.ARERA_ACTS, "343/2026/R/com").disposition
        == DiscoveryActDisposition.REVIEW_REQUIRED
    )
    unrelated_arera = _finding(scoped, RegulatoryRegistryChannel.ARERA_ACTS, "338/2026/R/eel")
    assert unrelated_arera.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
    assert unrelated_arera.rule_id == "domestic-projection-arera-tariff-index-scope"

    assert (
        _finding(scoped, RegulatoryRegistryChannel.NORMATTIVA_UPDATES, "095G0523").disposition
        == DiscoveryActDisposition.REVIEW_REQUIRED
    )
    unrelated_normattiva = _finding(
        scoped, RegulatoryRegistryChannel.NORMATTIVA_UPDATES, "22G00154"
    )
    assert unrelated_normattiva.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE

    assert (
        _finding(scoped, RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00184").disposition
        == DiscoveryActDisposition.REVIEW_REQUIRED
    )
    unrelated_gazzetta = _finding(
        scoped, RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00190"
    )
    assert unrelated_gazzetta.disposition == DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE

    # The direct ADM index remains the authority for the electricity-excise row.
    assert (
        _finding(scoped, RegulatoryRegistryChannel.ADM_EXCISE, "adm-new-sheet").disposition
        == DiscoveryActDisposition.REVIEW_REQUIRED
    )


def test_incomplete_scan_never_allows_scope_based_exclusion() -> None:
    report = _report(incomplete_channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES)

    scoped = scope_domestic_projection_discovery(report)

    assert not scoped.scans_complete
    assert all(
        item.disposition == DiscoveryActDisposition.REVIEW_REQUIRED for item in scoped.findings
    )


def test_scope_policy_keeps_official_tariff_records_and_source_updates_reviewable() -> None:
    report = _report()

    scoped = scope_domestic_projection_discovery(report)

    tariff_record = _finding(scoped, RegulatoryRegistryChannel.ARERA_TARIFFS, "343/2026/R/com")
    assert tariff_record.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
    assert tariff_record.source_record is not None
    assert tariff_record.source_record.document_id == "343/2026/R/com"

    watched = next(
        item
        for item in scoped.findings
        if item.channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES
        and item.act_id == "095G0523"
    )
    assert watched.source_record is not None
    assert watched.source_record.latest_amending_act_ids == ("26G00184",)


def test_scope_filters_unrelated_index_changes_but_keeps_watched_source_changes() -> None:
    records = (
        (RegulatoryRegistryChannel.ARERA_ACTS, "338/2026/R/eel"),
        (RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00184"),
        (RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00190"),
        (RegulatoryRegistryChannel.NORMATTIVA_UPDATES, "095G0523"),
        (RegulatoryRegistryChannel.NORMATTIVA_UPDATES, "22G00154"),
        (RegulatoryRegistryChannel.ADM_EXCISE, "adm-new-sheet"),
    )
    changes = tuple(
        DiscoveryRecordChange(
            channel=channel,
            act_id=act_id,
            kind=DiscoveryChangeKind.CHANGED,
            previous_sha256="a" * 64,
            observed_sha256="b" * 64,
        )
        for channel, act_id in records
    )
    report = _report().model_copy(update={"changes": changes})

    scoped = scope_domestic_projection_discovery(report)

    assert [(item.channel, item.act_id) for item in scoped.changes] == [
        (RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE, "26G00184"),
        (RegulatoryRegistryChannel.NORMATTIVA_UPDATES, "095G0523"),
        (RegulatoryRegistryChannel.ADM_EXCISE, "adm-new-sheet"),
    ]


def test_previous_tariff_index_keeps_its_arera_record_in_scope() -> None:
    report = _report()
    old_record = _record(RegulatoryRegistryChannel.ARERA_TARIFFS, "338/2026/R/eel")
    page = RegistryIndexPage(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        search_period=PERIOD,
        query="previous tariff index fixture",
        source_url="https://www.arera.it/previous-tariff-index",
        fetched_at=NOW,
        page_number=1,
        total_pages=1,
        total_results=1,
        cursor_in=None,
        cursor_out="previous-cutoff",
        index_sha256=sha256(b"previous tariff index").hexdigest(),
        complete=True,
        records=(old_record,),
    )
    previous_tariff_snapshot = scan_regulatory_registry(
        _Adapter(RegulatoryRegistryChannel.ARERA_TARIFFS, page), PERIOD, NOW
    )

    scoped = scope_domestic_projection_discovery(
        report, previous_snapshots=(previous_tariff_snapshot,)
    )

    old_tariff_act = _finding(scoped, RegulatoryRegistryChannel.ARERA_ACTS, "338/2026/R/eel")
    assert old_tariff_act.disposition == DiscoveryActDisposition.REVIEW_REQUIRED


def test_empty_complete_tariff_index_does_not_exclude_general_arera_records() -> None:
    report = _report()
    page = RegistryIndexPage(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        search_period=PERIOD,
        query="empty tariff index fixture",
        source_url="https://www.arera.it/empty-tariff-index",
        fetched_at=NOW,
        page_number=1,
        total_pages=1,
        total_results=0,
        cursor_in=None,
        cursor_out="empty-cutoff",
        index_sha256=sha256(b"empty tariff index").hexdigest(),
        complete=True,
        records=(),
    )
    empty_tariff_snapshot = scan_regulatory_registry(
        _Adapter(RegulatoryRegistryChannel.ARERA_TARIFFS, page), PERIOD, NOW
    )
    discovery = report.model_copy(
        update={
            "snapshots": tuple(
                empty_tariff_snapshot
                if item.channel == RegulatoryRegistryChannel.ARERA_TARIFFS
                else item
                for item in report.snapshots
            )
        }
    )

    scoped = scope_domestic_projection_discovery(discovery)

    assert scoped is discovery


def test_scope_preserves_preclassified_findings() -> None:
    report = _report()
    supported = _finding(report, RegulatoryRegistryChannel.ARERA_ACTS, "343/2026/R/com")
    supported = supported.model_copy(
        update={
            "disposition": DiscoveryActDisposition.SUPPORTED,
            "rationale": "fixture was already classified by its exact source policy",
            "rule_id": "fixture-supported-source",
            "rule_version": "1.0.0",
        }
    )
    discovery = report.model_copy(
        update={
            "findings": tuple(
                supported
                if item.act_id == "343/2026/R/com" and item.channel == supported.channel
                else item
                for item in report.findings
            )
        }
    )

    scoped = scope_domestic_projection_discovery(discovery)

    preserved = _finding(scoped, RegulatoryRegistryChannel.ARERA_ACTS, "343/2026/R/com")
    assert preserved.disposition == DiscoveryActDisposition.SUPPORTED
    assert preserved.rule_id == "fixture-supported-source"
