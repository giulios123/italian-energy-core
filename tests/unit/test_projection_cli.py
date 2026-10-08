import hashlib
import json
import urllib.error
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib import request as urllib_request

import pytest
from test_integration import _portal_result
from test_projected_contract import AS_OF
from test_projected_service import _catalog, _coverage, _history, _indexed_request

from italian_energy.arera.projection import load_domestic_projection_anchor
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.integration import (
    RegulatoryAnchorRefreshResult,
    dump_envelope,
    load_envelope,
    projection_cli,
)
from italian_energy.integration.errors import CoreContractError, CoreErrorCode
from italian_energy.integration.projected import GmeDefinitionCheck, ProjectedSourceBundle
from italian_energy.integration.projected_service import ProjectedDomesticEnergyService
from italian_energy.market.gme import (
    GME_INDEX_DEFINITION_SHA256,
    GmeBandReportSnapshot,
    GmeImportError,
    parse_monthly_band_report_text,
)


def _band_report(period_start: date = date(2026, 8, 1)) -> GmeBandReportSnapshot:
    fixtures = {
        date(2026, 7, 1): ("Luglio", (253, 179, 312), ("154,20", "169,38", "152,26")),
        date(2026, 8, 1): ("Agosto", (231, 169, 344), ("174,52", "204,35", "171,72")),
    }
    month_name, hours, values = fixtures[period_start]
    period = DatePeriod(start=period_start, end=date(2026, period_start.month + 1, 1))
    parsed = parse_monthly_band_report_text(
        "Prezzo medio di acquisto per fasce orarie* €/MWh "
        "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
        "*come definite dalla delibera dell'ARERA n°181 del 2006 "
        f"{month_name} 2026 "
        f"({hours[0]} ore) {values[0]} ({hours[1]} ore) {values[1]} "
        f"({hours[2]} ore) {values[2]}",
        period_start,
    )
    raw_digest = hashlib.sha256(b"verified band report fixture").hexdigest()
    date_stamp = "20260803" if period_start.month == 7 else "20260902"
    url_month = "Luglio" if period_start.month == 7 else "Agosto"
    url = f"https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/{date_stamp}Prezzomedioperfasce{url_month}2026.pdf"
    provenance = tuple(
        Provenance(
            source="GME",
            source_identifier=f"band:{price.band}",
            retrieved_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            effective_period=period,
            sha256=raw_digest,
            url=url,
            locator=ProvenanceLocator(document="band-report.pdf", section=price.band),
        )
        for price in parsed.prices
    )
    return GmeBandReportSnapshot(
        parsed=parsed, status=VerificationStatus.VERIFIED, provenance=provenance
    )


def test_anchor_live_digest_check_compares_pinned_and_unpinned_sources() -> None:
    anchor = load_domestic_projection_anchor()
    contents = {item.url: item.source_id.encode() for item in anchor.sources}
    pinned_sources = tuple(
        source.model_copy(update={"sha256": hashlib.sha256(contents[source.url]).hexdigest()})
        for source in anchor.sources
    )
    test_anchor = anchor.model_copy(update={"sources": pinned_sources})
    checks = projection_cli.verify_anchor_sources(test_anchor, lambda url: contents[url])

    assert len(checks) == len(anchor.sources)
    assert all(item["digest_matches"] is True for item in checks)
    assert all(item["digest_pinned"] is True for item in checks)
    mismatch = projection_cli.verify_anchor_sources(test_anchor, lambda _url: b"changed source")
    assert all(item["digest_matches"] is False for item in mismatch)
    unpinned = test_anchor.model_copy(
        update={
            "sources": (
                test_anchor.sources[0].model_copy(update={"sha256": None}),
                *test_anchor.sources[1:],
            )
        }
    )
    unpinned_checks = projection_cli.verify_anchor_sources(unpinned, lambda url: contents[url])
    assert unpinned_checks[0]["digest_pinned"] is False
    assert unpinned_checks[0]["digest_matches"] is True


def test_gme_definition_check_pins_the_official_mapping_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = b"the exact official GME definition document"
    digest = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(projection_cli, "GME_INDEX_DEFINITION_SHA256", digest)
    result = projection_cli.verify_gme_definition_source(lambda _url: content)

    assert result["source_identifier"] == "DTF 25 MPE"
    assert result["digest_matches"] is True


