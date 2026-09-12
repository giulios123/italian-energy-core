"""Acquisition and parsing of the ARERA domestic electricity workbook."""

from __future__ import annotations

import io
import math
import posixpath
import re
import zipfile
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from defusedxml import ElementTree as SafeET  # type: ignore[import-untyped, unused-ignore]

from italian_energy.arera.models import (
    AreraChargeRole,
    AreraChargeValue,
    AreraCustomerSegment,
    AreraDiagnostic,
    AreraDiagnosticSeverity,
    AreraHeader,
    AreraImportResult,
    AreraRegulatoryBundle,
    AreraSourceLocator,
    RawAreraSnapshot,
    make_provenance,
)
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import BillingCategory, BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod

ARERA_DOMESTIC_2026_URL = (
    "https://www.arera.it/fileadmin/area_operatori/prezzi_e_tariffe/"
    "Corrispettivi_libero_elettrico_domestico_2026.xlsx"
)
ARERA_HOST = "www.arera.it"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_CONTENT_BYTES = 5_000_000
MAX_UNCOMPRESSED_BYTES = 50_000_000
MAX_ARCHIVE_ENTRIES = 512
SCHEMA_VERSION = "005-domestic-electricity-2026-v1"

_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
_MONTHS = {
    "gennaio": 1,
    "febbraio": 2,
    "marzo": 3,
    "aprile": 4,
    "maggio": 5,
    "giugno": 6,
    "luglio": 7,
    "agosto": 8,
    "settembre": 9,
    "ottobre": 10,
    "novembre": 11,
    "dicembre": 12,
}
_SEGMENT_MARKERS = {
    "ABITAZIONI DI RESIDENZE ANAGRAFICHE": AreraCustomerSegment.RESIDENT,
    "ABITAZIONI DIVERSE DA RESIDENZE ANAGRAFICHE": AreraCustomerSegment.NON_RESIDENT,
}
_COLUMN_COMPONENTS = {
    "C": ("CDISPD", BillingCategory.SALES, AreraChargeRole.ATOMIC),
    "D": ("sigma1", BillingCategory.NETWORK, AreraChargeRole.ATOMIC),
    "E": ("sigma2", BillingCategory.NETWORK, AreraChargeRole.ATOMIC),
    "F": ("sigma3", BillingCategory.NETWORK, AreraChargeRole.ATOMIC),
    "G": ("UC3", BillingCategory.NETWORK, AreraChargeRole.ATOMIC),
    "H": ("UC6", BillingCategory.NETWORK, AreraChargeRole.ATOMIC),
    "I": ("network_total", BillingCategory.NETWORK, AreraChargeRole.TOTAL),
    "J": ("ASOS", BillingCategory.SYSTEM_CHARGES, AreraChargeRole.ATOMIC),
    "K": ("ARIM", BillingCategory.SYSTEM_CHARGES, AreraChargeRole.ATOMIC),
    "L": ("system_total", BillingCategory.SYSTEM_CHARGES, AreraChargeRole.TOTAL),
}
_EXPECTED_SUBHEADERS = {
    "C": "dispacciamento",
    "D": "\u03c31",
    "E": "\u03c32",
    "F": "\u03c33",
    "G": "uc3",
    "H": "uc6",
    "J": "asos",
    "K": "arim",
}
_QUOTA_ROWS = {
    "quota energia (euro/kwh)": (BillingQuota.CONSUMPTION, RateUnit.EUR_PER_KWH),
    "quota fissa (euro/anno)": (BillingQuota.FIXED, RateUnit.EUR_PER_YEAR),
    "quota potenza (euro/kw/anno)": (BillingQuota.POWER, RateUnit.EUR_PER_KW_YEAR),
}


class AreraImportError(ValueError):
    """Base error for malformed or unsupported ARERA import input."""


class AreraFetchError(AreraImportError):
    """Raised when an official snapshot cannot be acquired safely."""


class UnsupportedAreraDatasetError(AreraImportError):
    """Raised for a year or endpoint outside the accepted Spec 005 scope."""


class AreraHttpResponse:
    """Minimal transport response used by the importer and its tests."""

    def __init__(self, *, status: int, url: str, headers: Iterable[AreraHeader], content: bytes):
        self.status = status
        self.url = url
        self.headers = tuple(headers)
        self.content = content


class AreraTransport(Protocol):
    def get(self, url: str, timeout_seconds: float) -> AreraHttpResponse:
        """Return one fully buffered HTTP response."""


