from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import pytest

from italian_energy.arera.discovery import DiscoveryFailure, RegulatoryRegistryChannel
from italian_energy.arera.official_registry_adapters import (
    AdmExciseIndexAdapter,
    AreraActsIndexAdapter,
    AreraTariffIndexAdapter,
    GazzettaSerieGeneraleIndexAdapter,
    NormattivaUpdatesAdapter,
    OfficialRegistryHTTPResponse,
)
from italian_energy.arera.rollover_models import RegulatoryRolloverReason
from italian_energy.domain.time import DatePeriod

PERIOD = DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 1))
FETCHED_AT = datetime(2026, 10, 1, 8, tzinfo=UTC)


@dataclass(frozen=True)
class _Response:
    body: bytes
    content_type: str = "text/html; charset=utf-8"
    final_url: str | None = None
    fetched_at: datetime = FETCHED_AT


class _ScriptedTransport:
    def __init__(self, *responses: _Response) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def request(self, url: str, **_kwargs: Any) -> OfficialRegistryHTTPResponse:
        self.urls.append(url)
        if not self.responses:
            raise AssertionError(f"unexpected request: {url}")
        response = self.responses.pop(0)
        return OfficialRegistryHTTPResponse(
            requested_url=url,
            final_url=response.final_url or url,
            content_type=response.content_type,
            body=response.body,
            fetched_at=response.fetched_at,
        )


def _normattiva_payload(
    *,
    items: object | None = None,
    pages: object = 1,
    count: object | None = None,
    current_page: object = 1,
) -> bytes:
    records = (
        [
            {
                "codiceRedazionale": "26G00123",
                "titoloAtto": "Atto fiscale",
                "dataGU": "2026-06-01",
                "dataUltimaModifica": "2026-09-29",
                "descrizioneAtto": "Decreto legislativo",
            }
        ]
        if items is None
        else items
    )
    return json.dumps(
        {
            "listaAtti": records,
            "numeroPagine": pages,
            "numeroAttiTrovati": len(records)
            if count is None and isinstance(records, list)
            else count,
            "paginaCorrente": current_page,
        }
    ).encode()


@pytest.mark.parametrize(
    ("page_number", "response", "reason"),
    [
        (
            2,
            _Response(_normattiva_payload(), content_type="application/json"),
            RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
        ),
        (
            1,
            _Response(
                _normattiva_payload(),
                content_type="application/json",
                final_url="https://example.com/acts",
            ),
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            1,
            _Response(_normattiva_payload(), content_type="text/html"),
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            1,
            _Response(b"not-json", content_type="application/json"),
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            1,
            _Response(b"[]", content_type="application/json"),
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            1,
            _Response(_normattiva_payload(pages=2), content_type="application/json"),
            RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
        ),
        (
            1,
            _Response(
                _normattiva_payload(items=[{"codiceRedazionale": "26G00123"}]),
                content_type="application/json",
            ),
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            1,
            _Response(
                _normattiva_payload(
                    items=[
                        {
                            "codiceRedazionale": "26G00123",
                            "titoloAtto": "Atto",
                            "dataGU": "not-a-date",
                            "dataUltimaModifica": "2026-09-29",
                            "descrizioneAtto": "Decreto",
                        }
                    ]
                ),
                content_type="application/json",
            ),
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            1,
            _Response(
                _normattiva_payload(),
                content_type="application/json",
                fetched_at=datetime(2026, 10, 1),
            ),
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
    ],
)
def test_normattiva_rejects_incomplete_or_changed_contracts(
    page_number: int, response: _Response, reason: RegulatoryRolloverReason
) -> None:
    adapter = NormattivaUpdatesAdapter(
        transport=_ScriptedTransport(response),
    )
    with pytest.raises(DiscoveryFailure) as failure:
        adapter.fetch_page(PERIOD, page_number, None)
    assert failure.value.reason == reason


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"<html>changed layout</html>", RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY),
        (
            b"<html><body>Atti e provvedimenti Numero pagine: 1 per 1 risultati"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/1'>Documento nuovo</a></body></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            b"<html><body>Atti e provvedimenti Numero pagine: 1 per 1 risultati"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/1'>"
            b"Delibera 31/02/2026 1/2026/R/com</a></body></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            b"<html><body>Atti e provvedimenti Numero pagine: 1 per 1 risultati"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/1'>Delibera 01/09/2026 1/2026/R/com</a>"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/2'>"
            b"Delibera 02/09/2026 1/2026/R/com</a></body></html>",
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Atti e provvedimenti Numero pagine: 0 per 0 risultati</body></html>",
            RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
        ),
    ],
)
def test_arera_acts_index_fails_closed_on_unrecognized_rows_and_counts(
    body: bytes, reason: RegulatoryRolloverReason
) -> None:
    transport = _ScriptedTransport(_Response(body))
    adapter = AreraActsIndexAdapter(transport)
    with pytest.raises(DiscoveryFailure) as failure:
        adapter.fetch_page(PERIOD, 1, None)
    assert failure.value.reason == reason


