import importlib as importlib_module
import urllib.error
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from types import SimpleNamespace
from urllib import request as urllib_request
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

import italian_energy.market.gme as gme
from italian_energy.domain import Granularity, RateUnit
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.market.gme import (
    GmeBandReportSnapshot,
    GmeImportError,
    GmeMarketHistory,
    GmeMonthlyIndexSnapshot,
    ParsedGmeBandPrice,
    ParsedGmeBandReport,
    ParsedGmeBaseload,
    fetch_monthly_band_report,
    fetch_monthly_report,
    fetch_recent_market_history,
    history_from_reports,
    make_report_provenance,
    parse_monthly_band_report_bytes,
    parse_monthly_band_report_text,
    parse_monthly_baseload_text,
    parse_monthly_report_bytes,
    recent_months,
    report_url,
)


def test_monthly_baseload_parser_keeps_published_precision_and_units() -> None:
    parsed = parse_monthly_baseload_text(
        "Mercato del Giorno Prima\nSettembre 2025\n"
        "Prezzo medio\n€/MWh 2025 2024\nBaseload 109,08 117,13",
        date(2025, 9, 1),
    )

    assert parsed.index_code == "PUN"
    assert parsed.unit == RateUnit.EUR_PER_KWH
    assert parsed.published_unit == RateUnit.EUR_PER_MWH
    assert parsed.published_value_eur_per_mwh == Decimal("109.08")
    assert parsed.granularity == Granularity.MONTH
    assert parsed.period == DatePeriod(start=date(2025, 9, 1), end=date(2025, 10, 1))
    assert parsed.value_eur_per_kwh == Decimal("0.10908")
    assert str(parsed.value_eur_per_kwh) == "0.10908"


def test_parser_uses_current_year_column_not_prior_year_comparison() -> None:
    parsed = parse_monthly_baseload_text(
        "Mercato del Giorno Prima\nAgosto 2026\nPrezzo medio\n"
        "€/MWh 2026 2025 % Assoluta\nBaseload 180,00 108,79 +65,5% +71,21",
        date(2026, 8, 1),
    )

    assert parsed.value_eur_per_kwh == Decimal("0.18000")
    assert parsed.published_value_eur_per_mwh == Decimal("180.00")


@pytest.mark.parametrize(
    "text",
    (
        "Baseload 109,08 €/kWh settembre 2025",
        "Mercato del Giorno Prima Agosto 2025 €/MWh Baseload 109,08",
        "Mercato del Giorno Prima Settembre 2025 €/MWh Picco 109,08",
        "Mercato del Giorno Prima Settembre 2025 €/MWh Baseload 109,08 105,22",
    ),
)
def test_monthly_baseload_parser_fails_closed_on_unit_period_or_layout(text: str) -> None:
    with pytest.raises(GmeImportError):
        parse_monthly_baseload_text(text, date(2025, 9, 1))


def test_report_bytes_require_a_valid_single_period_pdf() -> None:
    with pytest.raises(GmeImportError):
        parse_monthly_report_bytes(b"not a pdf", date(2025, 9, 1), datetime.now(UTC))


def test_report_provenance_records_acquisition_and_digest() -> None:
    from italian_energy.market.gme import make_report_provenance

    raw = b"official report bytes"
    provenance = make_report_provenance(
        raw,
        report_period=DatePeriod(start=date(2025, 9, 1), end=date(2025, 10, 1)),
        retrieved_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
        url="https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/202509_Dati_di_sintesi_mensile.pdf",
    )

    assert provenance.source == "GME"
    assert provenance.effective_period == DatePeriod(start=date(2025, 9, 1), end=date(2025, 10, 1))
    assert provenance.sha256 == sha256(raw).hexdigest()


