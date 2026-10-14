"""Verified acquisition of the GME monthly PUN Index GME baseload reports."""

from __future__ import annotations

import calendar
import importlib
import posixpath
import re
import stat
import urllib.error
import urllib.request
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
from io import BytesIO
from typing import Any, cast
from urllib.parse import urljoin, urlsplit
from zipfile import ZipFile, ZipInfo
from zoneinfo import ZoneInfo

from defusedxml import ElementTree as SafeET  # type: ignore[import-untyped, unused-ignore]
from pydantic import Field, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.money import RateUnit
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval

GME_DOCUMENT_ROOT = "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/"
GME_ARCHIVE_ROOT = (
    "https://gme.mercatoelettrico.org/Home/Esiti/Elettricita/MGP/Statistiche/DatiStorici/"
    "moduleId/10874/controller/GmeDatiStoriciItem/action/DownloadFile?fileName=Anno"
)
GME_INDEX_DEFINITION_URL = (
    "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20250101DTF25MPE.pdf"
)
GME_INDEX_DEFINITION_SHA256 = "f380f542d9b99166c453f3e0e5e29c1c43921bb254374fa3834695ba2d19ee5c"
MAX_REPORT_BYTES = 3_000_000
MAX_REPORT_PAGES = 3
MAX_ARCHIVE_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_WORKBOOK_BYTES = 48 * 1024 * 1024
MAX_OOXML_BYTES = 320 * 1024 * 1024
MAX_OOXML_PART_BYTES = 64 * 1024 * 1024
MAX_WORKSHEET_ROWS = 40_000
MAX_OFFICIAL_REDIRECTS = 3
GME_MEAN_PRECISION = 50
_XML_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_XML_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XML_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_ARCHIVE_MEMBER = re.compile(r"Anno ([0-9]{4})_([0-9]{2})_(15|60)\.xlsx\Z")
_CELL_REFERENCE = re.compile(r"([A-Z]{1,3})([1-9][0-9]*)\Z")
_MONTH_NAMES = (
    "gennaio",
    "febbraio",
    "marzo",
    "aprile",
    "maggio",
    "giugno",
    "luglio",
    "agosto",
    "settembre",
    "ottobre",
    "novembre",
    "dicembre",
)
_PRICE = re.compile(r"([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),([0-9]{2})(?![0-9])")


class GmeImportError(ValueError):
    """The official GME report is missing or does not match the supported layout."""


class GmeReportNotFound(GmeImportError):
    """The exact official monthly PDF URL returned HTTP 404."""


def _decimal_power_of_ten(value: Decimal, exponent_delta: int) -> Decimal:
    parts = value.as_tuple()
    if not isinstance(parts.exponent, int):
        raise ValueError("decimal scale requires a finite value")
    return Decimal((parts.sign, parts.digits, parts.exponent + exponent_delta))


class ParsedGmeBaseload(DomainModel):
    """A monthly Baseload value parsed from a GME MGP report."""

    period: DatePeriod
    published_value_eur_per_mwh: Decimal
    value_eur_per_kwh: Decimal
    published_unit: RateUnit = RateUnit.EUR_PER_MWH
    unit: RateUnit = RateUnit.EUR_PER_KWH
    granularity: Granularity = Granularity.MONTH
    index_code: str = "PUN"

    @model_validator(mode="after")
    def validate_period_and_value(self) -> ParsedGmeBaseload:
        if self.period.end != _add_months(self.period.start, 1):
            raise ValueError("GME baseload period must cover one complete calendar month")
        if self.period.start.day != 1:
            raise ValueError("GME baseload period must start at the beginning of a month")
        if self.value_eur_per_kwh < 0:
            raise ValueError("GME baseload price cannot be negative")
        if (
            self.published_unit != RateUnit.EUR_PER_MWH
            or self.value_eur_per_kwh != _decimal_power_of_ten(self.published_value_eur_per_mwh, -3)
        ):
            raise ValueError("GME baseload conversion must preserve the published EUR/MWh value")
        if self.unit != RateUnit.EUR_PER_KWH or self.granularity != Granularity.MONTH:
            raise ValueError("GME baseload must be a monthly EUR/kWh index")
        if self.index_code != "PUN":
            raise ValueError("GME monthly baseload is supported as the PUN index only")
        return self


class ParsedGmeBandPrice(DomainModel):
    """One published average purchase price for an ARERA time band."""

    index_code: str
    period: DatePeriod
    band: str
    hours: int = Field(gt=0)
    published_value_eur_per_mwh: Decimal
    value_eur_per_kwh: Decimal
    unit: RateUnit = RateUnit.EUR_PER_KWH
    published_unit: RateUnit = RateUnit.EUR_PER_MWH
    granularity: Granularity = Granularity.MONTH

    @model_validator(mode="after")
    def validate_observation(self) -> ParsedGmeBandPrice:
        if self.band not in {"F1", "F2", "F3"}:
            raise ValueError("GME time band must be F1, F2 or F3")
        if self.index_code != f"GME_MGP_AVERAGE_PURCHASE_{self.band}":
            raise ValueError("GME average-purchase series must keep its distinct code")
        if self.value_eur_per_kwh < 0 or self.published_value_eur_per_mwh < 0:
            raise ValueError("GME band price cannot be negative")
        if self.value_eur_per_kwh != self.published_value_eur_per_mwh.scaleb(-3):
            raise ValueError("GME band conversion must preserve the published EUR/MWh value")
        if self.unit != RateUnit.EUR_PER_KWH or self.granularity != Granularity.MONTH:
            raise ValueError("GME band observations must be monthly EUR/kWh")
        return self


