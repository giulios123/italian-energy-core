"""Versioned, exact-layout parsers for regulatory rollover source material."""

from __future__ import annotations

import importlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from html.parser import HTMLParser
from io import BytesIO
from typing import ClassVar, Protocol
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from italian_energy.arera.discovery import RegulatoryRegistryChannel
from italian_energy.arera.importer import (
    SCHEMA_VERSION as ARERA_WORKBOOK_LAYOUT_V1,
)
from italian_energy.arera.importer import (
    AreraDomesticElectricityImporter,
    AreraImportError,
    extract_xlsx_cell_tokens,
)
from italian_energy.arera.models import AreraChargeRole, AreraCustomerSegment
from italian_energy.arera.rollover_models import (
    RegulatoryEffect,
    RegulatoryEffectAssertion,
    RegulatoryFact,
    RegulatoryFactFamily,
    RegulatoryRolloverReason,
)
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.domain.base import DomainModel
from italian_energy.domain.money import RateUnit
from italian_energy.domain.regulatory import BillingQuota, VerificationStatus
from italian_energy.domain.time import DatePeriod

ARERA_DOMESTIC_WORKBOOK_KIND = "arera_domestic_bt_workbook"
ARERA_DOMESTIC_WORKBOOK_PARSER_ID = "arera-domestic-electricity-workbook"
ARERA_DOMESTIC_WORKBOOK_PARSER_VERSION = "1.0.0"
ARERA_DOMESTIC_WORKBOOK_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
ARERA_343_CONFIRMATION_DOCUMENT_KIND = "arera_343_q4_confirmation_pdf"
ARERA_343_CONFIRMATION_LAYOUT_VERSION = "arera-343-r-com-2026-pdf-v1"
ARERA_343_CONFIRMATION_PARSER_ID = "arera-343-q4-confirmation"
ARERA_343_CONFIRMATION_PARSER_VERSION = "1.0.0"
ARERA_343_PDF_URL = "https://www.arera.it/fileadmin/allegati/docs/26/343-2026-R-com.pdf"
ARERA_343_DETAIL_URL = "https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26"
ADM_EXCISE_LAYOUT_VERSION = "adm-national-excise-pdf-v1"
ADM_EXCISE_DOMESTIC_KIND = "adm_national_domestic_excise_pdf"
ADM_EXCISE_DOMESTIC_PARSER_ID = "adm-national-domestic-electricity-excise"
ADM_EXCISE_DOMESTIC_PARSER_VERSION = "1.0.0"
ADM_EXCISE_PDF_MIME = "application/pdf"
ADM_EXCISE_MAX_BYTES = 24_000_000
_CIVIL_TIMEZONE = ZoneInfo("Europe/Rome")

NORMATTIVA_VAT_LAYOUT_VERSION = "normattiva-dpr633-akn-v1"
NORMATTIVA_VAT_TABLE_A_KIND = "normattiva_vat_table_a"
NORMATTIVA_VAT_ART16_KIND = "normattiva_vat_art16"
NORMATTIVA_VAT_TABLE_PARSER_ID = "normattiva-dpr633-table-a-domestic-electricity"
NORMATTIVA_VAT_RATE_PARSER_ID = "normattiva-dpr633-art16-part-iii-rate"
NORMATTIVA_VAT_PARSER_VERSION = "1.0.0"
_NORMATTIVA_VAT_PUBLISHED_AT = date(1972, 10, 26)
_NORMATTIVA_VAT_ACT_ID = "DPR 633/1972"
NORMATTIVA_VAT_TABLE_SOURCE_ID = "vat_dpr_633"
NORMATTIVA_VAT_TABLE_DOCUMENT_ID = "DPR-633-1972-Tabella-A-Parte-III-n-103"
NORMATTIVA_VAT_ART16_SOURCE_ID = "vat_dpr_633_art16"
NORMATTIVA_VAT_ART16_DOCUMENT_ID = "DPR-633-1972-art-16-aliquote"
NORMATTIVA_VAT_TABLE_URN = "urn:nir:stato:decreto.presidente.della.repubblica:1972-10-26;633:1~art1"
NORMATTIVA_VAT_ART16_URN = "urn:nir:stato:decreto.presidente.della.repubblica:1972-10-26;633~art16"
_NORMATTIVA_VAT_ART16_PROVISION = (
    "L'aliquota è ridotta al quattro, al cinque e al dieci per cento per le operazioni "
    "che hanno per oggetto i beni e i servizi elencati, rispettivamente, nella parte II, "
    "nella parte II-bis e nella parte III dell'allegata tabella A, salvo il disposto "
    "dell'articolo 34"
)


class ParserDisposition(StrEnum):
    """Outcome of an exact-key parser lookup and execution."""

    PARSED = "parsed"
    REVIEW_REQUIRED = "review_required"


