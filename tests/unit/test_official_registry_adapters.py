from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest

from italian_energy.arera.discovery import (
    DiscoveryFailure,
    OfficialRegistryRecord,
    RegulatoryRegistryChannel,
)
from italian_energy.arera.official_registry_adapters import (
    AdmExciseIndexAdapter,
    AreraActsIndexAdapter,
    AreraTariffIndexAdapter,
    GazzettaSerieGeneraleIndexAdapter,
    NormattivaUpdatesAdapter,
    OfficialRegistryHTTPResponse,
    OfficialRegulatoryDocumentAcquirer,
    RecordingOfficialRegistryTransport,
    UrllibOfficialRegistryTransport,
    _date_italian_long,
    default_official_registry_adapters,
    normattiva_vat_reference_records,
)
from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.arera.rollover_parsers import (
    ADM_EXCISE_DOMESTIC_KIND,
    ADM_EXCISE_LAYOUT_VERSION,
    ARERA_343_CONFIRMATION_DOCUMENT_KIND,
    ARERA_343_CONFIRMATION_LAYOUT_VERSION,
    ARERA_343_PDF_URL,
    ParserDisposition,
    default_regulatory_parser_registry,
)
from italian_energy.arera.rollover_sources import AcquiredOfficialBytes
from italian_energy.domain.time import DatePeriod

PERIOD = DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 1))
FETCHED_AT = datetime(2026, 10, 1, 8, tzinfo=UTC)


def test_italian_source_date_rejects_an_unrecognized_month_name() -> None:
    with pytest.raises(ValueError, match="unsupported official Italian month"):
        _date_italian_long("29 septembre 2026")


class _Transport:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> OfficialRegistryHTTPResponse:
        request_headers = headers or {}
        self.requests.append((url, method, request_headers, body))
        return OfficialRegistryHTTPResponse(
            requested_url=url,
            final_url=url,
            content_type="application/json",
            body=self.body,
            fetched_at=FETCHED_AT,
        )


class _RouteTransport(_Transport):
    def __init__(self, routes: dict[str, bytes]) -> None:
        super().__init__(b"")
        self.routes = routes

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> OfficialRegistryHTTPResponse:
        self.requests.append((url, method, headers or {}, body))
        response_body = next(value for key, value in self.routes.items() if key in url)
        return OfficialRegistryHTTPResponse(
            requested_url=url,
            final_url=url,
            content_type="text/html; charset=utf-8",
            body=response_body,
            fetched_at=FETCHED_AT,
        )


def _normattiva_body() -> bytes:
    return json.dumps(
        {
            "listaAtti": [
                {
                    "codiceRedazionale": "26G00123",
                    "titoloAtto": "Modifica del testo unico delle accise",
                    "dataGU": "2026-06-01",
                    "dataUltimaModifica": "2026-09-29",
                    "descrizioneAtto": "DECRETO LEGISLATIVO 1 giugno 2026",
                    "ultimiAttiModificanti": "26G00123 26G00456",
                }
            ],
            "numeroPagine": 1,
            "numeroAttiTrovati": 1,
            "paginaCorrente": 1,
        },
        separators=(",", ":"),
    ).encode()


def test_normattiva_uses_official_updated_acts_api_and_keeps_both_dates() -> None:
    body = _normattiva_body()
    transport = _Transport(body)
    adapter = NormattivaUpdatesAdapter(
        transport=transport,
        clock=lambda: FETCHED_AT,
    )

    page = adapter.fetch_page(PERIOD, 1, None)
    record = page.records[0]
    request_url, method, headers, request_body = transport.requests[0]

    assert adapter.channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES
    assert request_url == (
        "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/ricerca/aggiornati"
    )
    assert method == "POST"
    assert "Authorization" not in headers
    assert request_body is not None
    assert json.loads(request_body)["dataInizioAggiornamento"] == "2026-08-31T22:00:00Z"
    assert json.loads(request_body)["dataFineAggiornamento"] == "2026-09-30T22:00:00Z"
    assert record.published_at == date(2026, 6, 1)
    assert record.registry_date == date(2026, 9, 29)
    assert record.document_id == "26G00123"
    assert record.latest_amending_act_ids == ("26G00123", "26G00456")
    assert page.index_sha256 == sha256(body).hexdigest()
    assert page.complete is True


def test_normattiva_accepts_null_latest_amending_act_ids() -> None:
    payload = json.loads(_normattiva_body())
    payload["listaAtti"][0]["ultimiAttiModificanti"] = None
    adapter = NormattivaUpdatesAdapter(
        transport=_Transport(json.dumps(payload).encode()),
        clock=lambda: FETCHED_AT,
    )

    page = adapter.fetch_page(PERIOD, 1, None)

    assert page.records[0].latest_amending_act_ids == ()