def test_band_report_keeps_official_definition_separate_from_pun_index() -> None:
    parsed = parse_monthly_band_report_text(
        "Prezzo medio di acquisto per fasce orarie*\n"
        "€/MWh\nF1: ore di punta (peak)\n"
        "F2: ore intermedie (mid-level)\nF3: ore fuori punta (off-peak)\n"
        "*come definite dalla delibera dell'ARERA n°181 del 2006\nAgosto 2026\n"
        "(231 ore) 174,52\n(169 ore) 204,35\n(344 ore) 171,72",
        date(2026, 8, 1),
    )

    assert parsed.period == DatePeriod(start=date(2026, 8, 1), end=date(2026, 9, 1))
    assert [point.band for point in parsed.prices] == ["F1", "F2", "F3"]
    assert [point.value_eur_per_kwh for point in parsed.prices] == [
        Decimal("0.17452"),
        Decimal("0.20435"),
        Decimal("0.17172"),
    ]
    assert [point.published_value_eur_per_mwh for point in parsed.prices] == [
        Decimal("174.52"),
        Decimal("204.35"),
        Decimal("171.72"),
    ]
    assert [point.hours for point in parsed.prices] == [231, 169, 344]
    assert all(point.index_code != "PUN" for point in parsed.prices)


def test_july_band_report_uses_its_own_published_month_values() -> None:
    parsed = parse_monthly_band_report_text(
        "Prezzo medio di acquisto per fasce orarie* €/MWh "
        "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
        "*come definite dalla delibera dell'ARERA n°181 del 2006 Luglio 2026 "
        "(253 ore) 154,20 (179 ore) 169,38 (312 ore) 152,26",
        date(2026, 7, 1),
    )

    assert parsed.period == DatePeriod(start=date(2026, 7, 1), end=date(2026, 8, 1))
    assert [point.hours for point in parsed.prices] == [253, 179, 312]
    assert [point.value_eur_per_kwh for point in parsed.prices] == [
        Decimal("0.15420"),
        Decimal("0.16938"),
        Decimal("0.15226"),
    ]
    assert [str(point.value_eur_per_kwh) for point in parsed.prices] == [
        "0.15420",
        "0.16938",
        "0.15226",
    ]
    assert [point.index_code for point in parsed.prices] == [
        "GME_MGP_AVERAGE_PURCHASE_F1",
        "GME_MGP_AVERAGE_PURCHASE_F2",
        "GME_MGP_AVERAGE_PURCHASE_F3",
    ]


def _reports(as_of: date) -> tuple[GmeMonthlyIndexSnapshot, ...]:
    reports = []
    for month in recent_months(as_of):
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        period = DatePeriod(start=month, end=next_month)
        content = month.isoformat().encode()
        parsed = ParsedGmeBaseload(
            period=period,
            published_value_eur_per_mwh=Decimal("123.40"),
            value_eur_per_kwh=Decimal("0.12340"),
        )
        reports.append(
            GmeMonthlyIndexSnapshot(
                parsed=parsed,
                status=VerificationStatus.VERIFIED,
                provenance=make_report_provenance(
                    content,
                    report_period=period,
                    retrieved_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
                    url=report_url(month),
                ),
            )
        )
    return tuple(reports)


def test_monthly_report_bytes_parse_offline_without_claiming_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = (
        "Mercato del Giorno Prima Settembre 2025 Prezzo medio "
        "€/MWh 2025 2024 Baseload 109,08 117,13"
    )
    pages = [SimpleNamespace(extract_text=lambda: text)] + [
        SimpleNamespace(extract_text=lambda: "") for _ in range(2)
    ]
    reader = SimpleNamespace(is_encrypted=False, pages=pages)
    monkeypatch.setattr(
        "italian_energy.market.gme.importlib.import_module",
        lambda _name: SimpleNamespace(PdfReader=lambda _stream: reader),
    )

    snapshot = parse_monthly_report_bytes(
        b"%PDF-synthetic",
        date(2025, 9, 1),
        datetime(2026, 9, 27, 12, tzinfo=UTC),
        source_url=report_url(date(2025, 9, 1)),
    )

    assert snapshot.status == VerificationStatus.UNVERIFIED
    assert snapshot.parsed.published_value_eur_per_mwh == Decimal("109.08")
    assert str(snapshot.parsed.value_eur_per_kwh) == "0.10908"
    assert snapshot.provenance.locator is not None
    assert "Baseload" in (snapshot.provenance.locator.section or "")