class ParsedGmeBandReport(DomainModel):
    """Three monthly time-band averages as published by the GME report."""

    period: DatePeriod
    prices: tuple[ParsedGmeBandPrice, ...]
    definition: str = "ARERA Deliberation 181/06 time bands"

    @model_validator(mode="after")
    def validate_report(self) -> ParsedGmeBandReport:
        if tuple(item.band for item in self.prices) != ("F1", "F2", "F3"):
            raise ValueError("GME band report must contain F1, F2 and F3 in published order")
        if any(item.period != self.period for item in self.prices):
            raise ValueError("GME band periods must match their report month")
        expected_hours = (
            calendar.monthrange(self.period.start.year, self.period.start.month)[1] * 24
        )
        if sum(item.hours for item in self.prices) != expected_hours:
            raise ValueError("GME band hours do not add up to the report month")
        return self


class GmeMonthlyIndexSnapshot(DomainModel):
    """One report value with acquisition state and source provenance."""

    parsed: ParsedGmeBaseload
    status: VerificationStatus
    provenance: Provenance

    @model_validator(mode="after")
    def validate_source(self) -> GmeMonthlyIndexSnapshot:
        if self.provenance.effective_period != self.parsed.period:
            raise ValueError("GME provenance period must match the report month")
        if self.status == VerificationStatus.VERIFIED and (
            not is_official_gme_monthly_provenance(self.provenance, self.parsed.period)
        ):
            raise ValueError(
                "verified GME data requires official URL and raw digest for PDF or ZIP provenance"
            )
        return self


class GmeBandReportSnapshot(DomainModel):
    """A GME band report with document digest and per-band table provenance."""

    parsed: ParsedGmeBandReport
    status: VerificationStatus
    provenance: tuple[Provenance, ...]

    @model_validator(mode="after")
    def validate_snapshot(self) -> GmeBandReportSnapshot:
        if len(self.provenance) != 3:
            raise ValueError("GME band snapshot must preserve one locator per time band")
        if any(
            item.effective_period != self.parsed.period or not item.sha256
            for item in self.provenance
        ):
            raise ValueError("GME band provenance must preserve report month and source digest")
        if self.status == VerificationStatus.VERIFIED and any(
            item.source != "GME" or not _official_document_url(item.url or "")
            for item in self.provenance
        ):
            raise ValueError("verified GME band report requires official GME URLs")
        return self


class GmeMarketHistory(DomainModel):
    """An exact and source-verified monthly PUN window."""

    as_of: date
    status: VerificationStatus
    reports: tuple[GmeMonthlyIndexSnapshot, ...]
    market_data: MarketData

    @model_validator(mode="after")
    def validate_complete_window(self) -> GmeMarketHistory:
        expected = recent_months(self.as_of)
        actual = tuple(report.parsed.period.start for report in self.reports)
        if len({report.parsed.period for report in self.reports}) != 12:
            raise ValueError("GME history cannot contain duplicate months")
        if actual != expected:
            raise ValueError("GME history must contain the exact latest twelve complete months")
        if len(self.market_data.points) != len(self.reports):
            raise ValueError("GME history must contain one market point per report")
        point_months = tuple(point.interval.start.date() for point in self.market_data.points)
        if point_months != expected:
            raise ValueError("GME market data points must match all twelve report months")
        for report, point in zip(self.reports, self.market_data.points, strict=True):
            if (
                point.index_code != "PUN"
                or point.interval.start.date() != report.parsed.period.start
                or point.interval.end.date() != report.parsed.period.end
                or point.value != report.parsed.value_eur_per_kwh
                or not any(
                    item.sha256 == report.provenance.sha256
                    and item.effective_period == report.parsed.period
                    for item in point.provenance
                )
            ):
                raise ValueError("GME market point must reproduce its source-backed report value")
        if len(self.market_data.indexes) != 1 or self.market_data.indexes[0].code != "PUN":
            raise ValueError("GME history must expose only the verified PUN index")
        if self.status == VerificationStatus.VERIFIED and any(
            report.status != VerificationStatus.VERIFIED for report in self.reports
        ):
            raise ValueError("GME history cannot be verified while one report is unverified")
        return self


def report_url(period_start: date) -> str:
    """Return the observed official URL for one monthly statistical report."""

    if period_start.day != 1:
        raise GmeImportError("GME report period must start on day one")
    return f"{GME_DOCUMENT_ROOT}{period_start:%Y%m}_Dati_di_sintesi_mensile.pdf"


def recent_months(as_of: date) -> tuple[date, ...]:
    """Return the twelve completed calendar months before the month of as_of."""

    cutoff = as_of.replace(day=1)
    return tuple(_add_months(cutoff, offset) for offset in range(-12, 0))


def parse_monthly_baseload_text(text: str, period_start: date) -> ParsedGmeBaseload:
    """Read only the current-year MGP Baseload row from the first-page table."""

    period = DatePeriod(start=period_start, end=_add_months(period_start, 1))
    normalized = re.sub(r"\s+", " ", text).strip()
    month_name = _MONTH_NAMES[period_start.month - 1]
    title = re.search(
        rf"{re.escape(month_name)}\s*{period_start.year}(?![0-9])",
        normalized,
        flags=re.IGNORECASE,
    )
    market = re.search(r"Mercato\s+del\s+Giorno\s+Prima", normalized, re.IGNORECASE)
    table = re.search(r"Prezzo\s+medio", normalized, re.IGNORECASE)
    unit_year = re.search(
        rf"€/MWh\s*{period_start.year}\s*{period_start.year - 1}(?![0-9])",
        normalized,
        flags=re.IGNORECASE,
    )
    baseload = re.search(r"\bBaseload\b", normalized, re.IGNORECASE)
    if not all((title, market, table, unit_year, baseload)):
        raise GmeImportError("GME report title, period, EUR/MWh table or Baseload row is invalid")
    assert baseload is not None
    assert unit_year is not None
    if not (unit_year.start() < baseload.start()):
        raise GmeImportError("GME report does not contain the expected year column before Baseload")
    price = _PRICE.search(normalized, baseload.end())
    if price is None:
        raise GmeImportError("GME Baseload value is missing")
    try:
        value_eur_per_mwh = Decimal(price.group(1).replace(".", "") + "." + price.group(2))
    except InvalidOperation as exc:
        raise GmeImportError("GME Baseload value is not a decimal price") from exc
    return ParsedGmeBaseload(
        period=period,
        published_value_eur_per_mwh=value_eur_per_mwh,
        value_eur_per_kwh=value_eur_per_mwh.scaleb(-3),
    )