def test_normattiva_rejects_unexpected_latest_amending_act_id_shape() -> None:
    payload = json.loads(_normattiva_body())
    payload["listaAtti"][0]["ultimiAttiModificanti"] = ["26G00123"]
    adapter = NormattivaUpdatesAdapter(
        transport=_Transport(json.dumps(payload).encode()),
        clock=lambda: FETCHED_AT,
    )

    with pytest.raises(DiscoveryFailure):
        adapter.fetch_page(PERIOD, 1, None)


def test_normattiva_unsupported_response_contract_fails_closed() -> None:
    adapter = NormattivaUpdatesAdapter(
        transport=_Transport(b'{"unexpected":[]}'),
        clock=lambda: FETCHED_AT,
    )
    with pytest.raises(DiscoveryFailure):
        adapter.fetch_page(PERIOD, 1, None)


def test_date_dated_vat_references_are_acquired_through_exact_core_parsers() -> None:
    as_of = date(2026, 10, 1)
    records = normattiva_vat_reference_records(as_of)
    assert tuple(record.document_id for record in records) == (
        "DPR-633-1972-Tabella-A-Parte-III-n-103",
        "DPR-633-1972-art-16-aliquote",
    )
    assert all(record.act_id == "DPR 633/1972" for record in records)
    assert all(record.published_at == date(1972, 10, 26) for record in records)
    assert all(f"!vig={as_of.isoformat()}" in record.url for record in records)

    fixture_dir = Path(__file__).parents[1] / "fixtures/regulatory_rollover"
    table = (fixture_dir / "normattiva-dpr633-table-a-synthetic.html").read_bytes()
    article = (fixture_dir / "normattiva-dpr633-art16-synthetic.html").read_bytes()
    transport = _RouteTransport({"art1!vig=": table, "art16!vig=": article})
    acquirer = OfficialRegulatoryDocumentAcquirer(transport)
    parser_registry = default_regulatory_parser_registry()

    documents = tuple(acquirer.acquire_document(record) for record in records)
    parsed = tuple(parser_registry.parse(document) for document in documents)

    assert tuple(document.source_id for document in documents) == (
        "vat_dpr_633",
        "vat_dpr_633_art16",
    )
    assert tuple(result.disposition for result in parsed) == (
        ParserDisposition.PARSED,
        ParserDisposition.PARSED,
    )
    assert tuple(result.facts[0].value for result in parsed) == (
        Decimal("10"),
        Decimal("10"),
    )


def test_known_adm_current_pdf_record_is_routed_to_its_versioned_parser() -> None:
    url = (
        "https://www.adm.gov.it/portale/documents/20182/43975520/"
        "Aliquote+nazionali++aggiornamento+al+18+settembre+2026.pdf/"
        "059466a2-2c62-b667-6dd8-9474d215f88a?t=1789719130770"
    )
    record = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ADM_EXCISE,
        act_id="adm-excise:2026-09-18:059466a2-2c62-b667-6dd8-9474d215f88a",
        title="Aliquote nazionali - Aggiornamento al 18 settembre 2026 - PDF",
        published_at=date(2026, 9, 18),
        registry_date=date(2026, 9, 18),
        url=url,
        document_id="059466a2-2c62-b667-6dd8-9474d215f88a",
    )

    class _PdfResponseTransport:
        def request(
            self,
            requested_url: str,
            *,
            method: str = "GET",
            headers: dict[str, str] | None = None,
            body: bytes | None = None,
        ) -> OfficialRegistryHTTPResponse:
            assert method == "GET"
            assert headers is None or isinstance(headers, dict)
            assert body is None
            return OfficialRegistryHTTPResponse(
                requested_url=requested_url,
                final_url=requested_url,
                content_type="application/pdf",
                body=b"%PDF-1.4\nsynthetic test payload",
                fetched_at=FETCHED_AT,
            )

    document = OfficialRegulatoryDocumentAcquirer(_PdfResponseTransport()).acquire_document(record)

    assert document.source_id == "adm_excise_20260918"
    assert document.document_kind == ADM_EXCISE_DOMESTIC_KIND
    assert document.layout_version == ADM_EXCISE_LAYOUT_VERSION