def test_band_report_bytes_keeps_per_band_table_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = (
        "Prezzo medio di acquisto per fasce orarie* €/MWh "
        "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
        "*come definite dalla delibera dell'ARERA n°181 del 2006 Agosto 2026 "
        "(231 ore) 174,52 (169 ore) 204,35 (344 ore) 171,72"
    )
    reader = SimpleNamespace(is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda: text)])
    monkeypatch.setattr(
        "italian_energy.market.gme.importlib.import_module",
        lambda _name: SimpleNamespace(PdfReader=lambda _stream: reader),
    )

    snapshot = parse_monthly_band_report_bytes(
        b"%PDF-synthetic",
        date(2026, 8, 1),
        datetime(2026, 9, 27, 12, tzinfo=UTC),
        source_url=(
            "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/"
            "20260902PrezzomedioperfasceAgosto2026.pdf"
        ),
    )

    assert snapshot.status == VerificationStatus.UNVERIFIED
    assert len(snapshot.provenance) == 3
    assert all(item.sha256 == sha256(b"%PDF-synthetic").hexdigest() for item in snapshot.provenance)
    assert all(item.locator is not None for item in snapshot.provenance)
    assert all(item.locator.sheet is None for item in snapshot.provenance if item.locator)


def test_gme_bytes_and_models_reject_invalid_periods_units_and_digest_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="complete calendar month"):
        ParsedGmeBaseload(
            period=DatePeriod(start=date(2025, 9, 1), end=date(2025, 10, 2)),
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.1"),
        )
    with pytest.raises(ValueError, match="conversion"):
        ParsedGmeBaseload(
            period=DatePeriod(start=date(2025, 9, 1), end=date(2025, 10, 1)),
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.11"),
        )
    with pytest.raises(GmeImportError, match="not a PDF"):
        parse_monthly_report_bytes(b"no", date(2025, 9, 1), datetime.now(UTC))
    with pytest.raises(GmeImportError, match="not a PDF"):
        parse_monthly_band_report_bytes(b"no", date(2025, 9, 1), datetime.now(UTC))

    reader = SimpleNamespace(is_encrypted=True, pages=[])
    monkeypatch.setattr(
        "italian_energy.market.gme.importlib.import_module",
        lambda _name: SimpleNamespace(PdfReader=lambda _stream: reader),
    )
    with pytest.raises(GmeImportError, match="unsupported PDF structure"):
        parse_monthly_report_bytes(b"%PDF-synthetic", date(2025, 9, 1), datetime.now(UTC))
    with pytest.raises(GmeImportError, match="unsupported PDF structure"):
        parse_monthly_band_report_bytes(b"%PDF-synthetic", date(2025, 9, 1), datetime.now(UTC))

    period = DatePeriod(start=date(2026, 8, 1), end=date(2026, 9, 1))
    with pytest.raises(ValueError, match="beginning of a month"):
        ParsedGmeBaseload(
            period=DatePeriod(start=date(2026, 8, 2), end=date(2026, 9, 1)),
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.1"),
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        ParsedGmeBaseload(
            period=period,
            published_value_eur_per_mwh=Decimal("-100"),
            value_eur_per_kwh=Decimal("-0.1"),
        )
    with pytest.raises(ValueError, match="monthly EUR/kWh"):
        ParsedGmeBaseload(
            period=period,
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.1"),
            unit=RateUnit.EUR_PER_MWH,
        )
    with pytest.raises(ValueError, match="PUN index only"):
        ParsedGmeBaseload(
            period=period,
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.1"),
            index_code="PE",
        )


def test_gme_band_models_require_distinct_codes_periods_hours_and_official_provenance() -> None:
    period = DatePeriod(start=date(2026, 8, 1), end=date(2026, 9, 1))
    with pytest.raises(ValueError, match="must be F1, F2 or F3"):
        ParsedGmeBandPrice(
            index_code="GME_MGP_AVERAGE_PURCHASE_F4",
            period=period,
            band="F4",
            hours=1,
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.1"),
        )
    with pytest.raises(ValueError, match="distinct code"):
        ParsedGmeBandPrice(
            index_code="PUN",
            period=period,
            band="F1",
            hours=1,
            published_value_eur_per_mwh=Decimal("100"),
            value_eur_per_kwh=Decimal("0.1"),
        )

    parsed = parse_monthly_band_report_text(
        "Prezzo medio di acquisto per fasce orarie* €/MWh "
        "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
        "*come definite dalla delibera dell'ARERA n°181 del 2006 Agosto 2026 "
        "(231 ore) 174,52 (169 ore) 204,35 (344 ore) 171,72",
        date(2026, 8, 1),
    )
    out_of_order = tuple(reversed(parsed.prices))
    with pytest.raises(ValueError, match="published order"):
        ParsedGmeBandReport(period=period, prices=out_of_order)
    wrong_hours = tuple(
        item.model_copy(update={"hours": item.hours + (1 if item.band == "F1" else 0)})
        for item in parsed.prices
    )
    with pytest.raises(ValueError, match="do not add up"):
        ParsedGmeBandReport(period=period, prices=wrong_hours)

    provenance = tuple(
        make_report_provenance(
            b"band source",
            report_period=period,
            retrieved_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            url="https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/report.pdf",
        ).model_copy(
            update={"source_identifier": f"MGP-average-purchase-by-band:2026-08:{item.band}"}
        )
        for item in parsed.prices
    )
    with pytest.raises(ValueError, match="official GME URLs"):
        GmeBandReportSnapshot(
            parsed=parsed,
            status=VerificationStatus.VERIFIED,
            provenance=tuple(
                item.model_copy(update={"url": "https://example.com/file.pdf"})
                for item in provenance
            ),
        )


def test_band_parser_and_snapshots_reject_wrong_month_layout_and_missing_digests() -> None:
    with pytest.raises(GmeImportError, match="prices do not match"):
        parse_monthly_band_report_text(
            "Prezzo medio di acquisto per fasce orarie* €/MWh "
            "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
            "*come definite dalla delibera dell'ARERA n°181 del 2006 Agosto 2026 "
            "(230 ore) 174,52 (169 ore) 204,35 (344 ore) 171,72",
            date(2026, 8, 1),
        )
    with pytest.raises(GmeImportError, match="exactly three"):
        parse_monthly_band_report_text(
            "Prezzo medio di acquisto per fasce orarie* €/MWh "
            "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
            "*come definite dalla delibera dell'ARERA n°181 del 2006 Agosto 2026 "
            "(231 ore) 174,52 (169 ore) 204,35",
            date(2026, 8, 1),
        )

    as_of = date(2026, 9, 27)
    monthly = _reports(as_of)[0]
    bad_source = monthly.model_copy(
        update={"provenance": monthly.provenance.model_copy(update={"source": "Portal"})}
    )
    with pytest.raises(ValidationError, match="official URL and raw digest"):
        GmeMonthlyIndexSnapshot.model_validate(bad_source.model_dump(mode="python"))

    parsed = parse_monthly_band_report_text(
        "Prezzo medio di acquisto per fasce orarie* €/MWh "
        "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
        "*come definite dalla delibera dell'ARERA n°181 del 2006 Agosto 2026 "
        "(231 ore) 174,52 (169 ore) 204,35 (344 ore) 171,72",
        date(2026, 8, 1),
    )
    provenance = tuple(
        make_report_provenance(
            b"band report",
            report_period=parsed.period,
            retrieved_at=datetime(2026, 9, 27, 12, tzinfo=UTC),
            url="https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/bands.pdf",
        )
        for _ in parsed.prices
    )
    with pytest.raises(ValidationError, match="one locator per time band"):
        GmeBandReportSnapshot(
            parsed=parsed,
            status=VerificationStatus.UNVERIFIED,
            provenance=provenance[:2],
        )
    missing_digest = tuple(item.model_copy(update={"sha256": None}) for item in provenance)
    with pytest.raises(ValidationError, match="report month and source digest"):
        GmeBandReportSnapshot(
            parsed=parsed,
            status=VerificationStatus.UNVERIFIED,
            provenance=missing_digest,
        )


def test_exact_history_builder_rejects_gaps_and_keeps_offline_inputs_unverified() -> None:
    as_of = date(2026, 9, 27)
    reports = _reports(as_of)

    history = history_from_reports(as_of, reports)
    assert history.status == VerificationStatus.VERIFIED
    assert history.market_data.indexes[0].timezone == "Europe/Rome"
    assert history.market_data.points[0].interval.start.tzinfo == ZoneInfo("Europe/Rome")
    assert history.market_data.points[0].value == Decimal("0.12340")
    with pytest.raises(GmeImportError, match="latest consecutive twelve-month window"):
        history_from_reports(as_of, reports[1:])

    offline = tuple(
        item.model_copy(update={"status": VerificationStatus.UNVERIFIED}) for item in reports
    )
    offline_history = history_from_reports(as_of, offline)
    assert offline_history.status == VerificationStatus.UNVERIFIED

    payload = history.model_dump(mode="python")
    payload["market_data"]["points"][0]["value"] = Decimal("0.999")
    with pytest.raises(ValidationError, match="source-backed report value"):
        GmeMarketHistory.model_validate(payload)

    payload = history.model_dump(mode="python")
    payload["reports"][0]["status"] = VerificationStatus.UNVERIFIED
    with pytest.raises(ValidationError, match="while one report is unverified"):
        GmeMarketHistory.model_validate(payload)

    payload = history.model_dump(mode="python")
    payload["reports"] = list(payload["reports"])
    payload["reports"][1] = payload["reports"][0]
    with pytest.raises(ValidationError, match="duplicate months"):
        GmeMarketHistory.model_validate(payload)

    payload = history.model_dump(mode="python")
    payload["market_data"]["points"] = list(payload["market_data"]["points"])
    payload["market_data"]["points"] = payload["market_data"]["points"][:-1]
    with pytest.raises(ValidationError, match="one market point per report"):
        GmeMarketHistory.model_validate(payload)

    payload = history.model_dump(mode="python")
    payload["market_data"]["indexes"] = list(payload["market_data"]["indexes"])
    payload["market_data"]["indexes"].append(payload["market_data"]["indexes"][0] | {"code": "PE"})
    with pytest.raises(ValidationError, match="only the verified PUN index"):
        GmeMarketHistory.model_validate(payload)


def test_fetch_helpers_verify_official_redirects_and_exact_month_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    month = date(2025, 9, 1)
    report = _reports(date(2026, 9, 27))[0]

    class Response:
        def __init__(self, url: str) -> None:
            self.url = url

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def geturl(self) -> str:
            return self.url

        def read(self, _size: int) -> bytes:
            return b"%PDF-synthetic"

    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response(report_url(month)),
    )
    monkeypatch.setattr(
        gme,
        "parse_monthly_report_bytes",
        lambda *_args, **_kwargs: report.model_copy(
            update={"status": VerificationStatus.UNVERIFIED}
        ),
    )
    monthly = fetch_monthly_report(month)
    assert monthly.status == VerificationStatus.VERIFIED

    band_text = (
        "Prezzo medio di acquisto per fasce orarie* €/MWh "
        "F1: ore di punta F2: ore intermedie F3: ore fuori punta "
        "*come definite dalla delibera dell'ARERA n°181 del 2006 Agosto 2026 "
        "(231 ore) 174,52 (169 ore) 204,35 (344 ore) 171,72"
    )
    monkeypatch.setattr(
        importlib_module,
        "import_module",
        lambda _name: SimpleNamespace(
            PdfReader=lambda _stream: SimpleNamespace(
                is_encrypted=False,
                pages=[SimpleNamespace(extract_text=lambda: band_text)],
            )
        ),
    )
    band_url = (
        "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/"
        "20260902PrezzomedioperfasceAgosto2026.pdf"
    )
    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response(band_url),
    )
    band_report = fetch_monthly_band_report(date(2026, 8, 1), band_url)
    assert band_report.status == VerificationStatus.VERIFIED
    assert len(band_report.provenance) == 3
    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda _request, timeout: Response("https://example.com/report.pdf"),
    )
    with pytest.raises(GmeImportError, match="redirected outside"):
        fetch_monthly_band_report(date(2026, 8, 1), band_url)

    monkeypatch.setattr(
        urllib_request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(GmeImportError, match="acquisition failed for 2025-09"):
        fetch_monthly_report(month)
    with pytest.raises(GmeImportError, match="acquisition failed for 2026-08"):
        fetch_monthly_band_report(date(2026, 8, 1), band_url)

    calls: list[date] = []

    def fetch_fixture(period: date, **_kwargs: object) -> GmeMonthlyIndexSnapshot:
        calls.append(period)
        return next(
            item for item in _reports(date(2026, 9, 27)) if item.parsed.period.start == period
        )

    monkeypatch.setattr(gme, "fetch_monthly_report", fetch_fixture)
    recent = fetch_recent_market_history(date(2026, 9, 27))
    assert calls == list(recent_months(date(2026, 9, 27)))
    assert len(recent.reports) == 12

    with pytest.raises(GmeImportError, match="period must start on day one"):
        report_url(date(2025, 9, 2))
