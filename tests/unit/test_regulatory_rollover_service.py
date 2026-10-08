from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
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
    OfficialRegistryRecord,
    RegistryIndexPage,
    RegulatoryRegistryChannel,
    discover_regulatory_sources,
)
from italian_energy.arera.importer import SCHEMA_VERSION as ARERA_LAYOUT_VERSION
from italian_energy.arera.models import AreraCustomerSegment
from italian_energy.arera.official_registry_adapters import normattiva_vat_reference_records
from italian_energy.arera.projection import (
    ROLLOVER_ANCHOR_SCHEMA_VERSION,
    DomesticProjectionAnchor,
    load_domestic_projection_anchor,
)
from italian_energy.arera.rollover_coverage import (
    RegulatoryAnchorCoverageEvidence,
    RegulatoryAnchorSourceCheck,
    RegulatoryManualReview,
    RegulatoryReviewOutcome,
    RegulatoryReviewSourceCheck,
    verify_regulatory_anchor_coverage,
)
from italian_energy.arera.rollover_models import (
    RegulatoryEffectAssertion,
    RegulatoryFact,
    RegulatoryFactFamily,
    RegulatoryRolloverReason,
    RolloverPolicy,
)
from italian_energy.arera.rollover_parsers import (
    ARERA_DOMESTIC_WORKBOOK_KIND,
    ARERA_DOMESTIC_WORKBOOK_MIME,
    RegulatoryInterpretation,
    RegulatoryParserKey,
    RegulatoryParserRegistry,
    RegulatorySourceDocument,
    default_regulatory_parser_registry,
)
from italian_energy.arera.rollover_repository import InMemoryRegulatoryRepository
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.arera.rollover_state import RolloverAttemptStatus
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.integration.regulatory_rollover_service import (
    RegulatoryRolloverAction,
    RegulatoryRolloverReport,
    RegulatoryRolloverService,
    RegulatorySourcePreflightResult,
    create_official_regulatory_service,
)

AS_OF = date(2026, 9, 30)
NEXT_DAY = date(2026, 10, 1)
CURRENT_VALIDITY = DatePeriod(start=date(2026, 7, 1), end=NEXT_DAY)
NEXT_VALIDITY = DatePeriod(start=NEXT_DAY, end=date(2027, 1, 1))
CREATED_AT = datetime(2026, 9, 30, 12, tzinfo=UTC)
FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures/regulatory_rollover/domestic-2026-q4-synthetic.xlsx"
)


def test_official_factory_owns_all_five_channels_and_keeps_service_core_owned() -> None:
    current = load_domestic_projection_anchor()
    repository = InMemoryRegulatoryRepository(current, initialized_at=CREATED_AT)

    service = create_official_regulatory_service(
        repository,
        initial_search_start=current.validity.start,
        clock=lambda: CREATED_AT,
    )

    assert {adapter.channel for adapter in service._registry_adapters} == set(DISCOVERY_CHANNELS)
    assert service._source_port is not None
    assert service._known_source_records is normattiva_vat_reference_records
    assert tuple(item.document_id for item in service._known_source_records(NEXT_DAY)) == (
        "DPR-633-1972-Tabella-A-Parte-III-n-103",
        "DPR-633-1972-art-16-aliquote",
    )
    assert service.source_preflight(AS_OF, None).ready is False


class _DailyIndexAdapter:
    def __init__(
        self,
        channel: RegulatoryRegistryChannel,
        records: tuple[OfficialRegistryRecord, ...],
        clock: datetime,
    ) -> None:
        self.channel = channel
        self.records = records
        self.clock = clock
        self.adapter_id = f"fixture-index-{channel.value}"
        self.adapter_version = "1.0.0"

    def fetch_page(
        self,
        search_period: DatePeriod,
        page_number: int,
        cursor: str | None,
    ) -> RegistryIndexPage:
        assert page_number == 1
        records = tuple(
            item
            for item in self.records
            if search_period.start <= item.published_at < search_period.end
        )
        page_digest = hashlib.sha256(
            f"{self.channel.value}|{search_period.start}|{search_period.end}".encode()
        ).hexdigest()
        host = {
            RegulatoryRegistryChannel.ARERA_ACTS: "www.arera.it",
            RegulatoryRegistryChannel.ARERA_TARIFFS: "www.arera.it",
            RegulatoryRegistryChannel.ADM_EXCISE: "www.adm.gov.it",
            RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE: "www.gazzettaufficiale.it",
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES: "www.normattiva.it",
        }[self.channel]
        return RegistryIndexPage(
            channel=self.channel,
            search_period=search_period,
            query="fixture all acts in window",
            source_url=f"https://{host}/synthetic/index",
            fetched_at=self.clock,
            page_number=1,
            total_pages=1,
            total_results=len(records),
            cursor_in=cursor,
            cursor_out=f"fixture:{search_period.end.isoformat()}",
            index_sha256=page_digest,
            complete=True,
            records=records,
        )


class _FiscalFactParser:
    def __init__(
        self,
        *,
        document_kind: str,
        parser_id: str,
        family: RegulatoryFactFamily,
        value: Decimal,
        unit: RateUnit,
    ) -> None:
        self.key = RegulatoryParserKey(
            channel=(
                RegulatoryRegistryChannel.ADM_EXCISE
                if family == RegulatoryFactFamily.EXCISE_RATE
                else RegulatoryRegistryChannel.NORMATTIVA_UPDATES
            ),
            document_kind=document_kind,
            layout_version="fixture-v1",
        )
        self.parser_id = parser_id
        self.version = "1.0.0"
        self.family = family
        self.value = value
        self.unit = unit

    def parse(self, source: RegulatorySourceDocument) -> tuple[RegulatoryFact, ...]:
        return (
            RegulatoryFact(
                fact_id=f"{source.source_id}:fact",
                family=self.family,
                value=self.value,
                unit=self.unit,
                validity=NEXT_VALIDITY,
                source_id=source.source_id,
                source_url=source.acquired.url,
                source_sha256=source.acquired.sha256,
                act_id=source.act_id,
                document=source.document_id,
                published_at=source.published_at,
                fetched_at=source.acquired.fetched_at,
                parser_id=self.parser_id,
                parser_version=self.version,
                locator="synthetic table row 1",
                raw_value_token=str(self.value),
                derivation="synthetic fixture token parsed as Decimal",
                status=VerificationStatus.VERIFIED,
            ),
        )