def test_source_verifiers_preserve_acquisition_failures() -> None:
    anchor = load_domestic_projection_anchor()
    checks = projection_cli.verify_anchor_sources(
        anchor, lambda _url: (_ for _ in ()).throw(ValueError("connection timed out"))
    )
    assert len(checks) == len(anchor.sources)
    assert all(item["digest_matches"] is False for item in checks)
    assert all(item["acquisition_error"] == "connection timed out" for item in checks)

    definition = projection_cli.verify_gme_definition_source(
        lambda _url: (_ for _ in ()).throw(ValueError("source unavailable"))
    )
    assert definition["source_identifier"] == "DTF 25 MPE"
    assert definition["digest_matches"] is False
    assert definition["acquisition_error"] == "source unavailable"


def test_official_source_fetch_is_allowlisted_bounded_and_redirect_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="allowlisted official HTTPS host"):
        projection_cli._fetch_official_source("http://example.com/source.pdf")

    class Response:
        def __init__(self, url: str, content: bytes) -> None:
            self.url = url
            self.content = content

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return self.url

        def read(self, _size: int) -> bytes:
            return self.content

    source = "https://arera.it/source.pdf"
    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response("https://arera.it/source.pdf", b"official bytes"),
    )
    assert projection_cli._fetch_official_source(source) == b"official bytes"

    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response("https://example.com/source.pdf", b"official bytes"),
    )
    with pytest.raises(ValueError, match="redirected outside"):
        projection_cli._fetch_official_source(source)

    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response(source, b""),
    )
    with pytest.raises(ValueError, match="empty or exceeds"):
        projection_cli._fetch_official_source(source)

    monkeypatch.setattr(projection_cli, "_MAX_SOURCE_BYTES", 2)
    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response(source, b"three"),
    )
    with pytest.raises(ValueError, match="empty or exceeds"):
        projection_cli._fetch_official_source(source)

    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(ValueError, match="acquisition failed"):
        projection_cli._fetch_official_source(source)


def _configure_cli(
    monkeypatch: pytest.MonkeyPatch,
    *,
    sources_match: bool = True,
) -> None:
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    monkeypatch.setattr(
        projection_cli,
        "_now",
        lambda: datetime(2026, 9, 27, 12, tzinfo=UTC),
    )
    monkeypatch.setattr(
        ProjectedDomesticEnergyService,
        "acquire_catalog",
        lambda _self, _date: catalog,
    )
    monkeypatch.setattr(
        ProjectedDomesticEnergyService,
        "acquire_market_history",
        staticmethod(lambda _date: history),
    )
    monkeypatch.setattr(
        ProjectedDomesticEnergyService,
        "acquire_regulatory_anchor",
        staticmethod(lambda _as_of=None: anchor),
    )
    checks: tuple[dict[str, object], ...] = tuple(
        cast(
            dict[str, object],
            {
                "source_id": source.source_id,
                "source": source.source,
                "url": source.url,
                "expected_sha256": source.sha256,
                "live_sha256": source.sha256,
                "digest_matches": sources_match,
                "digest_pinned": source.sha256 is not None,
            },
        )
        for source in anchor.sources
    )
    monkeypatch.setattr(projection_cli, "verify_anchor_sources", lambda _anchor: checks)
    monkeypatch.setattr(
        projection_cli,
        "verify_gme_definition_source",
        lambda: {"digest_matches": True, "expected_sha256": "a" * 64},
    )
    monkeypatch.setattr(
        projection_cli,
        "fetch_monthly_band_report",
        lambda period, _url: _band_report(period),
    )
    monkeypatch.setattr(projection_cli, "ProjectedDomesticEnergyService", lambda: service)


def test_projection_cli_requires_explicit_live_source_verification() -> None:
    with pytest.raises(SystemExit, match="2"):
        projection_cli.main(["--date", AS_OF.isoformat()])


