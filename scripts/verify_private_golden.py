#!/usr/bin/env python3
"""Verify the private domestic golden scenario without publishing its data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from italian_energy.billing import (  # noqa: E402
    BillingError,
    BillingRequest,
    RegulatoryBillingEngine,
)
from italian_energy.domain.base import DomainModel  # noqa: E402
from italian_energy.domain.costs import (  # noqa: E402
    BillingResult,
    ExternalBillItem,
    ObservedBill,
    PricingResult,
)
from italian_energy.domain.offer import Contract  # noqa: E402
from italian_energy.domain.regulatory import (  # noqa: E402
    BillingMeasure,
    RegulatoryRuleSet,
    SupplyClassification,
)
from italian_energy.pricing.engine import PricingRequest  # noqa: E402
from italian_energy.pricing.fixed import FixedPricingEngine, FixedPricingError  # noqa: E402


class VerificationFailure(RuntimeError):
    """Raised when a private golden scenario is not safe to certify."""


class GoldenScenario(DomainModel):
    """Private, end-to-end inputs; this model is not part of the public API."""

    pricing_request: PricingRequest
    classification: SupplyClassification
    observed_bill: ObservedBill
    measurements: tuple[BillingMeasure, ...] = ()
    external_items: tuple[ExternalBillItem, ...] = ()


def _load_json(path: Path) -> object:
    if not path.is_file():
        raise VerificationFailure(f"missing private golden input: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise VerificationFailure(f"invalid JSON in {path}: {exc}") from exc


def _require_provenance(label: str, values: tuple[object, ...]) -> None:
    if not values:
        raise VerificationFailure(f"missing provenance: {label}")


def _validate_source_inputs(scenario: GoldenScenario, pricing: PricingResult) -> None:
    contract: Contract = scenario.pricing_request.contract
    _require_provenance("contract", contract.provenance)
    _require_provenance("tariff", contract.tariff.provenance)
    _require_provenance("observed bill", scenario.observed_bill.provenance)
    for component in pricing.breakdown.components:
        _require_provenance(f"pricing component {component.code}", component.provenance)
    for item in scenario.external_items:
        _require_provenance(f"external item {item.code}", item.provenance)
    if pricing.warnings:
        raise VerificationFailure(f"pricing warnings are unresolved: {pricing.warnings}")


def _billing_request(
    scenario: GoldenScenario,
    ruleset: RegulatoryRuleSet,
    pricing: PricingResult,
) -> BillingRequest:
    request = scenario.pricing_request
    return BillingRequest(
        contract=request.contract,
        consumption=request.consumption,
        period=request.period,
        observed_bill=scenario.observed_bill,
        pricing_result=pricing,
        classification=scenario.classification,
        rule_set=ruleset,
        measurements=scenario.measurements,
        external_items=scenario.external_items,
        rounding_policy=request.rounding_policy,
    )


def _evaluate_without_oracle(request: BillingRequest) -> BillingResult:
    return RegulatoryBillingEngine().evaluate(request.model_copy(update={"observed_bill": None}))


def verify(scenario_path: Path, ruleset_path: Path) -> None:
    scenario = GoldenScenario.model_validate(_load_json(scenario_path))
    ruleset = RegulatoryRuleSet.model_validate(_load_json(ruleset_path))
    pricing = FixedPricingEngine().price(scenario.pricing_request)
    _validate_source_inputs(scenario, pricing)
    billing_request = _billing_request(scenario, ruleset, pricing)

    baseline = _evaluate_without_oracle(billing_request)
    result = RegulatoryBillingEngine().evaluate(billing_request)
    repeated = RegulatoryBillingEngine().evaluate(billing_request)

    if baseline.bill != result.bill or result.bill != repeated.bill:
        raise VerificationFailure("bill changes when the observed oracle is present or repeated")
    if result.reconciliation is None:
        raise VerificationFailure("private golden did not produce a reconciliation")
    if result.reconciliation.status.value != "passed":
        failed = tuple(
            difference.reconciliation_key
            for difference in result.reconciliation.components
            if not difference.within_tolerance
        )
        raise VerificationFailure(
            "reconciliation failed for keys: " + ", ".join(failed or ("total",))
        )
    if result.warnings:
        raise VerificationFailure(f"billing warnings are unresolved: {result.warnings}")

    keys = tuple(
        component.reconciliation_key or component.code
        for component in result.bill.breakdown.components
    )
    print(
        "PRIVATE GOLDEN PASSED: "
        f"ruleset={ruleset.ruleset_id} profile={scenario.classification.contract_type_code} "
        f"components={','.join(keys)} bill_id={result.bill.bill_id}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario",
        type=Path,
        default=ROOT / "private/golden-bill-domestic-bt-resident.json",
    )
    parser.add_argument(
        "--ruleset",
        type=Path,
        default=ROOT / "tests/fixtures/regulatory-domestic-bt-resident-v1.json",
    )
    args = parser.parse_args(argv)
    try:
        verify(args.scenario, args.ruleset)
    except (BillingError, FixedPricingError, ValidationError, VerificationFailure) as exc:
        print(f"PRIVATE GOLDEN FAILED: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
