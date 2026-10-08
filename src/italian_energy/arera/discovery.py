"""Completeness-aware discovery contracts for official regulatory indexes.

This module deliberately does not parse generic HTML, PDF, or legal text. A
registry-specific adapter must return structurally validated pages with a
digest of the exact index bytes it interpreted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.domain.base import DomainModel
from italian_energy.domain.time import DatePeriod


class RegulatoryRegistryChannel(StrEnum):
    """Independent indexes required to establish a complete discovery run."""

    ARERA_ACTS = "arera_acts"
    ARERA_TARIFFS = "arera_tariffs"
    ADM_EXCISE = "adm_excise"
    GAZZETTA_SERIE_GENERALE = "gazzetta_serie_generale"
    NORMATTIVA_UPDATES = "normattiva_updates"

    @property
    def official_hosts(self) -> frozenset[str]:
        return {
            RegulatoryRegistryChannel.ARERA_ACTS: frozenset({"arera.it", "www.arera.it"}),
            RegulatoryRegistryChannel.ARERA_TARIFFS: frozenset({"arera.it", "www.arera.it"}),
            RegulatoryRegistryChannel.ADM_EXCISE: frozenset({"adm.gov.it", "www.adm.gov.it"}),
            RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: frozenset(
                {"gazzettaufficiale.it", "www.gazzettaufficiale.it"}
            ),
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES: frozenset(
                {"normattiva.it", "www.normattiva.it", "api.normattiva.it"}
            ),
        }[self]


DISCOVERY_CHANNELS = (
    RegulatoryRegistryChannel.ARERA_ACTS,
    RegulatoryRegistryChannel.ARERA_TARIFFS,
    RegulatoryRegistryChannel.ADM_EXCISE,
    RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
    RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
)


def _index_snapshot_digest(
    channel: RegulatoryRegistryChannel,
    search_period: DatePeriod,
    query: str,
    page_digests: tuple[str, ...],
) -> str:
    encoded = json.dumps(
        {
            "channel": channel.value,
            "period": search_period.model_dump(mode="json"),
            "query": query,
            "page_digests": list(page_digests),
        },
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DiscoveryActDisposition(StrEnum):
    """Explicit policy outcome for a newly discovered official record."""

    SUPPORTED = "supported"
    IRRELEVANT_BY_VERSIONED_RULE = "irrelevant_by_versioned_rule"
    REVIEW_REQUIRED = "review_required"


class DiscoveryChangeKind(StrEnum):
    """Observed changes to records in overlapping successful scans."""

    NEW = "new"
    CHANGED = "changed"
    REMOVED = "removed"


class OfficialRegistryRecord(DomainModel):
    """Structured metadata parsed from one versioned official index layout."""

    channel: RegulatoryRegistryChannel
    act_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    published_at: date
    registry_date: date | None = None
    effective_from: date | None = None
    url: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    latest_amending_act_ids: tuple[str, ...] = ()
    registry_section: str | None = Field(default=None, min_length=1)

    @field_validator("latest_amending_act_ids")
    @classmethod
    def canonicalize_latest_amending_act_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not act_id.strip() for act_id in value):
            raise ValueError("latest amending act IDs must be unique and non-empty")
        return tuple(sorted(value))

    @field_validator("registry_section")
    @classmethod
    def require_normalized_registry_section(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != " ".join(value.split())):
            raise ValueError("registry section must be non-empty and whitespace-normalized")
        return value

    @field_validator("url")
    @classmethod
    def require_official_https_url(cls, value: str) -> str:
        # The channel-specific host check is repeated by the after validator,
        # where Pydantic has already validated the channel field.
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("registry record URL must be an official HTTPS host")
        return value

    @model_validator(mode="after")
    def validate_registry_host(self) -> OfficialRegistryRecord:
        host = urlsplit(self.url).hostname
        if host not in self.channel.official_hosts:
            raise ValueError("registry record URL must be an official HTTPS host")
        return self


class RegistryIndexPage(DomainModel):
    """One completely parsed page from a versioned registry index adapter."""

    channel: RegulatoryRegistryChannel
    search_period: DatePeriod
    query: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    fetched_at: datetime
    page_number: int = Field(ge=1)
    total_pages: int = Field(ge=1)
    total_results: int = Field(ge=0)
    cursor_in: str | None = None
    cursor_out: str | None = None
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    complete: bool = True
    records_confined_to_search_period: bool = True
    records: tuple[OfficialRegistryRecord, ...] = ()

    @field_validator("source_url")
    @classmethod
    def require_official_index_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("registry index URL must be an official HTTPS host")
        return value

    @field_validator("fetched_at")
    @classmethod
    def require_aware_page_fetch_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registry page fetched_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_page(self) -> RegistryIndexPage:
        if self.page_number > self.total_pages:
            raise ValueError("registry page number exceeds the declared page count")
        if len(self.records) > self.total_results:
            raise ValueError("registry page contains more records than the declared total")
        if any(record.channel != self.channel for record in self.records):
            raise ValueError("registry page contains a record from another channel")
        if urlsplit(self.source_url).hostname not in self.channel.official_hosts:
            raise ValueError("registry index URL must be an official HTTPS host")
        record_ids = tuple(record.act_id for record in self.records)
        if len(set(record_ids)) != len(record_ids):
            raise ValueError("registry page act IDs must be unique")
        if (
            self.complete
            and self.page_number < self.total_pages
            and (not self.cursor_out or self.cursor_out == self.cursor_in)
        ):
            raise ValueError("non-final registry page requires a progressing cursor")
        return self


class RegistryCursor(DomainModel):
    """Last successfully committed observation for one registry channel."""

    channel: RegulatoryRegistryChannel
    covered_through: date
    next_token: str | None = None
    snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RegistryPageEvidence(DomainModel):
    """Acquisition provenance for one exact index page, without raw bytes."""

    channel: RegulatoryRegistryChannel
    page_number: int = Field(ge=1)
    source_url: str = Field(min_length=1)
    fetched_at: datetime
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("fetched_at")
    @classmethod
    def require_aware_fetch_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registry page evidence fetched_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_official_source(self) -> RegistryPageEvidence:
        parsed = urlsplit(self.source_url)
        if parsed.scheme != "https" or parsed.hostname not in self.channel.official_hosts:
            raise ValueError("registry page evidence URL must be an official HTTPS host")
        return self


class DiscoveryActFinding(DomainModel):
    """Versioned decision attached to a registry record and its source metadata."""

    channel: RegulatoryRegistryChannel
    act_id: str = Field(min_length=1)
    disposition: DiscoveryActDisposition
    rationale: str = Field(min_length=1)
    rule_id: str | None = None
    rule_version: str | None = None
    source_record: OfficialRegistryRecord | None = None

    @model_validator(mode="after")
    def validate_policy_reference(self) -> DiscoveryActFinding:
        if self.source_record is not None and (
            self.source_record.channel != self.channel or self.source_record.act_id != self.act_id
        ):
            raise ValueError("discovery finding source record must match its channel and act ID")
        if self.disposition == DiscoveryActDisposition.REVIEW_REQUIRED:
            if (self.rule_id is None) != (self.rule_version is None):
                raise ValueError("review finding rule ID and version must be supplied together")
        elif not self.rule_id or not self.rule_version:
            raise ValueError("automated discovery decision requires a versioned rule")
        return self


class DiscoveryRecordChange(DomainModel):
    """Machine-readable new, revised, or removed index record."""

    channel: RegulatoryRegistryChannel
    act_id: str = Field(min_length=1)
    kind: DiscoveryChangeKind
    previous_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    observed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digests(self) -> DiscoveryRecordChange:
        if self.kind == DiscoveryChangeKind.NEW:
            if self.previous_sha256 is not None or self.observed_sha256 is None:
                raise ValueError("new discovery record requires only its observed digest")
        elif self.kind == DiscoveryChangeKind.REMOVED:
            if self.previous_sha256 is None or self.observed_sha256 is not None:
                raise ValueError("removed discovery record requires only its prior digest")
        elif self.previous_sha256 is None or self.observed_sha256 is None:
            raise ValueError("changed discovery record requires both digests")
        return self


class DiscoverySnapshot(DomainModel):
    """Immutable evidence for one channel scan and its safe cursor transition."""

    channel: RegulatoryRegistryChannel
    search_period: DatePeriod
    query: str = Field(min_length=1)
    discovered_at: datetime
    adapter_id: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    input_cursor: str | None = None
    pages_received: int = Field(ge=0)
    page_evidence: tuple[RegistryPageEvidence, ...] = ()
    records: tuple[OfficialRegistryRecord, ...]
    index_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    complete: bool
    next_cursor: RegistryCursor | None
    reason_code: RegulatoryRolloverReason | None = None
    classification_complete: bool = False
    findings: tuple[DiscoveryActFinding, ...] = ()

    @field_validator("discovered_at")
    @classmethod
    def require_aware_discovery_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("registry discovery time must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_snapshot(self) -> DiscoverySnapshot:
        if any(record.channel != self.channel for record in self.records):
            raise ValueError("discovery snapshot contains a record from another channel")
        if any(item.channel != self.channel for item in self.page_evidence):
            raise ValueError("discovery page evidence channel must match its snapshot")
        if self.pages_received != len(self.page_evidence):
            raise ValueError("discovery snapshot requires provenance for every received page")
        page_numbers = tuple(item.page_number for item in self.page_evidence)
        if page_numbers != tuple(range(1, self.pages_received + 1)):
            raise ValueError("discovery page evidence must be sequential")
        if any(item.fetched_at > self.discovered_at for item in self.page_evidence):
            raise ValueError("discovery time cannot precede a page fetch")
        expected_digest = _index_snapshot_digest(
            self.channel,
            self.search_period,
            self.query,
            tuple(item.index_sha256 for item in self.page_evidence),
        )
        if expected_digest != self.index_sha256:
            raise ValueError("discovery index digest must match its page evidence")
        ids = tuple(record.act_id for record in self.records)
        if len(set(ids)) != len(ids):
            raise ValueError("discovery snapshot act IDs must be unique")
        finding_ids = tuple(item.act_id for item in self.findings)
        if len(set(finding_ids)) != len(finding_ids):
            raise ValueError("discovery snapshot findings must identify unique acts")
        if any(item.channel != self.channel for item in self.findings):
            raise ValueError("discovery snapshot findings must match its channel")
        if self.classification_complete and (
            not self.complete or not set(ids).issubset(set(finding_ids))
        ):
            raise ValueError("complete classification requires one decision per scanned act")
        if self.complete:
            if self.pages_received < 1 or self.next_cursor is None or self.reason_code is not None:
                raise ValueError("complete scan requires its next cursor and no failure reason")
            if self.next_cursor.channel != self.channel:
                raise ValueError("discovery cursor channel must match its snapshot")
            if self.next_cursor.covered_through != self.search_period.end:
                raise ValueError("discovery cursor cutoff must match the scanned period")
            if self.next_cursor.snapshot_sha256 != self.index_sha256:
                raise ValueError("discovery cursor digest must match its snapshot")
        elif self.next_cursor is not None or self.reason_code is None:
            raise ValueError("incomplete scan requires a failure reason and cannot advance cursor")
        return self


class RegulatoryDiscoveryReport(DomainModel):
    """All required registry observations, findings, and committable cursors."""

    as_of: date
    snapshots: tuple[DiscoverySnapshot, ...]
    findings: tuple[DiscoveryActFinding, ...]
    changes: tuple[DiscoveryRecordChange, ...] = ()

    @model_validator(mode="after")
    def validate_channels_and_findings(self) -> RegulatoryDiscoveryReport:
        channels = tuple(snapshot.channel for snapshot in self.snapshots)
        if len(set(channels)) != len(channels):
            raise ValueError("discovery report must contain unique channels")
        if set(channels) != set(DISCOVERY_CHANNELS):
            raise ValueError("discovery report must account for every required channel")
        if any(
            snapshot.search_period.end - timedelta(days=1) != self.as_of
            for snapshot in self.snapshots
        ):
            raise ValueError("discovery snapshots must identify the report date")
        finding_keys = tuple((item.channel, item.act_id) for item in self.findings)
        if len(set(finding_keys)) != len(finding_keys):
            raise ValueError("discovery findings must be unique")
        change_keys = tuple((item.channel, item.act_id) for item in self.changes)
        if len(set(change_keys)) != len(change_keys):
            raise ValueError("discovery changes must be unique")
        record_keys = {
            (record.channel, record.act_id)
            for snapshot in self.snapshots
            for record in snapshot.records
        }
        if any(
            (item.channel, item.act_id) not in record_keys and item.source_record is None
            for item in self.findings
        ):
            raise ValueError("discovery finding must reference a snapshot record")
        return self

    @property
    def scans_complete(self) -> bool:
        return all(snapshot.complete for snapshot in self.snapshots)

    @property
    def review_required(self) -> bool:
        return any(
            finding.disposition == DiscoveryActDisposition.REVIEW_REQUIRED
            for finding in self.findings
        )

    @property
    def integrity_changed(self) -> bool:
        return any(
            item.kind in {DiscoveryChangeKind.CHANGED, DiscoveryChangeKind.REMOVED}
            for item in self.changes
        )

    @property
    def cursor_updates(self) -> tuple[RegistryCursor, ...]:
        """Expose only cursors backed by a complete, validated scan."""

        return tuple(
            snapshot.next_cursor
            for snapshot in self.snapshots
            if snapshot.complete and snapshot.next_cursor is not None
        )


class RegistryIndexAdapter(Protocol):
    """Adapter for one approved registry layout and its pagination contract."""

    channel: RegulatoryRegistryChannel
    adapter_id: str
    adapter_version: str

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage: ...


class DiscoveryFailure(Exception):
    """Adapter boundary failure with a stable machine-readable reason."""

    def __init__(self, reason: RegulatoryRolloverReason) -> None:
        self.reason = reason
        super().__init__(reason.value)


def incremental_search_period(
    *,
    as_of: date,
    last_covered_through: date | None,
    overlap_days: int,
    initial_search_start: date | None = None,
) -> DatePeriod:
    """Re-scan an overlap window, including modifications to prior acts."""

    if overlap_days < 0:
        raise ValueError("discovery overlap days cannot be negative")
    if last_covered_through is None:
        if initial_search_start is None:
            raise ValueError("initial discovery search start must be configured")
        start = initial_search_start
    else:
        start = last_covered_through - timedelta(days=overlap_days)
    return DatePeriod(start=start, end=as_of + timedelta(days=1))


def scan_regulatory_registry(
    adapter: RegistryIndexAdapter,
    search_period: DatePeriod,
    discovered_at: datetime,
    *,
    previous_cursor: RegistryCursor | None = None,
    max_pages: int = 500,
) -> DiscoverySnapshot:
    """Read every page and create a cursor only after the complete scan passes."""

    if discovered_at.tzinfo is None or discovered_at.utcoffset() is None:
        raise ValueError("registry discovery time must be timezone-aware")
    if max_pages < 1:
        raise ValueError("registry scan page limit must be positive")
    if previous_cursor is not None and previous_cursor.channel != adapter.channel:
        raise ValueError("registry cursor channel does not match its adapter")

    input_token = previous_cursor.next_token if previous_cursor is not None else None
    pages: list[RegistryIndexPage] = []
    records: list[OfficialRegistryRecord] = []
    reason: RegulatoryRolloverReason | None = None
    expected_cursor = input_token
    expected_pages: int | None = None
    expected_results: int | None = None
    records_confined: bool | None = None
    query: str | None = None

    for page_number in range(1, max_pages + 1):
        try:
            page = adapter.fetch_page(search_period, page_number, expected_cursor)
        except DiscoveryFailure as exc:
            reason = exc.reason
            break
        except OSError:
            reason = RegulatoryRolloverReason.SOURCE_UNAVAILABLE
            break
        except (ValueError, TypeError):
            reason = RegulatoryRolloverReason.PARSER_FAILURE
            break

        if (
            page.channel != adapter.channel
            or page.search_period != search_period
            or page.page_number != page_number
            or page.cursor_in != expected_cursor
        ):
            reason = RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
            break
        if expected_pages is None:
            expected_pages = page.total_pages
            expected_results = page.total_results
            query = page.query
            records_confined = page.records_confined_to_search_period
        elif (
            page.total_pages != expected_pages
            or page.total_results != expected_results
            or page.query != query
            or page.records_confined_to_search_period != records_confined
        ):
            reason = RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
            break
        pages.append(page)
        if not page.complete:
            reason = RegulatoryRolloverReason.INCOMPLETE_COVERAGE
            break
        if page.records_confined_to_search_period and any(
            not search_period.start
            <= (record.registry_date or record.published_at)
            < search_period.end
            for record in page.records
        ):
            reason = RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
            break
        seen_ids = {record.act_id for record in records}
        if any(record.act_id in seen_ids for record in page.records):
            reason = RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY
            break
        records.extend(page.records)
        expected_cursor = page.cursor_out
        if page_number == page.total_pages:
            break
        if page_number >= max_pages:
            reason = RegulatoryRolloverReason.INCOMPLETE_COVERAGE
            break
    if reason is None and (
        expected_pages is None or len(pages) != expected_pages or expected_results != len(records)
    ):
        reason = RegulatoryRolloverReason.INCOMPLETE_COVERAGE

    snapshot_query = query or "unavailable"
    snapshot_digest = _index_snapshot_digest(
        adapter.channel,
        search_period,
        snapshot_query,
        tuple(page.index_sha256 for page in pages),
    )
    complete = reason is None
    next_cursor = (
        RegistryCursor(
            channel=adapter.channel,
            covered_through=search_period.end,
            next_token=expected_cursor,
            snapshot_sha256=snapshot_digest,
        )
        if complete
        else None
    )
    snapshot_discovered_at = max((discovered_at, *(page.fetched_at for page in pages)))
    return DiscoverySnapshot(
        channel=adapter.channel,
        search_period=search_period,
        query=snapshot_query,
        discovered_at=snapshot_discovered_at,
        adapter_id=adapter.adapter_id,
        adapter_version=adapter.adapter_version,
        input_cursor=input_token,
        pages_received=len(pages),
        records=tuple(
            sorted(
                (
                    item
                    for item in records
                    if search_period.start
                    <= (item.registry_date or item.published_at)
                    < search_period.end
                ),
                key=lambda item: (item.registry_date or item.published_at, item.act_id),
            )
        ),
        page_evidence=tuple(
            RegistryPageEvidence(
                channel=page.channel,
                page_number=page.page_number,
                source_url=page.source_url,
                fetched_at=page.fetched_at,
                index_sha256=page.index_sha256,
            )
            for page in pages
        ),
        index_sha256=snapshot_digest,
        complete=complete,
        next_cursor=next_cursor,
        reason_code=reason,
    )


def _record_digest(record: OfficialRegistryRecord) -> str:
    encoded = json.dumps(
        record.model_dump(mode="json"),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compare_overlapping_discoveries(
    previous: DiscoverySnapshot, current: DiscoverySnapshot
) -> tuple[DiscoveryRecordChange, ...]:
    """Detect revisions/removals in the date range intentionally re-scanned."""

    if previous.channel != current.channel:
        raise ValueError("discovery snapshots must belong to the same channel")
    if not previous.complete or not current.complete:
        raise ValueError("only complete discovery snapshots can be compared")
    overlap_start = max(previous.search_period.start, current.search_period.start)
    overlap_end = min(previous.search_period.end, current.search_period.end)
    if overlap_start >= overlap_end:
        raise ValueError("discovery snapshots must have an overlapping search period")

    prior_records = {
        record.act_id: record
        for record in previous.records
        if overlap_start <= (record.registry_date or record.published_at) < overlap_end
    }
    current_records = {record.act_id: record for record in current.records}
    changes: list[DiscoveryRecordChange] = []
    for act_id, record in current_records.items():
        prior = next((item for item in previous.records if item.act_id == act_id), None)
        if prior is None:
            changes.append(
                DiscoveryRecordChange(
                    channel=current.channel,
                    act_id=act_id,
                    kind=DiscoveryChangeKind.NEW,
                    observed_sha256=_record_digest(record),
                )
            )
        elif _record_digest(prior) != _record_digest(record):
            changes.append(
                DiscoveryRecordChange(
                    channel=current.channel,
                    act_id=act_id,
                    kind=DiscoveryChangeKind.CHANGED,
                    previous_sha256=_record_digest(prior),
                    observed_sha256=_record_digest(record),
                )
            )
    for act_id, record in prior_records.items():
        if act_id not in current_records:
            changes.append(
                DiscoveryRecordChange(
                    channel=current.channel,
                    act_id=act_id,
                    kind=DiscoveryChangeKind.REMOVED,
                    previous_sha256=_record_digest(record),
                )
            )
    return tuple(sorted(changes, key=lambda item: (item.act_id, item.kind.value)))


def discover_regulatory_sources(
    adapters: tuple[RegistryIndexAdapter, ...],
    search_period: DatePeriod,
    discovered_at: datetime,
    *,
    previous_cursors: tuple[RegistryCursor, ...] = (),
    previous_snapshots: tuple[DiscoverySnapshot, ...] = (),
    known_act_ids: tuple[tuple[RegulatoryRegistryChannel, str], ...] = (),
    classifier: Callable[[OfficialRegistryRecord], DiscoveryActFinding] | None = None,
) -> RegulatoryDiscoveryReport:
    """Scan every required channel and fail closed when an adapter is absent."""

    adapter_by_channel = {adapter.channel: adapter for adapter in adapters}
    if len(adapter_by_channel) != len(adapters):
        raise ValueError("discovery adapter channels must be unique")
    cursor_by_channel = {cursor.channel: cursor for cursor in previous_cursors}
    if len(cursor_by_channel) != len(previous_cursors):
        raise ValueError("discovery cursors must be unique by channel")

    snapshots: list[DiscoverySnapshot] = []
    findings: list[DiscoveryActFinding] = []
    known = set(known_act_ids)
    previous_by_channel = {snapshot.channel: snapshot for snapshot in previous_snapshots}
    if len(previous_by_channel) != len(previous_snapshots):
        raise ValueError("prior discovery snapshots must be unique by channel")
    changes: list[DiscoveryRecordChange] = []
    report_findings: dict[tuple[RegulatoryRegistryChannel, str], DiscoveryActFinding] = {}
    for channel in DISCOVERY_CHANNELS:
        adapter = adapter_by_channel.get(channel)
        if adapter is None:
            missing_query = "adapter_missing"
            empty_digest = _index_snapshot_digest(channel, search_period, missing_query, ())
            snapshot = DiscoverySnapshot(
                channel=channel,
                search_period=search_period,
                query=missing_query,
                discovered_at=discovered_at,
                adapter_id="unconfigured",
                adapter_version="0",
                input_cursor=None,
                pages_received=0,
                records=(),
                index_sha256=empty_digest,
                complete=False,
                next_cursor=None,
                reason_code=RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
            )
        else:
            snapshot = scan_regulatory_registry(
                adapter,
                search_period,
                discovered_at,
                previous_cursor=cursor_by_channel.get(channel),
            )
        snapshots.append(snapshot)
        previous_snapshot = previous_by_channel.get(channel)
        previous_records = (
            {record.act_id: record for record in previous_snapshot.records}
            if previous_snapshot is not None
            else {}
        )
        previous_findings = (
            {item.act_id: item for item in previous_snapshot.findings}
            if previous_snapshot is not None
            else {}
        )
        if (
            previous_snapshot is not None
            and previous_snapshot.complete
            and snapshot.complete
            and max(previous_snapshot.search_period.start, snapshot.search_period.start)
            < min(previous_snapshot.search_period.end, snapshot.search_period.end)
        ):
            changes.extend(compare_overlapping_discoveries(previous_snapshot, snapshot))

        def classify(record: OfficialRegistryRecord) -> DiscoveryActFinding:
            if (record.channel, record.act_id) in known:
                finding = DiscoveryActFinding(
                    channel=record.channel,
                    act_id=record.act_id,
                    disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
                    rationale="record is an existing anchor source checked by its source digest",
                    rule_id="known-anchor-source",
                    rule_version="1.0.0",
                )
            elif classifier is None:
                # Import lazily to keep the exact-source policy module free to
                # depend on these discovery contracts without a module cycle.
                from italian_energy.arera.rollover_classification import (
                    classify_official_regulatory_record,
                )

                finding = classify_official_regulatory_record(record)
            else:
                finding = classifier(record)
            if finding.channel != record.channel or finding.act_id != record.act_id:
                raise ValueError("discovery classifier result must identify its input record")
            return finding.model_copy(update={"source_record": record})

        decisions: dict[str, DiscoveryActFinding] = {}
        current_records = {record.act_id: record for record in snapshot.records}
        if snapshot.complete:
            for record in snapshot.records:
                prior_record = previous_records.get(record.act_id)
                prior_finding = previous_findings.get(record.act_id)
                if prior_record is None and prior_finding is not None:
                    prior_record = prior_finding.source_record
                if prior_record is not None and _record_digest(prior_record) != _record_digest(
                    record
                ):
                    finding = DiscoveryActFinding(
                        channel=record.channel,
                        act_id=record.act_id,
                        disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
                        rationale="official index metadata changed since the stored observation",
                        source_record=record,
                    )
                    observed = _record_digest(record)
                    previous_digest = _record_digest(prior_record)
                    if not any(
                        item.channel == channel
                        and item.act_id == record.act_id
                        and item.kind == DiscoveryChangeKind.CHANGED
                        for item in changes
                    ):
                        changes.append(
                            DiscoveryRecordChange(
                                channel=channel,
                                act_id=record.act_id,
                                kind=DiscoveryChangeKind.CHANGED,
                                previous_sha256=previous_digest,
                                observed_sha256=observed,
                            )
                        )
                else:
                    finding = classify(record)
                decisions[record.act_id] = finding

        prior_record_ids = set(previous_records)
        if previous_snapshot is not None:
            prior_record_ids.update(
                item.act_id for item in previous_findings.values() if item.source_record is not None
            )
        for act_id in sorted(prior_record_ids - set(current_records)):
            prior_finding = previous_findings.get(act_id)
            prior_record = previous_records.get(act_id)
            if prior_record is None and prior_finding is not None:
                prior_record = prior_finding.source_record
            if prior_finding is not None and prior_finding.disposition == (
                DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE
            ):
                continue
            if prior_record is None:
                continue
            # Backfill older persisted snapshots that predate classification fields.
            decision = (
                classify(prior_record)
                if not (
                    prior_finding is not None
                    and previous_snapshot is not None
                    and previous_snapshot.classification_complete
                )
                else prior_finding
            )
            decisions[act_id] = decision.model_copy(update={"source_record": prior_record})

        snapshot = DiscoverySnapshot.model_validate(
            {
                **snapshot.model_dump(mode="python"),
                "classification_complete": snapshot.complete
                and len(decisions) >= len(snapshot.records),
                "findings": tuple(decisions[key] for key in sorted(decisions)),
            }
        )
        snapshots[-1] = snapshot
        for finding in snapshot.findings:
            if finding.disposition != DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE:
                report_findings[(finding.channel, finding.act_id)] = finding

    findings = list(report_findings.values())
    return RegulatoryDiscoveryReport(
        as_of=search_period.end - timedelta(days=1),
        snapshots=tuple(snapshots),
        findings=tuple(sorted(findings, key=lambda item: (item.channel.value, item.act_id))),
        changes=tuple(
            sorted(changes, key=lambda item: (item.channel.value, item.act_id, item.kind.value))
        ),
    )


__all__ = [
    "DISCOVERY_CHANNELS",
    "DiscoveryActDisposition",
    "DiscoveryActFinding",
    "DiscoveryChangeKind",
    "DiscoveryFailure",
    "DiscoveryRecordChange",
    "DiscoverySnapshot",
    "OfficialRegistryRecord",
    "RegistryCursor",
    "RegistryIndexAdapter",
    "RegistryIndexPage",
    "RegulatoryDiscoveryReport",
    "RegulatoryRegistryChannel",
    "compare_overlapping_discoveries",
    "discover_regulatory_sources",
    "incremental_search_period",
    "scan_regulatory_registry",
]