class _FixtureSourcePort:
    def __init__(
        self,
        records: tuple[OfficialRegistryRecord, ...],
        now: datetime,
        *,
        unavailable_url: str | None = None,
    ) -> None:
        self.now = now
        self.unavailable_url = unavailable_url
        self._documents: dict[str, RegulatorySourceDocument] = {}
        self._bodies_by_url: dict[str, bytes] = {}
        self.fetch_count = 0
        for record in records:
            if record.act_id == "R-q4-workbook":
                body = FIXTURE_PATH.read_bytes()
                source_id = "arera-q4-fixture"
                content_type = ARERA_DOMESTIC_WORKBOOK_MIME
                document_kind = ARERA_DOMESTIC_WORKBOOK_KIND
                layout_version = ARERA_LAYOUT_VERSION
            elif record.act_id == "343/2026/R/com":
                body = b"synthetic ARERA confirmation fixture"
                source_id = "arera_343_q4_fixture"
                content_type = "application/pdf"
                document_kind = "fixture_arera_343"
                layout_version = "fixture-v1"
            elif record.act_id == "ADM-Q4-excise":
                body = b"synthetic official excise table"
                source_id = "adm_q4_excise_fixture"
                content_type = "application/octet-stream"
                document_kind = "fixture_excise"
                layout_version = "fixture-v1"
            elif record.act_id == "VAT-Q4-table":
                body = b"synthetic official VAT table"
                source_id = "vat_dpr_633"
                content_type = "application/octet-stream"
                document_kind = "fixture_vat_table"
                layout_version = "fixture-v1"
            elif record.act_id == "VAT-Q4-rate":
                body = b"synthetic official VAT rate source"
                source_id = "vat_dpr_633_art16"
                content_type = "application/octet-stream"
                document_kind = "fixture_vat_rate"
                layout_version = "fixture-v1"
            else:
                body = f"unsupported:{record.act_id}".encode()
                source_id = f"unsupported:{record.act_id}"
                content_type = "application/octet-stream"
                document_kind = "unregistered-layout"
                layout_version = "unknown"
            acquired = AcquiredOfficialBytes(
                url=record.url,
                body=body,
                sha256=hashlib.sha256(body).hexdigest(),
                fetched_at=now,
            )
            document = RegulatorySourceDocument(
                acquired=acquired,
                source_id=source_id,
                channel=record.channel,
                act_id=record.act_id,
                document_id=record.document_id,
                published_at=record.published_at,
                content_type=content_type,
                document_kind=document_kind,
                layout_version=layout_version,
            )
            self._documents[record.act_id] = document
            self._bodies_by_url[record.url] = body

    def add_current_anchor_sources(
        self, anchor: DomesticProjectionAnchor
    ) -> DomesticProjectionAnchor:
        payload = anchor.model_dump(mode="python")
        payload.update(
            {
                "schema_version": ROLLOVER_ANCHOR_SCHEMA_VERSION,
                "anchor_id": "synthetic-anchor-A",
                "as_of": CURRENT_VALIDITY.start,
                "validity": CURRENT_VALIDITY,
            }
        )
        for source in payload["sources"]:
            body = f"synthetic current source:{source['source_id']}".encode()
            source.update(
                {
                    "sha256": hashlib.sha256(body).hexdigest(),
                    "published_at": date(2026, 6, 15),
                    "retrieved_at": datetime(2026, 6, 30, 12, tzinfo=UTC),
                }
            )
            self._bodies_by_url[source["url"]] = body
        return DomesticProjectionAnchor.model_validate(payload)

    def acquire_document(self, record: OfficialRegistryRecord) -> RegulatorySourceDocument:
        return self._documents[record.act_id]

    def fetch_source(self, url: str) -> bytes:
        self.fetch_count += 1
        if url == self.unavailable_url:
            raise OSError("synthetic temporary outage")
        try:
            return self._bodies_by_url[url]
        except KeyError as exc:
            raise OSError("synthetic source is not in fixture cache") from exc


class _AcquisitionFaultPort:
    def __init__(
        self,
        delegate: _FixtureSourcePort,
        *,
        failure: Exception | None = None,
        mismatch_metadata: bool = False,
    ) -> None:
        self.delegate = delegate
        self.failure = failure
        self.mismatch_metadata = mismatch_metadata

    def acquire_document(self, record: OfficialRegistryRecord) -> RegulatorySourceDocument:
        if self.failure is not None:
            raise self.failure
        document = self.delegate.acquire_document(record)
        if self.mismatch_metadata:
            return replace(document, act_id=f"unexpected:{document.act_id}")
        return document

    def fetch_source(self, url: str) -> bytes:
        return self.delegate.fetch_source(url)


def _official_record(
    channel: RegulatoryRegistryChannel,
    act_id: str,
    *,
    document_id: str,
    path: str,
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
        title=f"Synthetic {act_id}",
        published_at=date(2026, 9, 25),
        url=f"https://{host}/synthetic/{path}",
        document_id=document_id,
    )


def _records(*, include_unsupported: bool = False) -> tuple[OfficialRegistryRecord, ...]:
    records = (
        _official_record(
            RegulatoryRegistryChannel.ARERA_TARIFFS,
            "R-q4-workbook",
            document_id="domestic-q4.xlsx",
            path="domestic-q4.xlsx",
        ),
        _official_record(
            RegulatoryRegistryChannel.ADM_EXCISE,
            "ADM-Q4-excise",
            document_id="q4-excise.html",
            path="q4-excise",
        ),
        _official_record(
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
            "VAT-Q4-table",
            document_id="dpr-633-table.html",
            path="vat-table",
        ),
        _official_record(
            RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
            "VAT-Q4-rate",
            document_id="dpr-633-art16.html",
            path="vat-rate",
        ),
    )
    if not include_unsupported:
        return records
    return (
        *records,
        _official_record(
            RegulatoryRegistryChannel.ARERA_ACTS,
            "R-unsupported-new-layout",
            document_id="new-layout.pdf",
            path="new-layout.pdf",
        ),
    )


def _records_with_343() -> tuple[OfficialRegistryRecord, ...]:
    return (
        *(record for record in _records() if record.act_id != "R-q4-workbook"),
        OfficialRegistryRecord(
            channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
            act_id="343/2026/R/com",
            title="Delibera 343/2026/R/com",
            published_at=date(2026, 9, 29),
            effective_from=date(2026, 10, 1),
            url="https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26",
            document_id="343/2026/R/com",
        ),
    )


def _classifier(record: OfficialRegistryRecord) -> DiscoveryActFinding:
    return DiscoveryActFinding(
        channel=record.channel,
        act_id=record.act_id,
        disposition=DiscoveryActDisposition.SUPPORTED,
        rationale="fixture act has an exact versioned parser and mapping",
        rule_id="fixture-supported-layout",
        rule_version="1.0.0",
    )