class RegulatoryParserKey(DomainModel):
    """All source identity dimensions required for parser selection."""

    channel: RegulatoryRegistryChannel
    document_kind: str = Field(min_length=1)
    layout_version: str = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class RegulatorySourceDocument:
    """Document bytes plus independently acquired official-source metadata."""

    acquired: AcquiredOfficialBytes
    source_id: str
    channel: RegulatoryRegistryChannel
    act_id: str
    document_id: str
    published_at: date
    content_type: str
    document_kind: str
    layout_version: str
    record_url: str | None = None

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.source_id,
                self.act_id,
                self.document_id,
                self.content_type,
                self.document_kind,
                self.layout_version,
            )
        ):
            raise ValueError("regulatory source identity fields cannot be empty")
        if self.published_at > self.acquired.fetched_at.astimezone(_CIVIL_TIMEZONE).date():
            raise ValueError("regulatory source cannot be fetched before publication")
        if urlsplit(self.acquired.url).hostname not in self.channel.official_hosts:
            raise ValueError("regulatory source URL must match its official registry channel")
        record_url = self.record_url or self.acquired.url
        parsed_record_url = urlsplit(record_url)
        if parsed_record_url.scheme != "https" or parsed_record_url.hostname not in (
            self.channel.official_hosts
        ):
            raise ValueError("regulatory record URL must match its official registry channel")
        object.__setattr__(self, "record_url", record_url)

    @property
    def key(self) -> RegulatoryParserKey:
        return RegulatoryParserKey(
            channel=self.channel,
            document_kind=self.document_kind,
            layout_version=self.layout_version,
        )


class RegulatoryParseResult(DomainModel):
    """Audit-safe parser output; it never includes the raw source bytes."""

    disposition: ParserDisposition
    source_id: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    parser_id: str | None = None
    parser_version: str | None = None
    facts: tuple[RegulatoryFact, ...] = ()
    effect_assertions: tuple[RegulatoryEffectAssertion, ...] = ()
    reason_code: RegulatoryRolloverReason | None = None
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_result(self) -> RegulatoryParseResult:
        if self.disposition == ParserDisposition.PARSED:
            if (
                not self.parser_id
                or not self.parser_version
                or not (self.facts or self.effect_assertions)
            ):
                raise ValueError("parsed result requires parser identity and normalized output")
            if self.reason_code is not None:
                raise ValueError("parsed result cannot contain a failure reason")
            if any(
                fact.source_id != self.source_id or fact.source_sha256 != self.source_sha256
                for fact in self.facts
            ):
                raise ValueError("parsed facts must retain the source identity and digest")
            if any(
                assertion.source_id != self.source_id
                or assertion.source_sha256 != self.source_sha256
                for assertion in self.effect_assertions
            ):
                raise ValueError("parsed assertions must retain the source identity and digest")
        elif self.reason_code is None:
            raise ValueError("review result requires a reason")
        elif self.facts or self.effect_assertions:
            raise ValueError("review result cannot expose partial facts or assertions")
        return self


@dataclass(frozen=True, slots=True)
class RegulatoryInterpretation:
    """Parser output for numeric facts and/or non-numeric legal effects."""

    facts: tuple[RegulatoryFact, ...] = ()
    effect_assertions: tuple[RegulatoryEffectAssertion, ...] = ()

    def __post_init__(self) -> None:
        if not self.facts and not self.effect_assertions:
            raise ValueError("regulatory interpretation cannot be empty")


class VersionedRegulatoryParser(Protocol):
    """A deterministic parser bound to one exact source family and layout."""

    key: RegulatoryParserKey
    parser_id: str
    version: str

    def parse(
        self, source: RegulatorySourceDocument
    ) -> tuple[RegulatoryFact, ...] | RegulatoryInterpretation: ...


class _ParserFailure(Exception):
    def __init__(self, reason_code: RegulatoryRolloverReason, detail: str) -> None:
        self.reason_code = reason_code
        super().__init__(detail)


@dataclass(slots=True)
class _HtmlTextCapture:
    stack: list[str]
    parts: list[str]


class _NormattivaVatHtmlCapture(HTMLParser):
    """Capture only exact Normattiva AKN nodes used by the certified VAT parsers."""

    _VOID_ELEMENTS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.counts: dict[str, int] = {}
        self.captures: dict[str, list[str]] = {}
        self.active: dict[str, _HtmlTextCapture] = {}
        self.body_testo_count = 0
        self.article_16_heading_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = frozenset((attributes.get("class") or "").split())
        if tag == "div" and "bodyTesto" in classes:
            self.body_testo_count += 1
        if tag == "h2" and attributes.get("id") == "art_16" and "article-num-akn" in classes:
            self.article_16_heading_count += 1

        if tag in self._VOID_ELEMENTS:
            if tag == "br":
                for capture in self.active.values():
                    capture.parts.append("\n")
            return

        for capture in self.active.values():
            capture.stack.append(tag)

        selectors = (
            ("valid_from", tag == "span" and attributes.get("id") == "artInizio"),
            ("valid_until", tag == "span" and attributes.get("id") == "artFine"),
            ("table_body", tag == "span" and "attachment-just-text" in classes),
            ("article_body", tag == "span" and "art-just-text-akn" in classes),
            (
                "article_16_reduced_rate",
                tag == "div" and attributes.get("eid") == "ins_3" and "ins-akn" in classes,
            ),
        )
        for name, matches in selectors:
            if not matches:
                continue
            self.counts[name] = self.counts.get(name, 0) + 1
            if self.counts[name] == 1:
                self.active[name] = _HtmlTextCapture(stack=[tag], parts=[])

    def handle_endtag(self, tag: str) -> None:
        for name, capture in tuple(self.active.items()):
            try:
                closing_index = len(capture.stack) - 1 - capture.stack[::-1].index(tag)
            except ValueError:
                continue
            del capture.stack[closing_index:]
            if not capture.stack:
                self.captures.setdefault(name, []).append("".join(capture.parts))
                del self.active[name]

    def handle_data(self, data: str) -> None:
        for capture in self.active.values():
            capture.parts.append(data)


