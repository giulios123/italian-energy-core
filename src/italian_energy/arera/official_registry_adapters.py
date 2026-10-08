"""Official, versioned registry adapters used by the rollover service.

The adapters in this module parse only known index/API contracts. They never
interpret legal prose into economic values. An index response outside its
registered layout fails closed and cannot advance a discovery cursor.
"""

from __future__ import annotations

import hashlib
import json
import re
import ssl
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

import truststore

from italian_energy.arera.discovery import (
    DiscoveryFailure,
    OfficialRegistryRecord,
    RegistryIndexAdapter,
    RegistryIndexPage,
    RegulatoryRegistryChannel,
)
from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.arera.rollover_parsers import (
    ADM_EXCISE_DOMESTIC_KIND,
    ADM_EXCISE_LAYOUT_VERSION,
    ADM_EXCISE_PDF_MIME,
    ARERA_343_CONFIRMATION_DOCUMENT_KIND,
    ARERA_343_CONFIRMATION_LAYOUT_VERSION,
    ARERA_343_DETAIL_URL,
    ARERA_343_PDF_URL,
    ARERA_DOMESTIC_WORKBOOK_KIND,
    NORMATTIVA_VAT_ART16_DOCUMENT_ID,
    NORMATTIVA_VAT_ART16_KIND,
    NORMATTIVA_VAT_ART16_SOURCE_ID,
    NORMATTIVA_VAT_ART16_URN,
    NORMATTIVA_VAT_LAYOUT_VERSION,
    NORMATTIVA_VAT_TABLE_A_KIND,
    NORMATTIVA_VAT_TABLE_DOCUMENT_ID,
    NORMATTIVA_VAT_TABLE_SOURCE_ID,
    NORMATTIVA_VAT_TABLE_URN,
    RegulatorySourceDocument,
)
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.domain.time import DatePeriod

_NORMATTIVA_PRODUCTION_ENDPOINT = (
    "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/ricerca/aggiornati"
)
_ROMAN = ZoneInfo("Europe/Rome")
_UTC = UTC
_MAX_RESPONSE_BYTES = 24_000_000
_NORMATTIVA_FIELDS = frozenset(
    {
        "codiceRedazionale",
        "titoloAtto",
        "dataGU",
        "dataUltimaModifica",
        "descrizioneAtto",
        "ultimiAttiModificanti",
    }
)


def normattiva_vat_reference_records(as_of: date) -> tuple[OfficialRegistryRecord, ...]:
    """Build exact date-dated records for the two known statutory VAT references.

    These are source acquisitions, not Normattiva registry findings. Registry
    discovery remains responsible for identifying new or amended acts.
    """

    return (
        OfficialRegistryRecord(
            channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
            act_id="DPR 633/1972",
            title="DPR 633/1972 Tabella A Parte III n. 103",
            published_at=date(1972, 10, 26),
            registry_date=as_of,
            url=(
                f"https://www.normattiva.it/uri-res/N2Ls?{NORMATTIVA_VAT_TABLE_URN}"
                f"!vig={as_of.isoformat()}"
            ),
            document_id="DPR-633-1972-Tabella-A-Parte-III-n-103",
        ),
        OfficialRegistryRecord(
            channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
            act_id="DPR 633/1972",
            title="DPR 633/1972 art. 16 aliquote",
            published_at=date(1972, 10, 26),
            registry_date=as_of,
            url=(
                f"https://www.normattiva.it/uri-res/N2Ls?{NORMATTIVA_VAT_ART16_URN}"
                f"!vig={as_of.isoformat()}"
            ),
            document_id="DPR-633-1972-art-16-aliquote",
        ),
    )


@dataclass(frozen=True, slots=True)
class OfficialRegistryHTTPResponse:
    """Exact response metadata and bytes returned by an official registry."""

    requested_url: str
    final_url: str
    content_type: str
    body: bytes
    fetched_at: datetime


class OfficialRegistryTransport(Protocol):
    """Minimal transport port; adapters own request and response semantics."""

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> OfficialRegistryHTTPResponse: ...


class RecordingOfficialRegistryTransport:
    """Record exact successful HTTP responses through the Core storage port."""

    def __init__(
        self,
        transport: OfficialRegistryTransport,
        observer: Callable[[AcquiredOfficialBytes], None],
    ) -> None:
        self._transport = transport
        self._observer = observer

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> OfficialRegistryHTTPResponse:
        response = self._transport.request(url, method=method, headers=headers, body=body)
        self._observer(
            AcquiredOfficialBytes(
                url=response.requested_url,
                body=response.body,
                sha256=hashlib.sha256(response.body).hexdigest(),
                fetched_at=response.fetched_at,
                final_url=response.final_url,
                content_type=response.content_type,
                byte_length=len(response.body),
            )
        )
        return response