class _ConfirmationParser:
    key = RegulatoryParserKey(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        document_kind="fixture_arera_343",
        layout_version="fixture-v1",
    )
    parser_id = "fixture-arera-343-confirmation"
    version = "1.0.0"

    def parse(self, source: RegulatorySourceDocument) -> RegulatoryInterpretation:
        prior_effective_from = {
            "ASOS": date(2026, 7, 1),
            "ARIM": date(2026, 1, 1),
            "UC3": date(2026, 1, 1),
            "UC6": date(2026, 1, 1),
        }
        return RegulatoryInterpretation(
            effect_assertions=tuple(
                RegulatoryEffectAssertion(
                    assertion_id=f"fixture-343:{component.lower()}",
                    component_code=component,
                    prior_effective_from=effective_from,
                    validity=NEXT_VALIDITY,
                    segments=tuple(AreraCustomerSegment),
                    quotas=tuple(BillingQuota),
                    source_id=source.source_id,
                    source_url=source.acquired.url,
                    source_sha256=source.acquired.sha256,
                    act_id=source.act_id,
                    document=source.document_id,
                    published_at=source.published_at,
                    fetched_at=source.acquired.fetched_at,
                    parser_id=self.parser_id,
                    parser_version=self.version,
                    locator=f"synthetic article 1, {component}",
                    raw_value_token="sono confermati",
                )
                for component, effective_from in prior_effective_from.items()
            )
        )


def _registry() -> RegulatoryParserRegistry:
    registry = default_regulatory_parser_registry()
    registry.register(
        _FiscalFactParser(
            document_kind="fixture_excise",
            parser_id="fixture-adm-excise",
            family=RegulatoryFactFamily.EXCISE_RATE,
            value=Decimal("0.0230"),
            unit=RateUnit.EUR_PER_KWH,
        )
    )
    registry.register(
        _FiscalFactParser(
            document_kind="fixture_vat_table",
            parser_id="fixture-vat-table",
            family=RegulatoryFactFamily.VAT_RATE,
            value=Decimal("10"),
            unit=RateUnit.PERCENT,
        )
    )
    registry.register(
        _FiscalFactParser(
            document_kind="fixture_vat_rate",
            parser_id="fixture-vat-rate",
            family=RegulatoryFactFamily.VAT_RATE,
            value=Decimal("10"),
            unit=RateUnit.PERCENT,
        )
    )
    return registry


def _service(
    as_of: date = AS_OF,
    *,
    include_unsupported: bool = False,
    include_343: bool = False,
    unavailable_candidate_source: bool = False,
) -> tuple[RegulatoryRolloverService, InMemoryRegulatoryRepository, _FixtureSourcePort]:
    now = datetime.combine(as_of, datetime.min.time(), tzinfo=UTC).replace(hour=12)
    records = (
        _records_with_343() if include_343 else _records(include_unsupported=include_unsupported)
    )
    source_port = _FixtureSourcePort(records, now)
    current = source_port.add_current_anchor_sources(load_domestic_projection_anchor())
    if unavailable_candidate_source:
        source_port.unavailable_url = records[1].url
    adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in records if record.channel == channel),
            now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    classifier = _classifier
    if include_unsupported:

        def classify_with_unknown(record: OfficialRegistryRecord) -> DiscoveryActFinding:
            if record.act_id == "R-unsupported-new-layout":
                return DiscoveryActFinding(
                    channel=record.channel,
                    act_id=record.act_id,
                    disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
                    rationale="fixture has no approved parser for the newly discovered format",
                )
            return _classifier(record)

        classifier = classify_with_unknown
    repository = InMemoryRegulatoryRepository(current, initialized_at=now)
    parser_registry = _registry()
    if include_343:
        parser_registry.register(_ConfirmationParser())
    service = RegulatoryRolloverService(
        repository,
        registry_adapters=adapters,
        source_port=source_port,
        parser_registry=parser_registry,
        classifier=classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: now,
    )
    return service, repository, source_port


def test_daily_rollover_stages_then_promotes_synthetic_successor_offline() -> None:
    service, repository, source_port = _service()

    staged = service.refresh_regulatory_state(AS_OF)

    assert staged.action == RegulatoryRolloverAction.STAGED
    assert staged.current_anchor_id == "synthetic-anchor-A"
    assert staged.current_coverage.ready
    assert staged.candidate is not None
    assert staged.candidate.anchor.validity == NEXT_VALIDITY
    assert staged.candidate_coverage is not None and staged.candidate_coverage.ready
    assert repository.read_current_anchor().anchor_id == "synthetic-anchor-A"
    assert repository.read_state().staged_candidate_id == staged.candidate_id
    assert service.source_preflight(AS_OF, staged.current_coverage).ready
    assert len(repository.read_discovery_cursors()) == len(DISCOVERY_CHANNELS)
    assert len(repository.read_discovery_snapshots()) == len(DISCOVERY_CHANNELS)

    from test_projected_service import _catalog, _history, _indexed_request

    from italian_energy.integration.projected_service import ProjectedDomesticEnergyService

    compare_service = ProjectedDomesticEnergyService(clock=lambda: CREATED_AT)
    request = _indexed_request().model_copy(update={"as_of": AS_OF})
    comparison = compare_service.compare(
        request,
        _catalog(AS_OF),
        _history(AS_OF),
        repository.read_current_anchor(),
        staged.current_coverage,
    )
    assert comparison.assumptions.future_values_verified is False
    assert comparison.verified_inputs.regulatory_coverage_id == staged.current_coverage.evidence_id

    staged_rerun = service.refresh_regulatory_state(AS_OF)
    assert staged_rerun.action == RegulatoryRolloverAction.STAGED
    assert repository.read_state().staged_candidate_id == staged.candidate_id
    assert len(repository.events()) == 1
    next_now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    next_records = _records()
    next_adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in next_records if record.channel == channel),
            next_now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    next_service = RegulatoryRolloverService(
        repository,
        registry_adapters=next_adapters,
        source_port=source_port,
        parser_registry=_registry(),
        classifier=_classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: next_now,
    )
    promoted = next_service.refresh_regulatory_state(
        NEXT_DAY,
        previous_cursors=staged.cursor_updates,
        previous_snapshots=staged.discovery.snapshots,
    )

    assert promoted.action == RegulatoryRolloverAction.PROMOTED
    assert promoted.current_coverage.ready
    assert repository.read_current_anchor().validity == NEXT_VALIDITY
    assert repository.read_state().staged_candidate_id is None
    reads_before_preflight = source_port.fetch_count
    assert next_service.source_preflight(NEXT_DAY, promoted.current_coverage).ready
    assert (
        next_service.resolve_active(NEXT_DAY, promoted.current_coverage)
        == repository.read_current_anchor()
    )
    assert source_port.fetch_count == reads_before_preflight
    assert len(repository.events()) == 2

    rerun = next_service.refresh_regulatory_state(NEXT_DAY)
    assert rerun.action == RegulatoryRolloverAction.PREPARATION_NOT_REQUIRED
    assert repository.read_current_anchor().anchor_id == promoted.current_anchor_id
    assert len(repository.events()) == 2