def parse_monthly_band_report_text(text: str, period_start: date) -> ParsedGmeBandReport:
    """Parse GME's average purchase prices without aliasing them to PUN Index GME."""
    period = DatePeriod(start=period_start, end=_add_months(period_start, 1))
    normalized = re.sub(r"\s+", " ", text).strip()
    month_name = _MONTH_NAMES[period_start.month - 1]
    expected_title = re.search(
        r"Prezzo medio di acquisto per fasce orarie", normalized, re.IGNORECASE
    )
    expected_period = re.search(
        rf"{re.escape(month_name)}\s+{period_start.year}(?![0-9])",
        normalized,
        flags=re.IGNORECASE,
    )
    expected_unit = re.search(r"€/MWh|EUR/MWh", normalized, re.IGNORECASE)
    expected_definition = re.search(r"ARERA\s+n[°º]?\s*181\s+del\s+2006", normalized, re.IGNORECASE)
    labels = tuple(re.findall(r"\b(F[123])\s*:\s*ore\b", normalized, flags=re.IGNORECASE))
    if (
        expected_title is None
        or expected_period is None
        or expected_unit is None
        or expected_definition is None
        or tuple(label.upper() for label in labels) != ("F1", "F2", "F3")
    ):
        raise GmeImportError(
            "GME band report title, period, unit or ARERA band definition is invalid"
        )
    data_start = expected_period.end()
    rows = tuple(
        re.finditer(
            r"\(([0-9]{1,3})\s+ore\)\s*([0-9]+),([0-9]{2})(?![0-9])", normalized[data_start:]
        )
    )
    if len(rows) != 3:
        raise GmeImportError("GME band report must contain exactly three hour-weighted prices")
    prices = tuple(
        ParsedGmeBandPrice(
            index_code=f"GME_MGP_AVERAGE_PURCHASE_{band}",
            period=period,
            band=band,
            hours=int(row.group(1)),
            published_value_eur_per_mwh=Decimal(row.group(2) + "." + row.group(3)),
            value_eur_per_kwh=Decimal(row.group(2) + "." + row.group(3)).scaleb(-3),
        )
        for band, row in zip(("F1", "F2", "F3"), rows, strict=True)
    )
    try:
        return ParsedGmeBandReport(period=period, prices=prices)
    except ValueError as exc:
        raise GmeImportError("GME band report prices do not match the published month") from exc


def parse_monthly_report_bytes(
    content: bytes,
    period_start: date,
    retrieved_at: datetime,
    *,
    source_url: str | None = None,
) -> GmeMonthlyIndexSnapshot:
    """Parse bytes as evidence only; offline bytes do not become VERIFIED."""

    if not content or len(content) > MAX_REPORT_BYTES or not content.startswith(b"%PDF-"):
        raise GmeImportError("GME report is empty, too large or not a PDF")
    try:
        pdf_reader = importlib.import_module("pypdf").PdfReader(BytesIO(content))
        if pdf_reader.is_encrypted or len(pdf_reader.pages) != MAX_REPORT_PAGES:
            raise GmeImportError("GME monthly report has an unsupported PDF structure")
        page_text = pdf_reader.pages[0].extract_text()
        if not page_text:
            raise GmeImportError("GME monthly report has no extractable first-page text")
        parsed = parse_monthly_baseload_text(page_text, period_start)
    except GmeImportError:
        raise
    except (ImportError, ValueError, TypeError) as exc:
        raise GmeImportError(
            "GME PDF parser is unavailable or the source PDF is malformed"
        ) from exc
    provenance = make_report_provenance(
        content,
        report_period=parsed.period,
        retrieved_at=retrieved_at,
        url=source_url,
    )
    return GmeMonthlyIndexSnapshot(
        parsed=parsed,
        status=VerificationStatus.UNVERIFIED,
        provenance=provenance,
    )


def parse_monthly_band_report_bytes(
    content: bytes,
    period_start: date,
    retrieved_at: datetime,
    *,
    source_url: str | None = None,
) -> GmeBandReportSnapshot:
    """Parse an official-layout PDF as unverified evidence with table locators."""
    if not content or len(content) > MAX_REPORT_BYTES or not content.startswith(b"%PDF-"):
        raise GmeImportError("GME band report is empty, too large or not a PDF")
    try:
        pdf_reader = importlib.import_module("pypdf").PdfReader(BytesIO(content))
        if pdf_reader.is_encrypted or not (1 <= len(pdf_reader.pages) <= MAX_REPORT_PAGES):
            raise GmeImportError("GME band report has an unsupported PDF structure")
        text = "\n".join(page.extract_text() or "" for page in pdf_reader.pages)
        parsed = parse_monthly_band_report_text(text, period_start)
    except GmeImportError:
        raise
    except (ImportError, ValueError, TypeError) as exc:
        raise GmeImportError(
            "GME band PDF parser is unavailable or the source PDF is malformed"
        ) from exc
    digest = sha256(content).hexdigest()
    url = source_url
    provenance = tuple(
        Provenance(
            source="GME",
            source_identifier=f"MGP-average-purchase-by-band:{parsed.period.start:%Y-%m}:{price.band}",
            retrieved_at=retrieved_at,
            effective_period=parsed.period,
            dataset_version=parsed.period.start.strftime("%Y-%m"),
            sha256=digest,
            url=url,
            locator=ProvenanceLocator(
                document=(
                    url.rsplit("/", maxsplit=1)[-1].split("?", maxsplit=1)[0] if url else None
                ),
                section=(
                    f"Prezzo medio di acquisto per fasce / {price.band} / "
                    f"{parsed.period.start:%Y-%m}; EUR/MWh; {price.hours} ore"
                ),
            ),
        )
        for price in parsed.prices
    )
    return GmeBandReportSnapshot(
        parsed=parsed,
        status=VerificationStatus.UNVERIFIED,
        provenance=provenance,
    )