def test_arera_acts_adapter_checks_pagination_and_parses_only_exact_listing_rows() -> None:
    body = (
        b"<html><body><h1>Atti e provvedimenti</h1>"
        b"<a href='/atti-e-provvedimenti/dettaglio/26/343-26'>"
        b"Delibera 29/09/2026 343/2026/R/com Aggiornamento oneri</a>"
        b"<p>Numero pagine: 1 per 1 risultati.</p></body></html>"
    )
    transport = _RouteTransport({"anno=2026": body})
    adapter = AreraActsIndexAdapter(transport=transport)

    page = adapter.fetch_page(PERIOD, 1, None)

    assert page.complete is True
    assert page.total_pages == 1
    assert page.records_confined_to_search_period is False
    assert page.records[0].act_id == "343/2026/R/com"
    assert page.records[0].published_at == date(2026, 9, 29)
    assert page.records[0].url == "https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26"


def test_arera_acts_adapter_accepts_registered_date_first_index_row_layout() -> None:
    body = (
        b"<html><body>Atti e provvedimenti Numero pagine: 1 per 4 risultati"
        b"<a href='/atti-e-provvedimenti/dettaglio/26/301-26'>"
        b"06/08/2026 301/2026/I/efr Analisi degli strumenti di sostegno</a>"
        b"<a href='/atti-e-provvedimenti/dettaglio/26/292-26'>"
        b"Relazione 30/07/2026 292/2026/I/idr Relazione annuale</a>"
        b"<a href='/atti-e-provvedimenti/dettaglio/26/16-26'>"
        b"Determina 07/07/2026 16/26 - DSAI-gas Avvio di procedimento</a>"
        b"<a href='/atti-e-provvedimenti/dettaglio/1-26'>"
        b"Determina 13/01/2026 1/2026/gas - DSAI Avvio di procedimento</a></body></html>"
    )
    adapter = AreraActsIndexAdapter(_RouteTransport({"anno=2026": body}))

    page = adapter.fetch_page(PERIOD, 1, None)

    assert {item.act_id: item.published_at for item in page.records} == {
        "292/2026/I/idr": date(2026, 7, 30),
        "301/2026/I/efr": date(2026, 8, 6),
        "16/26 - DSAI-gas": date(2026, 7, 7),
        "1/2026/gas - DSAI": date(2026, 1, 13),
    }


def test_arera_acts_index_keeps_department_suffix_in_short_determination_ids() -> None:
    body = (
        b"<html><body>Atti e provvedimenti Numero pagine: 1 per 2 risultati"
        b"<a href='/atti-e-provvedimenti/dettaglio/5-26dime'>"
        b"Determina 29/09/2026 5/2026 - DIME Aggiornamento della scheda</a>"
        b"<a href='/atti-e-provvedimenti/dettaglio/5-26-dcom'>"
        b"Determina 28/07/2026 5/2026 - DCOM Procedura telematica</a></body></html>"
    )
    adapter = AreraActsIndexAdapter(_RouteTransport({"anno=2026": body}))

    page = adapter.fetch_page(PERIOD, 1, None)

    assert {item.act_id for item in page.records} == {"5/2026 - DIME", "5/2026 - DCOM"}


def test_gazzetta_adapter_enumerates_acts_from_each_issue_summary() -> None:
    archive = b"\n".join(
        (
            b"<html><body><h1>Serie Generale (Formato Testuale)</h1>",
            b'<a href="/gazzetta/serie_generale/caricaDettaglio?'
            b'numeroGazzetta=226&dataPubblicazioneGazzetta=2026-09-29">'
            b"n\xc2\xb0 226 del 29-09-2026</a>",
            b'<a href="/gazzetta/serie_generale/caricaDettaglio?'
            b'numeroGazzetta=227&dataPubblicazioneGazzetta=2026-09-30">'
            b"n\xc2\xb0 227 del 30-09-2026</a>",
            b"</body></html>",
        )
    )
    issue = b"\n".join(
        (
            b"<html><body><h1>Serie Generale n. 226 del 29-9-2026</h1>",
            b"<h2>Sommario</h2>",
            b'<span class="rubrica"><strong>LEGGI ED ALTRI ATTI NORMATIVI</strong></span>',
            b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
            b"atto.codiceRedazionale=26G00188&"
            b'atto.dataPubblicazioneGazzetta=2026-09-29">'
            b"DECRETO-LEGGE 29 settembre 2026, n. 168</a>",
            b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
            b"atto.codiceRedazionale=26G00188&"
            b'atto.dataPubblicazioneGazzetta=2026-09-29">'
            b"Disposizioni urgenti in materia di energia. (26G00188) Pag. 1</a>",
            b'<span class="rubrica">DECRETI, DELIBERE E ORDINANZE MINISTERIALI</span>',
            b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
            b"atto.codiceRedazionale=26A05083&"
            b'atto.dataPubblicazioneGazzetta=2026-09-29">'
            b"DECRETO 1 settembre 2026</a>",
            b"</body></html>",
        )
    )
    transport = _RouteTransport({"serie_generale/2026": archive, "numeroGazzetta=226": issue})
    period = DatePeriod(start=date(2026, 9, 29), end=date(2026, 9, 30))

    page = GazzettaSerieGeneraleIndexAdapter(transport).fetch_page(period, 1, None)

    assert page.complete is True
    assert page.total_results == 2
    assert [item.act_id for item in page.records] == ["26A05083", "26G00188"]
    assert all(item.published_at == date(2026, 9, 29) for item in page.records)
    assert page.records[1].title == "Disposizioni urgenti in materia di energia. (26G00188) Pag. 1"
    assert page.records[0].registry_section == "DECRETI, DELIBERE E ORDINANZE MINISTERIALI"
    assert page.records[1].registry_section == "LEGGI ED ALTRI ATTI NORMATIVI"
    assert len(transport.requests) == 2


