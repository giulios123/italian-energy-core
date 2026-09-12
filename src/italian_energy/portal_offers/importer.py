"""Safe acquisition and source-faithful parsing of Portale Offerte open data."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from importlib import import_module
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from italian_energy.domain.market import MarketData
from italian_energy.domain.money import RateUnit
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers.models import (
    PortalCatalog,
    PortalEconomicComponent,
    PortalEligibilityProfile,
    PortalFileSnapshot,
    PortalIndexSnapshot,
    PortalOfferRecord,
    PortalOffersImportResult,
    PortalOffersSnapshot,
    PortalOfferType,
    PortalSnapshot,
    PortalSourceRole,
)

PORTAL_HOST = "www.ilportaleofferte.it"
PORTAL_BASE = "https://www.ilportaleofferte.it"
PORTAL_SCHEMA_VERSION = "OffertaRetail/01"
PORTAL_XML_NAMESPACE = "http://www.acquirenteunico.it/schemas/SII_AU/OffertaRetail/01"
PORTAL_PARSER_VERSION = "008-portal-offers-v1"
PORTAL_INDEX_URL = (
    f"{PORTAL_BASE}/portaleOfferte/resources/cms/documents/5d6f1085b4d5f20821af55764e647671.csv"
)
MAX_XML_BYTES = 64 * 1024 * 1024
MAX_CSV_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 96 * 1024 * 1024
MAX_FILES = 5
MAX_REDIRECTS = 3
EXPECTED_XML_MIME = frozenset({"application/xml", "text/xml"})
EXPECTED_CSV_MIME = frozenset({"text/csv"})


class PortalImportError(ValueError):
    """Base error for a malformed or unsupported Portale Offerte source."""


class PortalFetchError(PortalImportError):
    """Raised when an official snapshot cannot be acquired safely."""


class PortalHttpResponse:
    """Minimal injectable transport response."""

    def __init__(
        self,
        *,
        status: int,
        url: str,
        headers: Mapping[str, str] | Iterable[tuple[str, str]] = (),
        content: bytes,
    ) -> None:
        self.status = status
        self.url = url
        self.headers = tuple(headers.items()) if isinstance(headers, Mapping) else tuple(headers)
        self.content = content


class PortalTransport(Protocol):
    def get(self, url: str, timeout_seconds: float) -> PortalHttpResponse:
        """Return one fully buffered HTTP response."""


def _is_allowlisted_url(url: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme == "https"
        and parts.hostname == PORTAL_HOST
        and not parts.username
        and not parts.password
        and not parts.query
        and not parts.fragment
        and (
            parts.path.startswith("/portaleOfferte/resources/opendata/csv/")
            or parts.path.startswith("/portaleOfferte/resources/cms/documents/")
        )
    )


class _RedirectGuard(HTTPRedirectHandler):
    def __init__(self) -> None:
        super().__init__()
        self.redirects = 0

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request:
        self.redirects += 1
        if self.redirects > MAX_REDIRECTS or not _is_allowlisted_url(newurl):
            raise PortalFetchError("Portale Offerte redirect leaves the allowlisted endpoint")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            raise PortalFetchError("Portale Offerte redirect could not be constructed")
        return redirected


class _UrllibTransport:
    def get(self, url: str, timeout_seconds: float) -> PortalHttpResponse:
        if not _is_allowlisted_url(url):
            raise PortalFetchError("Portale Offerte URL is not allowlisted")
        request = Request(
            url, headers={"Accept": "application/xml,text/csv", "User-Agent": "italian-energy/0.8"}
        )
        opener = build_opener(_RedirectGuard())
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return PortalHttpResponse(
                    status=response.status,
                    url=response.geturl(),
                    headers=tuple(response.headers.items()),
                    content=response.read(MAX_TOTAL_BYTES + 1),
                )
        except PortalFetchError:
            raise
        except Exception as exc:  # pragma: no cover - platform/network dependent
            raise PortalFetchError(f"Portale Offerte fetch failed: {exc}") from exc


def _header(headers: Iterable[tuple[str, str]], name: str) -> str | None:
    lowered = name.lower()
    for key, value in headers:
        if key.lower() == lowered:
            return value
    return None


def _content_type(headers: Iterable[tuple[str, str]]) -> str:
    value = _header(headers, "Content-Type") or ""
    return value.split(";", 1)[0].strip().lower()


def _parse_date(value: str, *, field: str) -> date:
    raw = value.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    raise PortalImportError(f"invalid {field} date: {value!r}")


def _parse_decimal(value: str, *, field: str) -> Decimal:
    raw = value.strip().replace(",", ".")
    try:
        result = Decimal(raw)
    except InvalidOperation as exc:
        raise PortalImportError(f"invalid {field} decimal: {value!r}") from exc
    if not result.is_finite():
        raise PortalImportError(f"invalid {field} decimal: {value!r}")
    return result


def _parse_duration(value: str | None) -> int | None:
    if value is None or value.strip() in {"", "-1"}:
        return None
    try:
        duration = int(value.strip())
    except ValueError as exc:
        raise PortalImportError(f"invalid offer duration: {value!r}") from exc
    if duration < 1:
        raise PortalImportError(f"invalid offer duration: {value!r}")
    return duration


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: Any, name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == name and child.text is not None:
            value = str(child.text).strip()
            if value:
                return value
    return None


def _all_text(element: Any, name: str) -> tuple[str, ...]:
    values: list[str] = []
    for child in element.iter():
        if _local_name(child.tag) == name and child.text is not None:
            value = str(child.text).strip()
            if value:
                values.append(value)
    return tuple(values)


def _provenance(file: PortalFileSnapshot, identifier: str, row: int | None = None) -> Provenance:
    return Provenance(
        source="portale_offerte",
        source_identifier=identifier,
        retrieved_at=file.retrieved_at,
        dataset_version=PORTAL_SCHEMA_VERSION,
        sha256=file.sha256,
        url=file.final_url,
        locator=ProvenanceLocator(
            document=file.role.value, section=None if row is None else f"row:{row}"
        ),
    )


def _url_for(role: PortalSourceRole, dataset_date: date) -> str:
    stamp = dataset_date.strftime("%Y%m%d")
    folder = f"{dataset_date.year}_{dataset_date.month}"
    if role == PortalSourceRole.MARKET_FREE_OFFERS:
        return (
            f"{PORTAL_BASE}/portaleOfferte/resources/opendata/csv/offerteML/{folder}/"
            f"PO_Offerte_E_MLIBERO_{stamp}.xml"
        )
    if role == PortalSourceRole.MARKET_FREE_PARAMETERS:
        return (
            f"{PORTAL_BASE}/portaleOfferte/resources/opendata/csv/parametriML/{folder}/"
            f"PO_Parametri_Mercato_Libero_E_{stamp}.csv"
        )
    if role == PortalSourceRole.PLACET_OFFERS:
        return (
            f"{PORTAL_BASE}/portaleOfferte/resources/opendata/csv/offerte/{folder}/"
            f"PO_Offerte_E_PLACET_{stamp}.csv"
        )
    if role == PortalSourceRole.PLACET_PARAMETERS:
        return (
            f"{PORTAL_BASE}/portaleOfferte/resources/opendata/csv/parametri/{folder}/"
            f"PO_Parametri_E_{stamp}.csv"
        )
    return PORTAL_INDEX_URL


def _is_role_url(url: str, role: PortalSourceRole, dataset_date: date) -> bool:
    if role == PortalSourceRole.HISTORICAL_INDICES:
        return url == PORTAL_INDEX_URL
    return url == _url_for(role, dataset_date)


def _content(file: PortalFileSnapshot) -> bytes:
    if file.content is None:
        raise PortalImportError(f"snapshot content is not available for {file.role.value}")
    return file.content


class PortalOffersImporter:
    """Fetch and parse the official electricity catalogues."""

    def __init__(
        self,
        transport: PortalTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._transport = transport or _UrllibTransport()
        self._clock = clock or (lambda: datetime.now(UTC))

    def fetch(
        self,
        dataset_date: date,
        *,
        include_indexes: bool = True,
        timeout_seconds: float = 60.0,
    ) -> PortalSnapshot:
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be finite and positive")
        roles = (
            PortalSourceRole.MARKET_FREE_OFFERS,
            PortalSourceRole.MARKET_FREE_PARAMETERS,
            PortalSourceRole.PLACET_OFFERS,
            PortalSourceRole.PLACET_PARAMETERS,
        )
        files: list[PortalFileSnapshot] = []
        total = 0
        for role in roles:
            file = self._fetch_file(role, dataset_date, timeout_seconds)
            total += file.size
            if total > MAX_TOTAL_BYTES:
                raise PortalFetchError("Portale Offerte snapshot exceeds total size limit")
            files.append(file)
        offers = PortalOffersSnapshot(
            dataset_date=dataset_date,
            files=tuple(files),
            snapshot_id=self._snapshot_id(dataset_date, tuple(files)),
            status=VerificationStatus.VERIFIED,
            parser_version=PORTAL_PARSER_VERSION,
        )
        index_snapshot = None
        if include_indexes:
            index_file = self._fetch_file(
                PortalSourceRole.HISTORICAL_INDICES, dataset_date, timeout_seconds
            )
            if total + index_file.size > MAX_TOTAL_BYTES:
                raise PortalFetchError("Portale Offerte snapshot exceeds total size limit")
            index_snapshot = PortalIndexSnapshot(
                file=index_file,
                snapshot_id=self._index_snapshot_id(index_file),
                status=VerificationStatus.VERIFIED,
                parser_version=PORTAL_PARSER_VERSION,
            )
        return PortalSnapshot(offers=offers, indexes=index_snapshot)

    def _fetch_file(
        self, role: PortalSourceRole, dataset_date: date, timeout_seconds: float
    ) -> PortalFileSnapshot:
        url = _url_for(role, dataset_date)
        if not _is_allowlisted_url(url):
            raise PortalFetchError("Portale Offerte URL is not allowlisted")
        response = self._transport.get(url, timeout_seconds)
        if response.status != 200:
            raise PortalFetchError(f"Portale Offerte returned HTTP status {response.status}")
        if not _is_allowlisted_url(response.url) or not _is_role_url(
            response.url, role, dataset_date
        ):
            raise PortalFetchError("Portale Offerte response URL is not allowlisted")
        content_type = _content_type(response.headers)
        expected = (
            EXPECTED_XML_MIME if role == PortalSourceRole.MARKET_FREE_OFFERS else EXPECTED_CSV_MIME
        )
        if content_type not in expected:
            raise PortalFetchError(
                f"unexpected Portale Offerte content type: {content_type or 'missing'}"
            )
        limit = MAX_XML_BYTES if role == PortalSourceRole.MARKET_FREE_OFFERS else MAX_CSV_BYTES
        if len(response.content) > limit:
            raise PortalFetchError("Portale Offerte response exceeds the role size limit")
        digest = sha256(response.content).hexdigest()
        return PortalFileSnapshot(
            role=role,
            catalog=(
                PortalCatalog.MARKET_FREE
                if role.name.startswith("MARKET_FREE")
                else PortalCatalog.PLACET
            )
            if role != PortalSourceRole.HISTORICAL_INDICES
            else None,
            original_url=url,
            final_url=response.url,
            retrieved_at=self._clock(),
            content_type=content_type,
            size=len(response.content),
            sha256=digest,
            dataset_date=dataset_date if role != PortalSourceRole.HISTORICAL_INDICES else None,
            status=VerificationStatus.VERIFIED,
            content=response.content,
        )

    @staticmethod
    def _snapshot_id(dataset_date: date, files: tuple[PortalFileSnapshot, ...]) -> str:
        manifest = {
            "dataset_date": dataset_date.isoformat(),
            "files": [
                {"role": item.role.value, "url": item.final_url, "sha256": item.sha256}
                for item in sorted(files, key=lambda item: item.role.value)
            ],
        }
        digest = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return f"portal-snapshot:{digest}"

    @staticmethod
    def _index_snapshot_id(file: PortalFileSnapshot) -> str:
        digest = hashlib.sha256(
            json.dumps(
                {"role": file.role.value, "url": file.final_url, "sha256": file.sha256},
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        return f"portal-index-snapshot:{digest}"

    @staticmethod
    def parse_offers(snapshot: PortalOffersSnapshot) -> tuple[PortalOfferRecord, ...]:
        records: list[PortalOfferRecord] = []
        for file in sorted(snapshot.files, key=lambda item: item.role.value):
            if file.role == PortalSourceRole.MARKET_FREE_OFFERS:
                records.extend(_parse_market_free_xml(file))
            elif file.role == PortalSourceRole.PLACET_OFFERS:
                records.extend(_parse_placet_csv(file))
            elif file.role in (
                PortalSourceRole.MARKET_FREE_PARAMETERS,
                PortalSourceRole.PLACET_PARAMETERS,
            ):
                _validate_parameter_csv(file)
        if not records:
            raise PortalImportError("Portale Offerte catalogues contain no records")
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.catalog.value,
                    item.source_offer_id,
                    json.dumps(item.model_dump(mode="json"), sort_keys=True, separators=(",", ":")),
                ),
            )
        )

    @staticmethod
    def parse_market_data(snapshot: PortalIndexSnapshot) -> MarketData:
        return _parse_historical_indices(snapshot.file)

    @staticmethod
    def import_snapshot(
        snapshot: PortalOffersSnapshot,
        eligibility: PortalEligibilityProfile,
        period: DatePeriod,
        *,
        market_data: Any = None,
    ) -> PortalOffersImportResult:
        from italian_energy.portal_offers.normalizer import normalize_offers

        records = PortalOffersImporter.parse_offers(snapshot)
        return normalize_offers(
            snapshot,
            records,
            eligibility,
            period.start,
            period.end,
            market_data=market_data,
        )


def _validate_parameter_csv(file: PortalFileSnapshot) -> None:
    rows = _csv_rows(_content(file))
    if not rows:
        raise PortalImportError(f"empty parameter file: {file.role.value}")
    required = {"nome_parametro", "valore", "descrizione"}
    if set(rows[0]) != required:
        raise PortalImportError(f"unexpected parameter columns for {file.role.value}")


def _csv_rows(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        # The historical indices publication is currently Windows-1252.
        text = content.decode("cp1252")
    delimiter = (
        ";"
        if text.splitlines() and text.splitlines()[0].count(";") > text.splitlines()[0].count(",")
        else ","
    )
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if reader.fieldnames is None:
        raise PortalImportError("CSV has no header")
    return [
        {str(key).strip(): (value or "").strip() for key, value in row.items()} for row in reader
    ]


def _parse_placet_csv(file: PortalFileSnapshot) -> tuple[PortalOfferRecord, ...]:
    rows = _csv_rows(_content(file))
    required = {
        "p_iva",
        "nome_offerta",
        "cod_offerta",
        "modalita_attivazione",
        "modalita_pagamento",
        "data_inizio",
        "data_fine",
        "tipo_cliente",
        "tipo_offerta",
        "p_fix_f",
        "p_fix_v",
        "p_vol_f1",
        "p_vol_f2",
        "p_vol_f3",
        "p_vol_bf1",
        "p_vol_bf23",
        "p_vol_mono",
        "alpha",
        "regione",
        "provincia",
        "comune",
    }
    if not rows or not required.issubset(rows[0]):
        raise PortalImportError("unexpected PLACET columns")
    records: list[PortalOfferRecord] = []
    for number, row in enumerate(rows, start=2):
        offer_id = row.get("cod_offerta", "")
        if not offer_id:
            raise PortalImportError(f"PLACET row {number} has no offer code")
        start = _parse_date(row["data_inizio"], field="data_inizio")
        # Source catalogues express the last valid civil day inclusively;
        # canonical periods are half-open as required by the pricing engines.
        end = _parse_date(row["data_fine"], field="data_fine") + timedelta(days=1)
        period = DatePeriod(start=start, end=end)
        offer_type = (
            PortalOfferType.INDEXED
            if "variabil" in row["tipo_offerta"].lower()
            else PortalOfferType.FIXED
        )
        components: list[PortalEconomicComponent] = []
        for key, band in (
            ("p_fix_f", None),
            ("p_fix_v", None),
            ("p_vol_f1", "F1"),
            ("p_vol_f2", "F2"),
            ("p_vol_f3", "F3"),
            ("p_vol_bf1", "BF1"),
            ("p_vol_bf23", "BF23"),
            ("p_vol_mono", "ALL"),
            ("alpha", None),
        ):
            if not row.get(key):
                continue
            unit = "EUR/year" if key in {"p_fix_f", "p_fix_v"} else "EUR/kWh"
            components.append(
                PortalEconomicComponent(
                    code=key,
                    description=key,
                    amount=_parse_decimal(row[key], field=key),
                    unit=unit,
                    band=band,
                    # PLACET alpha is a fixed spread applied to the public index,
                    # not a second index reference.
                    index_code=None,
                    locator=ProvenanceLocator(document=file.role.value, section=f"row:{number}"),
                )
            )
        provenance = (_provenance(file, offer_id, number),)
        records.append(
            PortalOfferRecord(
                catalog=PortalCatalog.PLACET,
                source_offer_id=offer_id,
                supplier_id=row.get("p_iva") or row.get("codice_fiscale") or "unknown-supplier",
                name=row.get("nome_offerta") or offer_id,
                offer_type=offer_type,
                subscription_period=period,
                tariff_validity=period,
                duration_months=None,
                customer_type=row.get("tipo_cliente", ""),
                activation_methods=tuple(
                    item.strip()
                    for item in row.get("modalita_attivazione", "").split(";")
                    if item.strip()
                ),
                payment_methods=tuple(
                    item.strip()
                    for item in row.get("modalita_pagamento", "").split(";")
                    if item.strip()
                ),
                region_codes=(row["regione"],) if row.get("regione") else (),
                province_codes=(row["provincia"],) if row.get("provincia") else (),
                municipality_codes=(row["comune"],) if row.get("comune") else (),
                index_code="PUN" if offer_type == PortalOfferType.INDEXED else None,
                index_codes=("PUN",) if offer_type == PortalOfferType.INDEXED else (),
                index_granularity="month" if offer_type == PortalOfferType.INDEXED else None,
                components=tuple(components),
                source_provenance=provenance,
                raw_fields=tuple(sorted(row.items())),
            )
        )
    return tuple(records)


def _parse_market_free_xml(file: PortalFileSnapshot) -> tuple[PortalOfferRecord, ...]:
    try:
        safe_et = import_module("defusedxml.ElementTree")
    except ImportError as exc:  # pragma: no cover - base-package smoke has no XML parse
        raise PortalImportError("the portal extra is required for hardened XML parsing") from exc
    try:
        root = safe_et.fromstring(_content(file))
    except Exception as exc:
        raise PortalImportError("invalid Mercato Libero XML") from exc
    if root.tag != f"{{{PORTAL_XML_NAMESPACE}}}ListaOfferteMercatoLibero":
        raise PortalImportError("unexpected Mercato Libero XML root")
    namespace_prefix = f"{{{PORTAL_XML_NAMESPACE}}}"
    if any(not str(element.tag).startswith(namespace_prefix) for element in root.iter()):
        raise PortalImportError("unexpected Mercato Libero XML namespace")
    records: list[PortalOfferRecord] = []
    for number, offer in enumerate(
        (item for item in root if _local_name(item.tag) == "offerta"), start=1
    ):
        offer_id = _text(offer, "COD_OFFERTA")
        supplier_id = _text(offer, "PIVA_UTENTE")
        start_text = _text(offer, "DATA_INIZIO")
        end_text = _text(offer, "DATA_FINE")
        kind = _text(offer, "TIPO_OFFERTA")
        if (
            not offer_id
            or not supplier_id
            or not start_text
            or not end_text
            or kind not in {"01", "02"}
        ):
            raise PortalImportError(f"malformed Mercato Libero offer at row {number}")
        period = DatePeriod(
            start=_parse_date(start_text, field="DATA_INIZIO"),
            end=_parse_date(end_text, field="DATA_FINE") + timedelta(days=1),
        )
        offer_type = PortalOfferType.FIXED if kind == "01" else PortalOfferType.INDEXED
        components: list[PortalEconomicComponent] = []
        for component in offer:
            if _local_name(component.tag) != "ComponenteImpresa":
                continue
            code = _text(component, "NOME") or "component"
            description = _text(component, "DESCRIZIONE") or code
            macroarea = _text(component, "MACROAREA")
            for interval in component:
                if _local_name(interval.tag) != "IntervalloPrezzi":
                    continue
                price = _text(interval, "PREZZO")
                unit_code = _text(interval, "UNITA_MISURA")
                if price is None or unit_code is None:
                    continue
                unit = {"01": "EUR/year", "02": "EUR/kW/year", "03": "EUR/kWh"}.get(unit_code)
                if unit is None:
                    continue
                components.append(
                    PortalEconomicComponent(
                        code=code,
                        description=description,
                        amount=_parse_decimal(price, field="PREZZO"),
                        unit=unit,
                        band=_text(interval, "FASCIA_COMPONENTE"),
                        macroarea=macroarea,
                        discount="scont" in f"{code} {description}".lower(),
                        locator=ProvenanceLocator(
                            document=file.role.value, section=f"offer:{offer_id}"
                        ),
                    )
                )
        records.append(
            PortalOfferRecord(
                catalog=PortalCatalog.MARKET_FREE,
                source_offer_id=offer_id,
                supplier_id=supplier_id,
                name=_text(offer, "NOME_OFFERTA") or offer_id,
                offer_type=offer_type,
                subscription_period=period,
                tariff_validity=period,
                duration_months=_parse_duration(_text(offer, "DURATA")),
                customer_type=_text(offer, "TIPO_CLIENTE") or "",
                activation_methods=_all_text(offer, "MODALITA"),
                payment_methods=_all_text(offer, "MODALITA_PAGAMENTO"),
                index_code=_text(offer, "IDX_PREZZO_ENERGIA")
                if offer_type == PortalOfferType.INDEXED
                else None,
                index_codes=_all_text(offer, "IDX_PREZZO_ENERGIA")
                if offer_type == PortalOfferType.INDEXED
                else (),
                index_granularity="month" if offer_type == PortalOfferType.INDEXED else None,
                components=tuple(components),
                conditions=tuple(_all_text(offer, "DESCRIZIONE")),
                source_provenance=(_provenance(file, offer_id, number),),
                raw_fields=tuple(
                    sorted(
                        (
                            f"{_local_name(child.tag)}:{position}",
                            str(child.text).strip(),
                        )
                        for position, child in enumerate(offer.iter())
                        if child.text is not None and str(child.text).strip()
                    )
                ),
            )
        )
    return tuple(records)


def _parse_historical_indices(file: PortalFileSnapshot) -> MarketData:
    rows = _csv_rows(_content(file))
    if not rows:
        raise PortalImportError("empty historical index file")
    required = {"AnnoMese", "PUN (�/kWh)", "PE (�/kWh)"}
    if not required.issubset(rows[0]):
        # Some downloads decode the euro symbol correctly.
        required = {"AnnoMese", "PUN (€/kWh)", "PE (€/kWh)"}
        if not required.issubset(rows[0]):
            raise PortalImportError("unexpected historical index columns")
    indexes = []
    points = []
    from zoneinfo import ZoneInfo

    from italian_energy.domain.market import MarketData, MarketDataPoint, MarketIndex
    from italian_energy.domain.time import Granularity, TimeInterval

    zone = ZoneInfo("Europe/Rome")
    provenance = _provenance(file, "historical-indices")
    for code, label in (("PUN", "PUN (€/kWh)"), ("PE", "PE (€/kWh)")):
        if label not in rows[0]:
            continue
        indexes.append(
            MarketIndex(
                code=code,
                name=code,
                unit=RateUnit.EUR_PER_KWH,
                granularity=Granularity.MONTH,
                provenance=(provenance,),
            )
        )
    for number, row in enumerate(rows, start=2):
        raw_month = row.get("AnnoMese", "")
        if len(raw_month) != 6 or not raw_month.isdigit():
            raise PortalImportError(f"invalid historical index month at row {number}")
        year, month = int(raw_month[:4]), int(raw_month[4:])
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        interval = TimeInterval(
            start=datetime.combine(start, datetime.min.time(), zone),
            end=datetime.combine(end, datetime.min.time(), zone),
        )
        for code, label in (("PUN", "PUN (€/kWh)"), ("PE", "PE (€/kWh)")):
            value = row.get(label) or row.get(label.replace("€", "�"))
            if not value:
                continue
            points.append(
                MarketDataPoint(
                    index_code=code,
                    interval=interval,
                    value=_parse_decimal(value, field=code),
                    provenance=(provenance,),
                )
            )
    return MarketData(indexes=tuple(indexes), points=tuple(points))