def _single_html_capture(parsed: _NormattivaVatHtmlCapture, name: str) -> str:
    captures = parsed.captures.get(name, [])
    if parsed.counts.get(name, 0) != 1 or len(captures) != 1 or name in parsed.active:
        raise _ParserFailure(
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
            f"Normattiva AKN source does not contain one exact {name} element",
        )
    return captures[0]


def _parse_normattiva_date(value: str) -> date:
    normalized = value.replace("\xa0", " ").strip()
    if re.fullmatch(r"\d{1,2}-\d{1,2}-\d{4}", normalized) is None:
        raise _ParserFailure(
            RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
            "Normattiva validity date does not match the supported D-M-YYYY token",
        )
    day, month, year = (int(part) for part in normalized.split("-"))
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise _ParserFailure(
            RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
            "Normattiva validity date is not a calendar date",
        ) from exc


def _normattiva_period(parsed: _NormattivaVatHtmlCapture, fetched_on: date) -> DatePeriod:
    if parsed.body_testo_count != 1:
        raise _ParserFailure(
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
            "Normattiva source does not contain one exact bodyTesto container",
        )
    start = _parse_normattiva_date(_single_html_capture(parsed, "valid_from"))
    inclusive_end = _parse_normattiva_date(_single_html_capture(parsed, "valid_until"))
    try:
        period = DatePeriod(start=start, end=inclusive_end + timedelta(days=1))
    except ValueError as exc:
        raise _ParserFailure(
            RegulatoryRolloverReason.INVALID_VALIDITY_INTERVAL,
            "Normattiva source validity interval is not positive",
        ) from exc
    if not period.start <= fetched_on < period.end:
        raise _ParserFailure(
            RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
            "date-specific Normattiva text is not in force on its requested vig date",
        )
    return period


def _validate_normattiva_vat_source(
    source: RegulatorySourceDocument,
    *,
    expected_kind: str,
    expected_source_id: str,
    expected_document_id: str,
    expected_urn: str,
) -> date:
    if (
        source.channel != RegulatoryRegistryChannel.NORMATTIVA_UPDATES
        or source.content_type.split(";", 1)[0].strip().lower() != "text/html"
        or source.acquired.content_type.split(";", 1)[0].strip().lower() != "text/html"
        or source.document_kind != expected_kind
        or source.layout_version != NORMATTIVA_VAT_LAYOUT_VERSION
        or source.source_id != expected_source_id
        or source.act_id != _NORMATTIVA_VAT_ACT_ID
        or source.document_id != expected_document_id
        or source.published_at != _NORMATTIVA_VAT_PUBLISHED_AT
    ):
        raise _ParserFailure(
            RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
            "Normattiva VAT parser received a different source identity or media type",
        )

    fetched_on = source.acquired.fetched_at.astimezone(_CIVIL_TIMEZONE).date()
    expected_url = (
        f"https://www.normattiva.it/uri-res/N2Ls?{expected_urn}!vig={fetched_on.isoformat()}"
    )
    if source.acquired.url != expected_url or source.acquired.final_url != expected_url:
        raise _ParserFailure(
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
            "Normattiva URN or date-specific vig query does not match the acquired document",
        )
    return fetched_on


def _parse_normattiva_vat_html(source: RegulatorySourceDocument) -> _NormattivaVatHtmlCapture:
    parsed = _NormattivaVatHtmlCapture()
    try:
        parsed.feed(source.acquired.body.decode("utf-8"))
        parsed.close()
    except (UnicodeDecodeError, ValueError) as exc:
        raise _ParserFailure(
            RegulatoryRolloverReason.PARSER_FAILURE,
            "Normattiva HTML cannot be decoded with the certified UTF-8 layout",
        ) from exc
    return parsed


class NormattivaVatTableAParser:
    """Exact-layout parser for DPR 633/1972 Table A, Part III, item 103."""

    key = RegulatoryParserKey(
        channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
        document_kind=NORMATTIVA_VAT_TABLE_A_KIND,
        layout_version=NORMATTIVA_VAT_LAYOUT_VERSION,
    )
    parser_id = NORMATTIVA_VAT_TABLE_PARSER_ID
    version = NORMATTIVA_VAT_PARSER_VERSION

    def parse(self, source: RegulatorySourceDocument) -> tuple[RegulatoryFact, ...]:
        fetched_on = _validate_normattiva_vat_source(
            source,
            expected_kind=NORMATTIVA_VAT_TABLE_A_KIND,
            expected_source_id=NORMATTIVA_VAT_TABLE_SOURCE_ID,
            expected_document_id=NORMATTIVA_VAT_TABLE_DOCUMENT_ID,
            expected_urn=NORMATTIVA_VAT_TABLE_URN,
        )
        parsed = _parse_normattiva_vat_html(source)
        validity = _normattiva_period(parsed, fetched_on)
        table_text = re.sub(
            r"\s+", " ", _single_html_capture(parsed, "table_body").replace("\xa0", " ")
        ).strip()
        part_iii = tuple(re.finditer(r"(?<!\w)PARTE\s+III(?:\s+\(\d+\))?", table_text))
        if len(part_iii) != 1:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "Normattiva Table A does not contain one exact Part III heading",
            )
        part_iii_text = table_text[part_iii[0].end() :]
        item_103 = tuple(re.finditer(r"(?<!\d)103\)", part_iii_text))
        item_104 = tuple(re.finditer(r"(?<!\d)104\)", part_iii_text))
        if len(item_103) != 1 or len(item_104) != 1 or item_103[0].start() >= item_104[0].start():
            raise _ParserFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                "Normattiva Table A must contain one ordered item 103 and item 104 in Part III",
            )
        row_text = part_iii_text[item_103[0].start() : item_104[0].start()].strip()
        if re.search(r"\benergia elettrica per uso domestico\b", row_text, re.IGNORECASE) is None:
            raise _ParserFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                "Table A item 103 no longer names domestic electricity in the supported wording",
            )
        return (
            RegulatoryFact(
                fact_id=(
                    f"{source.source_id}:vat-rate:{validity.start.isoformat()}:{validity.end.isoformat()}"
                ),
                family=RegulatoryFactFamily.VAT_RATE,
                value=Decimal("10"),
                unit=RateUnit.PERCENT,
                validity=validity,
                source_id=source.source_id,
                source_url=source.acquired.url,
                source_sha256=source.acquired.sha256,
                act_id=source.act_id,
                document=source.document_id,
                published_at=source.published_at,
                fetched_at=source.acquired.fetched_at,
                parser_id=self.parser_id,
                parser_version=self.version,
                locator="bodyTesto/attachment-just-text/PARTE III/item 103",
                raw_value_token=row_text,
                derivation=(
                    "exact Table A item 103 classifies domestic electricity in Part III; "
                    "the versioned statutory cross-reference resolves Part III to 10% via "
                    "Art. 16, and candidate mapping independently requires that exact Art. 16 fact"
                ),
                effect=RegulatoryEffect(
                    provision=(
                        "DPR 633/1972 Tabella A, Parte III, n. 103; cross-reference to art. 16"
                    )
                ),
                status=VerificationStatus.VERIFIED,
            ),
        )


