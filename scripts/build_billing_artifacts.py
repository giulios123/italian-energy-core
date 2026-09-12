"""Freeze the verified ARERA 2026 billing artifacts without retaining XLSX bytes."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from italian_energy.arera import (
    AreraCustomerSegment,
    AreraDomesticElectricityImporter,
    AreraDomesticRuleSetComposer,
    DomesticFiscalPolicy,
)
from italian_energy.billing import BillingCoverageEntry, BillingCoverageMatrix, CoverageLevel
from italian_energy.domain.money import RateUnit, UnitRate
from italian_energy.domain.provenance import Provenance
from italian_energy.domain.regulatory import SupplyClassification, VerificationStatus, VoltageLevel
from italian_energy.domain.time import DatePeriod

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "src" / "italian_energy" / "data" / "billing"


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def main() -> None:
    result = AreraDomesticElectricityImporter().fetch_and_import(year=2026)
    if result.status != VerificationStatus.VERIFIED or result.bundle is None:
        raise RuntimeError("ARERA 2026 snapshot was not verified")
    bundle = result.bundle
    retrieved_at = result.snapshot.retrieved_at
    fiscal_policy = DomesticFiscalPolicy(
        schema_version="006-fiscal-official-v1",
        excise_rate=UnitRate(amount=Decimal("0.0227"), unit=RateUnit.EUR_PER_KWH),
        excise_provenance=(
            Provenance(
                source="ADM",
                source_identifier="Aliquote-naz-agg-01012023.pdf",
                retrieved_at=retrieved_at,
                effective_period=bundle.validity,
                dataset_version="2023-01-01",
                url="https://www.adm.gov.it/portale/documents/20182/43975520/Aliquote-naz-agg-01012023.pdf",
            ),
            Provenance(
                source="Gazzetta Ufficiale",
                source_identifier="11A16870",
                retrieved_at=retrieved_at,
                effective_period=bundle.validity,
                dataset_version="2011-12-31",
                url="https://www.gazzettaufficiale.it/eli/id/2011/12/31/11A16870/sg",
            ),
        ),
        vat_rate=UnitRate(amount=Decimal("10"), unit=RateUnit.PERCENT),
        vat_provenance=(
            Provenance(
                source="Normattiva",
                source_identifier="DPR-633-1972-tabella-A-parte-III-n-103",
                retrieved_at=retrieved_at,
                effective_period=bundle.validity,
                dataset_version="1972-current",
                url="https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:1972-10-26;633~art1",
            ),
        ),
        validity=bundle.validity,
    )
    composer = AreraDomesticRuleSetComposer()
    rulesets = {
        "resident": composer.compose(bundle, AreraCustomerSegment.RESIDENT, fiscal_policy),
        "non-resident": composer.compose(bundle, AreraCustomerSegment.NON_RESIDENT, fiscal_policy),
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    for segment, ruleset in rulesets.items():
        _write_json(
            ARTIFACT_DIR / f"arera-domestic-bt-{segment}-2026.json",
            ruleset.model_dump(mode="json"),
        )
    entries = []
    for segment, ruleset in rulesets.items():
        resident = segment == "resident"
        classification = SupplyClassification(
            contract_type_code=("domestic_bt_resident" if resident else "domestic_bt_non_resident"),
            voltage_level=VoltageLevel.BT,
            usage_code="domestic",
            residential=resident,
        )
        periods = (
            (bundle.validity,)
            if resident
            else (
                DatePeriod(start=date(2026, 1, 1), end=date(2026, 3, 1)),
                DatePeriod(start=date(2026, 5, 1), end=date(2026, 9, 1)),
            )
        )
        for period in periods:
            entries.append(
                BillingCoverageEntry(
                    profile_code=classification.contract_type_code,
                    classification=classification,
                    period=period,
                    ruleset_id=ruleset.ruleset_id,
                    level=CoverageLevel.RULESET_VERIFIED,
                    source_ids=(bundle.bundle_id, result.snapshot.snapshot_id),
                )
            )
    resident_classification = SupplyClassification(
        contract_type_code="domestic_bt_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=True,
    )
    entries.append(
        BillingCoverageEntry(
            profile_code=resident_classification.contract_type_code,
            classification=resident_classification,
            period=DatePeriod(start=date(2026, 5, 1), end=date(2026, 7, 1)),
            ruleset_id="arera-domestic-bt-resident-2026-05-06",
            level=CoverageLevel.GOLDEN_RECONCILED,
            source_ids=("private-golden-bill-domestic-bt-resident",),
            evidence_ids=("golden-bill-domestic-bt-resident",),
        )
    )
    non_resident_classification = SupplyClassification(
        contract_type_code="domestic_bt_non_resident",
        voltage_level=VoltageLevel.BT,
        usage_code="domestic",
        residential=False,
    )
    entries.append(
        BillingCoverageEntry(
            profile_code=non_resident_classification.contract_type_code,
            classification=non_resident_classification,
            period=DatePeriod(start=date(2026, 3, 1), end=date(2026, 5, 1)),
            ruleset_id=rulesets["non-resident"].ruleset_id,
            level=CoverageLevel.GOLDEN_RECONCILED,
            source_ids=("private-golden-bill-domestic-bt-non-resident",),
            evidence_ids=("golden-bill-domestic-bt-non-resident",),
        )
    )
    matrix = BillingCoverageMatrix(
        matrix_id="arera-domestic-bt-coverage:2026",
        schema_version="006-v1",
        entries=tuple(entries),
    )
    _write_json(
        ARTIFACT_DIR / "arera-domestic-bt-coverage-2026.json",
        matrix.model_dump(mode="json"),
    )
    _write_json(
        ARTIFACT_DIR / "arera-domestic-bt-snapshot-2026.json",
        {
            "dataset_version": bundle.dataset_version,
            "bundle_id": bundle.bundle_id,
            "snapshot_id": result.snapshot.snapshot_id,
            "sha256": result.snapshot.sha256,
            "validity": bundle.validity.model_dump(mode="json"),
            "segments": sorted(segment.value for segment in AreraCustomerSegment),
            "charge_count": len(bundle.charges),
            "status": result.status.value,
        },
    )


if __name__ == "__main__":
    main()
