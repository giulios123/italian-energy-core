"""Verify projection sources live or compare with a reusable offline source bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.integration.catalog_cli import summarize_catalog
from italian_energy.integration.current import CurrentCatalogSnapshot
from italian_energy.integration.errors import CoreContractError, CoreErrorCode
from italian_energy.integration.projected import (
    GmeDefinitionCheck,
    ProjectedDomesticComparisonRequest,
    ProjectedSourceBundle,
    RegulatoryCoverageEvidence,
    RegulatoryRegistryReview,
    RegulatorySourceDigestCheck,
    projection_anchor_digest,
)
from italian_energy.integration.projected_service import ProjectedDomesticEnergyService
from italian_energy.integration.serialization import dump_envelope, load_envelope
from italian_energy.market.gme import (
    GME_INDEX_DEFINITION_SHA256,
    GME_INDEX_DEFINITION_URL,
    GmeBandReportSnapshot,
    GmeImportError,
    GmeMarketHistory,
    fetch_monthly_band_report,
    recent_months,
)

_MAX_SOURCE_BYTES = 24_000_000
_OFFICIAL_HOSTS = {
    "adm.gov.it",
    "www.adm.gov.it",
    "arera.it",
    "www.arera.it",
    "gazzettaufficiale.it",
    "www.gazzettaufficiale.it",
    "gme.mercatoelettrico.org",
    "normattiva.it",
    "www.normattiva.it",
}
_BAND_REPORT_URLS = {
    date(2026, 7, 1): (
        "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/"
        "20260803PrezzomedioperfasceLuglio2026.pdf"
    ),
    date(2026, 8, 1): (
        "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/"
        "20260902PrezzomedioperfasceAgosto2026.pdf"
    ),
}


def _fetch_official_source(url: str) -> bytes:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in _OFFICIAL_HOSTS:
        raise ValueError("projection source URL is not on an allowlisted official HTTPS host")
    request = urllib.request.Request(
        url, headers={"User-Agent": "italian-energy-core/0.11", "Accept": "*/*"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final = urlsplit(response.geturl())
            if final.scheme != "https" or final.hostname != parsed.hostname:
                raise ValueError("official source redirected outside its original HTTPS host")
            content = cast(bytes, response.read(_MAX_SOURCE_BYTES + 1))
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ValueError("official source acquisition failed") from exc
    if not content or len(content) > _MAX_SOURCE_BYTES:
        raise ValueError("official source response is empty or exceeds the supported size")
    return content


def _now() -> datetime:
    return datetime.now(UTC)


def verify_anchor_sources(
    anchor: DomesticProjectionAnchor,
    fetch_source: Callable[[str], bytes] = _fetch_official_source,
) -> tuple[dict[str, object], ...]:
    """Reacquire each official anchor reference; compare any pinned digest."""
    results: list[dict[str, object]] = []
    for source in anchor.sources:
        checked_at = _now().isoformat()
        try:
            content = fetch_source(source.url)
        except (OSError, ValueError) as exc:
            results.append(
                {
                    "source_id": source.source_id,
                    "source": source.source,
                    "url": source.url,
                    "expected_sha256": source.sha256,
                    "live_sha256": None,
                    "digest_matches": False,
                    "digest_pinned": source.sha256 is not None,
                    "checked_at": checked_at,
                    "acquisition_error": str(exc),
                }
            )
            continue
        live_digest = hashlib.sha256(content).hexdigest()
        digest_matches = source.sha256 is None or live_digest == source.sha256
        results.append(
            {
                "source_id": source.source_id,
                "source": source.source,
                "url": source.url,
                "period": (
                    {
                        "start": source.effective_period.start.isoformat(),
                        "end": source.effective_period.end.isoformat(),
                    }
                    if source.effective_period is not None
                    else None
                ),
                "expected_sha256": source.sha256,
                "live_sha256": live_digest,
                "digest_matches": digest_matches,
                "digest_pinned": source.sha256 is not None,
                "checked_at": checked_at,
            }
        )
    return tuple(results)


def verify_gme_definition_source(
    fetch_source: Callable[[str], bytes] = _fetch_official_source,
) -> dict[str, object]:
    """Verify the pinned GME definition used to distinguish the commercial index."""
    checked_at = _now().isoformat()
    try:
        content = fetch_source(GME_INDEX_DEFINITION_URL)
    except (OSError, ValueError) as exc:
        return {
            "source": "GME",
            "source_identifier": "DTF 25 MPE",
            "url": GME_INDEX_DEFINITION_URL,
            "expected_sha256": GME_INDEX_DEFINITION_SHA256,
            "live_sha256": None,
            "digest_matches": False,
            "checked_at": checked_at,
            "acquisition_error": str(exc),
        }
    live_digest = hashlib.sha256(content).hexdigest()
    return {
        "source": "GME",
        "source_identifier": "DTF 25 MPE",
        "url": GME_INDEX_DEFINITION_URL,
        "expected_sha256": GME_INDEX_DEFINITION_SHA256,
        "live_sha256": live_digest,
        "digest_matches": live_digest == GME_INDEX_DEFINITION_SHA256,
        "checked_at": checked_at,
    }


def summarize_projection_sources(
    as_of: date,
    catalog: CurrentCatalogSnapshot,
    history: GmeMarketHistory,
    anchor: DomesticProjectionAnchor,
    anchor_source_checks: tuple[dict[str, object], ...],
    band_reports: tuple[GmeBandReportSnapshot, ...],
    band_report_errors: tuple[str, ...] = (),
    gme_definition_check: dict[str, object] | None = None,
    coverage_evidence: RegulatoryCoverageEvidence | None = None,
    regulatory_coverage_ready: bool = False,
    source_preflight_ready: bool = False,
    source_preflight_reasons: tuple[str, ...] = (),
) -> dict[str, object]:
    """Build a source-focused report without claiming forecast values are verified."""
    months = recent_months(as_of)
    reports = [
        {
            "period": report.parsed.period.start.strftime("%Y-%m"),
            "published_value_eur_per_mwh": str(report.parsed.published_value_eur_per_mwh),
            "value_eur_per_kwh": str(report.parsed.value_eur_per_kwh),
            "url": report.provenance.url,
            "retrieved_at": report.provenance.retrieved_at.isoformat(),
            "sha256": report.provenance.sha256,
            "table": report.provenance.locator.section if report.provenance.locator else None,
            "status": report.status.value,
        }
        for report in history.reports
    ]
    digest_complete = all(
        bool(item["digest_matches"]) and bool(item["digest_pinned"])
        for item in anchor_source_checks
    )
    anchor_complete = (
        anchor.status.value == "verified"
        and anchor.as_of <= as_of
        and anchor.validity.start <= as_of < anchor.validity.end
        and bool(anchor.charges)
        and digest_complete
        and coverage_evidence is not None
        and coverage_evidence.comparison_as_of == as_of
        and regulatory_coverage_ready
    )
    gme_complete = (
        history.status.value == "verified"
        and len(reports) == 12
        and tuple(report.parsed.period.start for report in history.reports) == months
        and gme_definition_check is not None
        and gme_definition_check.get("digest_matches") is True
    )
    catalog_summary = summarize_catalog(catalog)
    band_mapping: dict[str, object] = {
        "commercial_codes": [
            "GME_MGP_AVERAGE_PURCHASE_F1",
            "GME_MGP_AVERAGE_PURCHASE_F2",
            "GME_MGP_AVERAGE_PURCHASE_F3",
        ],
        "definition": "average purchase price by ARERA time band; distinct from PUN Index GME",
        "automatic_offer_mapping": False,
        "reports": [
            {
                "period": band_report.parsed.period.start.strftime("%Y-%m"),
                "status": band_report.status.value,
                "url": band_report.provenance[0].url,
                "sha256": band_report.provenance[0].sha256,
                "values_eur_per_kwh": {
                    item.band: str(item.value_eur_per_kwh) for item in band_report.parsed.prices
                },
                "published_eur_per_mwh": {
                    item.band: str(item.published_value_eur_per_mwh)
                    for item in band_report.parsed.prices
                },
                "hours": {item.band: item.hours for item in band_report.parsed.prices},
            }
            for band_report in band_reports
        ],
    }
    if band_report_errors:
        band_mapping["report_errors"] = list(band_report_errors)
    return {
        "status": (
            "verified" if source_preflight_ready and gme_complete and anchor_complete else "failed"
        ),
        "as_of": as_of.isoformat(),
        "historical_window": {
            "start": months[0].isoformat(),
            "end": months[-1].strftime("%Y-%m"),
            "month_count": len(months),
            "complete_and_consecutive": gme_complete,
        },
        "source_preflight": {
            "ready": source_preflight_ready,
            "regulatory_coverage_ready": regulatory_coverage_ready,
            "reason_codes": list(source_preflight_reasons),
        },
        "catalog": catalog_summary,
        "gme": {
            "supported_mapping": {
                "commercial_code": "PUN",
                "official_definition": "PUN Index GME, Mercato del Giorno Prima",
                "definition_source": gme_definition_check,
                "report_measure": "monthly MGP Baseload average",
                "published_unit": "EUR/MWh",
                "core_unit": "EUR/kWh",
                "conversion": "Decimal(EUR/MWh) / 1000",
                "granularity": "month",
                "verified_months": reports,
            },
            "band_mapping": band_mapping,
        },
        "regulatory_anchor": {
            "anchor_id": anchor.anchor_id,
            "as_of": anchor.as_of.isoformat(),
            "status": anchor.status.value,
            "validity": {
                "start": anchor.validity.start.isoformat(),
                "end": anchor.validity.end.isoformat(),
            },
            "complete": anchor_complete,
            "coverage_as_of": (
                coverage_evidence.comparison_as_of.isoformat()
                if coverage_evidence is not None
                else None
            ),
            "coverage_evidence_id": (
                coverage_evidence.evidence_id if coverage_evidence is not None else None
            ),
            "sources": list(anchor_source_checks),
            "charge_count": len(anchor.charges),
            "resident_nonresident_separate": True,
            "components_are_totals_without_atomic_double_count": True,
            "future_application": "assumption; not verified future validity",
        },
        "estimates": {
            "future_values_verified": False,
            "costs_are_estimates": True,
            "index_multipliers": ["0.80", "1.00", "1.20"],
            "ranking_scenario": "base",
        },
    }


def _coverage_evidence_from_live_checks(
    anchor: DomesticProjectionAnchor,
    as_of: date,
    checks: tuple[dict[str, object], ...],
    reviews: tuple[RegulatoryRegistryReview, ...],
) -> RegulatoryCoverageEvidence:
    checked_at = _now()
    checks_by_id = {str(item.get("source_id")): item for item in checks}
    digest_checks: list[RegulatorySourceDigestCheck] = []
    for source in anchor.sources:
        live = checks_by_id.get(source.source_id, {})
        raw_checked_at = live.get("checked_at")
        observed_time = (
            datetime.fromisoformat(raw_checked_at)
            if isinstance(raw_checked_at, str)
            else checked_at
        )
        observed_digest = live.get("live_sha256")
        digest_checks.append(
            RegulatorySourceDigestCheck(
                source_id=source.source_id,
                expected_sha256=source.sha256,
                observed_sha256=(observed_digest if isinstance(observed_digest, str) else None),
                checked_at=observed_time,
            )
        )
    return RegulatoryCoverageEvidence(
        anchor_id=anchor.anchor_id,
        anchor_sha256=projection_anchor_digest(anchor),
        comparison_as_of=as_of,
        checked_at=checked_at,
        source_checks=tuple(digest_checks),
        registry_reviews=tuple(reviews),
    )


def _load_review_evidence(
    path: Path | None,
    anchor: DomesticProjectionAnchor,
    as_of: date,
) -> RegulatoryCoverageEvidence | None:
    if path is None:
        return None
    payload = load_envelope(path.read_bytes())
    if not isinstance(payload, RegulatoryCoverageEvidence):
        raise CoreContractError(
            CoreErrorCode.INVALID_PAYLOAD,
            "--review envelope must contain RegulatoryCoverageEvidence",
        )
    if (
        payload.anchor_id != anchor.anchor_id
        or payload.anchor_sha256 != projection_anchor_digest(anchor)
        or payload.comparison_as_of != as_of
    ):
        raise ValueError("--review must match the anchor artifact and requested comparison date")
    return payload


def _run_offline(
    as_of: date,
    source_path: Path,
    request_path: Path | None,
) -> tuple[int, dict[str, object]]:
    bundle = load_envelope(source_path.read_bytes())
    if not isinstance(bundle, ProjectedSourceBundle):
        raise CoreContractError(
            CoreErrorCode.INVALID_PAYLOAD,
            "--sources envelope must contain ProjectedSourceBundle",
        )
    if bundle.as_of != as_of:
        raise ValueError("source bundle as_of must match --date")
    service = ProjectedDomesticEnergyService()
    gate = service.source_preflight(
        as_of,
        bundle.catalog,
        bundle.market_history,
        bundle.anchor,
        bundle.coverage_evidence,
    )
    definition = bundle.gme_definition_check
    definition_ready = (
        definition is not None
        and definition.expected_sha256 == GME_INDEX_DEFINITION_SHA256
        and definition.observed_sha256 == GME_INDEX_DEFINITION_SHA256
        and definition.checked_at <= _now()
    )
    ready = gate.ready and definition_ready
    summary: dict[str, object] = {
        "status": "verified" if ready else "failed",
        "as_of": as_of.isoformat(),
        "mode": "offline",
        "source_preflight": {
            "ready": ready,
            "checks": gate.checks,
            "reason_codes": [
                *gate.reason_codes,
                *([] if definition_ready else ["gme_index_definition_unverified"]),
            ],
        },
        "regulatory_anchor": {
            "anchor_id": bundle.anchor.anchor_id,
            "as_of": bundle.anchor.as_of.isoformat(),
            "validity": {
                "start": bundle.anchor.validity.start.isoformat(),
                "end": bundle.anchor.validity.end.isoformat(),
            },
            "coverage_evidence_id": bundle.coverage_evidence.evidence_id,
        },
        "estimates": {"future_values_verified": False, "costs_are_estimates": True},
    }
    if request_path is not None:
        payload = load_envelope(request_path.read_bytes())
        if not isinstance(payload, ProjectedDomesticComparisonRequest):
            raise CoreContractError(
                CoreErrorCode.INVALID_PAYLOAD,
                "--request envelope must contain a projected comparison request",
            )
        if payload.as_of != as_of:
            raise ValueError("--request as_of must match --date")
        if ready:
            comparison = service.compare(
                payload,
                bundle.catalog,
                bundle.market_history,
                bundle.anchor,
                bundle.coverage_evidence,
            )
            summary["comparison_envelope"] = json.loads(dump_envelope(comparison))
            summary["comparison_status"] = "estimated"
        else:
            summary["comparison_status"] = "blocked_by_source_preflight"
    return (0 if ready else 1), summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--verify-sources",
        action="store_true",
        help="live acquisition and verification of catalog, GME and regulatory sources",
    )
    mode.add_argument(
        "--refresh-anchor",
        action="store_true",
        help="download and recheck only the regulatory anchor sources",
    )
    mode.add_argument(
        "--sources",
        type=Path,
        help="reuse a versioned source bundle for an offline deterministic comparison",
    )
    parser.add_argument(
        "--request",
        type=Path,
        help="optional canonical ProjectedDomesticComparisonRequest envelope",
    )
    parser.add_argument(
        "--review",
        type=Path,
        help="manual RegulatoryCoverageEvidence envelope with the four dated registry reviews",
    )
    parser.add_argument(
        "--output-sources",
        type=Path,
        help="write the acquired snapshots and date-bound coverage evidence as an envelope",
    )
    parser.add_argument(
        "--output-anchor",
        type=Path,
        help="write the regulatory anchor refresh result as a reusable envelope",
    )
    args = parser.parse_args(argv)
    if args.sources is not None and args.review is not None:
        parser.error("--review is only used with --verify-sources")
    if args.sources is not None and args.output_sources is not None:
        parser.error("--output-sources is only used with --verify-sources")
    if args.sources is not None and args.output_anchor is not None:
        parser.error("--output-anchor is only used with --refresh-anchor")
    if args.refresh_anchor and (args.request is not None or args.output_sources is not None):
        parser.error("--request and --output-sources are only used with comparison source modes")
    if not args.refresh_anchor and args.output_anchor is not None:
        parser.error("--output-anchor is only used with --refresh-anchor")

    if args.sources is not None:
        try:
            status, summary = _run_offline(args.date, args.sources, args.request)
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return status
        except (CoreContractError, OSError, ValueError) as exc:
            code = exc.code.value if isinstance(exc, CoreContractError) else "source_bundle_invalid"
            detail = exc.detail if isinstance(exc, CoreContractError) else str(exc)
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "as_of": args.date.isoformat(),
                        "error": code,
                        "detail": detail,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                file=sys.stderr,
            )
            return 1

    service = ProjectedDomesticEnergyService()
    try:
        if args.refresh_anchor:
            anchor = service.acquire_regulatory_anchor(args.date)
            review_packet = _load_review_evidence(args.review, anchor, args.date)
            refresh = service.refresh_regulatory_anchor(
                args.date,
                review_packet.registry_reviews if review_packet is not None else (),
            )
            refresh_summary: dict[str, object] = {
                "status": "verified" if refresh.ready else "review_required",
                "mode": "regulatory_anchor_refresh",
                "as_of": args.date.isoformat(),
                "anchor": {
                    "anchor_id": refresh.anchor.anchor_id,
                    "snapshot_as_of": refresh.anchor.as_of.isoformat(),
                    "validity": {
                        "start": refresh.anchor.validity.start.isoformat(),
                        "end": refresh.anchor.validity.end.isoformat(),
                    },
                },
                "coverage_evidence_id": refresh.coverage_evidence.evidence_id,
                "checks": refresh.checks,
                "reason_codes": list(refresh.reason_codes),
            }
            if args.output_anchor is not None:
                args.output_anchor.write_bytes(dump_envelope(refresh))
            print(json.dumps(refresh_summary, ensure_ascii=False, sort_keys=True))
            return 0 if refresh.ready else 1

        catalog = service.acquire_catalog(args.date)
        history = service.acquire_market_history(args.date)
        anchor = service.acquire_regulatory_anchor(args.date)
        source_checks = verify_anchor_sources(anchor)
        review_packet = _load_review_evidence(args.review, anchor, args.date)
        coverage_evidence = _coverage_evidence_from_live_checks(
            anchor,
            args.date,
            source_checks,
            review_packet.registry_reviews if review_packet is not None else (),
        )
        source_gate = service.source_preflight(
            args.date, catalog, history, anchor, coverage_evidence
        )
        definition_check = verify_gme_definition_source()
        definition_checked_at = definition_check.get("checked_at")
        definition_observed_sha256 = definition_check.get("live_sha256")
        definition_evidence = GmeDefinitionCheck(
            expected_sha256=str(definition_check["expected_sha256"]),
            observed_sha256=(
                definition_observed_sha256 if isinstance(definition_observed_sha256, str) else None
            ),
            checked_at=(
                datetime.fromisoformat(definition_checked_at)
                if isinstance(definition_checked_at, str)
                else _now()
            ),
        )
        band_periods = tuple(
            month for month in recent_months(args.date)[-2:] if month in _BAND_REPORT_URLS
        )
        band_reports: list[GmeBandReportSnapshot] = []
        band_errors: list[str] = []
        if not band_periods:
            band_errors.append("no observed publication URLs are registered for these months")
        for band_period in band_periods:
            try:
                band_reports.append(
                    fetch_monthly_band_report(band_period, _BAND_REPORT_URLS[band_period])
                )
            except GmeImportError as exc:
                band_errors.append(f"{band_period:%Y-%m}: {exc}")
        summary = summarize_projection_sources(
            args.date,
            catalog,
            history,
            anchor,
            source_checks,
            tuple(band_reports),
            tuple(band_errors),
            definition_check,
            coverage_evidence,
            source_gate.checks["regulatory_anchor_verified"],
            source_gate.ready,
            source_gate.reason_codes,
        )
        if args.output_sources is not None:
            bundle = ProjectedSourceBundle(
                as_of=args.date,
                catalog=catalog,
                market_history=history,
                anchor=anchor,
                coverage_evidence=coverage_evidence,
                gme_definition_check=definition_evidence,
            )
            args.output_sources.write_bytes(dump_envelope(bundle))
        if args.request is not None:
            payload = load_envelope(args.request.read_bytes())
            if not isinstance(payload, ProjectedDomesticComparisonRequest):
                raise CoreContractError(
                    CoreErrorCode.INVALID_PAYLOAD,
                    detail="--request envelope must contain a projected comparison request",
                )
            if payload.as_of != args.date:
                raise ValueError("--request as_of must match --date")
            if not source_gate.ready or summary["status"] != "verified":
                summary["comparison_status"] = "blocked_by_live_source_failure"
            else:
                comparison = service.compare(payload, catalog, history, anchor, coverage_evidence)
                summary["comparison_envelope"] = json.loads(dump_envelope(comparison))
                summary["comparison_status"] = "estimated"
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0 if summary["status"] == "verified" else 1
    except (CoreContractError, GmeImportError, OSError, ValueError) as exc:
        code = (
            exc.code.value if isinstance(exc, CoreContractError) else "source_verification_failed"
        )
        detail = exc.detail if isinstance(exc, CoreContractError) else str(exc)
        print(
            json.dumps(
                {
                    "status": "failed",
                    "as_of": args.date.isoformat(),
                    "error": code,
                    "detail": detail,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":  # pragma: no cover - executable module entrypoint
    raise SystemExit(main())