class NormattivaVatArt16Parser:
    """Exact-layout parser for the reduced VAT rate in DPR 633/1972 Article 16."""

    key = RegulatoryParserKey(
        channel=RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
        document_kind=NORMATTIVA_VAT_ART16_KIND,
        layout_version=NORMATTIVA_VAT_LAYOUT_VERSION,
    )
    parser_id = NORMATTIVA_VAT_RATE_PARSER_ID
    version = NORMATTIVA_VAT_PARSER_VERSION

    def parse(self, source: RegulatorySourceDocument) -> tuple[RegulatoryFact, ...]:
        fetched_on = _validate_normattiva_vat_source(
            source,
            expected_kind=NORMATTIVA_VAT_ART16_KIND,
            expected_source_id=NORMATTIVA_VAT_ART16_SOURCE_ID,
            expected_document_id=NORMATTIVA_VAT_ART16_DOCUMENT_ID,
            expected_urn=NORMATTIVA_VAT_ART16_URN,
        )
        parsed = _parse_normattiva_vat_html(source)
        if parsed.article_16_heading_count != 1:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "Normattiva source does not contain one exact Article 16 heading",
            )
        validity = _normattiva_period(parsed, fetched_on)
        article_text = re.sub(
            r"\s+", " ", _single_html_capture(parsed, "article_body").replace("\xa0", " ")
        ).strip()
        provision = _single_html_capture(parsed, "article_16_reduced_rate")
        provision = re.sub(r"\s+", " ", provision.replace("\xa0", " ")).strip()
        if provision.startswith("((") and provision.endswith("))"):
            provision = provision[2:-2].strip()
        if provision != _NORMATTIVA_VAT_ART16_PROVISION or provision not in article_text:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "Normattiva Article 16 reduced-rate clause differs from the exact supported text",
            )
        return (
            RegulatoryFact(
                fact_id=(
                    f"{source.source_id}:vat-rate:{validity.start.isoformat()}:{validity.end.isoformat()}"
                ),
                family=RegulatoryFactFamily.VAT_RATE,
                value=Decimal("10"),
                unit=RateUnit.PERCENT,
                validity=validity,
                source_id=source.source_id,
                source_url=source.acquired.url,
                source_sha256=source.acquired.sha256,
                act_id=source.act_id,
                document=source.document_id,
                published_at=source.published_at,
                fetched_at=source.acquired.fetched_at,
                parser_id=self.parser_id,
                parser_version=self.version,
                locator="bodyTesto/art_16/art-just-text-akn/ins_3",
                raw_value_token="dieci per cento",
                derivation=(
                    "exact Article 16 AKN ins_3 clause maps Part III of Table A to ten percent; "
                    "Italian number words normalized to Decimal(10) by parser version 1.0.0"
                ),
                effect=RegulatoryEffect(provision="DPR 633/1972 art. 16, comma 2, Parte III"),
                status=VerificationStatus.VERIFIED,
            ),
        )


def _normalize_arera_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold().replace("°", "")
    without_marks = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", without_marks.replace("’", "'").replace("–", "-")).strip()  # noqa: RUF001