class UrllibOfficialRegistryTransport:
    """Bounded HTTPS transport restricted to the requested official registry host."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] | None = None,
        timeout_seconds: int = 30,
    ) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._timeout_seconds = timeout_seconds
        self._ssl_context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> OfficialRegistryHTTPResponse:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        request = urllib.request.Request(
            url,
            data=body,
            headers={"User-Agent": "italian-energy-core/0.13", **(headers or {})},
            method=method,
        )
        try:
            with urllib.request.urlopen(
                request, timeout=self._timeout_seconds, context=self._ssl_context
            ) as response:
                final_url = response.geturl()
                final = urlsplit(final_url)
                if final.scheme != "https" or final.hostname != parsed.hostname:
                    raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                content = response.read(_MAX_RESPONSE_BYTES + 1)
                content_type = response.headers.get("Content-Type", "")
        except DiscoveryFailure:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_UNAVAILABLE) from exc
        if not content or len(content) > _MAX_RESPONSE_BYTES:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        if not content_type.strip():
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        fetched_at = self._clock()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("official registry transport clock must be timezone-aware")
        return OfficialRegistryHTTPResponse(
            requested_url=url,
            final_url=final_url,
            content_type=content_type,
            body=content,
            fetched_at=fetched_at,
        )


class NormattivaUpdatesAdapter:
    """Normattiva Open Data `ricerca/aggiornati` production API adapter v1.

    The registry date is `dataUltimaModifica`; `dataGU` remains the original
    publication date. The documented API does not expose a page parameter, so
    a multi-page or internally limited response is incomplete by definition.
    """

    channel = RegulatoryRegistryChannel.NORMATTIVA_UPDATES
    adapter_id = "normattiva-open-data-updated-acts"
    adapter_version = "1.0.0"

    def __init__(
        self,
        *,
        transport: OfficialRegistryTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or UrllibOfficialRegistryTransport(clock=clock)
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        if page_number != 1:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        start = datetime.combine(search_period.start, time.min, tzinfo=_ROMAN).astimezone(_UTC)
        end = datetime.combine(search_period.end, time.min, tzinfo=_ROMAN).astimezone(_UTC)
        request_body = json.dumps(
            {
                "dataInizioAggiornamento": start.isoformat().replace("+00:00", "Z"),
                "dataFineAggiornamento": end.isoformat().replace("+00:00", "Z"),
            },
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._transport.request(
            _NORMATTIVA_PRODUCTION_ENDPOINT,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            body=request_body,
        )
        if (
            urlsplit(response.final_url).hostname != "api.normattiva.it"
            or response.content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
        if not isinstance(payload, Mapping):
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        items = payload.get("listaAtti")
        total_pages = payload.get("numeroPagine")
        total_results = payload.get("numeroAttiTrovati")
        current_page = payload.get("paginaCorrente")
        if (
            not isinstance(items, list)
            or isinstance(total_pages, bool)
            or not isinstance(total_pages, int)
            or isinstance(total_results, bool)
            or not isinstance(total_results, int)
            or current_page != 1
        ):
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        if total_pages != 1 or total_results != len(items):
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        records: list[OfficialRegistryRecord] = []
        for item in items:
            if not isinstance(item, Mapping) or not _NORMATTIVA_FIELDS.issubset(item):
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
            try:
                act_id = _required_text(item["codiceRedazionale"])
                title = _required_text(item["titoloAtto"])
                _required_text(item["descrizioneAtto"])
                published_at = date.fromisoformat(_required_text(item["dataGU"]))
                updated_at = date.fromisoformat(_required_text(item["dataUltimaModifica"]))
                raw_amending_act_ids = item["ultimiAttiModificanti"]
                if raw_amending_act_ids is None:
                    amending_act_ids: tuple[str, ...] = ()
                elif isinstance(raw_amending_act_ids, str):
                    amending_act_ids = tuple(sorted(set(raw_amending_act_ids.split())))
                else:
                    raise ValueError("Normattiva amending act IDs have an unsupported shape")
                record = OfficialRegistryRecord(
                    channel=self.channel,
                    act_id=act_id,
                    title=title,
                    published_at=published_at,
                    registry_date=updated_at,
                    url=response.final_url,
                    document_id=act_id,
                    latest_amending_act_ids=amending_act_ids,
                )
            except (TypeError, ValueError) as exc:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
            records.append(record)
        observed_at = response.fetched_at
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        return RegistryIndexPage(
            channel=self.channel,
            search_period=search_period,
            query="normattiva-open-data-updated-acts-v1",
            source_url=response.final_url,
            fetched_at=observed_at,
            page_number=1,
            total_pages=1,
            total_results=total_results,
            cursor_in=cursor,
            cursor_out=search_period.end.isoformat(),
            index_sha256=hashlib.sha256(response.body).hexdigest(),
            complete=True,
            records=tuple(sorted(records, key=lambda record: record.act_id)),
        )


class _LinkCollector(HTMLParser):
    """Collect anchor text and body text without interpreting arbitrary markup."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.contextual_links: list[tuple[str, str, str]] = []
        self.sectional_links: list[tuple[str, str, str | None]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._anchor_text: list[str] = []
        self._list_item_stack: list[list[str]] = []
        self._registry_section: str | None = None
        self._heading_kind: str | None = None
        self._heading_depth = 0
        self._heading_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        values = dict(attrs)
        classes = set((values.get("class") or "").split())
        if normalized_tag == "span" and "rubrica" in classes:
            if self._heading_kind is not None:
                raise ValueError("nested Gazzetta registry section headings are unsupported")
            self._heading_kind = "rubrica"
            self._heading_depth = 1
            self._heading_text = []
        elif self._heading_kind is not None:
            self._heading_depth += 1
        if normalized_tag == "li":
            self._list_item_stack.append([])
        if normalized_tag != "a":
            return
        self._href = values.get("href")
        self._anchor_text = []

    def handle_endtag(self, tag: str) -> None:
        normalized_tag = tag.lower()
        if self._heading_kind is not None:
            self._heading_depth -= 1
            if self._heading_depth == 0:
                if self._heading_kind == "rubrica":
                    section = " ".join("".join(self._heading_text).split()).upper()
                    if not section:
                        raise ValueError("empty Gazzetta registry section")
                    self._registry_section = section
                self._heading_kind = None
                self._heading_text = []
            return
        if normalized_tag == "li":
            if self._list_item_stack:
                self._list_item_stack.pop()
            return
        if normalized_tag != "a" or self._href is None:
            return
        label = " ".join("".join(self._anchor_text).split())
        self.links.append((self._href, label))
        context = (
            " ".join("".join(self._list_item_stack[-1]).split()) if self._list_item_stack else ""
        )
        self.contextual_links.append((self._href, label, context))
        self.sectional_links.append((self._href, label, self._registry_section))
        self._href = None
        self._anchor_text = []

    def handle_data(self, data: str) -> None:
        self.text.append(data)
        if self._heading_kind is not None:
            self._heading_text.append(data)
        if self._list_item_stack:
            self._list_item_stack[-1].append(data)
        if self._href is not None:
            self._anchor_text.append(data)


def _parse_html(response: OfficialRegistryHTTPResponse) -> _LinkCollector:
    if response.content_type.split(";", 1)[0].strip().lower() != "text/html":
        raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
    try:
        source = response.body.decode("utf-8")
        parser = _LinkCollector()
        parser.feed(source)
        parser.close()
    except (UnicodeDecodeError, ValueError) as exc:
        raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
    return parser


def _response_digest(*responses: OfficialRegistryHTTPResponse) -> str:
    digest = hashlib.sha256()
    for response in responses:
        digest.update(response.requested_url.encode("utf-8"))
        digest.update(b"\0")
        digest.update(response.body)
        digest.update(b"\0")
    return digest.hexdigest()


def _date_ddmmyyyy(value: str) -> date:
    return datetime.strptime(value, "%d/%m/%Y").date()


_ITALIAN_MONTHS = {
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


def _date_italian_long(value: str) -> date:
    match = re.fullmatch(r"\s*(\d{1,2})\s+([A-Za-zàèéìòù]+)\s+(\d{4})\s*", value)
    if match is None:
        raise ValueError("unsupported official Italian date layout")
    day, month_name, year = match.groups()
    month = _ITALIAN_MONTHS.get(month_name.lower())
    if month is None:
        raise ValueError("unsupported official Italian month")
    return date(int(year), month, int(day))


class AreraActsIndexAdapter:
    """ARERA acts listing v1, paginated by year and exact detail links."""

    channel = RegulatoryRegistryChannel.ARERA_ACTS
    adapter_id = "arera-acts-index"
    adapter_version = "1.1.0"
    _base_url = "https://www.arera.it/atti-e-provvedimenti"
    _result_count = re.compile(r"Numero pagine:\s*(\d+)\s+per\s+(\d+)\s+risultati", re.I)
    # The official index uses both date-first rows and rows with an opaque
    # category label before the date. The category is retained in the title,
    # never interpreted; date and act ID remain exact required fields.
    _act_prefix = re.compile(
        r"^(?:.+?\s+)?(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<rest>.+)$",
        re.I,
    )
    _act_id = re.compile(
        r"^(?P<id>\d+/\d{4}(?:(?:/[A-Za-z]+){1,2}"
        r"(?:\s*-\s*[A-Z]+(?:-[a-z]+)?)?|\s*-\s*[A-Z]+(?:-[a-z]+)?)?|"
        r"\d+/\d{2}\s*-\s*[A-Z]+(?:-[a-z]+)?)\b"
    )

    def __init__(self, transport: OfficialRegistryTransport | None = None) -> None:
        self._transport = transport or UrllibOfficialRegistryTransport()
        self._period_key: DatePeriod | None = None
        self._years: tuple[int, ...] = ()
        self._year_totals: dict[int, tuple[int, int]] = {}
        self._page_cache: dict[
            tuple[int, int], tuple[OfficialRegistryHTTPResponse, tuple[OfficialRegistryRecord, ...]]
        ] = {}

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        years = tuple(range(search_period.start.year, (search_period.end - _ONE_DAY).year + 1))
        if not years or len(years) > 3:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        if self._period_key != search_period:
            self._reset(search_period, years)
        self._initialize_years(search_period)
        total_pages = sum(item[0] for item in self._year_totals.values())
        total_results = sum(item[1] for item in self._year_totals.values())
        if page_number < 1 or page_number > total_pages:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        target_year, local_page = self._locate_page(page_number)
        response, records = self._get_year_page(search_period, target_year, local_page)
        next_cursor = (
            f"arera-page:{page_number + 1}"
            if page_number < total_pages
            else search_period.end.isoformat()
        )
        fetched_at = response.fetched_at
        return RegistryIndexPage(
            channel=self.channel,
            search_period=search_period,
            query=f"arera-acts-index-v1:years={','.join(map(str, self._years))}",
            source_url=response.final_url,
            fetched_at=fetched_at,
            page_number=page_number,
            total_pages=total_pages,
            total_results=total_results,
            cursor_in=cursor,
            cursor_out=next_cursor,
            index_sha256=hashlib.sha256(response.body).hexdigest(),
            complete=True,
            records_confined_to_search_period=False,
            records=records,
        )

    def _reset(self, period: DatePeriod, years: tuple[int, ...]) -> None:
        self._period_key = period
        self._years = years
        self._year_totals = {}
        self._page_cache = {}

    def _initialize_years(self, period: DatePeriod) -> None:
        for year in self._years:
            if year not in self._year_totals:
                response, _ = self._fetch_arera_page(period, year, 1)
                self._page_cache[(year, 1)] = (response, _)
                parser = _parse_html(response)
                match = self._result_count.search(" ".join(parser.text))
                if match is None:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
                pages, results = (int(match.group(1)), int(match.group(2)))
                if pages < 1 or results < len(_):
                    raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
                self._year_totals[year] = (pages, results)

    def _fetch_arera_page(
        self, period: DatePeriod, year: int, page_number: int
    ) -> tuple[OfficialRegistryHTTPResponse, tuple[OfficialRegistryRecord, ...]]:
        query = urlencode(
            {
                "ADMCMD_prev": "LIVE",
                "anno": str(year),
                "keyword": "",
                "numelements": "",
                "numero": "",
                "orderby": "",
                "orderbydir": "",
                "pagina": str(page_number),
                "settore": "",
                "tipologia": "",
            }
        )
        response = self._transport.request(f"{self._base_url}?{query}")
        parser = _parse_html(response)
        text = " ".join(parser.text)
        if "Atti e provvedimenti" not in text or "Numero pagine:" not in text:
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        records: list[OfficialRegistryRecord] = []
        for href, label in parser.links:
            if "/atti-e-provvedimenti/dettaglio/" not in href:
                continue
            match = self._act_prefix.match(label)
            if match is None:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
            id_match = self._act_id.match(match.group("rest"))
            if id_match is None:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
            act_id = " ".join(id_match.group("id").split())
            try:
                published_at = _date_ddmmyyyy(match.group("date"))
            except ValueError as exc:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
            records.append(
                OfficialRegistryRecord(
                    channel=self.channel,
                    act_id=act_id,
                    title=label,
                    published_at=published_at,
                    registry_date=published_at,
                    url=urljoin(response.final_url, href),
                    document_id=act_id,
                )
            )
        if not records and self._result_count.search(text) is None:
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        if len({item.act_id for item in records}) != len(records):
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        return response, tuple(records)

    def _get_year_page(
        self, period: DatePeriod, year: int, page_number: int
    ) -> tuple[OfficialRegistryHTTPResponse, tuple[OfficialRegistryRecord, ...]]:
        value = self._page_cache.get((year, page_number))
        if value is None:
            value = self._fetch_arera_page(period, year, page_number)
            self._page_cache[(year, page_number)] = value
        return value

    def _locate_page(self, page_number: int) -> tuple[int, int]:
        remaining = page_number
        for year in self._years:
            year_pages = self._year_totals[year][0]
            if remaining <= year_pages:
                return year, remaining
            remaining -= year_pages
        raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)


class AreraTariffIndexAdapter:
    """ARERA quarterly tariff listing v2, cross-checked for in-period acts."""

    channel = RegulatoryRegistryChannel.ARERA_TARIFFS
    adapter_id = "arera-system-charges-index"
    adapter_version = "1.2.0"
    _index_url = (
        "https://www.arera.it/area-operatori/prezzi-e-tariffe/"
        "oneri-generali-di-sistema-e-ulteriori-componenti"
    )
    _effective_date_prefix = re.compile(
        r"^\s*dal\s*(?P<day>\d{1,2})\s*(?:"
        r"\.(?P<short_month>\d{1,2})\.(?P<short_year>\d{2})|"
        r"(?P<long_month>[A-Za-zàèéìòù]+)\s*(?P<long_year>\d{4})"
        r")\s*(?:[\u2013:-]\s*)?(?P<rest>.*)$",
        re.I,
    )
    _published = re.compile(r"Data pubblicazione:\s*([^\n]+)", re.I)
    _act_number = re.compile(r"(?<!\d)(\d+/\d{4}/[A-Za-z]+/[A-Za-z]+)(?!\w)")
    _act_detail_path = re.compile(
        r"^/atti-e-provvedimenti/dettaglio/(?P<folder_year>\d{2})/"
        r"(?P<number>\d+)-(?P<file_year>\d{2})/?$",
        re.I,
    )

    def __init__(self, transport: OfficialRegistryTransport | None = None) -> None:
        self._transport = transport or UrllibOfficialRegistryTransport()

    @classmethod
    def _parse_effective_date_prefix(cls, value: str) -> tuple[date, str] | None:
        match = cls._effective_date_prefix.match(value)
        if match is None:
            return None
        try:
            day = int(match.group("day"))
            if match.group("short_month") is not None:
                year = 2000 + int(match.group("short_year"))
                month = int(match.group("short_month"))
            else:
                year = int(match.group("long_year"))
                month_name = match.group("long_month").lower()
                month = _ITALIAN_MONTHS.get(month_name, 0)
                if month == 0:
                    raise ValueError("unsupported official Italian month")
            effective_at = date(year, month, day)
        except (TypeError, ValueError) as exc:
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
        return effective_at, match.group("rest").strip()

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        if page_number != 1:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        index = self._transport.request(self._index_url)
        parser = _parse_html(index)
        if "Valori delle componenti" not in " ".join(parser.text):
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        records_by_act_id: dict[str, OfficialRegistryRecord] = {}
        digested = [index]
        saw_dated_entry = False
        for href, label, context in parser.contextual_links:
            if context and context.lstrip().lower().startswith("dal "):
                date_match = self._parse_effective_date_prefix(context)
                act_text = label
                if date_match is None:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
                effective_at = date_match[0]
            else:
                date_match = self._parse_effective_date_prefix(label)
                if date_match is None:
                    continue
                effective_at, act_text = date_match
            saw_dated_entry = True
            if not search_period.start <= effective_at < search_period.end:
                continue
            expected_number = self._act_number.search(act_text)
            if expected_number is None:
                raise DiscoveryFailure(RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE)
            act_url = urljoin(index.final_url, href)
            if urlsplit(act_url).hostname not in self.channel.official_hosts:
                raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            act_id = expected_number.group(1)
            existing = records_by_act_id.get(act_id)
            if existing is not None:
                if existing.effective_from != effective_at or existing.url != act_url:
                    raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                titles = sorted({existing.title, label})
                records_by_act_id[act_id] = existing.model_copy(
                    update={"title": " | ".join(titles)}
                )
                continue
            detail = self._transport.request(act_url)
            detail_parser = _parse_html(detail)
            detail_text = " ".join(detail_parser.text)
            published = self._published.search(detail_text)
            detail_number = self._act_number.search(detail_text)
            if published is None or detail_number is None:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
            if detail_number.group(1) != act_id:
                raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            act_identity = re.fullmatch(
                r"(?P<number>\d+)/(?P<year>\d{4})/[A-Za-z]+/[A-Za-z]+", act_id
            )
            if act_identity is None:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
            for detail_url in (act_url, detail.final_url):
                detail_parts = urlsplit(detail_url)
                detail_path = self._act_detail_path.fullmatch(detail_parts.path)
                if (
                    detail_parts.hostname not in self.channel.official_hosts
                    or detail_path is None
                    or int(detail_path.group("number")) != int(act_identity.group("number"))
                    or detail_path.group("folder_year") != detail_path.group("file_year")
                ):
                    raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            try:
                published_at = _date_italian_long(published.group(1))
            except ValueError as exc:
                raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
            records_by_act_id[act_id] = OfficialRegistryRecord(
                channel=self.channel,
                act_id=act_id,
                title=label,
                published_at=published_at,
                registry_date=published_at,
                effective_from=effective_at,
                url=act_url,
                document_id=act_id,
            )
            digested.append(detail)
        if not saw_dated_entry:
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        latest_fetch = max(item.fetched_at for item in digested)
        return RegistryIndexPage(
            channel=self.channel,
            search_period=search_period,
            query="arera-quarterly-system-charges-v1",
            source_url=index.final_url,
            fetched_at=latest_fetch,
            page_number=1,
            total_pages=1,
            total_results=len(records_by_act_id),
            cursor_in=cursor,
            cursor_out=search_period.end.isoformat(),
            index_sha256=_response_digest(*digested),
            complete=True,
            records_confined_to_search_period=True,
            records=tuple(
                sorted(
                    records_by_act_id.values(),
                    key=lambda item: (item.published_at, item.act_id),
                )
            ),
        )


class AdmExciseIndexAdapter:
    """ADM current and previous excise-rate index v1; PDFs remain parser-specific."""

    channel = RegulatoryRegistryChannel.ADM_EXCISE
    adapter_id = "adm-national-excise-index"
    adapter_version = "1.1.0"
    _current_url = "https://www.adm.gov.it/portale/aliquote-accisa-nazionali"
    _archive_url = "https://www.adm.gov.it/portale/-/aliquote-nazionali-anni-precedenti"
    _update = re.compile(
        r"^Aliquote nazionali\s*(?:\u2013\s*|-\s*)?Aggiornamento\s*(?:al\s*)?"
        r"(.+?)(?:\s*-\s*PDF|\.PDF)$",
        re.I,
    )

    def __init__(self, transport: OfficialRegistryTransport | None = None) -> None:
        self._transport = transport or UrllibOfficialRegistryTransport()

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        if page_number != 1:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        current = self._transport.request(self._current_url)
        archive = self._transport.request(self._archive_url)
        current_parser = _parse_html(current)
        archive_parser = _parse_html(archive)
        if "Aliquote nazionali periodi precedenti" not in " ".join(current_parser.text):
            raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
        records: dict[str, OfficialRegistryRecord] = {}
        for response, parser in ((current, current_parser), (archive, archive_parser)):
            for href, label in parser.links:
                if "aliquote" not in label.lower() or "pdf" not in label.lower():
                    continue
                match = self._update.search(label)
                if match is None:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
                try:
                    updated = _date_italian_long(match.group(1))
                except ValueError as exc:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
                source_url = urljoin(response.final_url, href)
                if urlsplit(source_url).hostname not in self.channel.official_hosts:
                    raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                path_id = urlsplit(source_url).path.rsplit("/", 1)[-1]
                record_id = f"adm-excise:{updated.isoformat()}:{path_id}"
                records[record_id] = OfficialRegistryRecord(
                    channel=self.channel,
                    act_id=record_id,
                    title=label,
                    published_at=updated,
                    registry_date=updated,
                    url=source_url,
                    document_id=path_id,
                )
        if not records:
            raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
        return RegistryIndexPage(
            channel=self.channel,
            search_period=search_period,
            query="adm-national-excise-current-and-archive-v1",
            source_url=current.final_url,
            fetched_at=max(current.fetched_at, archive.fetched_at),
            page_number=1,
            total_pages=1,
            total_results=len(records),
            cursor_in=cursor,
            cursor_out=search_period.end.isoformat(),
            index_sha256=_response_digest(current, archive),
            complete=True,
            records_confined_to_search_period=False,
            records=tuple(
                sorted(records.values(), key=lambda item: (item.published_at, item.act_id))
            ),
        )


class GazzettaSerieGeneraleIndexAdapter:
    """Enumerate every legal item and official rubric in issue summaries v2.

    The annual archive is only the issue index. A scan is complete only after
    every in-range issue page has been fetched and its act links enumerated.
    Rubric metadata is copied from the official `span.rubrica`; the adapter
    does not interpret the legal text.
    """

    channel = RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE
    adapter_id = "gazzetta-serie-generale-archive"
    adapter_version = "1.2.0"
    _base_url = "https://www.gazzettaufficiale.it/ricercaArchivioCompleto/serie_generale/"
    _issue_date = re.compile(
        r"^(?:n[°ºo]\s*\d+\s+del\s+(\d{2}-\d{2}-\d{4})|"
        r"Supplemento(?: ordinario)?\s+n[°ºo]\s*\d+\s+del\s+(\d{2}-\d{2}-\d{4}))$",
        re.I,
    )
    _issue_heading = re.compile(
        r"(?:Serie Generale\s+n\.\s*\d+\s+del\s+\d{1,2}-\d{1,2}-\d{4}|"
        r"Supplemento(?: ordinario)?\s+n\.\s*\d+)",
        re.I,
    )
    _act_path = "/atto/serie_generale/caricadettaglioatto/"

    def __init__(self, transport: OfficialRegistryTransport | None = None) -> None:
        self._transport = transport or UrllibOfficialRegistryTransport()

    def fetch_page(
        self, search_period: DatePeriod, page_number: int, cursor: str | None
    ) -> RegistryIndexPage:
        if page_number != 1:
            raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        years = range(search_period.start.year, (search_period.end - _ONE_DAY).year + 1)
        archive_responses = tuple(
            self._transport.request(f"{self._base_url}{year}") for year in years
        )
        issue_pages: list[OfficialRegistryHTTPResponse] = []
        issue_links: list[tuple[date, str, str]] = []
        for response in archive_responses:
            parser = _parse_html(response)
            text = " ".join(parser.text)
            if "Serie Generale (Formato Testuale)" not in text:
                raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            for href, label in parser.links:
                normalized_label = " ".join(label.split())
                if not normalized_label.lower().startswith(("n°", "nº", "no", "supplemento")):
                    parsed_href = urlsplit(href)
                    if parsed_href.path.endswith(
                        "caricaDettaglio"
                    ) and "numeroGazzetta" in parse_qs(parsed_href.query):
                        raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                    continue
                match = self._issue_date.fullmatch(normalized_label)
                if match is None:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
                raw_date = match.group(1) or match.group(2)
                try:
                    issue_date = datetime.strptime(raw_date, "%d-%m-%Y").date()
                except ValueError as exc:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
                if not search_period.start <= issue_date < search_period.end:
                    continue
                issue_url = urljoin(response.final_url, href)
                if urlsplit(issue_url).hostname not in self.channel.official_hosts:
                    raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                issue_links.append((issue_date, normalized_label, issue_url))

        records: dict[str, OfficialRegistryRecord] = {}
        for issue_date, _issue_label, issue_url in sorted(issue_links):
            issue_response = self._transport.request(issue_url)
            issue_parser = _parse_html(issue_response)
            issue_text = " ".join(issue_parser.text)
            date_tokens = {
                f"{issue_date.day}-{issue_date.month}-{issue_date.year}",
                issue_date.strftime("%d-%m-%Y"),
            }
            if (
                not self._issue_heading.search(issue_text)
                or "Sommario" not in issue_text
                or not any(token in issue_text for token in date_tokens)
            ):
                raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
            issue_pages.append(issue_response)
            issue_records = 0
            for href, title, registry_section in issue_parser.sectional_links:
                if self._act_path not in urlsplit(href).path.lower():
                    continue
                try:
                    query = parse_qs(urlsplit(href).query, strict_parsing=True)
                except ValueError as exc:
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE) from exc
                act_ids = query.get("atto.codiceRedazionale", [])
                normalized_title = " ".join(title.split())
                if (
                    len(act_ids) != 1
                    or not act_ids[0].strip()
                    or not normalized_title
                    or registry_section is None
                ):
                    raise DiscoveryFailure(RegulatoryRolloverReason.PARSER_FAILURE)
                act_id = act_ids[0].strip()
                source_url = urljoin(issue_response.final_url, href)
                if urlsplit(source_url).hostname not in self.channel.official_hosts:
                    raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                existing = records.get(act_id)
                if existing is not None:
                    if (
                        existing.published_at != issue_date
                        or existing.url != source_url
                        or existing.registry_section != registry_section
                    ):
                        raise DiscoveryFailure(RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY)
                    if len(normalized_title) > len(existing.title):
                        records[act_id] = existing.model_copy(update={"title": normalized_title})
                    continue
                records[act_id] = OfficialRegistryRecord(
                    channel=self.channel,
                    act_id=act_id,
                    title=normalized_title,
                    published_at=issue_date,
                    registry_date=issue_date,
                    url=source_url,
                    document_id=act_id,
                    registry_section=registry_section,
                )
                issue_records += 1
            if issue_records == 0:
                raise DiscoveryFailure(RegulatoryRolloverReason.INCOMPLETE_COVERAGE)
        responses = (*archive_responses, *issue_pages)
        return RegistryIndexPage(
            channel=self.channel,
            search_period=search_period,
            query=f"gazzetta-serie-generale-act-index-v2:years={','.join(map(str, years))}",
            source_url=archive_responses[0].final_url,
            fetched_at=max(item.fetched_at for item in responses),
            page_number=1,
            total_pages=1,
            total_results=len(records),
            cursor_in=cursor,
            cursor_out=search_period.end.isoformat(),
            index_sha256=_response_digest(*responses),
            complete=True,
            records_confined_to_search_period=True,
            records=tuple(
                sorted(records.values(), key=lambda item: (item.published_at, item.act_id))
            ),
        )