def test_gazzetta_adapter_fails_closed_when_act_has_no_official_section() -> None:
    archive = (
        b"<html><body><h1>Serie Generale (Formato Testuale)</h1>"
        b'<a href="/gazzetta/serie_generale/caricaDettaglio?'
        b'numeroGazzetta=226&dataPubblicazioneGazzetta=2026-09-29">'
        b"n\xc2\xb0 226 del 29-09-2026</a></body></html>"
    )
    issue = (
        b"<html><body><h1>Serie Generale n. 226 del 29-9-2026</h1>"
        b"<h2>Sommario</h2>"
        b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
        b"atto.codiceRedazionale=26G00188&"
        b'atto.dataPubblicazioneGazzetta=2026-09-29">DECRETO-LEGGE</a>'
        b"</body></html>"
    )
    transport = _RouteTransport({"serie_generale/2026": archive, "numeroGazzetta=226": issue})

    with pytest.raises(DiscoveryFailure):
        GazzettaSerieGeneraleIndexAdapter(transport).fetch_page(PERIOD, 1, None)


def test_gazzetta_adapter_fails_closed_on_nested_official_sections() -> None:
    archive = (
        b'<html><body>Serie Generale (Formato Testuale) <a href="/gazzetta/serie_generale/'
        b'caricaDettaglio?numeroGazzetta=226&dataPubblicazioneGazzetta=2026-09-29">'
        b"n\xc2\xb0 226 del 29-09-2026</a></body></html>"
    )
    issue = (
        b"<html><body>Serie Generale n. 226 del 29-9-2026 Sommario "
        b'<span class="rubrica">LEGGI <span class="rubrica">NORMATIVE</span></span>'
        b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
        b'atto.codiceRedazionale=26G00188&atto.dataPubblicazioneGazzetta=2026-09-29">'
        b"DECRETO-LEGGE 29 settembre 2026, n. 168</a></body></html>"
    )
    transport = _RouteTransport({"serie_generale/2026": archive, "numeroGazzetta=226": issue})

    with pytest.raises(DiscoveryFailure) as failure:
        GazzettaSerieGeneraleIndexAdapter(transport).fetch_page(PERIOD, 1, None)

    assert failure.value.reason == RegulatoryRolloverReason.PARSER_FAILURE


def test_gazzetta_adapter_fails_closed_on_empty_official_section() -> None:
    archive = (
        b'<html><body>Serie Generale (Formato Testuale) <a href="/gazzetta/serie_generale/'
        b'caricaDettaglio?numeroGazzetta=226&dataPubblicazioneGazzetta=2026-09-29">'
        b"n\xc2\xb0 226 del 29-09-2026</a></body></html>"
    )
    issue = (
        b"<html><body>Serie Generale n. 226 del 29-9-2026 Sommario "
        b'<span class="rubrica"> </span>'
        b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
        b'atto.codiceRedazionale=26G00188&atto.dataPubblicazioneGazzetta=2026-09-29">'
        b"DECRETO-LEGGE 29 settembre 2026, n. 168</a></body></html>"
    )
    transport = _RouteTransport({"serie_generale/2026": archive, "numeroGazzetta=226": issue})

    with pytest.raises(DiscoveryFailure) as failure:
        GazzettaSerieGeneraleIndexAdapter(transport).fetch_page(PERIOD, 1, None)

    assert failure.value.reason == RegulatoryRolloverReason.PARSER_FAILURE


def test_gazzetta_adapter_fails_closed_when_issue_summary_layout_is_unrecognized() -> None:
    archive = (
        b'<html><body>Serie Generale <a href="/issue?numeroGazzetta=226"'
        b">n. 226 del 29-09-2026</a></body></html>"
    )
    transport = _RouteTransport(
        {"serie_generale/2026": archive, "numeroGazzetta=226": b"<html>unknown</html>"}
    )

    with pytest.raises(DiscoveryFailure):
        GazzettaSerieGeneraleIndexAdapter(transport).fetch_page(PERIOD, 1, None)