def test_arera_acts_index_rejects_too_wide_windows_and_invalid_page_numbers() -> None:
    adapter = AreraActsIndexAdapter(_ScriptedTransport())
    wide_period = DatePeriod(start=date(2022, 1, 1), end=date(2026, 1, 1))
    with pytest.raises(DiscoveryFailure) as wide:
        adapter.fetch_page(wide_period, 1, None)
    assert wide.value.reason == RegulatoryRolloverReason.INCOMPLETE_COVERAGE

    too_late = _ScriptedTransport(
        _Response(
            b"<html><body>Atti e provvedimenti Numero pagine: 1 per 0 risultati</body></html>"
        )
    )
    with pytest.raises(DiscoveryFailure):
        AreraActsIndexAdapter(too_late).fetch_page(PERIOD, 0, None)


@pytest.mark.parametrize(
    ("index", "detail", "expected_reason"),
    [
        (
            b"<html><body>layout aggiornato</body></html>",
            None,
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Valori delle componenti tariffarie"
            b"<a href='https://example.com/atto'>"
            b"dal 01.10.26 - delibera 343/2026/R/com</a></body></html>",
            None,
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Valori delle componenti tariffarie"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/343-26'>"
            b"dal 31.02.26 - delibera 343/2026/R/com</a></body></html>",
            b"<html><body>Data pubblicazione: 29 settembre 2026 343/2026/R/com</body></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            b"<html><body>Valori delle componenti tariffarie"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/999-26'>"
            b"dal 01.10.26 - delibera 343/2026/R/com</a></body></html>",
            b"<html><body>Data pubblicazione: 29 settembre 2026\n999/2026/R/com</body></html>",
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Valori delle componenti tariffarie"
            b"<a href='/atti-e-provvedimenti/dettaglio/26/343-26'>"
            b"dal 01.10.26 - delibera 343/2026/R/com</a></body></html>",
            b"<html><body>no publication metadata</body></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
    ],
)
def test_arera_tariff_index_rejects_unverified_layout_or_cross_reference(
    index: bytes, detail: bytes | None, expected_reason: RegulatoryRolloverReason
) -> None:
    responses = [_Response(index)]
    if detail is not None:
        responses.append(_Response(detail))
    adapter = AreraTariffIndexAdapter(_ScriptedTransport(*responses))
    tariff_period = DatePeriod(start=date(2026, 9, 1), end=date(2026, 10, 2))
    with pytest.raises(DiscoveryFailure) as failure:
        adapter.fetch_page(tariff_period, 1, None)
    assert failure.value.reason == expected_reason


def test_arera_tariff_index_rejects_nonfirst_page_and_empty_listing() -> None:
    transport = _ScriptedTransport()
    adapter = AreraTariffIndexAdapter(transport)
    with pytest.raises(DiscoveryFailure):
        adapter.fetch_page(PERIOD, 2, None)
    no_rows = _ScriptedTransport(_Response(b"<html><body>Valori delle componenti</body></html>"))
    with pytest.raises(DiscoveryFailure):
        AreraTariffIndexAdapter(no_rows).fetch_page(PERIOD, 1, None)


def test_arera_tariff_index_rejects_non_utf8_index_bytes() -> None:
    transport = _ScriptedTransport(_Response(b"\xff", content_type="text/html"))
    with pytest.raises(DiscoveryFailure) as failure:
        AreraTariffIndexAdapter(transport).fetch_page(PERIOD, 1, None)
    assert failure.value.reason == RegulatoryRolloverReason.PARSER_FAILURE


@pytest.mark.parametrize(
    ("current", "archive", "reason"),
    [
        (
            b"<html><body>updated</body></html>",
            b"<html></html>",
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Aliquote nazionali periodi precedenti"
            b"<a href='/x.pdf'>Aliquote nazionali - Aggiornamento al data errata - PDF</a>"
            b"</body></html>",
            b"<html></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
        (
            b"<html><body>Aliquote nazionali periodi precedenti"
            b"<a href='https://example.com/x.pdf'>"
            b"Aliquote nazionali - Aggiornamento al 18 settembre 2026 - PDF</a></body></html>",
            b"<html></html>",
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Aliquote nazionali periodi precedenti</body></html>",
            b"<html><body>periodi precedenti</body></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
    ],
)
def test_adm_excise_index_rejects_changed_dates_or_unofficial_links(
    current: bytes, archive: bytes, reason: RegulatoryRolloverReason
) -> None:
    transport = _ScriptedTransport(_Response(current), _Response(archive))
    with pytest.raises(DiscoveryFailure) as failure:
        AdmExciseIndexAdapter(transport).fetch_page(PERIOD, 1, None)
    assert failure.value.reason == reason


def test_adm_excise_index_rejects_nonfirst_page_and_nonhtml_response() -> None:
    adapter = AdmExciseIndexAdapter(_ScriptedTransport())
    with pytest.raises(DiscoveryFailure):
        adapter.fetch_page(PERIOD, 2, None)
    transport = _ScriptedTransport(
        _Response(b"bytes", content_type="application/pdf"), _Response(b"<html></html>")
    )
    with pytest.raises(DiscoveryFailure):
        AdmExciseIndexAdapter(transport).fetch_page(PERIOD, 1, None)


def _gazzetta_archive(issue_href: str = "/issue?numeroGazzetta=226") -> bytes:
    return (
        "<html><body>Serie Generale (Formato Testuale) "
        f'<a href="{issue_href}">n° 226 del 29-09-2026</a></body></html>'
    ).encode()


@pytest.mark.parametrize(
    ("archive", "issue", "reason"),
    [
        (
            b"<html><body>layout modificato</body></html>",
            None,
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            b"<html><body>Serie Generale (Formato Testuale) "
            b'<a href="/gazzetta/serie_generale/caricaDettaglio?numeroGazzetta=226">'
            b"numero 226 settembre</a></body></html>",
            None,
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            _gazzetta_archive("https://example.com/issue?numeroGazzetta=226"),
            None,
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            _gazzetta_archive(),
            b"<html><body>Serie Generale n. 226 del 29-9-2026</body></html>",
            RegulatoryRolloverReason.SOURCE_CHANGED_UNEXPECTEDLY,
        ),
        (
            _gazzetta_archive(),
            b"<html><body>Serie Generale n. 226 del 29-9-2026 Sommario</body></html>",
            RegulatoryRolloverReason.INCOMPLETE_COVERAGE,
        ),
        (
            _gazzetta_archive(),
            b"<html><body>Serie Generale n. 226 del 29-9-2026 Sommario "
            b'<a href="/atto/serie_generale/caricaDettaglioAtto/originario?'
            b'atto.codiceRedazionale=26G00188&atto.dataPubblicazioneGazzetta=2026-09-29"> </a>'
            b"</body></html>",
            RegulatoryRolloverReason.PARSER_FAILURE,
        ),
    ],
)
def test_gazzetta_index_requires_complete_issue_and_act_rows(
    archive: bytes, issue: bytes | None, reason: RegulatoryRolloverReason
) -> None:
    responses = [_Response(archive)]
    if issue is not None:
        responses.append(_Response(issue))
    with pytest.raises(DiscoveryFailure) as failure:
        GazzettaSerieGeneraleIndexAdapter(_ScriptedTransport(*responses)).fetch_page(
            PERIOD,
            1,
            None,
        )
    assert failure.value.reason == reason


def test_gazzetta_index_rejects_nonfirst_page_and_malformed_query() -> None:
    adapter = GazzettaSerieGeneraleIndexAdapter(_ScriptedTransport())
    with pytest.raises(DiscoveryFailure):
        adapter.fetch_page(PERIOD, 2, None)

    malformed = b"""<html><body>Serie Generale n. 226 del 29-9-2026 Sommario
      <a href="/atto/serie_generale/caricaDettaglioAtto/originario?broken">Decreto</a>
      </body></html>"""
    transport = _ScriptedTransport(_Response(_gazzetta_archive()), _Response(malformed))
    with pytest.raises(DiscoveryFailure) as failure:
        GazzettaSerieGeneraleIndexAdapter(transport).fetch_page(PERIOD, 1, None)
    assert failure.value.reason == RegulatoryRolloverReason.PARSER_FAILURE


def test_index_adapters_reject_unsupported_page_numbers_without_network() -> None:
    adapter = NormattivaUpdatesAdapter(
        transport=_ScriptedTransport(),
    )
    with pytest.raises(DiscoveryFailure) as normattiva:
        adapter.fetch_page(PERIOD, 0, None)
    assert normattiva.value.reason == RegulatoryRolloverReason.INCOMPLETE_COVERAGE
    assert RegulatoryRegistryChannel.ARERA_ACTS.value == "arera_acts"