class Arera343ConfirmationParser:
    """Exact-layout parser for the non-numeric household oneri confirmations."""

    key = RegulatoryParserKey(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        document_kind=ARERA_343_CONFIRMATION_DOCUMENT_KIND,
        layout_version=ARERA_343_CONFIRMATION_LAYOUT_VERSION,
    )
    parser_id = ARERA_343_CONFIRMATION_PARSER_ID
    version = ARERA_343_CONFIRMATION_PARSER_VERSION

    _published_at = date(2026, 9, 29)
    _validity = DatePeriod(start=date(2026, 10, 1), end=date(2027, 1, 1))
    _component_rules = (
        ("ASOS", date(2026, 7, 1), "1.1"),
        ("ARIM", date(2026, 1, 1), "1.3"),
        ("UC3", date(2026, 1, 1), "1.4"),
        ("UC6", date(2026, 1, 1), "1.4"),
    )

    def parse(self, source: RegulatorySourceDocument) -> RegulatoryInterpretation:
        if (
            source.channel != self.key.channel
            or source.source_id != "arera_343"
            or source.act_id != "343/2026/R/com"
            or source.document_id != "343/2026/R/com"
            or source.published_at != self._published_at
            or source.record_url != ARERA_343_DETAIL_URL
            or source.acquired.url != ARERA_343_PDF_URL
            or source.acquired.final_url != ARERA_343_PDF_URL
            or source.content_type.split(";", 1)[0].strip().lower() != "application/pdf"
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 parser received a different act identity, URL, or PDF type",
            )
        try:
            pdf = importlib.import_module("pypdf")
        except ImportError as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "ARERA 343 PDF parsing requires the optional pypdf dependency",
            ) from exc
        try:
            reader = pdf.PdfReader(BytesIO(source.acquired.body))
            if reader.is_encrypted:
                raise _ParserFailure(
                    RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                    "ARERA 343 PDF is encrypted and cannot be interpreted",
                )
            page_texts = tuple(page.extract_text() or "" for page in reader.pages)
        except _ParserFailure:
            raise
        except pdf.errors.PyPdfError as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "ARERA 343 PDF could not be read with the supported text extractor",
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "ARERA 343 PDF could not be read with the supported text extractor",
            ) from exc
        if len(page_texts) != 8 or not all(page_texts):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 PDF no longer matches the certified eight-page layout",
            )

        cover = _normalize_arera_text(page_texts[0])
        final_page = _normalize_arera_text(page_texts[7])
        if not all(
            token in cover
            for token in ("deliberazione 29 settembre 2026", "343/2026/r/com", "1 ottobre 2026")
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 PDF cover does not match the registered act and publication date",
            )
        if "entra in vigore dal 1 ottobre 2026" not in final_page:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 final provision no longer states its registered effective date",
            )

        article = _normalize_arera_text(page_texts[5])
        heading = "articolo 1 componenti tariffarie relative al settore elettrico"
        if heading not in article:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 page 6 no longer contains the registered electricity article",
            )
        markers = tuple(
            re.finditer(
                r"(?<!\d)(1\.[1-7])\s+(?=(?:i valori|le percentuali|il 100%))",
                article,
            )
        )
        if tuple(match.group(1) for match in markers) != tuple(
            f"1.{number}" for number in range(1, 8)
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 electricity article no longer contains clauses 1.1 through 1.7 once",
            )
        paragraphs = {
            marker.group(1): article[
                marker.end() : markers[index + 1].start()
                if index + 1 < len(markers)
                else len(article)
            ]
            for index, marker in enumerate(markers)
        }
        expected_tokens = {
            "1.1": (
                "asos",
                "1 luglio 2026",
                "non sono nella titolarita di imprese a forte consumo di energia elettrica",
                "tabella 1",
                "227/2026/r/com",
                "sono confermati",
            ),
            "1.2": (
                "asos",
                "imprese a forte consumo di energia elettrica",
                "tabelle 2, 3, 4 e 5",
                "227/2026/r/com",
                "sono confermati",
            ),
            "1.3": (
                "arim",
                "1 gennaio 2026",
                "tabella 6",
                "588/2025/r/com",
                "sono confermati",
            ),
            "1.4": (
                "uc3",
                "uc6",
                "1 gennaio 2026",
                "tabella 7",
                "588/2025/r/com",
                "sono confermati",
            ),
            "1.5": (
                "asos",
                "arim",
                "uc3",
                "uc6",
                "36.1 del tippi",
                "tabella 6",
                "227/2026/r/com",
                "sono confermati",
            ),
            "1.6": (
                "percentuali di ripartizione della componente arim",
                "comma 3.7 del tippi",
                "1 gennaio 2026",
                "588/2025/r/com",
                "sono confermati",
            ),
            "1.7": ("100% della componente asos", "conto per nuovi impianti"),
        }
        if any(
            token not in paragraphs[number]
            for number, tokens in expected_tokens.items()
            for token in tokens
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA 343 electricity clauses differ from the exact supported legal wording",
            )

        assertions = tuple(
            RegulatoryEffectAssertion(
                assertion_id=(
                    f"arera_343:{component_code.lower()}:{self._validity.start.isoformat()}"
                ),
                component_code=component_code,
                prior_effective_from=prior_effective_from,
                validity=self._validity,
                segments=tuple(AreraCustomerSegment),
                quotas=(BillingQuota.CONSUMPTION, BillingQuota.FIXED, BillingQuota.POWER),
                source_id=source.source_id,
                source_url=source.acquired.url,
                source_sha256=source.acquired.sha256,
                act_id=source.act_id,
                document="343-2026-R-com.pdf",
                published_at=source.published_at,
                fetched_at=source.acquired.fetched_at,
                parser_id=self.parser_id,
                parser_version=self.version,
                locator=f"page 6, article 1, paragraph {paragraph}",
                raw_value_token="sono confermati",
            )
            for component_code, prior_effective_from, paragraph in self._component_rules
        )
        return RegulatoryInterpretation(effect_assertions=assertions)