def test_arera_tariff_index_binds_published_date_and_effective_date() -> None:
    tariff_index = (
        b"<html><body><h1>Valori delle componenti tariffarie</h1>"
        b"<ul><li>dal 01.10.26 \xe2\x80\x93 "
        b'<a href="/atti-e-provvedimenti/dettaglio/26/343-26">'
        b"delibera 343/2026/R/com</a></li></ul></body></html>"
    )
    detail = b"""<html><body>343/2026/R/com
      Data pubblicazione: 29 settembre 2026</body></html>"""
    transport = _RouteTransport({"oneri-generali": tariff_index, "dettaglio/26/343-26": detail})

    page = AreraTariffIndexAdapter(transport).fetch_page(
        DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 2)), 1, None
    )

    assert page.records[0].act_id == "343/2026/R/com"
    assert page.records[0].published_at == date(2026, 9, 29)
    assert page.records[0].effective_from == date(2026, 10, 1)


def test_arera_tariff_index_deduplicates_same_act_listed_for_multiple_components() -> None:
    tariff_index = (
        b"<html><body>Valori delle componenti tariffarie<ul>"
        b"<li>dal 01.10.26 - "
        b'<a href="/atti-e-provvedimenti/dettaglio/26/343-26">'
        b"delibera 343/2026/R/com - ASOS</a></li>"
        b"<li>dal 01 ottobre 2026 - "
        b'<a href="/atti-e-provvedimenti/dettaglio/26/343-26">'
        b"delibera 343/2026/R/com - ARIM, UC3 e UC6</a></li>"
        b"</ul></body></html>"
    )
    detail = b"<html><body>343/2026/R/com Data pubblicazione: 29 settembre 2026</body></html>"
    transport = _RouteTransport({"oneri-generali": tariff_index, "dettaglio/26/343-26": detail})

    page = AreraTariffIndexAdapter(transport).fetch_page(
        DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 5)), 1, None
    )

    assert page.total_results == 1
    assert len(page.records) == 1
    assert page.records[0].act_id == "343/2026/R/com"
    assert page.records[0].effective_from == date(2026, 10, 1)
    assert page.records[0].title == (
        "delibera 343/2026/R/com - ARIM, UC3 e UC6 | delibera 343/2026/R/com - ASOS"
    )
    assert len(transport.requests) == 2


def test_arera_tariff_index_rejects_duplicate_act_with_conflicting_effective_dates() -> None:
    tariff_index = (
        b"<html><body>Valori delle componenti tariffarie<ul>"
        b"<li>dal 01.10.26 - "
        b'<a href="/atti-e-provvedimenti/dettaglio/26/343-26">'
        b"delibera 343/2026/R/com - ASOS</a></li>"
        b"<li>dal 01.11.26 - "
        b'<a href="/atti-e-provvedimenti/dettaglio/26/343-26">'
        b"delibera 343/2026/R/com - ARIM</a></li>"
        b"</ul></body></html>"
    )
    detail = b"<html><body>343/2026/R/com Data pubblicazione: 29 settembre 2026</body></html>"
    transport = _RouteTransport({"oneri-generali": tariff_index, "dettaglio/26/343-26": detail})

    with pytest.raises(DiscoveryFailure) as failure:
        AreraTariffIndexAdapter(transport).fetch_page(
            DatePeriod(start=date(2026, 9, 1), end=date(2026, 12, 1)), 1, None
        )

    assert failure.value.reason == RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY


def test_arera_tariff_index_parses_live_long_dates_and_skips_old_detail_fetches() -> None:
    tariff_index = (
        b"<html><body>Valori delle componenti tariffarie<ul>"
        b"<li>dal 01 ottobre 2026: "
        b'<a href="/atti-e-provvedimenti/dettaglio/26/343-26">'
        b"delibera 343/2026/R/com</a></li>"
        b"<li>dal 01 gennaio 2026: "
        b'<a href="/atti-e-provvedimenti/dettaglio/25/588-25">'
        b"delibera 588/2025/R/com</a></li></ul></body></html>"
    )
    detail = b"<html><body>343/2026/R/com Data pubblicazione: 29 settembre 2026</body></html>"
    transport = _RouteTransport(
        {
            "oneri-generali": tariff_index,
            "dettaglio/26/343-26": detail,
            "dettaglio/25/588-25": b"old detail must not be fetched",
        }
    )

    page = AreraTariffIndexAdapter(transport).fetch_page(
        DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 5)), 1, None
    )

    assert len(page.records) == 1
    assert page.records[0].act_id == "343/2026/R/com"
    assert page.records[0].effective_from == date(2026, 10, 1)
    assert len(transport.requests) == 2