class OfficialRegulatoryDocumentAcquirer:
    """Acquire source bytes with exact metadata; unsupported layouts remain review."""

    def __init__(self, transport: OfficialRegistryTransport | None = None) -> None:
        self._transport = transport or UrllibOfficialRegistryTransport()

    def acquire(self, record: OfficialRegistryRecord) -> OfficialRegistryHTTPResponse:
        if self._is_exact_arera_343_record(record):
            return self._transport.request(ARERA_343_PDF_URL)
        return self._transport.request(record.url)

    @staticmethod
    def _is_exact_arera_343_record(record: OfficialRegistryRecord) -> bool:
        return (
            record.channel == RegulatoryRegistryChannel.ARERA_TARIFFS
            and record.act_id == "343/2026/R/com"
            and record.document_id == "343/2026/R/com"
            and record.published_at == date(2026, 9, 29)
            and record.effective_from == date(2026, 10, 1)
            and record.url == ARERA_343_DETAIL_URL
        )

    def acquire_document(self, record: OfficialRegistryRecord) -> RegulatorySourceDocument:
        """Freeze one document observation without assigning an unknown layout."""

        response = self.acquire(record)
        content_type = response.content_type.split(";", 1)[0].strip().lower()
        source_id = f"{record.channel.value}:{record.act_id}:{record.document_id}"
        known_normattiva_vat = {
            NORMATTIVA_VAT_TABLE_DOCUMENT_ID: (
                NORMATTIVA_VAT_TABLE_SOURCE_ID,
                NORMATTIVA_VAT_TABLE_A_KIND,
                NORMATTIVA_VAT_TABLE_URN,
            ),
            NORMATTIVA_VAT_ART16_DOCUMENT_ID: (
                NORMATTIVA_VAT_ART16_SOURCE_ID,
                NORMATTIVA_VAT_ART16_KIND,
                NORMATTIVA_VAT_ART16_URN,
            ),
        }.get(record.document_id)
        exact_arera_343 = self._is_exact_arera_343_record(record)
        if (
            known_normattiva_vat is not None
            and record.channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES
            and record.act_id == "DPR 633/1972"
            and record.published_at == date(1972, 10, 26)
            and record.registry_date is not None
            and record.url
            == (
                f"https://www.normattiva.it/uri-res/N2Ls?{known_normattiva_vat[2]}"
                f"!vig={record.registry_date.isoformat()}"
            )
            and content_type == "text/html"
        ):
            source_id, document_kind, layout_version = (
                known_normattiva_vat[0],
                known_normattiva_vat[1],
                NORMATTIVA_VAT_LAYOUT_VERSION,
            )
        elif exact_arera_343 and content_type == "application/pdf":
            source_id = "arera_343"
            document_kind = ARERA_343_CONFIRMATION_DOCUMENT_KIND
            layout_version = ARERA_343_CONFIRMATION_LAYOUT_VERSION
        elif (
            record.channel == RegulatoryRegistryChannel.ADM_EXCISE
            and content_type == ADM_EXCISE_PDF_MIME
            and record.registry_date == record.published_at
            and record.act_id
            == f"adm-excise:{record.published_at.isoformat()}:{record.document_id}"
            and urlsplit(record.url).scheme == "https"
            and urlsplit(record.url).hostname in record.channel.official_hosts
            and urlsplit(record.url).path.rsplit("/", 1)[-1] == record.document_id
        ):
            source_id = f"adm_excise_{record.published_at:%Y%m%d}"
            document_kind = ADM_EXCISE_DOMESTIC_KIND
            layout_version = ADM_EXCISE_LAYOUT_VERSION
        elif (
            record.channel == RegulatoryRegistryChannel.ARERA_TARIFFS
            and content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ):
            document_kind = ARERA_DOMESTIC_WORKBOOK_KIND
            layout_version = "005-domestic-electricity-2026-v1"
        else:
            document_kind = f"{record.channel.value}_unclassified_document"
            layout_version = "unregistered-v1"
        acquired = AcquiredOfficialBytes(
            url=response.requested_url,
            body=response.body,
            sha256=hashlib.sha256(response.body).hexdigest(),
            fetched_at=response.fetched_at,
            final_url=response.final_url,
            content_type=response.content_type,
            byte_length=len(response.body),
        )
        return RegulatorySourceDocument(
            acquired=acquired,
            source_id=source_id,
            channel=record.channel,
            act_id=record.act_id,
            document_id=record.document_id,
            published_at=record.published_at,
            content_type=response.content_type,
            document_kind=document_kind,
            layout_version=layout_version,
            record_url=record.url,
        )

    def fetch_source(self, url: str) -> bytes:
        """Fetch exact source bytes for existing-anchor coverage checks."""

        return self._transport.request(url).body