class AdmDomesticExcisePdfParser:
    """Exact-layout parser for the domestic electricity row in ADM's current PDF."""

    key = RegulatoryParserKey(
        channel=RegulatoryRegistryChannel.ADM_EXCISE,
        document_kind=ADM_EXCISE_DOMESTIC_KIND,
        layout_version=ADM_EXCISE_LAYOUT_VERSION,
    )
    parser_id = ADM_EXCISE_DOMESTIC_PARSER_ID
    version = ADM_EXCISE_DOMESTIC_PARSER_VERSION
    _update_label = re.compile(r"Aggiornamento al (\d{1,2} \w+ \d{4})")
    _rate = re.compile(r"€\s*(?P<value>0,\d{4})\s+per ogni kWh", re.IGNORECASE)
    _page_number = re.compile(r"Pagina\s+5\s+di\s+11", re.IGNORECASE)
    _italian_months: ClassVar[dict[str, int]] = {
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

    def parse(self, source: RegulatorySourceDocument) -> tuple[RegulatoryFact, ...]:
        self._validate_identity(source)
        try:
            pypdf = importlib.import_module("pypdf")
        except ImportError as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "ADM PDF parser dependency is unavailable in this installation",
            ) from exc
        try:
            reader = pypdf.PdfReader(BytesIO(source.acquired.body))
            if reader.is_encrypted or len(reader.pages) != 11:
                raise _ParserFailure(
                    RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                    "ADM PDF must use the certified unencrypted eleven-page layout",
                )
            page = reader.pages[4]
            page_text = page.extract_text() or ""
            fragments: list[tuple[str, float, float]] = []

            def capture_text(
                text: str,
                _current_matrix: object,
                text_matrix: list[float],
                _font: object,
                _font_size: float,
            ) -> None:
                if text.strip():
                    fragments.append((text, float(text_matrix[4]), float(text_matrix[5])))

            page.extract_text(visitor_text=capture_text)
        except _ParserFailure:
            raise
        except (pypdf.errors.PdfReadError, IndexError, OSError, TypeError, ValueError) as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "ADM source is not a readable PDF in the certified parser environment",
            ) from exc

        normalized = re.sub(r"\s+", " ", page_text.replace("\xa0", " ")).strip()
        if (
            "ACCISE SULL' ENERGIA ELETTRICA" not in normalized
            or self._page_number.search(normalized) is None
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM PDF page five does not match the certified electricity-excise layout",
            )
        update_matches = tuple(self._update_label.finditer(normalized))
        if len(update_matches) != 1:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM PDF must contain one explicit Italian update date",
            )
        published_at = self._parse_italian_date(update_matches[0].group(1))
        if published_at != source.published_at:
            raise _ParserFailure(
                RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
                "ADM PDF update date differs from the official index record",
            )

        domestic_rows = tuple(
            (text, x, y)
            for text, x, y in fragments
            if "per qualsiasi applicazione" in text.lower() or "nelle abitazioni" in text.lower()
        )
        rate_rows = tuple(
            (match, x, y) for text, x, y in fragments for match in self._rate.finditer(text)
        )
        domestic_starts = tuple(
            row for row in domestic_rows if "per qualsiasi applicazione" in row[0].lower()
        )
        domestic_ends = tuple(row for row in domestic_rows if "nelle abitazioni" in row[0].lower())
        if len(domestic_starts) != 1 or len(domestic_ends) != 1:
            raise _ParserFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                "ADM domestic row is missing or duplicated",
            )
        start_x, start_y = domestic_starts[0][1:]
        end_x, end_y = domestic_ends[0][1:]
        aligned_rates = tuple(
            (match, x, y) for match, x, y in rate_rows if 130 < x < 250 and abs(y - start_y) <= 3
        )
        if len(aligned_rates) != 1:
            raise _ParserFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                "ADM domestic row must have one uniquely aligned kWh amount",
            )
        rate_match, rate_x, rate_y = aligned_rates[0]
        if not (
            end_y < start_y
            and start_x < 120
            and end_x < 120
            and 130 < rate_x < 250
            and abs(rate_y - start_y) <= 3
            and abs(end_y - start_y) <= 20
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.AMBIGUOUS_APPLICABILITY,
                "ADM domestic label and rate no longer occupy the certified table row",
            )
        if re.search(r"D\.M\.\s*30/12/2011", normalized) is None:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM domestic rate no longer carries the certified statutory reference",
            )

        rate_token = rate_match.group(0)
        amount = Decimal(rate_match.group("value").replace(",", "."))
        return (
            RegulatoryFact(
                fact_id=(f"{source.source_id}:domestic-excise:{published_at.isoformat()}"),
                family=RegulatoryFactFamily.EXCISE_RATE,
                value=amount,
                unit=RateUnit.EUR_PER_KWH,
                validity=DatePeriod(start=published_at, end=date.max),
                source_id=source.source_id,
                source_url=source.acquired.url,
                source_sha256=source.acquired.sha256,
                act_id=source.act_id,
                document=source.document_id,
                published_at=published_at,
                fetched_at=source.acquired.fetched_at,
                parser_id=self.parser_id,
                parser_version=self.version,
                locator=(
                    "page 5/11: ACCISE SULL' ENERGIA ELETTRICA / "
                    "per qualsiasi applicazione nelle abitazioni"
                ),
                raw_value_token=rate_token,
                derivation=(
                    "exact domestic electricity row in the current ADM national excise PDF; "
                    "Decimal rate is in EUR/kWh; the listed update date starts the observed "
                    "current-rate period, which remains subject to complete later ADM discovery"
                ),
                effect=RegulatoryEffect(
                    provision=(
                        "D.M. 30/12/2011 as cited by the current ADM domestic electricity row"
                    )
                ),
                status=VerificationStatus.VERIFIED,
            ),
        )

    def _validate_identity(self, source: RegulatorySourceDocument) -> None:
        parsed = urlsplit(source.acquired.url)
        expected_act_id = f"adm-excise:{source.published_at.isoformat()}:{source.document_id}"
        expected_source_id = f"adm_excise_{source.published_at:%Y%m%d}"
        if (
            source.channel != RegulatoryRegistryChannel.ADM_EXCISE
            or source.content_type.split(";", 1)[0].strip().lower() != ADM_EXCISE_PDF_MIME
            or source.acquired.content_type.split(";", 1)[0].strip().lower() != ADM_EXCISE_PDF_MIME
            or source.document_kind != ADM_EXCISE_DOMESTIC_KIND
            or source.layout_version != ADM_EXCISE_LAYOUT_VERSION
            or source.source_id != expected_source_id
            or source.act_id != expected_act_id
            or parsed.hostname not in RegulatoryRegistryChannel.ADM_EXCISE.official_hosts
            or parsed.path.rsplit("/", 1)[-1] != source.document_id
            or source.acquired.final_url != source.acquired.url
            or not source.acquired.body.startswith(b"%PDF-")
            or len(source.acquired.body) > ADM_EXCISE_MAX_BYTES
        ):
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM parser received a different source identity, URL, size, or media type",
            )

    def _parse_italian_date(self, value: str) -> date:
        match = re.fullmatch(r"(\d{1,2}) ([a-zà-ù]+) (\d{4})", value, re.IGNORECASE)
        if match is None:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM update date no longer uses the certified Italian long-date layout",
            )
        month = self._italian_months.get(match.group(2).lower())
        if month is None:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM update date uses an unrecognized Italian month",
            )
        try:
            return date(int(match.group(3)), month, int(match.group(1)))
        except ValueError as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ADM update date is not a valid civil date",
            ) from exc