def test_arera_tariff_index_accepts_a_complete_scan_with_no_in_period_changes() -> None:
    tariff_index = (
        b"<html><body>Valori delle componenti tariffarie<ul><li>"
        b"dal 01 gennaio 2026: "
        b'<a href="/atti-e-provvedimenti/dettaglio/25/588-25">'
        b"delibera 588/2025/R/com</a></li></ul></body></html>"
    )
    transport = _RouteTransport({"oneri-generali": tariff_index})

    page = AreraTariffIndexAdapter(transport).fetch_page(PERIOD, 1, None)

    assert page.complete is True
    assert page.records == ()
    assert len(transport.requests) == 1


def test_arera_tariff_index_binds_each_act_link_to_its_shared_list_period() -> None:
    tariff_index = (
        b"<html><body><h1>Valori delle componenti tariffarie</h1><ul><li>"
        b"dal 01.01.22 \xe2\x80\x93 "
        b'<a href="/atti-e-provvedimenti/dettaglio/21/635-21">'
        b"delibera 635/2021/R/com</a> (per UC3 e UC6) e "
        b'<a href="/atti-e-provvedimenti/dettaglio/22/035-22">'
        b"delibera 35/2022/R/eel</a></li></ul></body></html>"
    )
    detail_2021 = b"<html><body>635/2021/R/com Data pubblicazione: 27 dicembre 2021</body></html>"
    detail_2022 = b"<html><body>35/2022/R/eel Data pubblicazione: 27 gennaio 2022</body></html>"
    transport = _RouteTransport(
        {
            "oneri-generali": tariff_index,
            "dettaglio/21/635-21": detail_2021,
            "dettaglio/22/035-22": detail_2022,
        }
    )

    page = AreraTariffIndexAdapter(transport).fetch_page(
        DatePeriod(start=date(2022, 1, 1), end=date(2022, 2, 1)), 1, None
    )

    assert {item.act_id: item.effective_from for item in page.records} == {
        "635/2021/R/com": date(2022, 1, 1),
        "35/2022/R/eel": date(2022, 1, 1),
    }


def test_arera_tariff_detail_route_year_is_not_inferred_from_act_dates() -> None:
    tariff_index = (
        b"<html><body>Valori delle componenti tariffarie<ul><li>"
        b"dal 01.01.20 - "
        b'<a href="/atti-e-provvedimenti/dettaglio/20/572-20">'
        b"delibera 572/2019/R/com</a></li></ul></body></html>"
    )
    detail = b"<html><body>572/2019/R/com Data pubblicazione: 12 gennaio 2021</body></html>"
    transport = _RouteTransport({"oneri-generali": tariff_index, "dettaglio/20/572-20": detail})

    page = AreraTariffIndexAdapter(transport).fetch_page(
        DatePeriod(start=date(2020, 1, 1), end=date(2020, 2, 1)), 1, None
    )

    assert page.records[0].act_id == "572/2019/R/com"
    assert page.records[0].published_at == date(2021, 1, 12)
    assert page.records[0].effective_from == date(2020, 1, 1)


def test_adm_index_reads_current_and_archive_updates_by_exact_date_labels() -> None:
    current = b"".join(
        (
            b"<html><body>Aliquote nazionali periodi precedenti",
            b'<a href="/documents/aliquote-2026.pdf">',
            b"Aliquote nazionali aggiornamento al 26 settembre 2026.pdf</a></body></html>",
        )
    )
    archive = b"".join(
        (
            b"<html><body>",
            b'<a href="/documents/aliquote-2025.pdf">Aliquote nazionali - ',
            b"Aggiornamento al 31 dicembre 2025 - PDF</a></body></html>",
        )
    )
    transport = _RouteTransport({"aliquote-accisa-nazionali": current, "anni-precedenti": archive})

    page = AdmExciseIndexAdapter(transport).fetch_page(PERIOD, 1, None)

    assert page.total_results == 2
    assert {item.published_at for item in page.records} == {
        date(2025, 12, 31),
        date(2026, 9, 26),
    }