def test_daily_rollover_binds_parser_confirmations_to_explicit_prior_values() -> None:
    service, repository, source_port = _service(include_343=True)

    report = service.refresh_regulatory_state(AS_OF)

    assert report.action == RegulatoryRolloverAction.STAGED
    assert report.candidate is not None
    current = load_domestic_projection_anchor()
    prior_values = {
        (item.segment, item.component_code, item.quota): item.value for item in current.charges
    }
    candidate_values = {
        (item.segment, item.component_code, item.quota): item.value
        for item in report.candidate.anchor.charges
    }
    assert candidate_values == prior_values
    confirmations = tuple(
        fact for fact in report.candidate.facts if fact.effect.kind.value == "confirm_value"
    )
    assert confirmations
    assert all(fact.effect.previous_anchor_id == "synthetic-anchor-A" for fact in confirmations)
    assert all(fact.effect.previous_value == fact.value for fact in confirmations)
    assert all(fact.act_id == "343/2026/R/com" for fact in confirmations)
    assert report.candidate_coverage is not None and report.candidate_coverage.ready
    assert report.current_coverage.ready
    assert service.source_preflight(AS_OF, report.current_coverage).ready
    assert repository.read_state().staged_candidate_id == report.candidate_id

    service._clock = lambda: datetime(2026, 10, 1, 12, tzinfo=UTC)
    reads_before_preflight = source_port.fetch_count
    promoted = service.refresh_regulatory_state(NEXT_DAY)
    assert promoted.action == RegulatoryRolloverAction.PROMOTED
    assert promoted.current_coverage.ready
    assert repository.read_current_anchor().validity == NEXT_VALIDITY
    assert service.source_preflight(NEXT_DAY, promoted.current_coverage).ready
    assert source_port.fetch_count > reads_before_preflight
    reads_after_refresh = source_port.fetch_count
    assert service.source_preflight(NEXT_DAY, promoted.current_coverage).ready
    assert source_port.fetch_count == reads_after_refresh


def test_live_source_fetches_precede_candidate_creation_timestamp() -> None:
    service, _, source_port = _service(include_343=True)
    started_at = source_port.now
    fetched_at = started_at + timedelta(minutes=1)
    for act_id, document in tuple(source_port._documents.items()):
        source_port._documents[act_id] = replace(
            document,
            acquired=replace(document.acquired, fetched_at=fetched_at),
        )
    timestamps = iter(
        (
            started_at,
            fetched_at + timedelta(minutes=1),
            fetched_at + timedelta(minutes=2),
            fetched_at + timedelta(minutes=3),
        )
    )
    service._clock = lambda: next(timestamps, fetched_at + timedelta(minutes=4))

    report = service.refresh_regulatory_state(AS_OF)

    assert report.action == RegulatoryRolloverAction.STAGED
    assert report.candidate is not None
    assert report.candidate.created_at >= fetched_at
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY not in report.reason_codes


def test_unsupported_new_act_blocks_staging_and_expired_anchor_readiness() -> None:
    service, repository, _ = _service(include_unsupported=True)

    result = service.refresh_regulatory_state(AS_OF)

    assert result.action == RegulatoryRolloverAction.REVIEW_REQUIRED
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in result.reason_codes
    assert repository.read_state().staged_candidate_id is None
    assert result.candidate_coverage is not None and not result.candidate_coverage.ready

    expired_service = RegulatoryRolloverService(
        repository,
        clock=lambda: datetime(2026, 10, 1, 12, tzinfo=UTC),
        policy=RolloverPolicy(prepare_lead_days=30),
    )
    expired = expired_service.refresh_regulatory_state(NEXT_DAY)
    assert expired.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.NEXT_ANCHOR_MISSING in expired.reason_codes
    assert not expired_service.source_preflight(NEXT_DAY, expired.current_coverage).ready
    assert not expired.current_coverage.ready


def test_late_recovery_promotes_only_after_complete_gap_discovery() -> None:
    recovery_date = date(2026, 10, 4)
    recovery_time = datetime(2026, 10, 4, 12, tzinfo=UTC)
    service, repository, _ = _service(recovery_date)

    report = service.refresh_regulatory_state(recovery_date)

    assert report.action == RegulatoryRolloverAction.PROMOTED
    assert report.current_coverage.ready
    assert report.promotion_outcome is not None
    assert report.current_coverage.checked_at == recovery_time
    assert repository.read_current_anchor().validity == NEXT_VALIDITY
    assert repository.read_state().staged_candidate_id is None
    assert tuple(event.kind.value for event in repository.events()) == (
        "candidate_staged",
        "anchor_promoted",
    )

    _, expired_repository, _ = _service(recovery_date)
    incomplete = RegulatoryRolloverService(
        expired_repository,
        clock=lambda: recovery_time,
        policy=RolloverPolicy(prepare_lead_days=30),
    )
    blocked = incomplete.refresh_regulatory_state(recovery_date)
    assert blocked.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.CURRENT_ANCHOR_EXPIRED in blocked.reason_codes
    assert RegulatoryRolloverReason.NEXT_ANCHOR_MISSING in blocked.reason_codes
    assert expired_repository.read_current_anchor().anchor_id == "synthetic-anchor-A"


def test_temporary_candidate_source_outage_is_infrastructure_failure() -> None:
    service, repository, source_port = _service(unavailable_candidate_source=True)
    unavailable_url = source_port.unavailable_url

    result = service.refresh_regulatory_state(AS_OF)

    assert result.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in result.reason_codes
    assert RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY not in result.reason_codes
    assert repository.read_state().staged_candidate_id is None
    assert unavailable_url is not None


