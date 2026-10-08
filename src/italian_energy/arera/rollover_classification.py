"""Exact, versioned policies for reviewed official regulatory records.

Rules bind to exact registry metadata. This module does not parse titles or
document content at runtime; other records remain in review unless separately
supported by a versioned, auditable policy.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import parse_qs, urlsplit

from italian_energy.arera.discovery import (
    DiscoveryActDisposition,
    DiscoveryActFinding,
    OfficialRegistryRecord,
    RegulatoryRegistryChannel,
)

_ARERA_343_RULE_ID = "arera-343-q4-confirmation"
_ARERA_343_RULE_VERSION = "1.0.0"
_ARERA_343_DUPLICATE_RULE_ID = "arera-343-general-index-duplicate"
_ARERA_343_URL = "https://www.arera.it/atti-e-provvedimenti/dettaglio/26/343-26"
_ARERA_338_URL = "https://www.arera.it/atti-e-provvedimenti/dettaglio/26/338-26"
_GQ_148_REDACTIONAL_ID = "26A04702"
_GQ_2026_SEPTEMBER_DIESEL_ID = "26A04766"
_GQ_2026_LAW_166_ID = "26G00184"
_GAZZETTA_INFORMATIONAL_SECTION = "ESTRATTI, SUNTI E COMUNICATI"
_NORMATTIVA_TUA_ID = "095G0523"
_NORMATTIVA_UPDATES_URL = (
    "https://api.normattiva.it/t/normattiva.api/bff-opendata/v1/api/v1/ricerca/aggiornati"
)
_ADM_BASE_URL = "https://www.adm.gov.it/portale/documents/20182/43975520/"
_ADM_Q4_RECORDS = {
    (date(2026, 9, 26), "520d8bc6-cd18-ab4b-ea07-63b5a1ad1b85"): (
        "Aliquote+nazionali++aggiornamento+al+26+settembre+2026.pdf",
        "1791278639804",
    ),
    (date(2026, 10, 6), "843f942b-f77d-a718-b5f5-63559bd5fdb7"): (
        "Aliquote+nazionali++aggiornamento+al+6+ottobre+2026.pdf",
        "1791278679997",
    ),
}
_ADM_HISTORICAL_Q4_RECORDS = {
    (date(2025, 1, 1), "74c6d6b2-51ea-4e06-3d76-9c506ef0dfd0"): (
        "Aliquote+nazionali+aggiornamento+al+1+gennaio+2025.pdf",
        "1737560216015",
    ),
    (date(2026, 6, 7), "acef980d-4a2e-5feb-d59a-8ff962da87d5"): (
        "Aliquote+nazionali+aggiornamento+07+giugno+2026.pdf",
        "1783331967929",
    ),
}


def _is_known_arera_343(record: OfficialRegistryRecord) -> bool:
    if (
        record.channel
        not in (
            RegulatoryRegistryChannel.ARERA_ACTS,
            RegulatoryRegistryChannel.ARERA_TARIFFS,
        )
        or record.act_id != "343/2026/R/com"
        or record.document_id != "343/2026/R/com"
        or record.published_at != date(2026, 9, 29)
        or record.url != _ARERA_343_URL
    ):
        return False
    expected_effective_from = (
        date(2026, 10, 1) if record.channel == RegulatoryRegistryChannel.ARERA_TARIFFS else None
    )
    return record.effective_from == expected_effective_from


def _is_known_arera_338(record: OfficialRegistryRecord) -> bool:
    return (
        record.channel == RegulatoryRegistryChannel.ARERA_ACTS
        and record.act_id == "338/2026/R/eel"
        and record.document_id == "338/2026/R/eel"
        and record.published_at == date(2026, 9, 29)
        and record.effective_from is None
        and record.url == _ARERA_338_URL
    )


def _matches_adm_record(
    record: OfficialRegistryRecord,
    known_records: dict[tuple[date, str], tuple[str, str]],
) -> bool:
    identity = (record.published_at, record.document_id)
    known = known_records.get(identity)
    if known is None:
        return False
    filename, cache_timestamp = known
    expected_url = f"{_ADM_BASE_URL}{filename}/{record.document_id}?t={cache_timestamp}"
    return (
        record.channel == RegulatoryRegistryChannel.ADM_EXCISE
        and record.act_id == f"adm-excise:{record.published_at.isoformat()}:{record.document_id}"
        and record.registry_date == record.published_at
        and record.effective_from is None
        and record.url == expected_url
    )


def _is_known_gazzetta_148(record: OfficialRegistryRecord) -> bool:
    if (
        record.channel != RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE
        or record.act_id != _GQ_148_REDACTIONAL_ID
        or record.document_id != _GQ_148_REDACTIONAL_ID
        or record.published_at != date(2026, 9, 4)
        or record.registry_date != date(2026, 9, 4)
    ):
        return False
    parsed = urlsplit(record.url)
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.gazzettaufficiale.it"
        and parsed.path == "/atto/serie_generale/caricaDettaglioAtto/originario"
        and query.get("atto.codiceRedazionale") == [_GQ_148_REDACTIONAL_ID]
    )


def _is_known_september_diesel_decree(record: OfficialRegistryRecord) -> bool:
    if (
        record.channel != RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE
        or record.act_id != _GQ_2026_SEPTEMBER_DIESEL_ID
        or record.document_id != _GQ_2026_SEPTEMBER_DIESEL_ID
        or record.published_at != date(2026, 9, 4)
        or record.registry_date != date(2026, 9, 4)
    ):
        return False
    parsed = urlsplit(record.url)
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.gazzettaufficiale.it"
        and parsed.path == "/atto/serie_generale/caricaDettaglioAtto/originario"
        and query.get("atto.codiceRedazionale") == [_GQ_2026_SEPTEMBER_DIESEL_ID]
        and query.get("atto.dataPubblicazioneGazzetta") == ["2026-09-04"]
    )


def _is_known_law_166_petroleum_measure(record: OfficialRegistryRecord) -> bool:
    if (
        record.channel != RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE
        or record.act_id != _GQ_2026_LAW_166_ID
        or record.document_id != _GQ_2026_LAW_166_ID
        or record.published_at != date(2026, 9, 25)
        or record.registry_date != date(2026, 9, 25)
    ):
        return False
    parsed = urlsplit(record.url)
    try:
        query = parse_qs(parsed.query, strict_parsing=True)
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and parsed.hostname == "www.gazzettaufficiale.it"
        and parsed.path == "/atto/serie_generale/caricaDettaglioAtto/originario"
        and query.get("atto.codiceRedazionale") == [_GQ_2026_LAW_166_ID]
        and query.get("atto.dataPubblicazioneGazzetta") == ["2026-09-25"]
    )


def _is_known_normattiva_tua_petroleum_update(record: OfficialRegistryRecord) -> bool:
    return (
        record.channel == RegulatoryRegistryChannel.NORMATTIVA_UPDATES
        and record.act_id == _NORMATTIVA_TUA_ID
        and record.document_id == _NORMATTIVA_TUA_ID
        and record.published_at == date(1995, 11, 29)
        and record.registry_date == date(2026, 9, 25)
        and record.url == _NORMATTIVA_UPDATES_URL
        and record.latest_amending_act_ids == (_GQ_2026_LAW_166_ID,)
    )


def classify_official_regulatory_record(
    record: OfficialRegistryRecord,
) -> DiscoveryActFinding:
    """Classify exact registered records and leave all others in review.

    No titles, keywords, fuzzy IDs, or document parsing are used at runtime.
    Each policy binds to an exact official record reviewed outside this
    classifier. Any record outside those exact cases remains review-required.
    """

    if _is_known_arera_343(record):
        if record.channel == RegulatoryRegistryChannel.ARERA_ACTS:
            return DiscoveryActFinding(
                channel=record.channel,
                act_id=record.act_id,
                disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
                rationale=(
                    "the exact act is parsed once from the ARERA system-charges index; "
                    "this general-index record is its metadata cross-check"
                ),
                rule_id=_ARERA_343_DUPLICATE_RULE_ID,
                rule_version=_ARERA_343_RULE_VERSION,
            )
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.SUPPORTED,
            rationale=(
                "exact ARERA 343/2026/R/com record is supported by the versioned Q4 "
                "electricity confirmation parser"
            ),
            rule_id=_ARERA_343_RULE_ID,
            rule_version=_ARERA_343_RULE_VERSION,
        )
    if _is_known_arera_338(record):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "the exact act updates protected-service PE, PD, PED, PPE and STG sale terms, "
                "plus time bands; this projection anchor models only network/system totals, "
                "domestic excise and VAT"
            ),
            rule_id="arera-338-sale-terms-out-of-projection-anchor",
            rule_version="1.0.0",
        )
    if _matches_adm_record(record, _ADM_Q4_RECORDS):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.SUPPORTED,
            rationale=(
                "exact Q4 2026 official ADM domestic-electricity excise update; the exact-layout "
                "parser must still confirm the date, domestic row and EUR/kWh value"
            ),
            rule_id="adm-domestic-excise-q4-2026",
            rule_version="1.0.0",
        )
    if _matches_adm_record(record, _ADM_HISTORICAL_Q4_RECORDS):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "exact archived ADM snapshots predate the Q4 2026 validity window and are "
                "superseded for this candidate by the official 2026-09-26 and 2026-10-06 sheets"
            ),
            rule_id="adm-excise-historical-snapshots-superseded-q4-2026",
            rule_version="1.0.0",
        )
    if _is_known_gazzetta_148(record):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "the verified VAT and excise amendments in exact D.Lgs. 148/2026 do not "
                "change the household electricity tax rates represented by this anchor"
            ),
            rule_id="gazzetta-dl148-domestic-electricity-rates-out-of-scope",
            rule_version="1.0.0",
        )
    if _is_known_september_diesel_decree(record):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "the officially reviewed decree changes diesel-fuel excise only through "
                "2026-09-10 and defines no household-electricity Q4 anchor fact"
            ),
            rule_id="gazzetta-diesel-excise-out-of-scope",
            rule_version="1.0.0",
        )
    if _is_known_law_166_petroleum_measure(record):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "the exact Law 166/2026 converts a temporary measure on diesel-fuel excise; "
                "the Q4 household-electricity rate is unaffected and the fuel measure ends "
                "before 2026-10-01"
            ),
            rule_id="gazzetta-law-166-diesel-only-out-of-scope",
            rule_version="1.0.0",
        )
    if (
        record.channel == RegulatoryRegistryChannel.GAZZETTA_SERIE_GENERALE
        and record.registry_section == _GAZZETTA_INFORMATIONAL_SECTION
    ):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "the official Gazzetta rubric identifies this entry as an extract, summary, "
                "or communication, not a normative instrument changing the anchor's values; "
                "ARERA, ADM, and Normattiva indexes are checked independently for those values"
            ),
            rule_id="gazzetta-extracts-summaries-communications-out-of-scope",
            rule_version="1.0.0",
        )
    if _is_known_normattiva_tua_petroleum_update(record):
        return DiscoveryActFinding(
            channel=record.channel,
            act_id=record.act_id,
            disposition=DiscoveryActDisposition.IRRELEVANT_BY_VERSIONED_RULE,
            rationale=(
                "the exact Normattiva TUA update identifies Law 166/2026 as its latest "
                "amending act; that act changes only a temporary diesel-fuel excise measure "
                "ending before Q4, not household-electricity excise"
            ),
            rule_id="normattiva-tua-updated-by-law-166-diesel-only",
            rule_version="1.0.0",
        )
    return DiscoveryActFinding(
        channel=record.channel,
        act_id=record.act_id,
        disposition=DiscoveryActDisposition.REVIEW_REQUIRED,
        rationale="official record has no exact registered interpretation policy",
    )


__all__ = ["classify_official_regulatory_record"]