class AreraDomesticWorkbookParser:
    """Parser for the already supported Spec 005 ARERA XLSX layout only."""

    key = RegulatoryParserKey(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        document_kind=ARERA_DOMESTIC_WORKBOOK_KIND,
        layout_version=ARERA_WORKBOOK_LAYOUT_V1,
    )
    parser_id = ARERA_DOMESTIC_WORKBOOK_PARSER_ID
    version = ARERA_DOMESTIC_WORKBOOK_PARSER_VERSION

    def parse(self, source: RegulatorySourceDocument) -> tuple[RegulatoryFact, ...]:
        if source.channel != self.key.channel:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA workbook parser received a different source channel",
            )
        if source.content_type.split(";", 1)[0].strip().lower() != ARERA_DOMESTIC_WORKBOOK_MIME:
            raise _ParserFailure(
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                "ARERA workbook parser requires the supported XLSX media type",
            )
        imported = AreraDomesticElectricityImporter(
            clock=lambda: source.acquired.fetched_at
        ).parse_bytes(
            source.acquired.body,
            retrieved_at=source.acquired.fetched_at,
            source_url=source.acquired.url,
        )
        if imported.bundle is None or imported.status == VerificationStatus.REVIEW_REQUIRED:
            codes = {item.code for item in imported.diagnostics}
            reason = (
                RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE
                if "UNKNOWN_SHEET" in codes
                else RegulatoryRolloverReason.PARSER_FAILURE
            )
            raise _ParserFailure(reason, "ARERA workbook did not match the supported layout")

        try:
            cell_tokens = extract_xlsx_cell_tokens(source.acquired.body)
        except (AreraImportError, OSError, ValueError) as exc:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "ARERA workbook cell provenance could not be reconstructed",
            ) from exc

        facts: list[RegulatoryFact] = []
        for charge in imported.bundle.charges:
            if charge.role != AreraChargeRole.TOTAL:
                continue
            locator = (charge.source.sheet, charge.source.cell)
            raw_token = cell_tokens.get(locator)
            if raw_token is None:
                raise _ParserFailure(
                    RegulatoryRolloverReason.PARSER_FAILURE,
                    "ARERA total cell has no exact OOXML value token",
                )
            fact_id = ":".join(
                (
                    source.source_id,
                    charge.validity.start.isoformat(),
                    charge.segment.value,
                    charge.component_code,
                    charge.quota.value,
                )
            )
            facts.append(
                RegulatoryFact(
                    fact_id=fact_id,
                    family=RegulatoryFactFamily.CHARGE,
                    component_code=charge.component_code,
                    segment=charge.segment,
                    quota=charge.quota,
                    value=charge.rate.amount,
                    unit=charge.rate.unit,
                    validity=charge.validity,
                    source_id=source.source_id,
                    source_url=source.acquired.url,
                    source_sha256=source.acquired.sha256,
                    act_id=source.act_id,
                    document=source.document_id,
                    published_at=source.published_at,
                    fetched_at=source.acquired.fetched_at,
                    parser_id=self.parser_id,
                    parser_version=self.version,
                    locator=f"{charge.source.sheet}!{charge.source.cell}",
                    raw_value_token=raw_token,
                    derivation=(
                        "Spec 005 exact-layout aggregate total; Decimal normalization by "
                        "the versioned ARERA importer; raw OOXML token retained"
                    ),
                    status=VerificationStatus.VERIFIED,
                )
            )
        if not facts:
            raise _ParserFailure(
                RegulatoryRolloverReason.PARSER_FAILURE,
                "supported ARERA workbook produced no aggregate charge facts",
            )
        return tuple(sorted(facts, key=lambda item: item.fact_id))