def test_staged_candidate_survives_temporary_outage_and_is_revoked_on_digest_change() -> None:
    service, repository, source_port = _service()
    staged = service.refresh_regulatory_state(AS_OF)
    assert staged.candidate is not None
    assert repository.read_state().staged_candidate_id == staged.candidate.candidate_id

    staged_source = staged.candidate.anchor.sources[0]
    source_port.unavailable_url = staged_source.url
    transient = service.refresh_regulatory_state(
        AS_OF,
        previous_cursors=staged.cursor_updates,
        previous_snapshots=staged.discovery.snapshots,
    )
    assert transient.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in transient.reason_codes
    assert repository.read_state().staged_candidate_id == staged.candidate.candidate_id

    source_port.unavailable_url = None
    source_port._bodies_by_url[staged_source.url] = b"changed after staging"
    changed = service.refresh_regulatory_state(
        AS_OF,
        previous_cursors=staged.cursor_updates,
        previous_snapshots=staged.discovery.snapshots,
    )
    assert changed.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in changed.reason_codes
    assert repository.read_state().staged_candidate_id is None


def test_source_preflight_rejects_missing_mismatched_and_stale_evidence_offline() -> None:
    service, repository, source_port = _service()
    report = service.refresh_regulatory_state(AS_OF)
    assert report.current_coverage.ready
    fetch_count = source_port.fetch_count

    missing = service.source_preflight(AS_OF, None)
    wrong_anchor = report.current_coverage.model_copy(update={"anchor_id": "other-anchor"})
    mismatched = service.source_preflight(AS_OF, wrong_anchor)
    old = report.current_coverage.model_copy(
        update={"checked_at": datetime(2026, 9, 1, 12, tzinfo=UTC)}
    )
    stale = service.source_preflight(AS_OF, old)
    future = report.current_coverage.model_copy(
        update={"checked_at": datetime(2026, 10, 1, 12, tzinfo=UTC)}
    )
    future_result = service.source_preflight(AS_OF, future)

    assert not missing.ready
    assert not mismatched.ready
    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in mismatched.reason_codes
    assert not stale.ready and not future_result.ready
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in stale.reason_codes
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in future_result.reason_codes
    assert source_port.fetch_count == fetch_count
    assert repository.read_current_anchor().anchor_id == "synthetic-anchor-A"
    assert service.resolve_active(AS_OF, None) is None


def test_service_rejects_naive_or_wrong_civil_clock() -> None:
    service, repository, _ = _service()
    naive = RegulatoryRolloverService(
        repository,
        clock=lambda: datetime(2026, 9, 30, 12),
    )
    wrong_day = RegulatoryRolloverService(
        repository,
        clock=lambda: datetime(2026, 10, 1, 1, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="timezone-aware"):
        naive.refresh_regulatory_state(AS_OF)
    with pytest.raises(ValueError, match="Europe/Rome"):
        wrong_day.refresh_regulatory_state(AS_OF)
    assert service


def test_staged_unknown_act_can_clear_current_coverage_with_digest_bound_review() -> None:
    service, repository, _ = _service(include_unsupported=True)
    report = service.refresh_regulatory_state(AS_OF)
    assert report.candidate is not None
    assert not report.current_coverage.ready
    record = next(
        item
        for snapshot in report.discovery.snapshots
        for item in snapshot.records
        if item.act_id == "R-unsupported-new-layout"
    )
    review = RegulatoryManualReview(
        channel=record.channel,
        act_id=record.act_id,
        source_url=record.url,
        source_sha256="a" * 64,
        scope=CURRENT_VALIDITY,
        outcome=RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE,
        reviewer="operator-fixture",
        reviewed_at=CREATED_AT,
        rationale="Synthetic review establishes that this act is outside the anchor scope.",
        rule_id="synthetic-scope-rule",
        rule_version="1.0.0",
    )
    review_check = RegulatoryReviewSourceCheck(
        review_id=review.decision_id,
        expected_sha256=review.source_sha256,
        observed_sha256=review.source_sha256,
        checked_at=CREATED_AT,
    )
    reviewed = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts,
        reviews=(review,),
        review_source_checks=(review_check,),
    )

    assert reviewed.ready
    assert reviewed.review_ids == (review.decision_id,)


def test_changed_registry_record_requires_a_review_bound_to_current_scope() -> None:
    service, repository, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    change = DiscoveryRecordChange(
        channel=RegulatoryRegistryChannel.ARERA_ACTS,
        act_id="R-amended-current-scope",
        kind=DiscoveryChangeKind.CHANGED,
        previous_sha256="a" * 64,
        observed_sha256="b" * 64,
    )
    changed_discovery = report.discovery.model_copy(update={"changes": (change,)})
    without_review = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=changed_discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
    )
    review = RegulatoryManualReview(
        channel=change.channel,
        act_id=change.act_id,
        source_url=f"https://www.arera.it/atti-e-provvedimenti/{change.act_id}",
        source_sha256="b" * 64,
        scope=CURRENT_VALIDITY,
        outcome=RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE,
        reviewer="operator-fixture",
        reviewed_at=CREATED_AT,
        rationale="The changed synthetic act is outside the covered profile.",
        rule_id="synthetic-scope-rule",
        rule_version="1.0.0",
    )
    check = RegulatoryReviewSourceCheck(
        review_id=review.decision_id,
        expected_sha256=review.source_sha256,
        observed_sha256=review.source_sha256,
        checked_at=CREATED_AT,
    )
    with_review = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=changed_discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
        reviews=(review,),
        review_source_checks=(check,),
    )

    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in without_review.reason_codes
    assert with_review.ready


def test_rollover_skips_early_preparation_when_anchor_is_not_near_expiry() -> None:
    _, repository, source_port = _service()
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    anchor_payload = repository.read_current_anchor().model_dump(mode="python")
    anchor_payload["validity"] = DatePeriod(start=date(2026, 7, 1), end=date(2026, 12, 1))
    extended_anchor = DomesticProjectionAnchor.model_validate(anchor_payload)
    repository = InMemoryRegulatoryRepository(extended_anchor, initialized_at=now)
    no_new_acts = tuple(_DailyIndexAdapter(channel, (), now) for channel in DISCOVERY_CHANNELS)
    service = RegulatoryRolloverService(
        repository,
        registry_adapters=no_new_acts,
        source_port=source_port,
        parser_registry=_registry(),
        classifier=_classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: now,
    )

    report = service.refresh_regulatory_state(AS_OF)

    assert report.action == RegulatoryRolloverAction.PREPARATION_NOT_REQUIRED
    assert report.days_to_expiry == 62
    assert report.current_coverage.ready


def test_unregistered_format_is_a_parser_failure_and_blocks_candidate_build() -> None:
    _, repository, source_port = _service(include_unsupported=True)
    records = _records(include_unsupported=True)
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in records if record.channel == channel),
            now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    parser_failing = RegulatoryRolloverService(
        repository,
        registry_adapters=adapters,
        source_port=source_port,
        parser_registry=_registry(),
        classifier=_classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: now,
    )

    result = parser_failing.refresh_regulatory_state(AS_OF)

    assert result.action == RegulatoryRolloverAction.REVIEW_REQUIRED
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in result.reason_codes
    assert result.candidate is None