def make_report_provenance(
    content: bytes,
    *,
    report_period: DatePeriod,
    retrieved_at: datetime,
    url: str | None,
) -> Provenance:
    """Bind digest and cell locator to one monthly GME report."""

    return Provenance(
        source="GME",
        source_identifier=f"MGP-monthly-baseload:{report_period.start:%Y-%m}",
        retrieved_at=retrieved_at,
        effective_period=report_period,
        dataset_version=report_period.start.strftime("%Y-%m"),
        sha256=sha256(content).hexdigest(),
        url=url,
        locator=ProvenanceLocator(
            document=f"{report_period.start:%Y%m}_Dati_di_sintesi_mensile.pdf",
            section="Mercato del Giorno Prima / Prezzo medio / Baseload / page 1",
        ),
    )


def annual_archive_url(year: int) -> str:
    """Return the exact official GME MGP annual-history ZIP endpoint."""

    if not 2025 <= year <= 9999:
        raise GmeImportError("GME annual archive fallback supports years from 2025 onward")
    return f"{GME_ARCHIVE_ROOT}{year}.zip"


def is_official_gme_monthly_provenance(provenance: Provenance, period: DatePeriod) -> bool:
    """Validate either supported official source form for one monthly PUN value."""

    expected_identifier = f"MGP-monthly-baseload:{period.start:%Y-%m}"
    if (
        period.start.day != 1
        or period.end != _add_months(period.start, 1)
        or provenance.source != "GME"
        or provenance.source_identifier != expected_identifier
        or provenance.effective_period != period
        or provenance.sha256 is None
        or not re.fullmatch(r"[0-9a-fA-F]{64}", provenance.sha256)
    ):
        return False
    if provenance.url == report_url(period.start):
        return True
    if period.start < date(2025, 10, 1) or provenance.url != annual_archive_url(period.start.year):
        return False
    locator = provenance.locator
    if locator is None or locator.sheet != "Prezzi-Prices" or locator.cell is None:
        return False
    workbook_name = locator.document or ""
    match = re.fullmatch(rf"Anno {period.start.year}_[0-9]{{2}}_15\.xlsx", workbook_name)
    cell_match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]*):\1([1-9][0-9]*)", locator.cell)
    return bool(
        match
        and cell_match
        and int(cell_match.group(3)) >= int(cell_match.group(2))
        and int(cell_match.group(2)) >= 2
    )


def _official_redirect_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.lower() == "https"
        and parsed.hostname == "gme.mercatoelettrico.org"
        and port in (None, 443)
        and parsed.username is None
        and parsed.password is None
        and not parsed.fragment
    )


