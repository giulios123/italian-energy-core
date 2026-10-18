"""Typed extraction of selected current values from official Portal CSVs."""

from __future__ import annotations

import csv
import io
from decimal import Decimal, InvalidOperation
from hashlib import sha256

from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import Provenance, ProvenanceLocator
from italian_energy.domain.regulatory import VerificationStatus
from italian_energy.domain.time import DatePeriod
from italian_energy.portal_offers.models import (
    PortalCdispDParameterSnapshot,
    PortalCdispDProjection,
    PortalFileSnapshot,
    PortalOffersSnapshot,
    PortalSourceRole,
    market_free_parameters_url,
)

MAX_PARAMETER_CSV_BYTES = 8 * 1024 * 1024


def parse_market_free_cdispd_parameter(
    file: PortalFileSnapshot,
) -> PortalCdispDParameterSnapshot | None:
    """Parse one exact official current CdispD row; malformed values fail closed."""
    if (
        file.role != PortalSourceRole.MARKET_FREE_PARAMETERS
        or file.status != VerificationStatus.VERIFIED
        or file.dataset_date is None
        or file.original_url != market_free_parameters_url(file.dataset_date)
        or file.final_url != market_free_parameters_url(file.dataset_date)
        or file.content_type != "text/csv"
        or file.content is None
        or len(file.content) > MAX_PARAMETER_CSV_BYTES
        or len(file.content) != file.size
        or sha256(file.content).hexdigest() != file.sha256
    ):
        return None

    try:
        text = file.content.decode("utf-8-sig")
        first_line = text.splitlines()[0] if text.splitlines() else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        headers = tuple((header or "").strip() for header in (reader.fieldnames or ()))
        if len(headers) != 3 or set(headers) != {"nome_parametro", "valore", "descrizione"}:
            return None
        rows = list(reader)
    except (UnicodeDecodeError, csv.Error, IndexError):
        return None

    cdispd_rows: list[tuple[int, dict[str, str | None]]] = []
    for row_number, row in enumerate(rows, start=2):
        if None in row:
            return None
        normalized = {(key or "").strip(): value for key, value in row.items()}
        if (normalized.get("nome_parametro") or "").strip() == "cdispd":
            cdispd_rows.append((row_number, normalized))
    if len(cdispd_rows) != 1:
        return None

    row_number, row = cdispd_rows[0]
    raw_amount = (row.get("valore") or "").strip()
    description = (row.get("descrizione") or "").strip()
    try:
        amount = Decimal(raw_amount)
    except (InvalidOperation, ValueError):
        return None
    if not amount.is_finite() or amount < 0 or not description:
        return None

    filename = f"PO_Parametri_Mercato_Libero_E_{file.dataset_date:%Y%m%d}.csv"
    return PortalCdispDParameterSnapshot(
        dataset_date=file.dataset_date,
        rate=UnitRate(amount=amount, unit=RateUnit.EUR_PER_KWH),
        description=description,
        status=VerificationStatus.VERIFIED,
        provenance=(
            Provenance(
                source="portale_offerte",
                source_identifier=filename,
                retrieved_at=file.retrieved_at,
                dataset_version="OffertaRetail/01",
                sha256=file.sha256,
                url=file.final_url,
                locator=ProvenanceLocator(
                    document=PortalSourceRole.MARKET_FREE_PARAMETERS.value,
                    section=f"row:{row_number}",
                ),
            ),
        ),
    )


def projection_matches_snapshot(
    projection: PortalCdispDProjection,
    snapshot: PortalOffersSnapshot,
    period: DatePeriod,
) -> bool:
    """Check the projected assumption is bound to the exact frozen catalog row."""
    if (
        projection.catalog_snapshot_id != snapshot.snapshot_id
        or projection.period != period
        or snapshot.status != VerificationStatus.VERIFIED
        or snapshot.dataset_date != projection.parameter.dataset_date
        or snapshot.cdispd_parameter != projection.parameter
    ):
        return False
    parameter_files = tuple(
        item for item in snapshot.files if item.role == PortalSourceRole.MARKET_FREE_PARAMETERS
    )
    if len(parameter_files) != 1:
        return False
    file = parameter_files[0]
    source = projection.parameter.provenance[0]
    return (
        file.status == VerificationStatus.VERIFIED
        and file.dataset_date == projection.parameter.dataset_date
        and file.final_url == market_free_parameters_url(file.dataset_date)
        and file.final_url == source.url
        and file.sha256 == source.sha256
        and file.retrieved_at == source.retrieved_at
    )