def test_parser_acquisition_boundary_classifies_missing_and_bad_source_documents() -> None:
    service, _, source_port = _service()
    report = service.refresh_regulatory_state(AS_OF)
    assert report.candidate is not None
    records_by_key = {
        (record.channel, record.act_id): record
        for snapshot in report.discovery.snapshots
        for record in snapshot.records
    }

    embedded_records, embedded_assertions, embedded_reasons = service._parse_supported_records(
        report.discovery, {}
    )
    assert embedded_records
    assert embedded_assertions == ()
    assert embedded_reasons == ()

    legacy_findings = tuple(
        finding.model_copy(update={"source_record": None}) for finding in report.discovery.findings
    )
    legacy_discovery = report.discovery.model_copy(update={"findings": legacy_findings})
    missing_records, missing_assertions, missing_reasons = service._parse_supported_records(
        legacy_discovery, {}
    )
    assert missing_records == ()
    assert missing_assertions == ()
    assert missing_reasons == (RegulatoryRolloverReason.INCOMPLETE_COVERAGE,)

    service._source_port = None
    no_source_facts, no_source_assertions, no_source_reasons = service._parse_supported_records(
        report.discovery, records_by_key
    )
    assert no_source_facts == ()
    assert no_source_assertions == ()
    assert no_source_reasons == (RegulatoryRolloverReason.SOURCE_UNAVAILABLE,)

    service._source_port = _AcquisitionFaultPort(
        source_port, failure=TypeError("invalid transport response")
    )
    _, _, type_reasons = service._parse_supported_records(report.discovery, records_by_key)
    assert type_reasons == (RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,)

    service._source_port = _AcquisitionFaultPort(source_port, mismatch_metadata=True)
    _, _, mismatch_reasons = service._parse_supported_records(report.discovery, records_by_key)
    assert mismatch_reasons == (RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,)


def test_parser_registry_unknown_document_and_duplicate_fact_conflict_fail_closed() -> None:
    service, _, source_port = _service()
    report = service.refresh_regulatory_state(AS_OF)
    records_by_key = {
        (record.channel, record.act_id): record
        for snapshot in report.discovery.snapshots
        for record in snapshot.records
    }

    class _UnknownDocumentPort:
        def acquire_document(self, record: OfficialRegistryRecord) -> RegulatorySourceDocument:
            return replace(
                source_port.acquire_document(record),
                document_kind="not-registered",
            )

        def fetch_source(self, url: str) -> bytes:
            return source_port.fetch_source(url)

    service._source_port = _UnknownDocumentPort()
    _, _, parser_reasons = service._parse_supported_records(report.discovery, records_by_key)
    assert RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE in parser_reasons

    class _ConflictingParser:
        key = RegulatoryParserKey(
            channel=RegulatoryRegistryChannel.ADM_EXCISE,
            document_kind="fixture_excise",
            layout_version="fixture-v1",
        )
        parser_id = "fixture-conflicting-excise"
        version = "1.0.0"

        def parse(self, source: RegulatorySourceDocument) -> tuple[RegulatoryFact, ...]:
            fact = _FiscalFactParser(
                document_kind="fixture_excise",
                parser_id="fixture-conflicting-excise",
                family=RegulatoryFactFamily.EXCISE_RATE,
                value=Decimal("0.0230"),
                unit=RateUnit.EUR_PER_KWH,
            ).parse(source)[0]
            return (fact, fact.model_copy(update={"value": Decimal("0.0240")}))

    registry = default_regulatory_parser_registry()
    registry.register(_ConflictingParser())
    service._source_port = source_port
    service._parser_registry = registry
    _, _, conflict_reasons = service._parse_supported_records(report.discovery, records_by_key)
    assert RegulatoryRolloverReason.DETERMINISM_VIOLATION in conflict_reasons


def test_candidate_builder_reports_empty_facts_and_review_interval_failures() -> None:
    service, repository, _ = _service()
    with pytest.raises(ValueError, match="no normalized facts"):
        service._build_candidate(
            repository.read_current_anchor(),
            AS_OF,
            CREATED_AT,
            (),
            (),
            allow_late_recovery=False,
        )


def test_candidate_without_supported_facts_records_incomplete_attempt() -> None:
    _, repository, _ = _service()
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    no_registry = RegulatoryRolloverService(repository, clock=lambda: now)

    result = no_registry.refresh_regulatory_state(AS_OF)

    assert result.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in result.reason_codes
    assert result.attempt_id is not None
    assert repository.attempt_history(result.attempt_id)


def test_no_source_port_fails_closed_before_candidate_construction() -> None:
    _, repository, _ = _service()
    records = _records()
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in records if record.channel == channel),
            now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    service = RegulatoryRolloverService(
        repository,
        registry_adapters=adapters,
        parser_registry=_registry(),
        classifier=_classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: now,
    )

    report = service.refresh_regulatory_state(AS_OF)

    assert report.action == RegulatoryRolloverAction.BLOCKED
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in report.reason_codes
    assert report.candidate is None


def test_attempt_failure_classification_is_fail_closed() -> None:
    assert RegulatoryRolloverService._failure_status(()) == RolloverAttemptStatus.PREPARING
    assert (
        RegulatoryRolloverService._failure_status(
            (RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,)
        )
        == RolloverAttemptStatus.REVIEW_REQUIRED
    )
    assert (
        RegulatoryRolloverService._failure_status((RegulatoryRolloverReason.DETERMINISM_VIOLATION,))
        == RolloverAttemptStatus.REJECTED
    )
    assert RegulatoryRolloverService._permanent_staged_failure(()) is False
    assert RegulatoryRolloverService._permanent_staged_failure(
        (RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,)
    )
    assert RegulatoryRolloverService._blocked_action(()) == RegulatoryRolloverAction.BLOCKED
    assert (
        RegulatoryRolloverService._blocked_action(
            (RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,)
        )
        == RegulatoryRolloverAction.REVIEW_REQUIRED
    )


@pytest.mark.parametrize(
    ("failure", "expected_reason"),
    (
        (OSError("temporary transport outage"), RegulatoryRolloverReason.SOURCE_UNAVAILABLE),
        (
            DiscoveryFailure(RegulatoryRolloverReason.SOURCE_UNAVAILABLE),
            RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
        ),
        (
            ValueError("source metadata was invalid"),
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
    ),
)
def test_acquisition_exceptions_keep_transport_and_integrity_failures_distinct(
    failure: Exception, expected_reason: RegulatoryRolloverReason
) -> None:
    _, repository, source_port = _service()
    records = _records()
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in records if record.channel == channel),
            now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    service = RegulatoryRolloverService(
        repository,
        registry_adapters=adapters,
        source_port=_AcquisitionFaultPort(source_port, failure=failure),
        parser_registry=_registry(),
        classifier=_classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: now,
    )

    result = service.refresh_regulatory_state(AS_OF)

    assert result.action == RegulatoryRolloverAction.BLOCKED
    assert expected_reason in result.reason_codes
    assert result.candidate is None


