"""Verify official projection sources and optionally evaluate a typed request."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from italian_energy.arera.projection import DomesticProjectionAnchor
from italian_energy.integration.catalog_cli import summarize_catalog
from italian_energy.integration.current import CurrentCatalogSnapshot
from italian_energy.integration.errors import CoreContractError, CoreErrorCode
from italian_energy.integration.projected import ProjectedDomesticComparisonRequest
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


def verify_anchor_sources(
    anchor: DomesticProjectionAnchor,
    fetch_source: Callable[[str], bytes] = _fetch_official_source,
) -> tuple[dict[str, object], ...]:
    """Reacquire each official anchor reference; compare any pinned digest."""
    results: list[dict[str, object]] = []
    for source in anchor.sources:
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
            }
        )
    return tuple(results)


def verify_gme_definition_source(
    fetch_source: Callable[[str], bytes] = _fetch_official_source,
) -> dict[str, object]:
    """Verify the pinned GME definition used to distinguish the commercial index."""
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
        and anchor.as_of == as_of
        and anchor.validity.start <= as_of < anchor.validity.end
        and bool(anchor.charges)
        and digest_complete
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
        "status": "verified" if gme_complete and anchor_complete else "failed",
        "as_of": as_of.isoformat(),
        "historical_window": {
            "start": months[0].isoformat(),
            "end": months[-1].strftime("%Y-%m"),
            "month_count": len(months),
            "complete_and_consecutive": gme_complete,
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
            "status": anchor.status.value,
            "validity": {
                "start": anchor.validity.start.isoformat(),
                "end": anchor.validity.end.isoformat(),
            },
            "complete": anchor_complete,
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, type=date.fromisoformat, help="YYYY-MM-DD")
    parser.add_argument(
        "--verify-sources",
        action="store_true",
        help="reacquire catalog, exact GME history, and regulatory source documents",
    )
    parser.add_argument(
        "--request",
        type=Path,
        help="optional canonical ProjectedDomesticComparisonRequest envelope",
    )
    args = parser.parse_args(argv)
    if not args.verify_sources:
        parser.error("--verify-sources is required for this live verification command")

    service = ProjectedDomesticEnergyService()
    try:
        catalog = service.acquire_catalog(args.date)
        history = service.acquire_market_history(args.date)
        anchor = service.acquire_regulatory_anchor()
        source_checks = verify_anchor_sources(anchor)
        definition_check = verify_gme_definition_source()
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
        )
        if args.request is not None:
            payload = load_envelope(args.request.read_bytes())
            if not isinstance(payload, ProjectedDomesticComparisonRequest):
                raise CoreContractError(
                    CoreErrorCode.INVALID_PAYLOAD,
                    detail="--request envelope must contain a projected comparison request",
                )
            if payload.as_of != args.date:
                raise ValueError("--request as_of must match --date")
            if summary["status"] != "verified":
                summary["comparison_status"] = "blocked_by_live_source_failure"
            else:
                comparison = service.compare(payload, catalog, history, anchor)
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
