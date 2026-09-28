"""Verified acquisition of the GME monthly PUN Index GME baseload reports."""

from __future__ import annotations

import calendar
import importlib
import re
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from italian_energy.domain.base import DomainModel
from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
from italian_energy.domain.money import RateUnit
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod, Granularity, TimeInterval

GME_DOCUMENT_ROOT = "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/"
GME_INDEX_DEFINITION_URL = (
    "https://gme.mercatoelettrico.org/Portals/0/Documents/it-IT/20250101DTF25MPE.pdf"
)
GME_INDEX_DEFINITION_SHA256 = "f380f542d9b99166c453f3e0e5e29c1c43921bb254374fa3834695ba2d19ee5c"
MAX_REPORT_BYTES = 3_000_000
MAX_REPORT_PAGES = 3
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
            or self.value_eur_per_kwh != self.published_value_eur_per_mwh.scaleb(-3)
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
            self.provenance.source != "GME"
            or not self.provenance.sha256
            or self.provenance.url != report_url(self.parsed.period.start)
        ):
            raise ValueError("verified GME data requires official URL and raw digest")
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
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if not _official_document_url(final_url):
                raise GmeImportError(
                    "GME report redirected outside the official HTTPS document host"
                )
            content = response.read(MAX_REPORT_BYTES + 1)
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
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            final_url = response.geturl()
            if not _official_document_url(final_url):
                raise GmeImportError(
                    "GME band report redirected outside the official HTTPS document host"
                )
            content = response.read(MAX_REPORT_BYTES + 1)
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

    reports = tuple(
        fetch_monthly_report(period, timeout_seconds=timeout_seconds)
        for period in recent_months(as_of)
    )
    return history_from_reports(as_of, reports)


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
    return value.startswith(GME_DOCUMENT_ROOT) and value.split(":", 1)[0].lower() == "https"


def _add_months(value: date, months: int) -> date:
    absolute = value.year * 12 + value.month - 1 + months
    year, month0 = divmod(absolute, 12)
    return date(year, month0 + 1, 1)


def _rome() -> ZoneInfo:
    return ZoneInfo("Europe/Rome")


__all__ = [
    "GME_DOCUMENT_ROOT",
    "GME_INDEX_DEFINITION_SHA256",
    "GME_INDEX_DEFINITION_URL",
    "GmeBandReportSnapshot",
    "GmeImportError",
    "GmeMarketHistory",
    "GmeMonthlyIndexSnapshot",
    "ParsedGmeBandPrice",
    "ParsedGmeBandReport",
    "ParsedGmeBaseload",
    "fetch_monthly_band_report",
    "fetch_monthly_report",
    "fetch_recent_market_history",
    "history_from_reports",
    "make_report_provenance",
    "parse_monthly_band_report_bytes",
    "parse_monthly_band_report_text",
    "parse_monthly_baseload_text",
    "parse_monthly_report_bytes",
    "recent_months",
    "report_url",
]