_ONE_DAY = timedelta(days=1)


def default_official_registry_adapters(
    *,
    transport_factory: Callable[[], OfficialRegistryTransport] = UrllibOfficialRegistryTransport,
    source_observer: Callable[[AcquiredOfficialBytes], None] | None = None,
) -> tuple[RegistryIndexAdapter, ...]:
    """Construct the five official registry adapters with isolated transports."""

    def new_transport() -> OfficialRegistryTransport:
        transport = transport_factory()
        if source_observer is not None:
            return RecordingOfficialRegistryTransport(transport, source_observer)
        return transport

    return (
        AreraActsIndexAdapter(new_transport()),
        AreraTariffIndexAdapter(new_transport()),
        AdmExciseIndexAdapter(new_transport()),
        GazzettaSerieGeneraleIndexAdapter(new_transport()),
        NormattivaUpdatesAdapter(transport=new_transport()),
    )


def _required_text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("official registry field is missing")
    return value.strip()


__all__ = [
    "AdmExciseIndexAdapter",
    "AreraActsIndexAdapter",
    "AreraTariffIndexAdapter",
    "GazzettaSerieGeneraleIndexAdapter",
    "NormattivaUpdatesAdapter",
    "OfficialRegistryHTTPResponse",
    "OfficialRegistryTransport",
    "OfficialRegulatoryDocumentAcquirer",
    "RecordingOfficialRegistryTransport",
    "UrllibOfficialRegistryTransport",
    "normattiva_vat_reference_records",
]