class _OfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Keep every redirect on the official HTTPS host and within a short chain."""

    def __init__(self) -> None:
        super().__init__()
        self.redirect_count = 0

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        self.redirect_count += 1
        resolved_url = urljoin(request.full_url, new_url)
        if self.redirect_count > MAX_OFFICIAL_REDIRECTS:
            raise GmeImportError("GME source exceeded the maximum of three redirects")
        if not _official_redirect_url(resolved_url):
            raise GmeImportError("GME source redirected outside the official HTTPS host")
        return super().redirect_request(
            request,
            response,
            code,
            message,
            headers,
            resolved_url,
        )


def _open_official(
    request: urllib.request.Request, timeout_seconds: float
) -> urllib.response.addinfourl:
    opener = urllib.request.build_opener(_OfficialRedirectHandler())
    return cast(urllib.response.addinfourl, opener.open(request, timeout=timeout_seconds))


def _download_annual_archive(year: int, *, timeout_seconds: float = 30) -> tuple[bytes, datetime]:
    """Download one bounded annual archive and retain its acquisition time."""

    url = annual_archive_url(year)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/zip", "User-Agent": "italian-energy-core/0.13"},
    )
    try:
        with _open_official(request, timeout_seconds) as response:
            if not _official_redirect_url(response.geturl()):
                raise GmeImportError("GME archive redirected outside the official HTTPS host")
            content = response.read(MAX_ARCHIVE_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise GmeImportError(
            f"GME annual archive acquisition failed for {year} (HTTP {exc.code})"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GmeImportError(f"GME annual archive acquisition failed for {year}") from exc
    if not content or len(content) > MAX_ARCHIVE_DOWNLOAD_BYTES:
        raise GmeImportError("GME annual archive is empty or exceeds the 64 MiB download limit")
    return content, datetime.now(UTC)


def parse_annual_market_archive(
    content: bytes,
    *,
    year: int,
    period_starts: tuple[date, ...],
    retrieved_at: datetime,
) -> dict[date, GmeMonthlyIndexSnapshot]:
    """Parse requested monthly PUN averages from an official annual GME ZIP."""

    if not 2025 <= year <= 9999:
        raise GmeImportError("GME annual archive fallback supports years from 2025 onward")
    if not content or len(content) > MAX_ARCHIVE_DOWNLOAD_BYTES:
        raise GmeImportError("GME annual archive is empty or exceeds the 64 MiB download limit")
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise GmeImportError("GME archive retrieval time must be timezone-aware")
    if not period_starts or len(set(period_starts)) != len(period_starts):
        raise GmeImportError("GME archive request must contain unique months")
    if any(
        start.year != year or start.day != 1 or start < date(2025, 10, 1) for start in period_starts
    ):
        raise GmeImportError("GME _15 fallback supports complete months from October 2025")

    try:
        with ZipFile(BytesIO(content)) as archive:
            workbook_name, workbook_bytes = _read_official_archive_workbook(archive, year)
        return _parse_gme_workbook(
            workbook_bytes,
            workbook_name=workbook_name,
            archive_digest=sha256(content).hexdigest(),
            year=year,
            period_starts=period_starts,
            retrieved_at=retrieved_at,
        )
    except GmeImportError:
        raise
    except Exception as exc:
        raise GmeImportError(
            "GME annual archive is corrupt or has an unsupported OOXML layout"
        ) from exc


def _read_official_archive_workbook(archive: ZipFile, year: int) -> tuple[str, bytes]:
    infos = archive.infolist()
    names: set[str] = set()
    candidates: dict[str, tuple[str, ZipInfo]] = {}
    edition_month: str | None = None
    for info in infos:
        name = info.filename
        _validate_zip_member(info)
        if name in names:
            raise GmeImportError("GME ZIP contains duplicate member paths")
        names.add(name)
        match = _ARCHIVE_MEMBER.fullmatch(name)
        if match is None or int(match.group(1)) != year:
            raise GmeImportError("GME annual ZIP contains an unexpected workbook path")
        if edition_month is None:
            edition_month = match.group(2)
        elif edition_month != match.group(2):
            raise GmeImportError("GME annual ZIP workbook names use different editions")
        if info.file_size > MAX_WORKBOOK_BYTES:
            raise GmeImportError("GME workbook exceeds the 48 MiB workbook limit")
        candidates[match.group(3)] = (name, info)
    if set(candidates) != {"15", "60"} or len(infos) != 2:
        raise GmeImportError("GME annual ZIP must contain the official _15 and _60 workbooks")
    fifteen_name, fifteen_info = candidates["15"]
    return fifteen_name, archive.read(fifteen_info)


def _validate_zip_member(info: ZipInfo) -> None:
    name = info.filename
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or "\x00" in name
        or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
        or info.flag_bits & 0x1
    ):
        raise GmeImportError("GME ZIP contains an unsafe or encrypted member path")
    mode = info.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise GmeImportError("GME ZIP contains a symbolic-link member")


def _parse_gme_workbook(
    content: bytes,
    *,
    workbook_name: str,
    archive_digest: str,
    year: int,
    period_starts: tuple[date, ...],
    retrieved_at: datetime,
) -> dict[date, GmeMonthlyIndexSnapshot]:
    if not content or len(content) > MAX_WORKBOOK_BYTES:
        raise GmeImportError("GME workbook is empty or exceeds the 48 MiB workbook limit")
    with ZipFile(BytesIO(content)) as workbook:
        parts: dict[str, ZipInfo] = {}
        total_uncompressed = 0
        for info in workbook.infolist():
            _validate_ooxml_path(info)
            if info.filename in parts:
                raise GmeImportError("GME workbook contains duplicate OOXML parts")
            if info.file_size > MAX_OOXML_PART_BYTES:
                raise GmeImportError("GME workbook contains an OOXML part over the 64 MiB limit")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_OOXML_BYTES:
                raise GmeImportError("GME workbook exceeds the 320 MiB OOXML content limit")
            parts[info.filename] = info

        workbook_xml = _read_ooxml_part(workbook, parts, "xl/workbook.xml")
        rels_xml = _read_ooxml_part(workbook, parts, "xl/_rels/workbook.xml.rels")
        workbook_root = _parse_safe_xml(workbook_xml, "workbook")
        rels_root = _parse_safe_xml(rels_xml, "workbook relationships")
        sheet_path, shared_strings_path = _resolve_workbook_parts(workbook_root, rels_root)
        shared_strings = _read_shared_strings(workbook, parts, shared_strings_path)
        sheet_bytes = _read_ooxml_part(workbook, parts, sheet_path)
        selected = set(period_starts)
        monthly_values: dict[date, list[Decimal]] = {month: [] for month in period_starts}
        ranges: dict[date, tuple[int, int]] = {}
        header_columns: dict[str, str] | None = None
        selected_columns: dict[str, str] = {}
        current_day: date | None = None
        day_period_count = 0
        previous_period = 0
        expected_row = 1
        data_row_count = 0

        try:
            rows = SafeET.iterparse(
                BytesIO(sheet_bytes),
                events=("end",),
                forbid_dtd=True,
                forbid_entities=True,
                forbid_external=True,
            )
            for _event, element in rows:
                if element.tag != f"{{{_XML_MAIN}}}row":
                    continue
                row_number_text = element.attrib.get("r")
                if row_number_text is None or not row_number_text.isdigit():
                    raise GmeImportError("GME worksheet contains a row without a valid number")
                row_number = int(row_number_text)
                if row_number != expected_row or row_number > MAX_WORKSHEET_ROWS:
                    raise GmeImportError(
                        "GME worksheet row sequence or 40,000-row limit is invalid"
                    )
                expected_row += 1
                cell_elements: dict[str, Any] = {}
                for cell in element.findall(f"{{{_XML_MAIN}}}c"):
                    reference = cell.attrib.get("r", "")
                    match = _CELL_REFERENCE.fullmatch(reference)
                    if match is None or match.group(1) in cell_elements:
                        raise GmeImportError("GME worksheet contains an invalid or duplicate cell")
                    cell_elements[match.group(1)] = cell
                if row_number == 1:
                    header_columns = _resolve_gme_header(cell_elements, shared_strings)
                    selected_columns = {label: column for label, column in header_columns.items()}
                    element.clear()
                    continue
                if header_columns is None:
                    raise GmeImportError("GME worksheet header row is missing")
                data_row_count += 1
                if data_row_count + 1 > MAX_WORKSHEET_ROWS:
                    raise GmeImportError("GME worksheet exceeds the 40,000-row limit")
                values: dict[str, object] = {}
                for label, column in selected_columns.items():
                    cell = cell_elements.get(column)
                    if cell is None:
                        raise GmeImportError("GME worksheet has a missing required value cell")
                    if cell.find(f"{{{_XML_MAIN}}}f") is not None:
                        raise GmeImportError("GME worksheet formulas are not accepted")
                    values[label] = cell
                date_raw = _cell_value(values["date"], shared_strings, numeric=True)
                hour_raw = _cell_value(values["hour"], shared_strings, numeric=True)
                period_raw = _cell_value(values["period"], shared_strings)
                price_raw = _cell_value(values["pun"], shared_strings, numeric=True)
                if not re.fullmatch(r"[0-9]{8}", date_raw):
                    raise GmeImportError("GME row date is not a YYYYMMDD token")
                try:
                    row_day = date(int(date_raw[:4]), int(date_raw[4:6]), int(date_raw[6:8]))
                    hour = int(hour_raw)
                    period_number = int(period_raw)
                    price = Decimal(price_raw)
                except (ValueError, InvalidOperation) as exc:
                    raise GmeImportError(
                        "GME row date, hour, period or PUN token is invalid"
                    ) from exc
                if row_day.year != year or not price.is_finite():
                    raise GmeImportError(
                        "GME row is outside its archive year or has a non-finite value"
                    )
                if current_day != row_day:
                    if current_day is not None:
                        expected_count = _expected_day_periods(current_day)
                        if day_period_count != expected_count:
                            raise GmeImportError(
                                "GME day does not contain all expected quarter-hours"
                            )
                        if row_day != current_day + timedelta(days=1):
                            raise GmeImportError(
                                "GME annual workbook has a missing or out-of-order day"
                            )
                    current_day = row_day
                    day_period_count = 0
                    previous_period = 0
                day_period_count += 1
                if (
                    period_number != previous_period + 1
                    or period_number > _expected_day_periods(row_day)
                    or hour != (period_number - 1) // 4 + 1
                ):
                    raise GmeImportError("GME interval sequence or local market hour is invalid")
                previous_period = period_number
                month_start = row_day.replace(day=1)
                if month_start in selected:
                    monthly_values[month_start].append(price)
                    if month_start not in ranges:
                        ranges[month_start] = (row_number, row_number)
                    else:
                        ranges[month_start] = (ranges[month_start][0], row_number)
                element.clear()
        except GmeImportError:
            raise
        except Exception as exc:
            raise GmeImportError("GME worksheet XML is malformed or unsafe") from exc

        if header_columns is None or current_day is None:
            raise GmeImportError("GME workbook has no supported PUN data rows")
        if day_period_count != _expected_day_periods(current_day):
            raise GmeImportError("GME final day does not contain all expected quarter-hours")

    result: dict[date, GmeMonthlyIndexSnapshot] = {}
    for month in period_starts:
        expected_count = sum(
            _expected_day_periods(date(year, month.month, day_number))
            for day_number in range(1, calendar.monthrange(year, month.month)[1] + 1)
        )
        if len(monthly_values[month]) != expected_count or month not in ranges:
            raise GmeImportError(f"GME _15 workbook does not completely cover {month:%Y-%m}")
        first_row, last_row = ranges[month]
        if last_row - first_row + 1 != expected_count:
            raise GmeImportError("GME monthly PUN cells are not in one consecutive range")
        with localcontext() as context:
            context.prec = GME_MEAN_PRECISION
            total = sum(monthly_values[month], Decimal(0))
            mean = total / Decimal(expected_count)
            value_kwh = mean / Decimal(1000)
        period = DatePeriod(start=month, end=_add_months(month, 1))
        provenance = Provenance(
            source="GME",
            source_identifier=f"MGP-monthly-baseload:{month:%Y-%m}",
            retrieved_at=retrieved_at,
            effective_period=period,
            dataset_version=month.strftime("%Y-%m"),
            sha256=archive_digest,
            url=annual_archive_url(year),
            locator=ProvenanceLocator(
                document=workbook_name,
                sheet="Prezzi-Prices",
                cell=f"{selected_columns['pun']}{first_row}:{selected_columns['pun']}{last_row}",
                section="PUN INDEX GME; _15; 15-minute arithmetic mean",
            ),
        )
        try:
            parsed = ParsedGmeBaseload(
                period=period,
                published_value_eur_per_mwh=mean,
                value_eur_per_kwh=value_kwh,
            )
            result[month] = GmeMonthlyIndexSnapshot(
                parsed=parsed,
                status=VerificationStatus.VERIFIED,
                provenance=provenance,
            )
        except ValueError as exc:
            raise GmeImportError(
                "GME archive mean does not satisfy the monthly PUN contract"
            ) from exc
    return result


def _validate_ooxml_path(info: ZipInfo) -> None:
    name = info.filename
    if (
        not name
        or "\\" in name
        or name.startswith("/")
        or "\x00" in name
        or any(part in {"", ".", ".."} for part in name.rstrip("/").split("/"))
        or info.flag_bits & 0x1
        or stat.S_ISLNK(info.external_attr >> 16)
    ):
        raise GmeImportError("GME workbook contains an unsafe or encrypted OOXML path")


def _read_ooxml_part(archive: ZipFile, parts: dict[str, ZipInfo], name: str) -> bytes:
    info = parts.get(name)
    if info is None:
        raise GmeImportError(f"GME workbook is missing required OOXML part {name}")
    content = archive.read(info)
    if len(content) > MAX_OOXML_PART_BYTES:
        raise GmeImportError("GME workbook contains an OOXML part over the 64 MiB limit")
    return content


def _parse_safe_xml(content: bytes, label: str) -> Any:
    try:
        return SafeET.fromstring(
            content,
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
    except Exception as exc:
        raise GmeImportError(f"GME {label} XML is malformed or unsafe") from exc


def _resolve_workbook_parts(workbook_root: Any, rels_root: Any) -> tuple[str, str | None]:
    relationships: dict[str, tuple[str, str]] = {}
    for relationship in rels_root.findall(f"{{{_XML_PACKAGE_REL}}}Relationship"):
        relationship_id = relationship.attrib.get("Id")
        target = relationship.attrib.get("Target")
        relationship_type = relationship.attrib.get("Type")
        if not relationship_id or not target or not relationship_type:
            raise GmeImportError("GME workbook has an incomplete OOXML relationship")
        if relationship_id in relationships or relationship.attrib.get("TargetMode") == "External":
            raise GmeImportError("GME workbook has a duplicate or external OOXML relationship")
        relationships[relationship_id] = (relationship_type, target)

    sheets = workbook_root.find(f"{{{_XML_MAIN}}}sheets")
    if sheets is None:
        raise GmeImportError("GME workbook sheet list is missing")
    matching = [
        sheet
        for sheet in sheets.findall(f"{{{_XML_MAIN}}}sheet")
        if sheet.attrib.get("name") == "Prezzi-Prices"
    ]
    if len(matching) != 1:
        raise GmeImportError("GME workbook must have exactly one Prezzi-Prices sheet")
    sheet_id = matching[0].attrib.get(f"{{{_XML_REL}}}id")
    if not sheet_id or sheet_id not in relationships:
        raise GmeImportError("GME Prezzi-Prices sheet relationship is missing")
    sheet_type, sheet_target = relationships[sheet_id]
    if not sheet_type.endswith("/worksheet"):
        raise GmeImportError("GME Prezzi-Prices relationship is not a worksheet")
    sheet_path = _resolve_internal_target(sheet_target)
    shared_targets = [
        target
        for relationship_type, target in relationships.values()
        if relationship_type.endswith("/sharedStrings")
    ]
    if len(shared_targets) > 1:
        raise GmeImportError("GME workbook has ambiguous shared-strings relationships")
    shared_path = _resolve_internal_target(shared_targets[0]) if shared_targets else None
    return sheet_path, shared_path


def _resolve_internal_target(target: str) -> str:
    if "\\" in target or "\x00" in target or "?" in target or "#" in target:
        raise GmeImportError("GME workbook relationship target is not a safe internal path")
    path = (
        target.lstrip("/")
        if target.startswith("/")
        else posixpath.normpath(posixpath.join("xl", target))
    )
    if (
        path.startswith("../")
        or path.startswith("/")
        or not path.startswith("xl/")
        or any(part in {"", ".", ".."} for part in path.split("/"))
    ):
        raise GmeImportError("GME workbook relationship escapes the OOXML package")
    return path


def _read_shared_strings(
    archive: ZipFile, parts: dict[str, ZipInfo], path: str | None
) -> tuple[str, ...]:
    if path is None:
        return ()
    content = _read_ooxml_part(archive, parts, path)
    values: list[str] = []
    try:
        elements = SafeET.iterparse(
            BytesIO(content),
            events=("end",),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        )
        for _event, element in elements:
            if element.tag == f"{{{_XML_MAIN}}}si":
                values.append(
                    "".join(text.text or "" for text in element.findall(f".//{{{_XML_MAIN}}}t"))
                )
                element.clear()
    except Exception as exc:
        raise GmeImportError("GME workbook shared strings are malformed or unsafe") from exc
    return tuple(values)


def _resolve_gme_header(cells: dict[str, Any], shared_strings: tuple[str, ...]) -> dict[str, str]:
    expected = {
        "data/date(yyyymmdd)": "date",
        "ora/hour": "hour",
        "periodo/period": "period",
        "punindexgme": "pun",
    }
    columns: dict[str, str] = {}
    for column, cell in cells.items():
        value = _cell_value(cell, shared_strings)
        normalized = re.sub(r"\s+", "", value).casefold()
        label = expected.get(normalized)
        if label is None:
            continue
        if label in columns:
            raise GmeImportError("GME workbook has duplicate or ambiguous required column headers")
        columns[label] = column
    if set(columns) != set(expected.values()):
        raise GmeImportError("GME workbook does not expose the exact PUN INDEX GME layout")
    return columns


def _cell_value(cell: Any, shared_strings: tuple[str, ...], *, numeric: bool = False) -> str:
    cell_type = cell.attrib.get("t")
    if cell_type == "s":
        if numeric:
            raise GmeImportError("GME numeric data cell is stored as a shared string")
        value = cell.findtext(f"{{{_XML_MAIN}}}v")
        if value is None or not value.isdigit():
            raise GmeImportError("GME shared-string index is invalid")
        index = int(value)
        if index >= len(shared_strings):
            raise GmeImportError("GME shared-string index is outside its table")
        return shared_strings[index]
    if cell_type == "inlineStr":
        if numeric:
            raise GmeImportError("GME numeric data cell is stored as inline text")
        return "".join(text.text or "" for text in cell.findall(f".//{{{_XML_MAIN}}}t"))
    if cell_type not in (None, "n"):
        raise GmeImportError("GME cell type is unsupported")
    value = cell.findtext(f"{{{_XML_MAIN}}}v")
    if not isinstance(value, str) or not value.strip():
        raise GmeImportError("GME workbook contains a missing required cell value")
    return value.strip()


def _expected_day_periods(day: date) -> int:
    start = datetime(day.year, day.month, day.day, tzinfo=_rome())
    end = datetime(day.year, day.month, day.day, tzinfo=_rome()) + timedelta(days=1)
    seconds = (end.astimezone(UTC) - start.astimezone(UTC)).total_seconds()
    if seconds not in (23 * 3600, 24 * 3600, 25 * 3600):
        raise GmeImportError("GME local civil day has an unsupported Europe/Rome duration")
    return int(seconds // 900)


def fetch_monthly_report(
    period_start: date, *, timeout_seconds: float = 30
) -> GmeMonthlyIndexSnapshot:
    """Fetch and verify a monthly report from the fixed official GME document path."""

    url = report_url(period_start)
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/pdf", "User-Agent": "italian-energy-core/0.11"},
    )
    try:
        with _open_official(request, timeout_seconds) as response:
            final_url = response.geturl()
            if not _official_redirect_url(final_url):
                raise GmeImportError("GME report redirected outside the official HTTPS host")
            content = response.read(MAX_REPORT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise GmeReportNotFound(
                f"GME monthly report returned HTTP 404 for {period_start:%Y-%m}"
            ) from exc
        raise GmeImportError(
            f"GME report acquisition failed for {period_start:%Y-%m} (HTTP {exc.code})"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GmeImportError(f"GME report acquisition failed for {period_start:%Y-%m}") from exc
    parsed = parse_monthly_report_bytes(
        content,
        period_start,
        datetime.now(UTC),
        source_url=url,
    )
    return parsed.model_copy(update={"status": VerificationStatus.VERIFIED})


def fetch_monthly_band_report(
    period_start: date,
    source_url: str,
    *,
    timeout_seconds: float = 30,
) -> GmeBandReportSnapshot:
    """Fetch one observed official GME time-band publication URL and verify its digest."""
    if not _official_document_url(source_url):
        raise GmeImportError("GME band report URL must be on the official HTTPS document host")
    request = urllib.request.Request(
        source_url,
        headers={"Accept": "application/pdf", "User-Agent": "italian-energy-core/0.11"},
    )
    try:
        with _open_official(request, timeout_seconds) as response:
            final_url = response.geturl()
            if not _official_redirect_url(final_url):
                raise GmeImportError("GME band report redirected outside the official HTTPS host")
            content = response.read(MAX_REPORT_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise GmeImportError(
            f"GME band report acquisition failed for {period_start:%Y-%m} (HTTP {exc.code})"
        ) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GmeImportError(
            f"GME band report acquisition failed for {period_start:%Y-%m}"
        ) from exc
    parsed = parse_monthly_band_report_bytes(
        content,
        period_start,
        datetime.now(UTC),
        source_url=source_url,
    )
    return parsed.model_copy(update={"status": VerificationStatus.VERIFIED})


def fetch_recent_market_history(
    as_of: date,
    *,
    timeout_seconds: float = 30,
) -> GmeMarketHistory:
    """Acquire and verify exactly the twelve most recent complete PUN months."""

    periods = recent_months(as_of)
    reports_by_month: dict[date, GmeMonthlyIndexSnapshot] = {}
    missing_by_year: dict[int, list[date]] = {}
    for period in periods:
        try:
            reports_by_month[period] = fetch_monthly_report(period, timeout_seconds=timeout_seconds)
        except GmeReportNotFound as exc:
            if period < date(2025, 10, 1):
                raise GmeImportError(
                    f"GME annual fallback does not support {period:%Y-%m}"
                ) from exc
            missing_by_year.setdefault(period.year, []).append(period)
    for year, missing_months in sorted(missing_by_year.items()):
        archive_bytes, retrieved_at = _download_annual_archive(
            year, timeout_seconds=timeout_seconds
        )
        reports_by_month.update(
            parse_annual_market_archive(
                archive_bytes,
                year=year,
                period_starts=tuple(missing_months),
                retrieved_at=retrieved_at,
            )
        )
    return history_from_reports(as_of, tuple(reports_by_month[period] for period in periods))


def history_from_reports(
    as_of: date,
    reports: tuple[GmeMonthlyIndexSnapshot, ...],
) -> GmeMarketHistory:
    """Build a twelve-month view without elevating offline-parsed inputs."""

    periods = tuple(recent_months(as_of))
    if tuple(item.parsed.period.start for item in reports) != periods:
        raise GmeImportError("GME reports do not match the latest consecutive twelve-month window")
    provenance = tuple(report.provenance for report in reports)
    index = MarketIndex(
        code="PUN",
        name="PUN Index GME MGP baseload monthly average",
        unit=RateUnit.EUR_PER_KWH,
        granularity=Granularity.MONTH,
        timezone="Europe/Rome",
        provenance=provenance,
    )
    points = tuple(
        MarketDataPoint(
            index_code="PUN",
            interval=TimeInterval(
                start=datetime(
                    report.parsed.period.start.year,
                    report.parsed.period.start.month,
                    1,
                    tzinfo=_rome(),
                ),
                end=datetime(
                    report.parsed.period.end.year, report.parsed.period.end.month, 1, tzinfo=_rome()
                ),
            ),
            value=report.parsed.value_eur_per_kwh,
            provenance=(report.provenance,),
        )
        for report in reports
    )
    status = (
        VerificationStatus.VERIFIED
        if all(report.status == VerificationStatus.VERIFIED for report in reports)
        else VerificationStatus.UNVERIFIED
    )
    return GmeMarketHistory(
        as_of=as_of,
        status=status,
        reports=reports,
        market_data=MarketData(indexes=(index,), points=points),
    )


def _official_document_url(value: str) -> bool:
    if not _official_redirect_url(value):
        return False
    parsed = urlsplit(value)
    return parsed.path.startswith("/Portals/0/Documents/it-IT/") and not parsed.query


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, 1)


def _rome() -> ZoneInfo:
    return ZoneInfo("Europe/Rome")


__all__ = [
    "GME_ARCHIVE_ROOT",
    "GME_DOCUMENT_ROOT",
    "GME_INDEX_DEFINITION_SHA256",
    "GME_INDEX_DEFINITION_URL",
    "GmeBandReportSnapshot",
    "GmeImportError",
    "GmeMarketHistory",
    "GmeMonthlyIndexSnapshot",
    "GmeReportNotFound",
    "ParsedGmeBandPrice",
    "ParsedGmeBandReport",
    "ParsedGmeBaseload",
    "annual_archive_url",
    "fetch_monthly_band_report",
    "fetch_monthly_report",
    "fetch_recent_market_history",
    "history_from_reports",
    "is_official_gme_monthly_provenance",
    "make_report_provenance",
    "parse_annual_market_archive",
    "parse_monthly_band_report_bytes",
    "parse_monthly_band_report_text",
    "parse_monthly_baseload_text",
    "parse_monthly_report_bytes",
    "recent_months",
    "report_url",
]