def test_acquired_document_metadata_must_match_registry_record() -> None:
    _, repository, source_port = _service()
    records = _records()
    now = datetime(2026, 9, 30, 12, tzinfo=UTC)
    adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in records if record.channel == channel),
            now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    service = RegulatoryRolloverService(
        repository,
        registry_adapters=adapters,
        source_port=_AcquisitionFaultPort(source_port, mismatch_metadata=True),
        parser_registry=_registry(),
        classifier=_classifier,
        policy=RolloverPolicy(prepare_lead_days=30),
        clock=lambda: now,
    )

    result = service.refresh_regulatory_state(AS_OF)

    assert RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY in result.reason_codes
    assert result.candidate is None


def test_supported_new_act_requires_facts_and_matching_current_source_digest() -> None:
    service, repository, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    assert report.candidate is not None
    anchor = repository.read_current_anchor()

    missing_facts = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=(),
    )
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in missing_facts.reason_codes

    current_source = anchor.sources[0]
    assert current_source.sha256 is not None
    overlapping_fact = report.candidate.facts[0].model_copy(
        update={
            "validity": DatePeriod(start=date(2026, 9, 15), end=date(2026, 10, 15)),
            "source_id": current_source.source_id,
            "source_sha256": "f" * 64,
        }
    )
    ambiguous = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=(overlapping_fact,),
    )
    assert RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY in ambiguous.reason_codes


def test_rollover_report_and_preflight_models_reject_mismatched_contracts() -> None:
    service, _, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    report_payload = report.model_dump(mode="python")
    report_payload["candidate_id"] = "wrong-candidate"

    with pytest.raises(ValidationError, match="candidate ID must match"):
        RegulatoryRolloverReport.model_validate(report_payload)

    preflight = service.source_preflight(AS_OF, report.current_coverage)
    preflight_payload = preflight.model_dump(mode="python")
    preflight_payload["ready"] = not preflight.ready
    with pytest.raises(ValidationError, match="readiness must match"):
        RegulatorySourcePreflightResult.model_validate(preflight_payload)

    bad_coverage = report.current_coverage.model_copy(update={"as_of": NEXT_DAY})
    bad_payload = report.model_dump(mode="python")
    bad_payload["current_coverage"] = bad_coverage.model_dump(mode="python")
    with pytest.raises(ValueError, match="current coverage must match"):
        RegulatoryRolloverReport.model_validate(bad_payload)

    next_now = datetime(2026, 10, 1, 12, tzinfo=UTC)
    next_records = _records()
    next_adapters = tuple(
        _DailyIndexAdapter(
            channel,
            tuple(record for record in next_records if record.channel == channel),
            next_now,
        )
        for channel in DISCOVERY_CHANNELS
    )
    next_discovery = discover_regulatory_sources(
        next_adapters,
        DatePeriod(start=CURRENT_VALIDITY.start, end=NEXT_DAY + timedelta(days=1)),
        next_now,
        classifier=_classifier,
    )
    bad_payload = report.model_dump(mode="python")
    bad_payload["discovery"] = next_discovery.model_dump(mode="python")
    with pytest.raises(ValueError, match="discovery must match"):
        RegulatoryRolloverReport.model_validate(bad_payload)

    assert report.candidate_coverage is not None
    bad_candidate_coverage = report.candidate_coverage.model_copy(
        update={"candidate_id": "another-candidate"}
    )
    bad_payload = report.model_dump(mode="python")
    bad_payload["candidate_coverage"] = bad_candidate_coverage.model_dump(mode="python")
    with pytest.raises(ValueError, match="coverage must match its candidate"):
        RegulatoryRolloverReport.model_validate(bad_payload)

    duplicate_reasons = report.model_dump(mode="python")
    duplicate_reasons["reason_codes"] = [
        RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
        RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
    ]
    with pytest.raises(ValueError, match="reasons must be unique"):
        RegulatoryRolloverReport.model_validate(duplicate_reasons)


def test_current_coverage_evidence_requires_canonical_digest_bound_checks() -> None:
    service, _, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    evidence = report.current_coverage
    assert evidence.comparison_as_of == AS_OF
    assert evidence.evidence_id.startswith("regulatory-anchor-coverage:")
    assert evidence.evidence_id == evidence.evidence_id

    with pytest.raises(ValidationError, match="timezone-aware"):
        RegulatoryAnchorSourceCheck(
            source_id="synthetic-source",
            expected_sha256="a" * 64,
            checked_at=datetime(2026, 9, 30),
        )

    payload = evidence.model_dump(mode="python")
    payload["source_checks"] = [*payload["source_checks"], payload["source_checks"][0]]
    with pytest.raises(ValidationError, match="unique source IDs"):
        RegulatoryAnchorCoverageEvidence.model_validate(payload)

    payload = evidence.model_dump(mode="python")
    payload["ready"] = False
    with pytest.raises(ValidationError, match="readiness must match"):
        RegulatoryAnchorCoverageEvidence.model_validate(payload)

    duplicate_reasons = evidence.model_dump(mode="python")
    duplicate_reasons["ready"] = False
    duplicate_reasons["reason_codes"] = [
        RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
        RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
    ]
    with pytest.raises(ValueError, match="reason codes must be unique"):
        RegulatoryAnchorCoverageEvidence.model_validate(duplicate_reasons)


@pytest.mark.parametrize(
    ("check_update", "expected_reason"),
    (
        ({"expected_sha256": "c" * 64}, RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY),
        ({"observed_sha256": None}, RegulatoryRolloverReason.SOURCE_UNAVAILABLE),
        (
            {"observed_sha256": "d" * 64},
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            {"checked_at": datetime(2026, 9, 1, 12, tzinfo=UTC)},
            RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE,
        ),
    ),
)
def test_current_anchor_source_observation_digest_and_age_are_verified(
    check_update: dict[str, object], expected_reason: RegulatoryRolloverReason
) -> None:
    service, repository, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    first = report.current_coverage.source_checks[0]
    changed = first.model_copy(update=check_update)
    result = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=report.discovery,
        source_checks=(changed, *report.current_coverage.source_checks[1:]),
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
    )

    assert expected_reason in result.reason_codes