class RegulatoryParserRegistry:
    """Exact-key registry; no fallback parser or layout guessing is allowed."""

    def __init__(self) -> None:
        self._parsers: dict[RegulatoryParserKey, VersionedRegulatoryParser] = {}

    def register(self, parser: VersionedRegulatoryParser) -> None:
        if parser.key in self._parsers:
            raise ValueError("a parser is already registered for this source layout")
        if not parser.parser_id.strip() or not parser.version.strip():
            raise ValueError("parser identity and version cannot be empty")
        self._parsers[parser.key] = parser

    def parse(self, source: RegulatorySourceDocument) -> RegulatoryParseResult:
        parser = self._parsers.get(source.key)
        if parser is None:
            return RegulatoryParseResult(
                disposition=ParserDisposition.REVIEW_REQUIRED,
                source_id=source.source_id,
                source_sha256=source.acquired.sha256,
                reason_code=RegulatoryRolloverReason.UNSUPPORTED_REGULATORY_SOURCE,
                detail="no parser is registered for this exact official source layout",
            )
        try:
            output = parser.parse(source)
            if isinstance(output, RegulatoryInterpretation):
                facts = output.facts
                assertions = output.effect_assertions
            else:
                facts = output
                assertions = ()
        except _ParserFailure as exc:
            return RegulatoryParseResult(
                disposition=ParserDisposition.REVIEW_REQUIRED,
                source_id=source.source_id,
                source_sha256=source.acquired.sha256,
                parser_id=parser.parser_id,
                parser_version=parser.version,
                reason_code=exc.reason_code,
                detail=str(exc),
            )
        except (AreraImportError, OSError, TypeError, ValueError) as exc:
            return RegulatoryParseResult(
                disposition=ParserDisposition.REVIEW_REQUIRED,
                source_id=source.source_id,
                source_sha256=source.acquired.sha256,
                parser_id=parser.parser_id,
                parser_version=parser.version,
                reason_code=RegulatoryRolloverReason.PARSER_FAILURE,
                detail=f"versioned parser rejected source: {type(exc).__name__}",
            )
        return RegulatoryParseResult(
            disposition=ParserDisposition.PARSED,
            source_id=source.source_id,
            source_sha256=source.acquired.sha256,
            parser_id=parser.parser_id,
            parser_version=parser.version,
            facts=facts,
            effect_assertions=assertions,
            detail="official source parsed with the registered exact layout",
        )


def default_regulatory_parser_registry() -> RegulatoryParserRegistry:
    """Create the parser registry for exact, explicitly supported source layouts."""

    registry = RegulatoryParserRegistry()
    registry.register(AreraDomesticWorkbookParser())
    registry.register(Arera343ConfirmationParser())
    registry.register(AdmDomesticExcisePdfParser())
    registry.register(NormattivaVatTableAParser())
    registry.register(NormattivaVatArt16Parser())
    return registry


__all__ = [
    "ADM_EXCISE_DOMESTIC_KIND",
    "ADM_EXCISE_DOMESTIC_PARSER_ID",
    "ADM_EXCISE_DOMESTIC_PARSER_VERSION",
    "ADM_EXCISE_LAYOUT_VERSION",
    "ADM_EXCISE_PDF_MIME",
    "ARERA_343_CONFIRMATION_DOCUMENT_KIND",
    "ARERA_343_CONFIRMATION_LAYOUT_VERSION",
    "ARERA_343_CONFIRMATION_PARSER_ID",
    "ARERA_343_CONFIRMATION_PARSER_VERSION",
    "ARERA_343_DETAIL_URL",
    "ARERA_343_PDF_URL",
    "ARERA_DOMESTIC_WORKBOOK_KIND",
    "ARERA_DOMESTIC_WORKBOOK_MIME",
    "ARERA_DOMESTIC_WORKBOOK_PARSER_ID",
    "ARERA_DOMESTIC_WORKBOOK_PARSER_VERSION",
    "NORMATTIVA_VAT_ART16_DOCUMENT_ID",
    "NORMATTIVA_VAT_ART16_KIND",
    "NORMATTIVA_VAT_ART16_SOURCE_ID",
    "NORMATTIVA_VAT_ART16_URN",
    "NORMATTIVA_VAT_LAYOUT_VERSION",
    "NORMATTIVA_VAT_PARSER_VERSION",
    "NORMATTIVA_VAT_RATE_PARSER_ID",
    "NORMATTIVA_VAT_TABLE_A_KIND",
    "NORMATTIVA_VAT_TABLE_DOCUMENT_ID",
    "NORMATTIVA_VAT_TABLE_PARSER_ID",
    "NORMATTIVA_VAT_TABLE_SOURCE_ID",
    "NORMATTIVA_VAT_TABLE_URN",
    "AdmDomesticExcisePdfParser",
    "Arera343ConfirmationParser",
    "AreraDomesticWorkbookParser",
    "NormattivaVatArt16Parser",
    "NormattivaVatTableAParser",
    "ParserDisposition",
    "RegulatoryInterpretation",
    "RegulatoryParseResult",
    "RegulatoryParserKey",
    "RegulatoryParserRegistry",
    "RegulatorySourceDocument",
    "VersionedRegulatoryParser",
    "default_regulatory_parser_registry",
]