def test_adm_index_accepts_the_live_en_dash_update_label() -> None:
    current = (
        b"<html><body>Aliquote nazionali periodi precedenti"
        b'<a href="/documents/aliquote-2026.pdf">'
        b"Aliquote nazionali \xe2\x80\x93 Aggiornamento al 6 ottobre 2026.pdf</a></body></html>"
    )
    archive = (
        b'<html><body><a href="/documents/aliquote-2025.pdf">'
        b"Aliquote nazionali - Aggiornamento al 31 dicembre 2025 - PDF</a></body></html>"
    )
    transport = _RouteTransport({"aliquote-accisa-nazionali": current, "anni-precedenti": archive})

    page = AdmExciseIndexAdapter(transport).fetch_page(PERIOD, 1, None)

    assert {item.published_at for item in page.records} == {
        date(2025, 12, 31),
        date(2026, 10, 6),
    }


class _HTTPResponse:
    def __init__(
        self,
        body: bytes = b"<html></html>",
        *,
        final_url: str = "https://www.arera.it/resource",
        content_type: str = "text/html; charset=utf-8",
    ) -> None:
        self.body = BytesIO(body)
        self.final_url = final_url
        self.headers = {"Content-Type": content_type}

    def __enter__(self) -> _HTTPResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.final_url

    def read(self, limit: int) -> bytes:
        return self.body.read(limit)


def test_urllib_transport_keeps_exact_response_metadata_and_observes_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    body = b"official bytes exactly"
    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: _HTTPResponse(body))
    transport = UrllibOfficialRegistryTransport(clock=lambda: FETCHED_AT)
    saved: list[AcquiredOfficialBytes] = []
    recording = RecordingOfficialRegistryTransport(transport, saved.append)

    response = recording.request("https://www.arera.it/index")

    assert response.requested_url == "https://www.arera.it/index"
    assert response.final_url == "https://www.arera.it/resource"
    assert response.content_type == "text/html; charset=utf-8"
    assert response.body == body
    assert saved[0].sha256 == sha256(body).hexdigest()
    assert saved[0].byte_length == len(body)
    assert saved[0].body == body


def test_urllib_transport_uses_verified_native_system_trust_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import ssl
    import urllib.request

    captured: dict[str, object] = {}

    def open_request(*_args: object, **kwargs: object) -> _HTTPResponse:
        captured.update(kwargs)
        return _HTTPResponse(b"verified bytes")

    monkeypatch.setattr(urllib.request, "urlopen", open_request)

    UrllibOfficialRegistryTransport(clock=lambda: FETCHED_AT).request("https://www.arera.it/index")

    context = captured["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED  # type: ignore[attr-defined]
    assert context.check_hostname is True  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("url", "response", "expected"),
    [
        ("http://www.arera.it/index", _HTTPResponse(), DiscoveryFailure),
        (
            "https://www.arera.it/index",
            _HTTPResponse(final_url="https://example.com/redirect"),
            DiscoveryFailure,
        ),
        (
            "https://www.arera.it/index",
            _HTTPResponse(content_type=""),
            DiscoveryFailure,
        ),
        ("https://www.arera.it/index", _HTTPResponse(body=b""), DiscoveryFailure),
    ],
)
def test_urllib_transport_rejects_unsafe_or_incomplete_responses(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    response: _HTTPResponse,
    expected: type[Exception],
) -> None:
    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", lambda *_a, **_k: response)
    with pytest.raises(expected):
        UrllibOfficialRegistryTransport(clock=lambda: FETCHED_AT).request(url)


def test_urllib_transport_maps_network_failure_and_rejects_naive_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.error
    import urllib.request

    def fail(*_args: object, **_kwargs: object) -> None:
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    with pytest.raises(DiscoveryFailure):
        UrllibOfficialRegistryTransport(clock=lambda: FETCHED_AT).request(
            "https://www.arera.it/index"
        )
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HTTPResponse(),
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        UrllibOfficialRegistryTransport(clock=lambda: datetime(2026, 10, 1)).request(
            "https://www.arera.it/index"
        )