def test_projection_cli_refreshes_anchor_sources_without_catalog_or_market_acquisition(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    anchor = load_domestic_projection_anchor()
    review = _coverage(anchor, AS_OF)
    result = RegulatoryAnchorRefreshResult(
        as_of=AS_OF,
        anchor=anchor,
        coverage_evidence=review,
        ready=False,
        checks={"source_digests_match": False},
        reason_codes=("regulatory_source_changed",),
    )
    # Replace the live acquisition result so this CLI contract test remains offline.
    monkeypatch.setattr(
        projection_cli,
        "ProjectedDomesticEnergyService",
        lambda: type(
            "AnchorOnlyService",
            (),
            {
                "acquire_regulatory_anchor": staticmethod(lambda _as_of=None: anchor),
                "refresh_regulatory_anchor": lambda _self, _date, _reviews: result,
                "acquire_catalog": lambda *_args: pytest.fail("catalog must not be acquired"),
                "acquire_market_history": staticmethod(
                    lambda *_args: pytest.fail("market data must not be acquired")
                ),
            },
        )(),
    )
    review_path = tmp_path / "review.json"
    review_path.write_bytes(dump_envelope(review))
    output_path = tmp_path / "anchor-refresh.json"

    status = projection_cli.main(
        [
            "--date",
            AS_OF.isoformat(),
            "--refresh-anchor",
            "--review",
            str(review_path),
            "--output-anchor",
            str(output_path),
        ]
    )

    summary = json.loads(capsys.readouterr().out)
    saved = load_envelope(output_path.read_bytes())
    assert status == (0 if result.ready else 1)
    assert summary["mode"] == "regulatory_anchor_refresh"
    assert summary["anchor"]["snapshot_as_of"] == "2026-09-27"
    assert isinstance(saved, RegulatoryAnchorRefreshResult)


def test_projection_cli_fails_closed_when_a_pinned_anchor_digest_changes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_cli(monkeypatch, sources_match=False)

    assert projection_cli.main(["--date", AS_OF.isoformat(), "--verify-sources"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "failed"
    assert result["regulatory_anchor"]["complete"] is False


def test_matching_document_hashes_without_later_act_review_are_incomplete(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _configure_cli(monkeypatch)

    assert projection_cli.main(["--date", AS_OF.isoformat(), "--verify-sources"]) == 1
    result = json.loads(capsys.readouterr().out)
    assert result["regulatory_anchor"]["complete"] is False
    assert "regulatory_coverage_unconfirmed" in result["source_preflight"]["reason_codes"]


def test_projection_cli_rejects_request_with_a_different_comparison_date(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_cli(monkeypatch)
    request_path = tmp_path / "projection-request.json"
    request_path.write_bytes(dump_envelope(_indexed_request()))

    assert (
        projection_cli.main(
            [
                "--date",
                "2026-09-28",
                "--verify-sources",
                "--request",
                str(request_path),
            ]
        )
        == 1
    )
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "source_verification_failed"
    assert "as_of must match" in error["detail"]


def test_source_summary_keeps_pun_and_band_series_distinct() -> None:
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    checks: tuple[dict[str, object], ...] = tuple(
        cast(
            dict[str, object],
            {
                "source_id": source.source_id,
                "source": source.source,
                "url": source.url,
                "expected_sha256": source.sha256,
                "live_sha256": source.sha256,
                "digest_matches": True,
                "digest_pinned": True,
            },
        )
        for source in anchor.sources
    )

    summary = projection_cli.summarize_projection_sources(
        AS_OF,
        catalog,
        history,
        anchor,
        checks,
        (_band_report(date(2026, 7, 1)), _band_report(date(2026, 8, 1))),
        gme_definition_check={
            "digest_matches": True,
            "expected_sha256": "a" * 64,
            "live_sha256": "a" * 64,
        },
        coverage_evidence=_coverage(anchor, AS_OF),
        regulatory_coverage_ready=True,
        source_preflight_ready=True,
    )

    source_summary = summary
    historical_window = cast(dict[str, object], source_summary["historical_window"])
    gme = cast(dict[str, object], source_summary["gme"])
    supported_mapping = cast(dict[str, object], gme["supported_mapping"])
    definition_source = cast(dict[str, object], supported_mapping["definition_source"])
    band_mapping = cast(dict[str, object], gme["band_mapping"])
    band_reports = cast(list[dict[str, object]], band_mapping["reports"])
    assert source_summary["status"] == "verified"
    assert historical_window["month_count"] == 12
    assert historical_window["start"] == "2025-09-01"
    assert supported_mapping["commercial_code"] == "PUN"
    assert definition_source["digest_matches"] is True
    assert band_mapping["automatic_offer_mapping"] is False
    assert band_reports[0]["period"] == "2026-07"
    assert band_reports[0]["values_eur_per_kwh"] == {
        "F1": "0.15420",
        "F2": "0.16938",
        "F3": "0.15226",
    }
    assert band_reports[1]["period"] == "2026-08"
    assert band_reports[1]["values_eur_per_kwh"] == {
        "F1": "0.17452",
        "F2": "0.20435",
        "F3": "0.17172",
    }
    regulatory = cast(dict[str, object], source_summary["regulatory_anchor"])
    estimates = cast(dict[str, object], source_summary["estimates"])
    assert regulatory["complete"] is True
    assert estimates["future_values_verified"] is False

    with_band_error = projection_cli.summarize_projection_sources(
        AS_OF,
        catalog,
        history,
        anchor,
        checks,
        (),
        ("2026-08: report layout changed",),
        {"digest_matches": True, "expected_sha256": "a" * 64},
        _coverage(anchor, AS_OF),
        True,
        True,
    )
    gme_with_error = cast(dict[str, object], with_band_error["gme"])
    band_mapping_with_error = cast(dict[str, object], gme_with_error["band_mapping"])
    assert band_mapping_with_error["report_errors"] == ["2026-08: report layout changed"]


def test_projection_cli_verifies_sources_and_runs_canonical_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    catalog = _catalog(AS_OF)
    history = _history(AS_OF)
    anchor = load_domestic_projection_anchor()
    service = ProjectedDomesticEnergyService(clock=lambda: datetime(2026, 9, 27, 12, tzinfo=UTC))
    monkeypatch.setattr(
        projection_cli,
        "_now",
        lambda: datetime(2026, 9, 27, 12, tzinfo=UTC),
    )
    service_type = ProjectedDomesticEnergyService
    monkeypatch.setattr(service_type, "acquire_catalog", lambda self, _date: catalog)
    monkeypatch.setattr(
        service_type,
        "acquire_market_history",
        staticmethod(lambda _date: history),
    )
    monkeypatch.setattr(
        service_type,
        "acquire_regulatory_anchor",
        staticmethod(lambda _as_of=None: anchor),
    )
    checks: tuple[dict[str, object], ...] = tuple(
        cast(
            dict[str, object],
            {
                "source_id": source.source_id,
                "source": source.source,
                "url": source.url,
                "expected_sha256": source.sha256,
                "live_sha256": source.sha256 or "manual-live-verification",
                "digest_matches": True,
                "digest_pinned": source.sha256 is not None,
            },
        )
        for source in anchor.sources
    )
    monkeypatch.setattr(projection_cli, "verify_anchor_sources", lambda _anchor: checks)
    monkeypatch.setattr(
        projection_cli,
        "verify_gme_definition_source",
        lambda: {
            "digest_matches": True,
            "expected_sha256": "a" * 64,
            "live_sha256": "a" * 64,
        },
    )
    monkeypatch.setattr(
        projection_cli,
        "fetch_monthly_band_report",
        lambda period, _url: _band_report(period),
    )
    monkeypatch.setattr(
        "italian_energy.integration.projection_cli.ProjectedDomesticEnergyService",
        lambda: service,
    )
    request_path = tmp_path / "projection-request.json"
    request_path.write_bytes(dump_envelope(_indexed_request()))
    review_path = tmp_path / "regulatory-review.json"
    review_path.write_bytes(dump_envelope(_coverage(anchor, AS_OF)))
    output_sources_path = tmp_path / "verified-sources.json"

    assert (
        projection_cli.main(
            [
                "--date",
                AS_OF.isoformat(),
                "--verify-sources",
                "--review",
                str(review_path),
                "--output-sources",
                str(output_sources_path),
                "--request",
                str(request_path),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)

    assert summary["status"] == "verified"
    assert summary["comparison_status"] == "estimated"
    assert summary["comparison_envelope"]["schema_id"] == (
        "italian-energy/projected-domestic-comparison-result/v2"
    )
    assert summary["comparison_envelope"]["payload"]["status"] == "estimated"
    acquired_bundle = load_envelope(output_sources_path.read_bytes())
    assert isinstance(acquired_bundle, ProjectedSourceBundle)
    assert acquired_bundle.anchor.as_of == date(2026, 9, 27)
    assert acquired_bundle.coverage_evidence.comparison_as_of == AS_OF


def test_projection_cli_uses_a_source_bundle_without_network(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    anchor = load_domestic_projection_anchor()
    coverage = _coverage(anchor, AS_OF)
    bundle = ProjectedSourceBundle(
        as_of=AS_OF,
        catalog=_catalog(AS_OF),
        market_history=_history(AS_OF),
        anchor=anchor,
        coverage_evidence=coverage,
        gme_definition_check=GmeDefinitionCheck(
            expected_sha256=GME_INDEX_DEFINITION_SHA256,
            observed_sha256=GME_INDEX_DEFINITION_SHA256,
            checked_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        ),
    )
    bundle_path = tmp_path / "verified-sources.json"
    bundle_bytes = dump_envelope(bundle)
    bundle_path.write_bytes(bundle_bytes)
    restored_bundle = load_envelope(bundle_bytes)
    assert isinstance(restored_bundle, ProjectedSourceBundle)
    assert dump_envelope(restored_bundle) == bundle_bytes
    request_path = tmp_path / "projection-request.json"
    request_path.write_bytes(dump_envelope(_indexed_request()))

    def unexpected_network(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("offline source-bundle mode must not use network acquisition")

    monkeypatch.setattr(projection_cli, "_fetch_official_source", unexpected_network)
    monkeypatch.setattr(projection_cli, "verify_anchor_sources", unexpected_network)
    monkeypatch.setattr(projection_cli, "verify_gme_definition_source", unexpected_network)
    monkeypatch.setattr(projection_cli, "fetch_monthly_band_report", unexpected_network)
    monkeypatch.setattr(
        ProjectedDomesticEnergyService,
        "acquire_catalog",
        unexpected_network,
    )

    assert (
        projection_cli.main(
            [
                "--date",
                AS_OF.isoformat(),
                "--sources",
                str(bundle_path),
                "--request",
                str(request_path),
            ]
        )
        == 0
    )
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "offline"
    assert result["status"] == "verified"
    assert result["comparison_status"] == "estimated"
    assert result["comparison_envelope"]["schema_id"].endswith("comparison-result/v2")

    changed_bundle = bundle.model_copy(
        update={"coverage_evidence": _coverage(anchor, AS_OF, changed_source=True)}
    )
    bundle_path.write_bytes(dump_envelope(changed_bundle))
    assert (
        projection_cli.main(
            [
                "--date",
                AS_OF.isoformat(),
                "--sources",
                str(bundle_path),
                "--request",
                str(request_path),
            ]
        )
        == 1
    )
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["source_preflight"]["ready"] is False
    assert blocked["comparison_status"] == "blocked_by_source_preflight"


def test_projection_cli_review_evidence_must_match_anchor_and_date(tmp_path: Path) -> None:
    anchor = load_domestic_projection_anchor()
    evidence_path = tmp_path / "review.json"
    evidence_path.write_bytes(dump_envelope(_coverage(anchor, AS_OF)))

    with pytest.raises(ValueError, match="anchor artifact and requested comparison date"):
        projection_cli._load_review_evidence(evidence_path, anchor, date(2026, 9, 28))

    wrong_type_path = tmp_path / "wrong-type.json"
    wrong_type_path.write_bytes(dump_envelope(_indexed_request()))
    with pytest.raises(CoreContractError) as error:
        projection_cli._load_review_evidence(wrong_type_path, anchor, AS_OF)
    assert error.value.code == CoreErrorCode.INVALID_PAYLOAD


def test_projection_cli_reports_missing_band_urls_and_optional_layout_errors(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_cli(monkeypatch)
    anchor = load_domestic_projection_anchor()
    review_path = tmp_path / "regulatory-review.json"
    review_path.write_bytes(dump_envelope(_coverage(anchor, AS_OF)))

    assert projection_cli.main(["--date", "2026-01-20", "--verify-sources"]) == 1
    missing = json.loads(capsys.readouterr().out)
    assert missing["gme"]["band_mapping"]["report_errors"] == [
        "no observed publication URLs are registered for these months"
    ]

    _configure_cli(monkeypatch)
    monkeypatch.setattr(
        projection_cli,
        "fetch_monthly_band_report",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(GmeImportError("published layout changed")),
    )
    assert (
        projection_cli.main(
            ["--date", AS_OF.isoformat(), "--verify-sources", "--review", str(review_path)]
        )
        == 0
    )
    optional = json.loads(capsys.readouterr().out)
    assert optional["status"] == "verified"
    assert len(optional["gme"]["band_mapping"]["report_errors"]) == 2


def test_projection_cli_rejects_non_projected_envelope_after_source_checks(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    _configure_cli(monkeypatch)
    request_path = tmp_path / "historical-request.json"
    request_path.write_bytes(dump_envelope(_portal_result()))

    assert (
        projection_cli.main(
            [
                "--date",
                AS_OF.isoformat(),
                "--verify-sources",
                "--request",
                str(request_path),
            ]
        )
        == 1
    )
    error = json.loads(capsys.readouterr().err)
    assert error["error"] == "invalid_payload"
    assert "projected comparison request" in error["detail"]