class _RedirectGuard(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request:
        if not _is_allowed_url(newurl):
            raise AreraFetchError("ARERA redirect leaves the allowlisted HTTPS host")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise AreraFetchError("ARERA redirect could not be constructed")
        return redirected


class _UrllibTransport:
    def get(self, url: str, timeout_seconds: float) -> AreraHttpResponse:
        request = Request(url, headers={"Accept": XLSX_MIME, "User-Agent": "italian-energy/0.6"})
        opener = build_opener(_RedirectGuard())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                content = _read_limited(response, MAX_CONTENT_BYTES)
                headers = tuple(
                    AreraHeader(name=name, value=value) for name, value in response.headers.items()
                )
                return AreraHttpResponse(
                    status=response.status,
                    url=response.geturl(),
                    headers=headers,
                    content=content,
                )
        except AreraFetchError:
            raise
        except Exception as exc:  # pragma: no cover - concrete network errors vary by platform
            raise AreraFetchError(f"ARERA fetch failed: {exc}") from exc


class _RawCell:
    def __init__(self, *, ref: str, kind: str | None, value: str | None, formula: bool):
        self.ref = ref
        self.kind = kind
        self.value = value
        self.formula = formula


class _RawSheet:
    def __init__(self, *, name: str, cells: Mapping[str, _RawCell]):
        self.name = name
        self.cells = dict(cells)


class AreraDomesticElectricityImporter:
    """Fetch and parse the single official ARERA domestic workbook in Spec 005."""

    def __init__(
        self,
        transport: AreraTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or _UrllibTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_and_import(
        self,
        year: int = 2026,
        timeout_seconds: float = 30.0,
    ) -> AreraImportResult:
        if year != 2026:
            raise UnsupportedAreraDatasetError(
                "only the ARERA domestic electricity dataset for 2026 is supported"
            )
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        try:
            response = self._transport.get(ARERA_DOMESTIC_2026_URL, timeout_seconds)
        except AreraFetchError:
            raise
        except Exception as exc:
            raise AreraFetchError(f"ARERA fetch failed: {exc}") from exc
        if response.status != 200:
            raise AreraFetchError(f"ARERA returned HTTP status {response.status}")
        if not _is_allowed_url(response.url):
            raise AreraFetchError("ARERA response URL is not allowlisted")
        content_type = _content_type(response.headers)
        if content_type != XLSX_MIME:
            raise AreraFetchError(f"unexpected ARERA content type: {content_type or 'missing'}")
        if len(response.content) > MAX_CONTENT_BYTES:
            raise AreraFetchError("ARERA response exceeds the maximum content size")
        try:
            snapshot = RawAreraSnapshot(
                content=response.content,
                source_url=response.url,
                retrieved_at=self._clock(),
                content_type=content_type,
                headers=response.headers,
                sha256=sha256(response.content).hexdigest(),
            )
        except (TypeError, ValueError) as exc:
            raise AreraFetchError(f"invalid ARERA snapshot metadata: {exc}") from exc
        return self._parse_snapshot(snapshot, trusted=True)

    def parse_bytes(
        self,
        content: bytes,
        retrieved_at: datetime,
        source_url: str | None = None,
    ) -> AreraImportResult:
        if len(content) > MAX_CONTENT_BYTES:
            raise AreraImportError("ARERA input exceeds the maximum content size")
        snapshot = RawAreraSnapshot(
            content=content,
            source_url=source_url,
            retrieved_at=retrieved_at,
            content_type="application/octet-stream",
            sha256=sha256(content).hexdigest(),
        )
        return self._parse_snapshot(snapshot, trusted=False)

    def _parse_snapshot(self, snapshot: RawAreraSnapshot, *, trusted: bool) -> AreraImportResult:
        try:
            _validate_archive(snapshot.content)
            raw_sheets, workbook = _read_workbook(snapshot.content)
            diagnostics: list[AreraDiagnostic] = []
            charges = self._parse_sheets(snapshot, raw_sheets, workbook, diagnostics)
        except (AreraImportError, KeyError, SafeET.ParseError, ValueError) as exc:
            return AreraImportResult(
                snapshot=snapshot,
                status=VerificationStatus.REVIEW_REQUIRED,
                diagnostics=(
                    AreraDiagnostic(
                        severity=AreraDiagnosticSeverity.ERROR,
                        code="IMPORT_ERROR",
                        message=str(exc),
                    ),
                ),
            )
        if diagnostics:
            return AreraImportResult(
                snapshot=snapshot,
                status=VerificationStatus.REVIEW_REQUIRED,
                diagnostics=tuple(diagnostics),
            )
        status = VerificationStatus.VERIFIED if trusted else VerificationStatus.UNVERIFIED
        periods = [charge.validity for charge in charges]
        validity = DatePeriod(
            start=min(period.start for period in periods),
            end=max(period.end for period in periods),
        )
        provenance = _dedupe_provenance(
            provenance for charge in charges for provenance in charge.provenance
        )
        charges = [charge.model_copy(update={"status": status}) for charge in charges]
        bundle = AreraRegulatoryBundle(
            bundle_id=f"arera-bundle:{snapshot.sha256}",
            schema_version=SCHEMA_VERSION,
            dataset_version="2026",
            validity=validity,
            charges=tuple(charges),
            status=status,
            provenance=provenance,
        )
        return AreraImportResult(snapshot=snapshot, status=status, bundle=bundle)

    def _parse_sheets(
        self,
        snapshot: RawAreraSnapshot,
        raw_sheets: tuple[_RawSheet, ...],
        workbook: Any,
        diagnostics: list[AreraDiagnostic],
    ) -> list[AreraChargeValue]:
        by_name = {sheet.title: sheet for sheet in workbook.worksheets}
        parsed: list[tuple[int, _RawSheet]] = []
        for raw_sheet in raw_sheets:
            month = _month_from_sheet_name(raw_sheet.name)
            if month is None:
                diagnostics.append(
                    _error("UNKNOWN_SHEET", "sheet is not a supported 2026 month", raw_sheet.name)
                )
                continue
            if raw_sheet.name not in by_name:
                diagnostics.append(
                    _error(
                        "SHEET_MISSING",
                        "sheet is missing from openpyxl workbook",
                        raw_sheet.name,
                    )
                )
                continue
            parsed.append((month, raw_sheet))
        months = sorted(month for month, _ in parsed)
        if not months:
            diagnostics.append(
                _error("NO_MONTHS", "workbook contains no supported 2026 month sheets", None)
            )
        if len(months) != len(set(months)):
            diagnostics.append(_error("DUPLICATE_MONTH", "duplicate month sheet", None))
        if months and months != list(range(months[0], months[-1] + 1)):
            diagnostics.append(_error("MONTH_GAP", "month sheets are not contiguous", None))
        for raw_sheet in raw_sheets:
            for cell in raw_sheet.cells.values():
                if cell.formula:
                    diagnostics.append(
                        _error("FORMULA", "workbook contains a formula", raw_sheet.name, cell.ref)
                    )
        if diagnostics:
            return []
        charges: list[AreraChargeValue] = []
        for month, raw_sheet in sorted(parsed):
            worksheet = by_name[raw_sheet.name]
            period = _month_period(2026, month)
            charges.extend(self._parse_sheet(snapshot, raw_sheet, worksheet, period, diagnostics))
        return charges

    def _parse_sheet(
        self,
        snapshot: RawAreraSnapshot,
        raw_sheet: _RawSheet,
        worksheet: Any,
        period: DatePeriod,
        diagnostics: list[AreraDiagnostic],
    ) -> list[AreraChargeValue]:
        text_cells = {
            ref: _normalise_text(cell.value)
            for ref, cell in raw_sheet.cells.items()
            if cell.value is not None and cell.kind in {"s", "inlineStr", "str"}
        }
        markers: list[tuple[int, AreraCustomerSegment]] = []
        for ref, text in text_cells.items():
            row = _row_number(ref)
            segment = _SEGMENT_MARKERS.get(text.upper())
            if segment is not None and _column_name(ref) == "B":
                markers.append((row, segment))
        if len(markers) != 2:
            diagnostics.append(
                _error("SEGMENT_MARKERS", "expected two customer segment markers", raw_sheet.name)
            )
            return []
        charges: list[AreraChargeValue] = []
        seen_segments: set[AreraCustomerSegment] = set()
        for marker_row, segment in sorted(markers):
            if segment in seen_segments:
                diagnostics.append(
                    _error("DUPLICATE_SEGMENT", "duplicate customer segment", raw_sheet.name)
                )
                continue
            seen_segments.add(segment)
            charges.extend(
                self._parse_segment(
                    snapshot, raw_sheet, worksheet, period, marker_row, segment, diagnostics
                )
            )
        return charges

    def _parse_segment(
        self,
        snapshot: RawAreraSnapshot,
        raw_sheet: _RawSheet,
        worksheet: Any,
        period: DatePeriod,
        marker_row: int,
        segment: AreraCustomerSegment,
        diagnostics: list[AreraDiagnostic],
    ) -> list[AreraChargeValue]:
        group_row = marker_row + 1
        subheader_row = marker_row + 2
        group_expected = {
            "C": "vendita di energia elettrica",
            "I": "tariffa per l'uso della rete elettrica",
            "L": "oneri generali di sistema",
        }
        for column, expected in group_expected.items():
            actual = _text_at(raw_sheet, f"{column}{group_row}")
            if actual != expected:
                diagnostics.append(
                    _error(
                        "HEADER_GROUP",
                        f"expected {expected!r}, found {actual!r}",
                        raw_sheet.name,
                        f"{column}{group_row}",
                    )
                )
        for column, expected in _EXPECTED_SUBHEADERS.items():
            actual = _text_at(raw_sheet, f"{column}{subheader_row}")
            if actual != expected:
                diagnostics.append(
                    _error(
                        "HEADER_COMPONENT",
                        f"expected {expected!r}, found {actual!r}",
                        raw_sheet.name,
                        f"{column}{subheader_row}",
                    )
                )
        known_header_columns = set(_EXPECTED_SUBHEADERS) | {"I", "L"}
        for ref, cell in raw_sheet.cells.items():
            if _row_number(ref) != subheader_row or cell.value is None:
                continue
            column = _column_name(ref)
            if column not in known_header_columns:
                diagnostics.append(
                    _error(
                        "HEADER_COMPONENT",
                        "unexpected component header",
                        raw_sheet.name,
                        ref,
                    )
                )
        labels: dict[BillingQuota, tuple[int, RateUnit]] = {}
        for row in range(marker_row + 3, marker_row + 8):
            label = _text_at(raw_sheet, f"B{row}")
            if label in _QUOTA_ROWS:
                labels[_QUOTA_ROWS[label][0]] = (row, _QUOTA_ROWS[label][1])
        if set(labels) != {BillingQuota.CONSUMPTION, BillingQuota.FIXED, BillingQuota.POWER}:
            diagnostics.append(
                _error("QUOTA_ROWS", "expected energy, fixed, and power rows", raw_sheet.name)
            )
            return []
        charges: list[AreraChargeValue] = []
        values_by_row: dict[BillingQuota, dict[str, Decimal]] = {}
        formats_by_row: dict[BillingQuota, dict[str, str]] = {}
        for quota, (row, rate_unit) in labels.items():
            row_values: dict[str, Decimal] = {}
            row_formats: dict[str, str] = {}
            for column, (component, category, role) in _COLUMN_COMPONENTS.items():
                ref = f"{column}{row}"
                raw_cell = raw_sheet.cells.get(ref)
                if raw_cell is None:
                    diagnostics.append(
                        _error("MISSING_CELL", "economic cell is missing", raw_sheet.name, ref)
                    )
                    continue
                value = _economic_cell_value(
                    raw_cell,
                    worksheet[ref].number_format,
                    diagnostics,
                    raw_sheet.name,
                    ref,
                )
                if value is None:
                    continue
                row_values[column] = value
                row_formats[column] = worksheet[ref].number_format
                code = (
                    f"arera:2026:{period.start.month:02d}:{segment.value}:{component}:{quota.value}"
                )
                locator = AreraSourceLocator(
                    sheet=raw_sheet.name,
                    cell=ref,
                    label=_text_at(raw_sheet, f"{column}{subheader_row}") or component,
                    number_format=worksheet[ref].number_format,
                )
                charges.append(
                    AreraChargeValue(
                        code=code,
                        segment=segment,
                        component_code=component,
                        category=category,
                        quota=quota,
                        rate=UnitRate(amount=value, unit=rate_unit),
                        validity=period,
                        role=role,
                        source=locator,
                        status=VerificationStatus.UNVERIFIED,
                        provenance=(make_provenance(snapshot, period),),
                    )
                )
            values_by_row[quota] = row_values
            formats_by_row[quota] = row_formats
            self._validate_totals(
                values_by_row, formats_by_row, quota, raw_sheet.name, row, diagnostics
            )
        return charges

    @staticmethod
    def _validate_totals(
        values_by_row: Mapping[BillingQuota, Mapping[str, Decimal]],
        formats_by_row: Mapping[BillingQuota, Mapping[str, str]],
        quota: BillingQuota,
        sheet: str,
        row: int,
        diagnostics: list[AreraDiagnostic],
    ) -> None:
        values = values_by_row[quota]
        formats = formats_by_row[quota]
        network_parts = [values[column] for column in ("D", "E", "F", "G", "H") if column in values]
        system_parts = [values[column] for column in ("J", "K") if column in values]
        network_total = _quantize_for_format(sum(network_parts, Decimal(0)), formats.get("I"))
        system_total = _quantize_for_format(sum(system_parts, Decimal(0)), formats.get("L"))
        if "I" in values and network_total != values["I"]:
            diagnostics.append(
                _error(
                    "NETWORK_TOTAL",
                    "network total does not match source components",
                    sheet,
                    f"I{row}",
                )
            )
        if "L" in values and system_total != values["L"]:
            diagnostics.append(
                _error(
                    "SYSTEM_TOTAL",
                    "system total does not match source components",
                    sheet,
                    f"L{row}",
                )
            )


def _read_limited(response: Any, limit: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(min(64 * 1024, limit + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
        if total > limit:
            raise AreraFetchError("ARERA response exceeds the maximum content size")


def _is_allowed_url(value: str) -> bool:
    parsed = urlsplit(value)
    return (
        parsed.scheme == "https"
        and parsed.hostname == ARERA_HOST
        and parsed.path == urlsplit(ARERA_DOMESTIC_2026_URL).path
        and not parsed.query
        and not parsed.fragment
    )


def _content_type(headers: Iterable[AreraHeader]) -> str | None:
    for header in headers:
        if header.name.lower() == "content-type":
            return header.value.split(";", 1)[0].strip().lower()
    return None


def _validate_archive(content: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise AreraImportError("XLSX archive has too many entries")
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise AreraImportError("XLSX archive contains duplicate paths")
            total = 0
            for info in infos:
                path = PurePosixPath(info.filename)
                if path.is_absolute() or ".." in path.parts:
                    raise AreraImportError("XLSX archive contains an unsafe path")
                total += info.file_size
                if total > MAX_UNCOMPRESSED_BYTES:
                    raise AreraImportError("XLSX archive exceeds the maximum uncompressed size")
            lower_names = {name.lower() for name in names}
            if any(
                name.endswith("vbaproject.bin")
                or name.startswith("xl/externallinks/")
                or name.startswith("xl/activex/")
                for name in lower_names
            ):
                raise AreraImportError("XLSX archive contains macros or external links")
            required = {"[content_types].xml", "xl/workbook.xml", "xl/styles.xml"}
            if not required.issubset(lower_names):
                raise AreraImportError("XLSX archive misses required OOXML parts")
    except zipfile.BadZipFile as exc:
        raise AreraImportError("input is not a valid XLSX archive") from exc


def _read_workbook(content: bytes) -> tuple[tuple[_RawSheet, ...], Any]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        shared = _read_shared_strings(archive)
        workbook_root = SafeET.fromstring(archive.read("xl/workbook.xml"))
        relationships = SafeET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships.findall(f"{{{_PKG_REL_NS}}}Relationship")
        }
        sheets: list[_RawSheet] = []
        for sheet in workbook_root.findall(f".//{{{_MAIN_NS}}}sheet"):
            name = sheet.attrib.get("name", "")
            relation_id = sheet.attrib.get(f"{{{_REL_NS}}}id")
            if not name or relation_id not in targets:
                raise AreraImportError("workbook sheet relationship is incomplete")
            target = posixpath.normpath(posixpath.join("xl", targets[relation_id])).lstrip("/")
            if target not in archive.namelist():
                raise AreraImportError(f"worksheet target is missing: {target}")
            sheets.append(_read_sheet(archive.read(target), name, shared))
    try:
        from openpyxl import load_workbook

        workbook = load_workbook(
            io.BytesIO(content), read_only=False, data_only=False, keep_links=False
        )
    except Exception as exc:
        raise AreraImportError(f"openpyxl could not read workbook: {exc}") from exc
    return tuple(sheets), workbook


def _read_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    try:
        root = SafeET.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return ()
    result: list[str] = []
    for item in root.findall(f"{{{_MAIN_NS}}}si"):
        result.append("".join(text.text or "" for text in item.iter(f"{{{_MAIN_NS}}}t")))
    return tuple(result)


def _read_sheet(content: bytes, name: str, shared: tuple[str, ...]) -> _RawSheet:
    root = SafeET.fromstring(content)
    cells: dict[str, _RawCell] = {}
    for element in root.findall(f".//{{{_MAIN_NS}}}c"):
        ref = element.attrib.get("r")
        if not ref or ref in cells:
            raise AreraImportError(f"duplicate or missing cell reference in sheet {name}")
        kind = element.attrib.get("t")
        formula = element.find(f"{{{_MAIN_NS}}}f") is not None
        value_element = element.find(f"{{{_MAIN_NS}}}v")
        inline = element.find(f"{{{_MAIN_NS}}}is")
        value = None if value_element is None else value_element.text
        if kind == "s" and value is not None:
            try:
                value = shared[int(value)]
            except (IndexError, ValueError) as exc:
                raise AreraImportError(f"invalid shared string at {name}!{ref}") from exc
        elif kind == "inlineStr" and inline is not None:
            value = "".join(text.text or "" for text in inline.iter(f"{{{_MAIN_NS}}}t"))
        cells[ref] = _RawCell(ref=ref, kind=kind, value=value, formula=formula)
    return _RawSheet(name=name, cells=cells)


def _month_from_sheet_name(name: str) -> int | None:
    match = re.fullmatch(r"([A-Za-zàèéìòù]+)\s+2026", name.strip(), flags=re.IGNORECASE)
    return None if match is None else _MONTHS.get(match.group(1).casefold())


def _month_period(year: int, month: int) -> DatePeriod:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return DatePeriod(start=start, end=end)


def _normalise_text(value: str | None) -> str:
    return " ".join((value or "").strip().split()).casefold()


def _text_at(sheet: _RawSheet, ref: str) -> str:
    cell = sheet.cells.get(ref)
    if cell is None or cell.value is None:
        return ""
    return _normalise_text(cell.value)


def _economic_cell_value(
    cell: _RawCell,
    number_format: str,
    diagnostics: list[AreraDiagnostic],
    sheet: str,
    ref: str,
) -> Decimal | None:
    if cell.formula:
        diagnostics.append(_error("FORMULA", "economic cell contains a formula", sheet, ref))
        return None
    if cell.kind in {"s", "inlineStr", "str"}:
        text = _normalise_text(cell.value)
        if text in {"", "-", "\u2013", "\u2014"}:
            return None
        diagnostics.append(_error("NON_NUMERIC", "economic cell is not numeric or '-'", sheet, ref))
        return None
    if cell.value is None:
        diagnostics.append(_error("MISSING_VALUE", "economic cell has no value", sheet, ref))
        return None
    places = _decimal_places(number_format)
    if places is None:
        diagnostics.append(
            _error("NUMBER_FORMAT", "economic cell has no fixed decimal format", sheet, ref)
        )
        return None
    try:
        value = Decimal(cell.value)
    except InvalidOperation:
        diagnostics.append(_error("DECIMAL", "economic cell is not a finite Decimal", sheet, ref))
        return None
    if not value.is_finite() or value < 0:
        diagnostics.append(
            _error(
                "ECONOMIC_VALUE",
                "economic cell must be finite and non-negative",
                sheet,
                ref,
            )
        )
        return None
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def _decimal_places(number_format: str) -> int | None:
    section = number_format.split(";", 1)[0]
    section = re.sub(r'"[^"]*"', "", section)
    section = re.sub(r"\\.", "", section)
    if "." not in section:
        return 0 if re.search(r"[0#]", section) else None
    fraction = section.split(".", 1)[1]
    fraction = re.split(r"[_*]", fraction, maxsplit=1)[0]
    fraction = re.sub(r"[^0#]", "", fraction)
    return len(fraction) if fraction else None


def _quantize_for_format(value: Decimal, number_format: str | None) -> Decimal:
    places = _decimal_places(number_format or "")
    if places is None:
        return value
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def _column_name(ref: str) -> str:
    return re.match(r"[A-Za-z]+", ref).group(0).upper()  # type: ignore[union-attr]


def _row_number(ref: str) -> int:
    return int(re.search(r"[0-9]+$", ref).group(0))  # type: ignore[union-attr]


def _error(code: str, message: str, sheet: str | None, cell: str | None = None) -> AreraDiagnostic:
    return AreraDiagnostic(
        severity=AreraDiagnosticSeverity.ERROR,
        code=code,
        message=message,
        sheet=sheet,
        cell=cell,
    )


def _dedupe_provenance(items: Iterable[Provenance]) -> tuple[Provenance, ...]:
    result: list[Provenance] = []
    seen: set[str] = set()
    for item in items:
        key = item.model_dump_json()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return tuple(result)
