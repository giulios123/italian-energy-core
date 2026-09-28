import json
from datetime import date

import pytest
from test_portal_offers import DATE, _transport

from italian_energy.integration import CoreContractError, CoreErrorCode, catalog_cli
from italian_energy.integration.service import CurrentDomesticEnergyService
from italian_energy.portal_offers import PortalOffersImporter


def test_catalog_command_reports_sources_and_index_coverage_without_raw_bytes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    transport = _transport()
    service = CurrentDomesticEnergyService(importer=PortalOffersImporter(transport=transport))
    monkeypatch.setattr(catalog_cli, "CurrentDomesticEnergyService", lambda: service)

    assert catalog_cli.main(["--date", DATE.isoformat()]) == 0
    output = capsys.readouterr()
    summary = json.loads(output.out)
    assert output.err == ""
    assert summary["dataset_date"] == DATE.isoformat()
    assert summary["status"] == "verified"
    assert summary["records"] == 2
    assert summary["records_by_type"] == {"fixed": 2}
    assert len(summary["files"]) == len(transport.urls) == 5
    assert all(item["size"] > 0 and len(item["sha256"]) == 64 for item in summary["files"])
    assert "content" not in {key for item in summary["files"] for key in item}
    assert summary["historical_indexes"] == [
        {"code": "PE", "points": 1, "first_month": "2026-01", "last_month": "2026-01"},
        {"code": "PUN", "points": 1, "first_month": "2026-01", "last_month": "2026-01"},
    ]


def test_catalog_command_fails_explicitly_without_another_date_or_stale_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dates: list[date | None] = []

    def fail(self: CurrentDomesticEnergyService, dataset_date: date | None = None) -> object:
        dates.append(dataset_date)
        raise CoreContractError(CoreErrorCode.SOURCE_ACQUISITION_FAILED, "official source failed")

    monkeypatch.setattr(CurrentDomesticEnergyService, "acquire_catalog", fail)
    assert catalog_cli.main(["--date", DATE.isoformat()]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err) == {
        "status": "failed",
        "dataset_date": DATE.isoformat(),
        "error": "source_acquisition_failed",
        "detail": "official source failed",
    }
    assert dates == [DATE]


def test_catalog_summary_allows_catalogue_without_index_observations() -> None:
    catalog = CurrentDomesticEnergyService(
        importer=PortalOffersImporter(transport=_transport())
    ).acquire_catalog(DATE)
    without_market = catalog.model_copy(update={"market_data": None})
    assert catalog_cli.summarize_catalog(without_market)["historical_indexes"] == []
    empty_market = catalog.market_data
    assert empty_market is not None
    without_points = catalog.model_copy(
        update={"market_data": empty_market.model_copy(update={"points": ()})}
    )
    assert catalog_cli.summarize_catalog(without_points)["historical_indexes"] == []


@pytest.mark.parametrize("args", [[], ["--date", "not-a-date"]])
def test_catalog_command_requires_an_exact_valid_date(args: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        catalog_cli.main(args)
    assert error.value.code == 2