def test_document_acquirer_preserves_xlsx_layout_and_marks_unknown_bytes_for_review() -> None:
    xlsx = OfficialRegistryHTTPResponse(
        requested_url="https://www.arera.it/prices.xlsx",
        final_url="https://www.arera.it/prices.xlsx",
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        body=b"xlsx-bytes",
        fetched_at=FETCHED_AT,
    )

    class _SingleTransport:
        def request(self, *_args: object, **_kwargs: object) -> OfficialRegistryHTTPResponse:
            return xlsx

    record = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="343/2026/R/com",
        title="Q4 tariff update",
        published_at=date(2026, 9, 29),
        url=xlsx.requested_url,
        document_id="343/2026/R/com",
    )
    document = OfficialRegulatoryDocumentAcquirer(_SingleTransport()).acquire_document(record)

    assert document.document_kind == "arera_domestic_bt_workbook"
    assert document.layout_version == "005-domestic-electricity-2026-v1"
    assert document.acquired.final_url == xlsx.final_url
    assert document.acquired.byte_length == len(xlsx.body)

    unknown = OfficialRegistryHTTPResponse(
        requested_url="https://www.arera.it/unknown.pdf",
        final_url="https://www.arera.it/unknown.pdf",
        content_type="application/pdf",
        body=b"unregistered document bytes",
        fetched_at=FETCHED_AT,
    )

    class _UnknownTransport:
        def request(self, *_args: object, **_kwargs: object) -> OfficialRegistryHTTPResponse:
            return unknown

    unknown_record = record.model_copy(
        update={"url": unknown.requested_url, "document_id": "unknown-document"}
    )
    unclassified = OfficialRegulatoryDocumentAcquirer(_UnknownTransport()).acquire_document(
        unknown_record
    )
    assert unclassified.document_kind == "arera_tariffs_unclassified_document"
    assert unclassified.layout_version == "unregistered-v1"
    assert unclassified.acquired.body == unknown.body
    assert (
        OfficialRegulatoryDocumentAcquirer(_UnknownTransport()).fetch_source(unknown_record.url)
        == unknown.body
    )


def test_document_acquirer_uses_exact_official_pdf_for_the_registered_arera_343_record() -> None:
    detail_url = "https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26"
    pdf_body = b"%PDF-1.4\n343 source fixture"

    class _PdfTransport:
        def __init__(self) -> None:
            self.requested: list[str] = []

        def request(
            self,
            url: str,
            *,
            method: str = "GET",
            headers: dict[str, str] | None = None,
            body: bytes | None = None,
        ) -> OfficialRegistryHTTPResponse:
            assert method == "GET"
            assert headers is None
            assert body is None
            self.requested.append(url)
            return OfficialRegistryHTTPResponse(
                requested_url=url,
                final_url=url,
                content_type="application/pdf",
                body=pdf_body,
                fetched_at=FETCHED_AT,
            )

    transport = _PdfTransport()
    record = OfficialRegistryRecord(
        channel=RegulatoryRegistryChannel.ARERA_TARIFFS,
        act_id="343/2026/R/com",
        title="Delibera 29/09/2026 343/2026/R/com",
        published_at=date(2026, 9, 29),
        effective_from=date(2026, 10, 1),
        url=detail_url,
        document_id="343/2026/R/com",
    )

    document = OfficialRegulatoryDocumentAcquirer(transport).acquire_document(record)

    assert transport.requested == [ARERA_343_PDF_URL]
    assert document.acquired.url == ARERA_343_PDF_URL
    assert document.record_url == detail_url
    assert document.document_kind == ARERA_343_CONFIRMATION_DOCUMENT_KIND
    assert document.layout_version == ARERA_343_CONFIRMATION_LAYOUT_VERSION
    assert document.acquired.body == pdf_body


def test_urllib_transport_rejects_response_larger_than_registered_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import urllib.request

    monkeypatch.setattr("italian_energy.arera.official_registry_adapters._MAX_RESPONSE_BYTES", 4)
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _HTTPResponse(body=b"12345"),
    )
    with pytest.raises(DiscoveryFailure) as failure:
        UrllibOfficialRegistryTransport(clock=lambda: FETCHED_AT).request(
            "https://www.arera.it/index"
        )
    assert failure.value.reason.value == "incomplete_coverage"


def test_default_factory_registers_all_five_official_channels() -> None:
    class _UnusedTransport:
        def request(self, *_args: object, **_kwargs: object) -> OfficialRegistryHTTPResponse:
            raise AssertionError("factory construction must not make network calls")

    adapters = default_official_registry_adapters(transport_factory=_UnusedTransport)

    assert tuple(item.channel for item in adapters) == (
        RegulatoryRegistryChannel.ARERA_ACTS,
        RegulatoryRegistryChannel.ARERA_TARIFFS,
        RegulatoryRegistryChannel.ADM_EXCISE,
        RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE,
        RegulatoryRegistryChannel.NORMATTIVA_UPDATES,
    )


def test_default_factory_records_exact_bytes_from_registry_requests() -> None:
    body = b"<html><body>Atti e provvedimenti Numero pagine: 1 per 0 risultati</body></html>"
    transport = _RouteTransport({"anno=2026": body})
    saved: list[AcquiredOfficialBytes] = []
    adapters = default_official_registry_adapters(
        transport_factory=lambda: transport,
        source_observer=saved.append,
    )

    page = adapters[0].fetch_page(PERIOD, 1, None)

    assert page.complete is True
    assert len(saved) == 1
    assert saved[0].body == body
    assert saved[0].sha256 == sha256(body).hexdigest()
    assert saved[0].byte_length == len(body)