def test_current_anchor_coverage_rejects_stale_scan_and_nonverified_anchor() -> None:
    service, repository, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    anchor = repository.read_current_anchor()
    not_verified = anchor.model_copy(update={"status": VerificationStatus.REVIEW_REQUIRED})
    incomplete_snapshot = report.discovery.snapshots[0].model_copy(
        update={
            "complete": False,
            "next_cursor": None,
            "reason_code": RegulatoryRolloverReason.SOURCE_UNAVAILABLE,
        }
    )
    stale_discovery = report.discovery.model_copy(
        update={
            "snapshots": (incomplete_snapshot, *report.discovery.snapshots[1:]),
        }
    )
    not_verified_result = verify_regulatory_anchor_coverage(
        anchor=not_verified,
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
    )
    incomplete = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=stale_discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
    )
    stale_date = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=NEXT_DAY,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
    )

    assert RegulatoryRolloverReason.CANDIDATE_VALIDATION_FAILED in not_verified_result.reason_codes
    assert RegulatoryRolloverReason.SOURCE_UNAVAILABLE in incomplete.reason_codes
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in stale_date.reason_codes


def test_current_coverage_requires_full_fresh_source_and_registry_evidence() -> None:
    service, repository, _ = _service()
    report = service.refresh_regulatory_state(AS_OF)
    anchor = repository.read_current_anchor()
    facts = report.candidate.facts if report.candidate else ()

    missing_sources = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=report.discovery,
        source_checks=(),
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=facts,
    )
    stale_snapshot = report.discovery.snapshots[0].model_copy(
        update={"discovered_at": datetime(2026, 9, 1, 12, tzinfo=UTC)}
    )
    stale_discovery = report.discovery.model_copy(
        update={"snapshots": (stale_snapshot, *report.discovery.snapshots[1:])}
    )
    stale_scan = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=stale_discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=facts,
    )
    irrelevant_findings = tuple(
        finding.model_copy(
            update={
                "disposition": DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
                "rationale": "Synthetic profile rule excludes this act.",
                "rule_id": "fixture-exclusion",
                "rule_version": "1.0.0",
            }
        )
        for finding in report.discovery.findings
    )
    irrelevant_discovery = report.discovery.model_copy(update={"findings": irrelevant_findings})
    irrelevant_result = verify_regulatory_anchor_coverage(
        anchor=anchor,
        discovery=irrelevant_discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=facts,
    )

    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in missing_sources.reason_codes
    assert RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE in stale_scan.reason_codes
    assert irrelevant_result.ready


@pytest.mark.parametrize(
    ("check_update", "expected_reason"),
    (
        ({"expected_sha256": "c" * 64}, RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY),
        ({"observed_sha256": None}, RegulatoryRolloverReason.SOURCE_UNAVAILABLE),
        (
            {"observed_sha256": "d" * 64},
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            {"checked_at": datetime(2026, 9, 1, 12, tzinfo=UTC)},
            RegulatoryRolloverReason.STALE_COVERAGE_EVIDENCE,
        ),
    ),
)
def test_current_review_digest_and_freshness_checks_fail_closed(
    check_update: dict[str, object], expected_reason: RegulatoryRolloverReason
) -> None:
    service, repository, _ = _service(include_unsupported=True)
    report = service.refresh_regulatory_state(AS_OF)
    record = next(
        item
        for snapshot in report.discovery.snapshots
        for item in snapshot.records
        if item.act_id == "R-unsupported-new-layout"
    )
    review = RegulatoryManualReview(
        channel=record.channel,
        act_id=record.act_id,
        source_url=record.url,
        source_sha256="a" * 64,
        scope=CURRENT_VALIDITY,
        outcome=RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE,
        reviewer="operator-fixture",
        reviewed_at=CREATED_AT,
        rationale="The act does not apply to the synthetic current anchor.",
        rule_id="synthetic-scope-rule",
        rule_version="1.0.0",
    )
    source_check = RegulatoryReviewSourceCheck(
        review_id=review.decision_id,
        expected_sha256=review.source_sha256,
        observed_sha256=review.source_sha256,
        checked_at=CREATED_AT,
    ).model_copy(update=check_update)
    result = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=report.candidate.facts if report.candidate else (),
        reviews=(review,),
        review_source_checks=(source_check,),
    )

    assert expected_reason in result.reason_codes


def test_current_coverage_requires_review_source_check_and_rejects_duplicates() -> None:
    service, repository, _ = _service(include_unsupported=True)
    report = service.refresh_regulatory_state(AS_OF)
    record = next(
        item
        for snapshot in report.discovery.snapshots
        for item in snapshot.records
        if item.act_id == "R-unsupported-new-layout"
    )
    review = RegulatoryManualReview(
        channel=record.channel,
        act_id=record.act_id,
        source_url=record.url,
        source_sha256="a" * 64,
        scope=CURRENT_VALIDITY,
        outcome=RegulatoryReviewOutcome.IRRELEVANT_BY_VERSIONED_RULE,
        reviewer="operator-fixture",
        reviewed_at=CREATED_AT,
        rationale="The act does not apply to the synthetic current anchor.",
        rule_id="synthetic-scope-rule",
        rule_version="1.0.0",
    )
    facts = report.candidate.facts if report.candidate else ()
    missing = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=facts,
        reviews=(review,),
    )
    duplicate_review = review.model_copy(update={"rationale": "Second synthetic decision."})
    duplicated = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=report.discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=facts,
        reviews=(review, duplicate_review),
    )
    incomplete_snapshot = report.discovery.snapshots[0].model_copy(
        update={"complete": False, "next_cursor": None, "reason_code": None}
    )
    incomplete_discovery = report.discovery.model_copy(
        update={
            "snapshots": (incomplete_snapshot, *report.discovery.snapshots[1:]),
        }
    )
    incomplete = verify_regulatory_anchor_coverage(
        anchor=repository.read_current_anchor(),
        discovery=incomplete_discovery,
        source_checks=report.current_coverage.source_checks,
        as_of=AS_OF,
        checked_at=CREATED_AT,
        facts=facts,
    )

    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in missing.reason_codes
    assert RegulatoryRolloverReason.MAPPING_FAILURE in duplicated.reason_codes
    assert RegulatoryRolloverReason.INCOMPLETE_COVERAGE in incomplete.reason_codes
    with pytest.raises(ValueError, match="timezone-aware"):
        verify_regulatory_anchor_coverage(
            anchor=repository.read_current_anchor(),
            discovery=report.discovery,
            source_checks=report.current_coverage.source_checks,
            as_of=AS_OF,
            checked_at=datetime(2026, 9, 30),
        )
