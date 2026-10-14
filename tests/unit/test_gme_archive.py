from __future__ import annotations

import calendar
import urllib.error
import xml.etree.ElementTree as ET
import xml.sax.saxutils
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from email.message import Message
from hashlib import sha256
from io import BytesIO
from urllib import request as urllib_request
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

import italian_energy.market.gme as gme
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.market.gme import (
    GmeImportError,
    GmeMonthlyIndexSnapshot,
    GmeReportNotFound,
    annual_archive_url,
    fetch_monthly_report,
    fetch_recent_market_history,
    parse_annual_market_archive,
    recent_months,
    report_url,
)

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_RETRIEVED = datetime(2026, 10, 8, 12, tzinfo=UTC)


def _expected_periods(day: date) -> int:
    start = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo("Europe/Rome"))
    end = datetime.combine(day + timedelta(days=1), datetime.min.time()).replace(
        tzinfo=ZoneInfo("Europe/Rome")
    )
    return int((end.astimezone(UTC) - start.astimezone(UTC)).total_seconds() // 900)


def _month_rows(
    month_start: date,
    *,
    prices: tuple[str, ...] = ("207.5422170555555555555555",),
) -> list[tuple[date, int, int, str]]:
    rows: list[tuple[date, int, int, str]] = []
    days = calendar.monthrange(month_start.year, month_start.month)[1]
    for day_number in range(1, days + 1):
        day = date(month_start.year, month_start.month, day_number)
        for period in range(1, _expected_periods(day) + 1):
            hour = (period - 1) // 4 + 1
            price = prices[(period - 1) % len(prices)]
            rows.append((day, hour, period, price))
    return rows


def _worksheet_xml(
    month_starts: tuple[date, ...],
    *,
    mutation: str | None = None,
    prices: tuple[str, ...] = ("207.5422170555555555555555",),
) -> bytes:
    rows = [row for month in month_starts for row in _month_rows(month, prices=prices)]
    if mutation == "gap":
        rows.pop(4)
    elif mutation == "duplicate":
        rows[4] = rows[3]
    elif mutation == "missing_price":
        rows[4] = (*rows[4][:3], "")
    elif mutation == "non_finite":
        rows[4] = (*rows[4][:3], "Infinity")
    elif mutation == "bad_period":
        rows[4] = (*rows[4][:2], 99, rows[4][3])
    elif mutation == "bad_price":
        rows[4] = (*rows[4][:3], "not-a-decimal")
    elif mutation == "missing_day":
        rows = [row for row in rows if row[0].day != 2]
    elif mutation == "final_period_gap":
        rows.pop()
    elif mutation == "incomplete_day":
        rows.pop(95)

    header = (
        "   Data/Date\n(YYYYMMDD)",
        "Ora\n/Hour",
        "Periodo\n/Period",
        "PUN INDEX GME",
    )
    shared = (*header, *(str(number) for number in range(1, 101)))
    shared_index = {value: index for index, value in enumerate(shared)}
    strings_xml = "".join(f"<si><t>{xml.sax.saxutils.escape(value)}</t></si>" for value in shared)
    shared_xml = (
        f'<sst xmlns="{_NS}" count="{len(shared)}" uniqueCount="{len(shared)}">{strings_xml}</sst>'
    )
    row_xml = [
        '<row r="1">'
        + "".join(
            f'<c r="{column}1" t="s"><v>{shared_index[value]}</v></c>'
            for column, value in zip(("A", "B", "C", "D"), header, strict=True)
        )
        + "</row>"
    ]
    for row_number, (day, hour, period, price) in enumerate(rows, start=2):
        cells = [
            f'<c r="A{row_number}"><v>{day:%Y%m%d}</v></c>',
            f'<c r="B{row_number}"><v>{hour}</v></c>',
            f'<c r="C{row_number}" t="s"><v>{shared_index[str(period)]}</v></c>',
        ]
        if mutation == "formula" and row_number == 6:
            cells.append(f'<c r="D{row_number}"><f>100+1</f><v>101</v></c>')
        elif price:
            cells.append(f'<c r="D{row_number}"><v>{price}</v></c>')
        else:
            cells.append(f'<c r="D{row_number}"/>')
        if mutation == "missing_required_cell" and row_number == 6:
            cells.pop(2)
        row_xml.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    sheet_xml = f'<worksheet xmlns="{_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    if mutation == "invalid_date":
        sheet_xml = sheet_xml.replace("<v>20260901</v>", "<v>20260231</v>", 1)
    elif mutation == "invalid_date_token":
        sheet_xml = sheet_xml.replace("<v>20260901</v>", "<v>2026-09-01</v>", 1)
    elif mutation == "outside_year":
        sheet_xml = sheet_xml.replace("<v>20260901</v>", "<v>20250901</v>", 1)
    elif mutation == "row_sequence":
        sheet_xml = sheet_xml.replace('<row r="6">', '<row r="7">', 1)
    elif mutation == "missing_row_number":
        sheet_xml = sheet_xml.replace('<row r="2">', "<row>", 1)
    elif mutation == "duplicate_cell":
        sheet_xml = sheet_xml.replace(
            '<c r="D6"><v>207.5422170555555555555555</v></c>',
            '<c r="D6"><v>207.5422170555555555555555</v></c>'
            '<c r="D6"><v>207.5422170555555555555555</v></c>',
            1,
        )
    elif mutation == "malformed_sheet":
        sheet_xml = sheet_xml[:-12]
    elif mutation == "empty_sheet":
        sheet_xml = f'<worksheet xmlns="{_NS}"><sheetData/></worksheet>'
    workbook_xml = (
        f'<workbook xmlns="{_NS}" xmlns:r="{_R_NS}"><sheets>'
        '<sheet name="Legenda" sheetId="4" r:id="rId1"/>'
        '<sheet name="Prezzi-Prices" sheetId="9" r:id="rId2"/>'
        "</sheets></workbook>"
    )
    rels_xml = (
        f'<Relationships xmlns="{_PKG_NS}">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet3.xml"/>'
        '<Relationship Id="rId3" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
    book = BytesIO()
    with ZipFile(book, "w", ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", b"<worksheet/>")
        archive.writestr("xl/worksheets/sheet3.xml", sheet_xml)
    return book.getvalue()


def _annual_zip(
    month_starts: tuple[date, ...],
    *,
    mutation: str | None = None,
    filename_month: int = 9,
) -> bytes:
    year = month_starts[0].year
    workbook = _worksheet_xml(month_starts, mutation=mutation)
    outer = BytesIO()
    with ZipFile(outer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(f"Anno {year}_{filename_month:02d}_15.xlsx", workbook)
        archive.writestr(f"Anno {year}_{filename_month:02d}_60.xlsx", b"control series")
    return outer.getvalue()


def test_official_archive_parser_uses_decimal_tokens_and_relationship_named_sheet() -> None:
    month = date(2026, 9, 1)
    zip_bytes = _annual_zip((month,))
    expected = Decimal("207.5422170555555555555555")

    snapshots = parse_annual_market_archive(
        zip_bytes,
        year=2026,
        period_starts=(month,),
        retrieved_at=_RETRIEVED,
    )

    snapshot = snapshots[month]
    assert snapshot.status == VerificationStatus.VERIFIED
    assert snapshot.parsed.published_value_eur_per_mwh == expected
    assert snapshot.parsed.value_eur_per_kwh == expected / Decimal(1000)
    provenance = snapshot.provenance
    assert provenance.url == annual_archive_url(2026)
    assert provenance.sha256 == sha256(zip_bytes).hexdigest()
    assert provenance.source_identifier == "MGP-monthly-baseload:2026-09"
    assert provenance.effective_period == DatePeriod(start=month, end=date(2026, 10, 1))
    assert provenance.locator is not None
    assert provenance.locator.document == "Anno 2026_09_15.xlsx"
    assert provenance.locator.sheet == "Prezzi-Prices"
    assert provenance.locator.cell == "D2:D2881"
    restored = GmeMonthlyIndexSnapshot.model_validate(snapshot.model_dump(mode="python"))
    assert restored == snapshot
    invalid = snapshot.model_dump(mode="python")
    invalid["provenance"]["url"] = "https://example.com/Anno2026.zip"
    with pytest.raises(ValidationError):
        GmeMonthlyIndexSnapshot.model_validate(invalid)


@pytest.mark.parametrize("month, expected", ((date(2026, 3, 1), 92), (date(2025, 10, 1), 100)))
def test_official_archive_parser_accepts_europe_rome_dst_period_counts(
    month: date, expected: int
) -> None:
    zip_bytes = _annual_zip((month,), filename_month=12 if month.year == 2025 else 9)
    snapshots = parse_annual_market_archive(
        zip_bytes,
        year=month.year,
        period_starts=(month,),
        retrieved_at=_RETRIEVED,
    )
    locator = snapshots[month].provenance.locator
    assert locator is not None
    expected_end_row = 1 + sum(
        _expected_periods(date(month.year, month.month, day_number))
        for day_number in range(1, calendar.monthrange(month.year, month.month)[1] + 1)
    )
    assert locator.cell == f"D2:D{expected_end_row}"
    transition_day = next(
        date(month.year, month.month, day_number)
        for day_number in range(1, calendar.monthrange(month.year, month.month)[1] + 1)
        if _expected_periods(date(month.year, month.month, day_number)) != 96
    )
    assert _expected_periods(transition_day) == expected


@pytest.mark.parametrize(
    "mutation",
    (
        "gap",
        "duplicate",
        "missing_price",
        "non_finite",
        "formula",
        "bad_period",
        "bad_price",
        "missing_day",
        "final_period_gap",
        "incomplete_day",
        "missing_required_cell",
        "invalid_date",
        "invalid_date_token",
        "outside_year",
        "row_sequence",
        "missing_row_number",
        "duplicate_cell",
        "malformed_sheet",
        "empty_sheet",
    ),
)
def test_official_archive_parser_rejects_incomplete_or_ambiguous_intervals(
    mutation: str,
) -> None:
    month = date(2026, 9, 1)
    with pytest.raises(GmeImportError):
        parse_annual_market_archive(
            _annual_zip((month,), mutation=mutation),
            year=2026,
            period_starts=(month,),
            retrieved_at=_RETRIEVED,
        )


@pytest.mark.parametrize("mutation", ("missing_15", "unsafe_path", "malformed_xml"))
def test_official_archive_parser_rejects_unsafe_or_incomplete_zip(
    mutation: str,
) -> None:
    month = date(2026, 9, 1)
    good_book = _worksheet_xml((month,))
    outer = BytesIO()
    with ZipFile(outer, "w", ZIP_DEFLATED) as archive:
        if mutation == "unsafe_path":
            archive.writestr("../Anno 2026_09_15.xlsx", good_book)
        elif mutation == "malformed_xml":
            bad_book = BytesIO()
            with ZipFile(bad_book, "w", ZIP_DEFLATED) as workbook:
                workbook.writestr(
                    "xl/workbook.xml",
                    b"<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///etc/passwd'>]><x>&e;</x>",
                )
                workbook.writestr("xl/_rels/workbook.xml.rels", b"<Relationships/>")
            archive.writestr("Anno 2026_09_15.xlsx", bad_book.getvalue())
            archive.writestr("Anno 2026_09_60.xlsx", b"control series")
        else:
            archive.writestr("Anno 2026_09_60.xlsx", b"control series")
    with pytest.raises(GmeImportError):
        parse_annual_market_archive(
            outer.getvalue(),
            year=2026,
            period_starts=(month,),
            retrieved_at=_RETRIEVED,
        )


@pytest.mark.parametrize(
    ("limit_name", "limit"),
    (
        ("MAX_ARCHIVE_DOWNLOAD_BYTES", 16),
        ("MAX_WORKBOOK_BYTES", 16),
        ("MAX_OOXML_BYTES", 16),
        ("MAX_OOXML_PART_BYTES", 16),
        ("MAX_WORKSHEET_ROWS", 10),
    ),
)
def test_official_archive_parser_enforces_size_and_row_limits(
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit: int,
) -> None:
    month = date(2026, 9, 1)
    monkeypatch.setattr(gme, limit_name, limit)
    with pytest.raises(GmeImportError):
        parse_annual_market_archive(
            _annual_zip((month,)),
            year=2026,
            period_starts=(month,),
            retrieved_at=_RETRIEVED,
        )


def test_official_redirects_are_host_bound_and_limited_to_three() -> None:
    handler = gme._OfficialRedirectHandler()
    request = urllib_request.Request(report_url(date(2026, 9, 1)))
    for index in range(3):
        next_request = handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            f"https://gme.mercatoelettrico.org/redirect/{index}",
        )
        assert next_request is not None
        request = next_request
    with pytest.raises(GmeImportError, match="maximum of three"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://gme.mercatoelettrico.org/redirect/4",
        )
    with pytest.raises(GmeImportError, match="outside the official HTTPS host"):
        gme._OfficialRedirectHandler().redirect_request(
            urllib_request.Request(report_url(date(2026, 9, 1))),
            None,
            302,
            "Found",
            {},
            "https://example.com/report.pdf",
        )


def test_report_pdf_fallback_signal_is_only_explicit_http_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    month = date(2026, 9, 1)

    def fail_with(status: int) -> None:
        raise urllib.error.HTTPError(report_url(month), status, "response", Message(), None)

    monkeypatch.setattr(gme, "_open_official", lambda *_args, **_kwargs: fail_with(404))
    with pytest.raises(GmeReportNotFound):
        fetch_monthly_report(month)

    monkeypatch.setattr(gme, "_open_official", lambda *_args, **_kwargs: fail_with(503))
    with pytest.raises(GmeImportError, match="HTTP 503"):
        fetch_monthly_report(month)

    monkeypatch.setattr(
        gme,
        "_open_official",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(GmeImportError, match="acquisition failed"):
        fetch_monthly_report(month)


def test_recent_history_falls_back_only_for_404_and_reuses_one_zip_per_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of = date(2026, 10, 8)
    months = recent_months(as_of)
    fallback_months = (date(2026, 8, 1), date(2026, 9, 1))
    archive_bytes = _annual_zip(fallback_months)
    downloaded: list[int] = []

    def fetch_pdf(month: date, **_kwargs: object) -> GmeMonthlyIndexSnapshot:
        if month in fallback_months:
            raise GmeReportNotFound(f"missing {month}")
        from test_gme import _reports

        return next(item for item in _reports(as_of) if item.parsed.period.start == month)

    monkeypatch.setattr(gme, "fetch_monthly_report", fetch_pdf)

    def download_archive(year: int, **_kwargs: object) -> tuple[bytes, datetime]:
        downloaded.append(year)
        return archive_bytes, _RETRIEVED

    monkeypatch.setattr(gme, "_download_annual_archive", download_archive)

    history = fetch_recent_market_history(as_of)

    assert len(history.reports) == 12
    assert tuple(item.parsed.period.start for item in history.reports) == months
    assert downloaded == [2026]
    assert [
        item.provenance.url
        for item in history.reports
        if item.parsed.period.start in fallback_months
    ] == [
        annual_archive_url(2026),
        annual_archive_url(2026),
    ]
    assert all(item.status == VerificationStatus.VERIFIED for item in history.reports)


def test_recent_history_does_not_fallback_for_pdf_parsing_or_network_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of = date(2026, 10, 8)
    downloaded: list[int] = []
    first_month = recent_months(as_of)[0]

    def fail(month: date, **_kwargs: object) -> GmeMonthlyIndexSnapshot:
        if month == first_month:
            raise GmeImportError("PDF parsing failed")
        raise AssertionError("later months should not be fetched after a source failure")

    monkeypatch.setattr(gme, "fetch_monthly_report", fail)
    monkeypatch.setattr(
        gme,
        "_download_annual_archive",
        lambda year, **_kwargs: downloaded.append(year),
    )
    with pytest.raises(GmeImportError, match="PDF parsing failed"):
        fetch_recent_market_history(as_of)
    assert downloaded == []


def test_official_archive_url_is_exact_https_year_url() -> None:
    assert annual_archive_url(2026).startswith(
        "https://gme.mercatoelettrico.org/Home/Esiti/Elettricita/MGP/Statistiche/DatiStorici/"
    )
    assert annual_archive_url(2026).endswith("fileName=Anno2026.zip")
    with pytest.raises(GmeImportError):
        annual_archive_url(999)


class _FakeDownloadResponse:
    def __init__(self, content: bytes, final_url: str | None = None) -> None:
        self.content = content
        self.final_url = final_url or annual_archive_url(2026)
        self.read_limit: int | None = None

    def __enter__(self) -> _FakeDownloadResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, limit: int) -> bytes:
        self.read_limit = limit
        return self.content[:limit]


def test_annual_archive_download_checks_redirect_and_content_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeDownloadResponse(b"zip-content")
    monkeypatch.setattr(gme, "_open_official", lambda *_args, **_kwargs: response)
    content, retrieved_at = gme._download_annual_archive(2026)
    assert content == b"zip-content"
    assert retrieved_at.tzinfo is not None
    assert response.read_limit == gme.MAX_ARCHIVE_DOWNLOAD_BYTES + 1

    monkeypatch.setattr(
        gme,
        "_open_official",
        lambda *_args, **_kwargs: _FakeDownloadResponse(
            b"content", "https://example.com/Anno2026.zip"
        ),
    )
    with pytest.raises(GmeImportError, match="redirected outside"):
        gme._download_annual_archive(2026)

    monkeypatch.setattr(gme, "MAX_ARCHIVE_DOWNLOAD_BYTES", 3)
    monkeypatch.setattr(gme, "_open_official", lambda *_args, **_kwargs: _FakeDownloadResponse(b""))
    with pytest.raises(GmeImportError, match="empty or exceeds"):
        gme._download_annual_archive(2026)
    monkeypatch.setattr(
        gme, "_open_official", lambda *_args, **_kwargs: _FakeDownloadResponse(b"four")
    )
    with pytest.raises(GmeImportError, match="empty or exceeds"):
        gme._download_annual_archive(2026)


@pytest.mark.parametrize(
    "failure",
    (
        urllib.error.HTTPError("url", 503, "unavailable", Message(), None),
        urllib.error.URLError("offline"),
        TimeoutError("timed out"),
    ),
)
def test_annual_archive_download_wraps_http_and_network_errors(
    monkeypatch: pytest.MonkeyPatch, failure: BaseException
) -> None:
    def fail(*_args: object, **_kwargs: object) -> _FakeDownloadResponse:
        raise failure

    monkeypatch.setattr(gme, "_open_official", fail)
    with pytest.raises(GmeImportError, match="acquisition failed"):
        gme._download_annual_archive(2026)


@pytest.mark.parametrize(
    ("year", "period_starts", "retrieved_at", "content"),
    (
        (2024, (date(2026, 9, 1),), _RETRIEVED, b"archive"),
        (2026, (), _RETRIEVED, b"archive"),
        (2026, (date(2026, 9, 1), date(2026, 9, 1)), _RETRIEVED, b"archive"),
        (2026, (date(2026, 9, 2),), _RETRIEVED, b"archive"),
        (2025, (date(2025, 9, 1),), _RETRIEVED, b"archive"),
        (2026, (date(2026, 9, 1),), datetime(2026, 10, 8), b"archive"),
        (2026, (date(2026, 9, 1),), _RETRIEVED, b""),
        (2026, (date(2026, 9, 1),), _RETRIEVED, b"not a zip"),
    ),
)
def test_annual_archive_parser_rejects_invalid_request_or_container(
    monkeypatch: pytest.MonkeyPatch,
    year: int,
    period_starts: tuple[date, ...],
    retrieved_at: datetime,
    content: bytes,
) -> None:
    if content == b"archive":
        content = _annual_zip((date(2026, 9, 1),))
    if content == b"":
        pass
    if content == b"not a zip":
        monkeypatch.setattr(gme, "MAX_ARCHIVE_DOWNLOAD_BYTES", 100)
    with pytest.raises(GmeImportError):
        parse_annual_market_archive(
            content,
            year=year,
            period_starts=period_starts,
            retrieved_at=retrieved_at,
        )


@pytest.mark.parametrize("mutation", ("bad_header", "duplicate_header"))
def test_annual_archive_parser_rejects_ambiguous_headers(mutation: str) -> None:
    cells = {
        "A": ET.fromstring(
            f'<c xmlns="{_NS}" r="A1" t="inlineStr"><is><t>Data/Date (YYYYMMDD)</t></is></c>'
        ),
        "B": ET.fromstring(f'<c xmlns="{_NS}" r="B1" t="inlineStr"><is><t>Ora/Hour</t></is></c>'),
        "C": ET.fromstring(
            f'<c xmlns="{_NS}" r="C1" t="inlineStr"><is><t>Periodo/Period</t></is></c>'
        ),
        "D": ET.fromstring(
            f'<c xmlns="{_NS}" r="D1" t="inlineStr"><is><t>PUN INDEX GME</t></is></c>'
        ),
    }
    if mutation == "bad_header":
        cells.pop("D")
    else:
        cells["E"] = ET.fromstring(
            f'<c xmlns="{_NS}" r="E1" t="inlineStr"><is><t>PUN INDEX GME</t></is></c>'
        )
    with pytest.raises(GmeImportError):
        gme._resolve_gme_header(cells, ())


@pytest.mark.parametrize(
    ("cell_xml", "numeric", "message"),
    (
        ('<c xmlns="' + _NS + '" t="s"><v>x</v></c>', False, "index is invalid"),
        ('<c xmlns="' + _NS + '" t="s"><v>9</v></c>', False, "outside its table"),
        ('<c xmlns="' + _NS + '" t="s"><v>0</v></c>', True, "shared string"),
        ('<c xmlns="' + _NS + '" t="inlineStr"><is><t>42</t></is></c>', True, "inline text"),
        ('<c xmlns="' + _NS + '" t="b"><v>1</v></c>', False, "unsupported"),
        ('<c xmlns="' + _NS + '"><v> </v></c>', False, "missing required"),
    ),
)
def test_cell_value_rejects_unsupported_or_missing_xlsx_values(
    cell_xml: str, numeric: bool, message: str
) -> None:
    cell = ET.fromstring(cell_xml)
    with pytest.raises(GmeImportError, match=message):
        gme._cell_value(cell, (), numeric=numeric)


def test_cell_value_reads_numeric_and_inline_strings_without_conversion() -> None:
    numeric = ET.fromstring(f'<c xmlns="{_NS}"><v> 207.5001 </v></c>')
    inline = ET.fromstring(f'<c xmlns="{_NS}" t="inlineStr"><is><t>label</t></is></c>')
    shared = ET.fromstring(f'<c xmlns="{_NS}" t="s"><v>0</v></c>')
    assert gme._cell_value(numeric, (), numeric=True) == "207.5001"
    assert gme._cell_value(inline, ()) == "label"
    assert gme._cell_value(shared, ("shared",)) == "shared"


@pytest.mark.parametrize("mutation", ("unexpected_path", "different_editions", "duplicate_member"))
def test_annual_zip_rejects_unexpected_or_ambiguous_members(mutation: str) -> None:
    month = date(2026, 9, 1)
    workbook = _worksheet_xml((month,))
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        if mutation == "unexpected_path":
            archive.writestr("README.txt", b"unexpected")
            archive.writestr("Anno 2026_09_15.xlsx", workbook)
            archive.writestr("Anno 2026_09_60.xlsx", b"control")
        elif mutation == "different_editions":
            archive.writestr("Anno 2026_08_15.xlsx", workbook)
            archive.writestr("Anno 2026_09_60.xlsx", b"control")
        else:
            archive.writestr("Anno 2026_09_15.xlsx", workbook)
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("Anno 2026_09_15.xlsx", workbook)
            archive.writestr("Anno 2026_09_60.xlsx", b"control")
    with pytest.raises(GmeImportError):
        parse_annual_market_archive(
            output.getvalue(),
            year=2026,
            period_starts=(month,),
            retrieved_at=_RETRIEVED,
        )


def test_annual_zip_rejects_symbolic_link_member() -> None:
    month = date(2026, 9, 1)
    workbook = _worksheet_xml((month,))
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        info = ZipInfo("Anno 2026_09_15.xlsx")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, workbook)
        archive.writestr("Anno 2026_09_60.xlsx", b"control")
    with pytest.raises(GmeImportError, match="symbolic-link"):
        parse_annual_market_archive(
            output.getvalue(),
            year=2026,
            period_starts=(month,),
            retrieved_at=_RETRIEVED,
        )


def test_workbook_rejects_duplicate_ooxml_parts_and_missing_required_part() -> None:
    month = date(2026, 9, 1)
    valid = _worksheet_xml((month,))
    duplicate = BytesIO()
    with ZipFile(duplicate, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr("xl/workbook.xml", b"<workbook/>")
        with pytest.warns(UserWarning, match="Duplicate name"):
            workbook.writestr("xl/workbook.xml", b"<workbook/>")
    missing = BytesIO()
    with ZipFile(missing, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr("xl/workbook.xml", b"<workbook/>")
    for archive_bytes in (duplicate.getvalue(), missing.getvalue()):
        output = BytesIO()
        with ZipFile(output, "w", ZIP_DEFLATED) as archive:
            archive.writestr("Anno 2026_09_15.xlsx", archive_bytes)
            archive.writestr("Anno 2026_09_60.xlsx", b"control")
        with pytest.raises(GmeImportError):
            parse_annual_market_archive(
                output.getvalue(),
                year=2026,
                period_starts=(month,),
                retrieved_at=_RETRIEVED,
            )

    # The direct call reaches the workbook reader past its required OOXML envelope.
    with ZipFile(BytesIO(valid)) as workbook:
        parts = {info.filename: info for info in workbook.infolist()}
        with pytest.raises(GmeImportError, match="missing required OOXML part"):
            gme._read_ooxml_part(workbook, parts, "xl/not-present.xml")


@pytest.mark.parametrize(
    ("workbook_body", "relationships_body"),
    (
        ("<workbook/>", "<Relationships/>"),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Other" r:id="rId1"/></sheets></workbook>',
            "<Relationships/>",
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1"/>',
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1" Type="worksheet" Target="sheet.xml" TargetMode="External"/>',
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet2" '
            'Target="sheet.xml"/>',
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="missing"/></sheets></workbook>',
            "<Relationships/>",
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1" Type="http://example.com/not-a-worksheet" '
            'Target="sheet.xml"/>',
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="../escape.xml"/>',
        ),
        (
            '<workbook xmlns:r="' + _R_NS + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/>'
            '<sheet name="Prezzi-Prices" r:id="rId2"/></sheets></workbook>',
            "<Relationships/>",
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/sharedStrings" '
            'Target="shared.xml"/>'
            '<Relationship Id="rId3" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/sharedStrings" '
            'Target="other.xml"/>',
        ),
        (
            '<workbook xmlns:r="'
            + _R_NS
            + '"><sheets><sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>',
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/sharedStrings" '
            'Target="shared.xml"/>'
            '<Relationship Id="rId3" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/sharedStrings" '
            'Target="other.xml"/>',
        ),
    ),
)
def test_workbook_relationships_fail_closed(workbook_body: str, relationships_body: str) -> None:
    workbook_xml = workbook_body.replace("<workbook", f'<workbook xmlns="{_NS}"', 1)
    relationships_xml = f'<Relationships xmlns="{_PKG_NS}">{relationships_body}</Relationships>'
    workbook_root = gme._parse_safe_xml(workbook_xml.encode(), "test workbook")
    relationships_root = gme._parse_safe_xml(relationships_xml.encode(), "test relationships")
    with pytest.raises(GmeImportError):
        gme._resolve_workbook_parts(workbook_root, relationships_root)


def test_relationship_paths_and_optional_shared_strings_are_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for unsafe in ("../escape.xml", "xl/../../escape.xml", "/outside.xml", "sheet.xml?query=1"):
        with pytest.raises(GmeImportError):
            gme._resolve_internal_target(unsafe)
    assert gme._resolve_internal_target("worksheets/sheet3.xml") == "xl/worksheets/sheet3.xml"

    archive = BytesIO()
    with ZipFile(archive, "w", ZIP_DEFLATED) as workbook:
        workbook.writestr("xl/sharedStrings.xml", b"<!DOCTYPE x [<!ENTITY x 'bad'>]><sst>&x;</sst>")
        workbook.writestr("xl/large.xml", b"123456")
    with ZipFile(BytesIO(archive.getvalue())) as workbook:
        parts = {info.filename: info for info in workbook.infolist()}
        assert gme._read_shared_strings(workbook, parts, None) == ()
        with pytest.raises(GmeImportError, match="shared strings are malformed"):
            gme._read_shared_strings(workbook, parts, "xl/sharedStrings.xml")
        monkeypatch.setattr(gme, "MAX_OOXML_PART_BYTES", 3)
        with pytest.raises(GmeImportError, match="64 MiB limit"):
            gme._read_ooxml_part(workbook, parts, "xl/large.xml")


def test_workbook_relationships_allow_a_valid_sheet_without_shared_strings() -> None:
    workbook_root = gme._parse_safe_xml(
        (
            f'<workbook xmlns="{_NS}" xmlns:r="{_R_NS}"><sheets>'
            '<sheet name="Prezzi-Prices" r:id="rId1"/></sheets></workbook>'
        ).encode(),
        "test workbook",
    )
    relationships_root = gme._parse_safe_xml(
        (
            f'<Relationships xmlns="{_PKG_NS}">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            'Target="worksheets/sheet3.xml"/></Relationships>'
        ).encode(),
        "test relationships",
    )
    assert gme._resolve_workbook_parts(workbook_root, relationships_root) == (
        "xl/worksheets/sheet3.xml",
        None,
    )
